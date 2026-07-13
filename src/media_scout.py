"""Media scout: video-FIRST discovery. Scans robotics YouTube channels via
their RSS feeds (no API key needed; uses YOUTUBE_API_KEY for search when
present), filters to recent robotics demos, matches each video to its paper
(arXiv link in the description, else title search), and emits candidates
anchored on the video. These become the highest-value drafts: real footage
of real robots, with the paper and figures attached."""
import os
import re
import json
import requests
from utils import load_json, save_json, load_config

UA = {"User-Agent": "Mozilla/5.0 (compatible; RoboPost/1.0)"}
ROBO_WORDS = (
    "robot", "robotic", "quadruped", "humanoid", "manipulat", "drone", "uav",
    "underwater", "subsea", "legged", "gripper", "exoskeleton", "autonomous",
    "locomotion", "teleoperation", "slam", "swarm", "soft robot", "actuator",
)


def resolve_channel_id(handle: str) -> str | None:
    """@handle -> UC... channel id, cached (the page embeds it)."""
    cache = load_json("youtube_channels.json", {})
    if handle in cache:
        return cache[handle]
    try:
        r = requests.get(f"https://www.youtube.com/{handle}", headers=UA, timeout=30)
        m = re.search(r'"channelId":"(UC[\w-]{22})"', r.text)
        if m:
            cache[handle] = m.group(1)
            save_json("youtube_channels.json", cache)
            return m.group(1)
    except Exception as e:
        print(f"channel resolve failed {handle}: {e}")
    return None


def channel_videos(channel_id: str, days: int = 10) -> list[dict]:
    """Recent uploads via the channel's Atom feed (keyless)."""
    from datetime import datetime, timezone, timedelta
    out = []
    try:
        r = requests.get(
            f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}",
            headers=UA, timeout=30)
        import xml.etree.ElementTree as ET
        ns = {"a": "http://www.w3.org/2005/Atom",
              "yt": "http://www.youtube.com/xml/schemas/2015",
              "m": "http://search.yahoo.com/mrss/"}
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        for e in ET.fromstring(r.content).findall("a:entry", ns):
            vid = e.findtext("yt:videoId", "", ns)
            title = e.findtext("a:title", "", ns)
            pub = e.findtext("a:published", "", ns)
            desc = ""
            mg = e.find("m:group", ns)
            if mg is not None:
                desc = mg.findtext("m:description", "", ns) or ""
            try:
                if datetime.fromisoformat(pub.replace("Z", "+00:00")) < cutoff:
                    continue
            except Exception:
                pass
            out.append({"video_id": vid, "title": title, "desc": desc[:2000],
                        "published": pub})
    except Exception as e:
        print(f"channel feed failed {channel_id}: {e}")
    return out


def api_search(days: int = 7, max_results: int = 15) -> list[dict]:
    """Optional: YouTube Data API search for fresh robotics demos."""
    key = os.environ.get("YOUTUBE_API_KEY", "")
    if not key:
        return []
    from datetime import datetime, timezone, timedelta
    after = (datetime.now(timezone.utc) - timedelta(days=days)
             ).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = []
    try:
        r = requests.get("https://www.googleapis.com/youtube/v3/search", params={
            "key": key, "part": "snippet", "type": "video", "order": "date",
            "publishedAfter": after, "maxResults": max_results,
            "q": "robot demo | robotics paper | legged robot | robot field test",
            "relevanceLanguage": "en", "videoDuration": "short"}, timeout=30)
        for it in r.json().get("items", []):
            sn = it.get("snippet", {})
            out.append({"video_id": it["id"]["videoId"], "title": sn.get("title", ""),
                        "desc": sn.get("description", "")[:2000],
                        "published": sn.get("publishedAt", "")})
    except Exception as e:
        print(f"youtube api search failed: {e}")
    return out


def match_paper(video: dict) -> dict:
    """Attach the paper behind a video: arXiv link in description first,
    else a title search with a strict match threshold."""
    m = re.search(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})", video.get("desc", ""))
    if m:
        return {"arxiv_id": m.group(1), "how": "description-link"}
    try:
        from figures import find_open_version
        title = re.sub(r"[\[\(].*?[\]\)]", "", video["title"]).strip()
        info = find_open_version(title)
        if info and info.get("arxiv_id"):
            return {"arxiv_id": info["arxiv_id"], "how": "title-match"}
    except Exception:
        pass
    return {}


def is_robotics(v: dict) -> bool:
    blob = (v.get("title", "") + " " + v.get("desc", "")).lower()
    return any(w in blob for w in ROBO_WORDS)


def scout() -> list[dict]:
    cfg = load_config()
    handles = cfg["sources"].get("youtube_channels", [])
    videos = []
    for h in handles:
        cid = resolve_channel_id(h)
        if cid:
            videos += channel_videos(cid)
    videos += api_search()
    videos = [v for v in videos if is_robotics(v)]
    print(f"Media scout: {len(videos)} robotics videos found")
    items = []
    for v in videos:
        paper = match_paper(v)
        url = f"https://www.youtube.com/watch?v={v['video_id']}"
        item = {
            "id": paper.get("arxiv_id") or f"yt-{v['video_id']}",
            "title": v["title"],
            "abstract": (v.get("desc") or v["title"])[:900],
            "authors": [],
            "url": f"https://arxiv.org/abs/{paper['arxiv_id']}" if paper.get("arxiv_id") else url,
            "source": "media_scout",
            "item_type": "paper" if paper.get("arxiv_id") else "video",
            "video_url": url,
            "video_first": True,
        }
        if paper.get("arxiv_id"):
            item["open_version"] = f"https://arxiv.org/abs/{paper['arxiv_id']}"
            print(f"  video+paper: {v['title'][:45]} -> arXiv:{paper['arxiv_id']} ({paper['how']})")
        items.append(item)
    return items


if __name__ == "__main__":
    for it in scout():
        print(json.dumps({k: it[k] for k in ("id", "title", "item_type")},
                         ensure_ascii=False))
