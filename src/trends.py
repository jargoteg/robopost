"""Trends radar — every 6 hours, search Bluesky for what the robotics
community is actually discussing, and distill it into data/trends.md.
The ranker and writer read it, so daily posts ride live conversations."""
import requests
from datetime import datetime, timezone
from utils import load_config, claude, env, DATA


def bsky_session():
    base = "https://bsky.social/xrpc"
    s = requests.post(f"{base}/com.atproto.server.createSession",
                      json={"identifier": env("BLUESKY_HANDLE", True),
                            "password": env("BLUESKY_APP_PASSWORD", True)},
                      timeout=30).json()
    return base, {"Authorization": f"Bearer {s['accessJwt']}"}


def search_posts(base, H, query, limit=25):
    r = requests.get(f"{base}/app.bsky.feed.searchPosts",
                     params={"q": query, "sort": "top", "limit": limit},
                     headers=H, timeout=30)
    if not r.ok:
        return []
    return r.json().get("posts", [])


def main():
    cfg = load_config()
    queries = ["robotics", "robot learning", "humanoid robot", "swarm robotics"]
    base, H = bsky_session()
    seen_text = []
    for q in queries:
        for p in search_posts(base, H, q):
            likes = p.get("likeCount", 0) + 2 * p.get("repostCount", 0)
            text = (p.get("record", {}).get("text") or "").replace("\n", " ")
            if likes >= 3 and len(text) > 40:
                seen_text.append(f"[{likes} eng] {text[:220]}")
    seen_text = seen_text[:60]
    if not seen_text:
        print("No trend data collected.")
        return
    brief = claude(
        f"""Today is {datetime.now(timezone.utc).date()}. Below are currently
high-engagement Bluesky posts from the robotics community.

{chr(10).join(seen_text)}

Write a 150-word max "what the community is talking about" brief for a
content curator: 3-5 live conversation themes, any papers/demos/events people
keep mentioning, and one suggestion for a post angle that would land today.
Plain text, no headers, no dashes.""",
        system="You are a social listening analyst for robotics.")
    (DATA / "trends.md").write_text(
        f"# Community trends (updated {datetime.now(timezone.utc).isoformat()[:16]}Z)\n\n{brief}\n")
    print("trends.md updated.")


if __name__ == "__main__":
    main()
