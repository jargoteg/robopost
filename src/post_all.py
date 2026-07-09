"""Publish approved drafts to Bluesky, Instagram, and TikTok."""
import time
import requests
from datetime import datetime, timezone
from utils import load_config, load_json, save_json, env, ROOT

def compress_for_bluesky(path, limit=950_000):
    """Bluesky rejects blobs near 1MB; JPEG-compress (and downscale if
    needed) while preserving aspect ratio."""
    import io
    from PIL import Image
    img = Image.open(path).convert("RGB")
    for scale in (1.0, 0.85, 0.7, 0.55):
        w, h = int(img.width * scale), int(img.height * scale)
        frame = img if scale == 1.0 else img.resize((w, h), Image.LANCZOS)
        for q in (85, 75, 65):
            buf = io.BytesIO()
            frame.save(buf, "JPEG", quality=q)
            if buf.tell() <= limit:
                return buf.getvalue()
    return buf.getvalue()


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
        data = compress_for_bluesky(ROOT / rel)
        r = requests.post(f"{base}/com.atproto.repo.uploadBlob", headers={
            **H, "Content-Type": "image/jpeg"}, data=data, timeout=60)
        r.raise_for_status()
        images.append({"image": r.json()["blob"],
                       "alt": draft["paper"]["title"][:200]})

    embed = {"$type": "app.bsky.embed.images", "images": images}
    # native video when this draft is a video (Bluesky: <=60s, ~50MB)
    vid = draft["media"].get("video")
    if draft["content"].get("format") == "video" and vid:
        try:
            with open(ROOT / vid, "rb") as f:
                vblob = requests.post(f"{base}/com.atproto.repo.uploadBlob", headers={
                    **H, "Content-Type": "video/mp4"}, data=f.read(), timeout=180)
            vblob.raise_for_status()
            embed = {"$type": "app.bsky.embed.video",
                     "video": vblob.json()["blob"],
                     "aspectRatio": {"width": 1080, "height": 1920}}
            print("Bluesky: native video embed")
        except Exception as e:
            print(f"Bluesky video upload failed, using images: {e}")

    text = draft["content"]["post_bluesky"][:300]
    # idempotency against Bluesky itself: if a recent post has this same text,
    # the draft already went out (state was lost in a race) — do NOT repost
    try:
        feed = requests.get(f"{base}/app.bsky.feed.getAuthorFeed",
                            params={"actor": did, "limit": 30},
                            headers=H, timeout=30).json()
        probe = text[:60]
        for item in feed.get("feed", []):
            prev = (item.get("post", {}).get("record", {}).get("text") or "")
            if probe and prev[:60] == probe:
                uri = item["post"]["uri"]
                print(f"Bluesky: identical recent post exists ({uri}); skipping repost.")
                return uri
    except Exception as e:
        print(f"Dedup check failed (posting anyway): {e}")
    record = {
        "$type": "app.bsky.feed.post", "text": text,
        "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "embed": embed,
    }
    # link facet for the arXiv URL if present in text
    url = draft["paper"]["url"]
    if url in text:
        b = text.encode()
        start = b.find(url.encode())
        record["facets"] = [{
            "index": {"byteStart": start, "byteEnd": start + len(url.encode())},
            "features": [{"$type": "app.bsky.richtext.facet#link", "uri": url}],
        }]
    r = requests.post(f"{base}/com.atproto.repo.createRecord", headers=H, json={
        "repo": did, "collection": "app.bsky.feed.post", "record": record}, timeout=30)
    r.raise_for_status()
    root = r.json()
    # A/B experiment: alternate single post vs thread; metrics compare them
    posted_count = len(load_json("posted.json", []))
    draft["bsky_variant"] = "thread" if posted_count % 2 == 0 else "single"
    replies = draft["content"].get("bluesky_thread", [])[:2] \
        if draft["bsky_variant"] == "thread" else []
    print(f"Bluesky variant: {draft['bsky_variant']}")
    parent = root
    for reply_text in replies:
        rec = {"$type": "app.bsky.feed.post", "text": reply_text[:300],
               "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
               "reply": {"root": {"uri": root["uri"], "cid": root["cid"]},
                          "parent": {"uri": parent["uri"], "cid": parent["cid"]}}}
        rr = requests.post(f"{base}/com.atproto.repo.createRecord", headers=H, json={
            "repo": did, "collection": "app.bsky.feed.post", "record": rec}, timeout=30)
        if rr.ok:
            parent = rr.json()
    return root["uri"]

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
    from generate import ensure_complete
    from datetime import timedelta
    def set_status_label(num, status):
        """Cosmetic label; must NEVER break posting."""
        try:
            from github_review import set_status_label as _ssl
            _ssl(num, status)
        except Exception as e:
            print(f"label skipped ({status}): {e}")
    gap = timedelta(minutes=cfg.get("posting", {}).get("min_gap_minutes", 90))
    last = max((datetime.fromisoformat(p["posted_at"]) for p in posted), default=None)
    for d in drafts:
        if d["status"] != "approved":
            continue
        now = datetime.now(timezone.utc)
        if last and now - last < gap:
            eta = (last + gap).strftime("%H:%M UTC")
            print(f"{d['draft_id']}: spacing posts, next window at {eta}. Staying queued.")
            d["scheduled_after"] = (last + gap).isoformat()
            if d.get("issue"):
                set_status_label(d["issue"], "queued-to-post")
            continue
        d["content"] = ensure_complete(d["content"], d["paper"])
        import os
        NEEDS = {"bluesky": ["BLUESKY_HANDLE", "BLUESKY_APP_PASSWORD"],
                 "instagram": ["IG_ACCESS_TOKEN", "IG_USER_ID"],
                 "tiktok": ["TIKTOK_ACCESS_TOKEN"]}
        ids = {}
        for name, fn, enabled in [
            ("bluesky", post_bluesky, cfg["platforms"]["bluesky"]),
            ("instagram", post_instagram, cfg["platforms"]["instagram"]),
            ("tiktok", post_tiktok, cfg["platforms"]["tiktok"]),
        ]:
            if not enabled:
                continue
            if not all(os.environ.get(k) for k in NEEDS[name]):
                ids[name] = "skipped"
                print(f"{d['draft_id']} → {name}: skipped (secrets not configured)")
                continue
            try:
                ids[name] = fn(d, cfg)
                print(f"{d['draft_id']} → {name}: {ids[name]}")
            except Exception as e:
                print(f"{d['draft_id']} → {name} FAILED: {e}")
                ids[name] = None
        attempted = {k: v for k, v in ids.items() if v != "skipped"}
        if attempted and not any(attempted.values()):
            # every configured platform failed: stay approved, retry next cycle
            d["post_failures"] = d.get("post_failures", 0) + 1
            print(f"{d['draft_id']}: all platforms failed, will retry.")
            if d.get("issue"):
                set_status_label(d["issue"], "post-failed")
            continue
        d["status"] = "posted"
        last = datetime.now(timezone.utc)
        posted.append({
            "draft_id": d["draft_id"], "paper_id": d["paper"]["id"],
            "title": d["paper"]["title"], "format": d["content"]["format"],
            "hook": d["content"]["hook"],
            "posted_at": datetime.now(timezone.utc).isoformat(),
            "bsky_variant": d.get("bsky_variant", ""),
            "hook_style": d["content"].get("hook_style", ""),
            "platform_ids": ids, "metrics": {},
        })
        # persist IMMEDIATELY: if anything later crashes, this post is recorded
        save_json("drafts.json", drafts)
        save_json("posted.json", posted)
        if d.get("issue"):
            set_status_label(d["issue"], "posted")
    save_json("drafts.json", drafts)
    save_json("posted.json", posted)


if __name__ == "__main__":
    main()
