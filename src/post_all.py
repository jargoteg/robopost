"""Publish approved drafts to Bluesky, Instagram, and TikTok."""
import time
import requests
from datetime import datetime, timezone
from utils import load_config, load_json, save_json, env, ROOT

# ── Bluesky ─────────────────────────────────────────────────────────
def post_bluesky(draft, cfg):
    handle, pw = env("BLUESKY_HANDLE", True), env("BLUESKY_APP_PASSWORD", True)
    base = "https://bsky.social/xrpc"
    s = requests.post(f"{base}/com.atproto.server.createSession",
                      json={"identifier": handle, "password": pw}, timeout=30).json()
    jwt, did = s["accessJwt"], s["did"]
    H = {"Authorization": f"Bearer {jwt}"}

    images = []
    for rel in (draft["media"].get("bsky") or draft["media"]["slides"][:4]):
        with open(ROOT / rel, "rb") as f:
            blob = requests.post(f"{base}/com.atproto.repo.uploadBlob", headers={
                **H, "Content-Type": "image/png"}, data=f.read(), timeout=60).json()["blob"]
        images.append({"image": blob, "alt": draft["paper"]["title"][:200]})

    text = draft["content"]["post_bluesky"]
    record = {
        "$type": "app.bsky.feed.post", "text": text,
        "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "embed": {"$type": "app.bsky.embed.images", "images": images},
    }
    # link facet for the arXiv URL if present in text
    url = draft["paper"]["url"]
    if url in text:
        b = text.encode(); start = b.find(url.encode())
        record["facets"] = [{
            "index": {"byteStart": start, "byteEnd": start + len(url.encode())},
            "features": [{"$type": "app.bsky.richtext.facet#link", "uri": url}],
        }]
    r = requests.post(f"{base}/com.atproto.repo.createRecord", headers=H, json={
        "repo": did, "collection": "app.bsky.feed.post", "record": record}, timeout=30)
    r.raise_for_status()
    return r.json()["uri"]

# ── Instagram (Graph API) ───────────────────────────────────────────
def post_instagram(draft, cfg):
    token, ig_id = env("IG_ACCESS_TOKEN", True), env("IG_USER_ID", True)
    base_url = cfg["media_base_url"].rstrip("/")
    g = "https://graph.facebook.com/v21.0"

    if draft["content"]["format"] == "video" and draft["media"].get("video"):
        vurl = f"{base_url}/{draft['media']['video']}"
        c = requests.post(f"{g}/{ig_id}/media", data={
            "media_type": "REELS", "video_url": vurl,
            "caption": draft["content"]["caption_instagram"],
            "access_token": token}, timeout=60).json()
        cid = c["id"]
        for _ in range(30):  # wait for processing
            st = requests.get(f"{g}/{cid}?fields=status_code&access_token={token}", timeout=30).json()
            if st.get("status_code") == "FINISHED":
                break
            time.sleep(10)
    else:
        children = []
        for rel in draft["media"]["slides"][:10]:
            r = requests.post(f"{g}/{ig_id}/media", data={
                "image_url": f"{base_url}/{rel}", "is_carousel_item": "true",
                "access_token": token}, timeout=60).json()
            children.append(r["id"])
        c = requests.post(f"{g}/{ig_id}/media", data={
            "media_type": "CAROUSEL", "children": ",".join(children),
            "caption": draft["content"]["caption_instagram"],
            "access_token": token}, timeout=60).json()
        cid = c["id"]

    pub = requests.post(f"{g}/{ig_id}/media_publish", data={
        "creation_id": cid, "access_token": token}, timeout=60).json()
    return pub.get("id")

# ── TikTok (Content Posting API) ────────────────────────────────────
def post_tiktok(draft, cfg):
    """Uploads video to the user's TikTok inbox (draft) — the safe default
    for unaudited apps. Switch endpoint to /publish/video/init/ once your
    app is audited for direct posting."""
    token = env("TIKTOK_ACCESS_TOKEN", True)
    vid = draft["media"].get("video")
    if not vid:
        print("No video for TikTok; skipping (carousel-only draft).")
        return None
    path = ROOT / vid
    size = path.stat().st_size
    init = requests.post(
        "https://open.tiktokapis.com/v2/post/publish/inbox/video/init/",
        headers={"Authorization": f"Bearer {token}"},
        json={"source_info": {"source": "FILE_UPLOAD", "video_size": size,
                              "chunk_size": size, "total_chunk_count": 1}},
        timeout=60).json()
    info = init.get("data", {})
    with open(path, "rb") as f:
        requests.put(info["upload_url"], data=f.read(), headers={
            "Content-Range": f"bytes 0-{size-1}/{size}",
            "Content-Type": "video/mp4"}, timeout=300).raise_for_status()
    return info.get("publish_id")

# ── main ────────────────────────────────────────────────────────────
def main():
    cfg = load_config()
    drafts = load_json("drafts.json", [])
    posted = load_json("posted.json", [])
    for d in drafts:
        if d["status"] != "approved":
            continue
        ids = {}
        for name, fn, enabled in [
            ("bluesky", post_bluesky, cfg["platforms"]["bluesky"]),
            ("instagram", post_instagram, cfg["platforms"]["instagram"]),
            ("tiktok", post_tiktok, cfg["platforms"]["tiktok"]),
        ]:
            if not enabled:
                continue
            try:
                ids[name] = fn(d, cfg)
                print(f"{d['draft_id']} → {name}: {ids[name]}")
            except Exception as e:
                print(f"{d['draft_id']} → {name} FAILED: {e}")
                ids[name] = None
        d["status"] = "posted"
        posted.append({
            "draft_id": d["draft_id"], "paper_id": d["paper"]["id"],
            "title": d["paper"]["title"], "format": d["content"]["format"],
            "hook": d["content"]["hook"],
            "posted_at": datetime.now(timezone.utc).isoformat(),
            "platform_ids": ids, "metrics": {},
        })
    save_json("drafts.json", drafts)
    save_json("posted.json", posted)


if __name__ == "__main__":
    main()
