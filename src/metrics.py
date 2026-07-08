"""Collect engagement metrics per platform, then distill lessons into
data/feedback.md — which fetch_papers.py and generate.py inject into their
prompts. This closes the continuous-improvement loop."""
import requests
from datetime import datetime, timezone
from utils import load_json, save_json, claude, env, DATA


def bluesky_metrics(uri):
    handle, pw = env("BLUESKY_HANDLE"), env("BLUESKY_APP_PASSWORD")
    if not (handle and pw and uri):
        return {}
    base = "https://bsky.social/xrpc"
    s = requests.post(f"{base}/com.atproto.server.createSession",
                      json={"identifier": handle, "password": pw}, timeout=30).json()
    r = requests.get(f"{base}/app.bsky.feed.getPosts", params={"uris": [uri]},
                     headers={"Authorization": f"Bearer {s['accessJwt']}"}, timeout=30).json()
    posts = r.get("posts", [])
    if not posts:
        return {}
    p = posts[0]
    return {"likes": p.get("likeCount", 0), "reposts": p.get("repostCount", 0),
            "replies": p.get("replyCount", 0)}


def instagram_metrics(media_id):
    token = env("IG_ACCESS_TOKEN")
    if not (token and media_id):
        return {}
    r = requests.get(
        f"https://graph.facebook.com/v21.0/{media_id}/insights",
        params={"metric": "reach,likes,comments,saved,shares", "access_token": token},
        timeout=30).json()
    return {d["name"]: d["values"][0]["value"] for d in r.get("data", [])}


def tiktok_metrics(publish_id):
    # Inbox drafts have no public metrics until the user publishes manually.
    # Once the app is audited + direct-posting, query /v2/video/query/ here.
    return {}


def main():
    posted = load_json("posted.json", [])
    for p in posted:
        ids = p.get("platform_ids", {})
        m = {}
        for name, fn in [("bluesky", bluesky_metrics),
                         ("instagram", instagram_metrics),
                         ("tiktok", tiktok_metrics)]:
            try:
                m[name] = fn(ids.get(name))
            except Exception as e:
                print(f"metrics {name} failed: {e}")
        p["metrics"] = m
        p["metrics_at"] = datetime.now(timezone.utc).isoformat()
    save_json("posted.json", posted)

    # ── learning step ──
    recent = posted[-30:]
    rejections = load_json("rejections.json", [])[-20:]
    if not recent and not rejections:
        return
    table = "\n".join(
        f"- [{p['format']}] \"{p['hook']}\" ({p['title'][:60]}) → {p['metrics']}"
        for p in recent
    )
    lessons = claude(
        f"""Here are our last posts (format, hook, paper, engagement metrics):
{table}

Recently REJECTED by the owner (with reasons):
{chr(10).join(f"- [{r.get('item_type')}] {r.get('title','')[:60]}: {r.get('reason')}" for r in rejections) or "none"}

Write a short "lessons learned" brief (max 250 words) for the content team:
1. Topics/paper types that over- and under-performed
2. Hook styles that worked
3. Carousel vs video performance
4. 3 concrete recommendations for the next posts
Be specific and evidence-based; if data is too sparse, say what to test next.""",
        system="You are a social media analyst.",
    )
    (DATA / "feedback.md").write_text(
        f"# Engagement lessons (auto-updated {datetime.now(timezone.utc).date()})\n\n{lessons}\n"
    )
    print("feedback.md updated.")


if __name__ == "__main__":
    main()
