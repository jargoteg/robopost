"""Fetch recent robotics papers (arXiv + HF daily papers), rank with Claude,
and enqueue the best ones as draft candidates. Manual additions in
data/manual_queue.json always take priority."""
import re
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from utils import load_config, load_json, save_json, claude_json, get_feedback_notes

NS = {"a": "http://www.w3.org/2005/Atom"}


def get_with_retries(url, tries=3, timeout=60, **kw):
    import time
    for attempt in range(tries):
        try:
            r = requests.get(url, timeout=timeout, **kw)
            r.raise_for_status()
            return r
        except Exception as e:
            if attempt == tries - 1:
                raise
            wait = 15 * (attempt + 1)
            print(f"Fetch failed ({e}); retrying in {wait}s...")
            time.sleep(wait)


def fetch_arxiv(cfg) -> list[dict]:
    cats = " OR ".join(f"cat:{c}" for c in cfg["sources"]["arxiv_categories"])
    url = (
        "http://export.arxiv.org/api/query"
        f"?search_query={cats}&sortBy=submittedDate&sortOrder=descending"
        f"&max_results={cfg['sources']['arxiv_max_results']}"
    )
    r = get_with_retries(url)
    papers = []
    for e in ET.fromstring(r.text).findall("a:entry", NS):
        pid = e.find("a:id", NS).text.split("/abs/")[-1]
        papers.append({
            "id": pid,
            "title": re.sub(r"\s+", " ", e.find("a:title", NS).text).strip(),
            "abstract": re.sub(r"\s+", " ", e.find("a:summary", NS).text).strip(),
            "authors": [a.find("a:name", NS).text for a in e.findall("a:author", NS)][:6],
            "url": f"https://arxiv.org/abs/{pid}",
            "source": "arxiv",
        })
    return papers


def fetch_hf_daily() -> list[dict]:
    try:
        r = requests.get("https://huggingface.co/api/daily_papers", timeout=30)
        r.raise_for_status()
        out = []
        for item in r.json():
            p = item.get("paper", {})
            if not p.get("id"):
                continue
            out.append({
                "id": p["id"],
                "title": p.get("title", "").strip(),
                "abstract": p.get("summary", "").strip(),
                "authors": [a.get("name", "") for a in p.get("authors", [])][:6],
                "url": f"https://arxiv.org/abs/{p['id']}",
                "source": "hf_daily",
                "hf_upvotes": item.get("paper", {}).get("upvotes", 0),
            })
        return out
    except Exception as e:
        print(f"HF daily papers fetch failed (non-fatal): {e}")
        return []


def fetch_rss(cfg, feeds_key="news_feeds", item_type="article") -> list[dict]:
    """Pull items from RSS feeds. news_feeds → articles (subject to the news
    cap); journal_feeds (Science Robotics, Nature MI...) → papers (no cap)."""
    import hashlib
    from datetime import timedelta
    kw = [k.lower() for k in cfg["sources"].get("news_keywords", ["robot"])]
    if item_type == "paper":
        kw = kw + ["learn", "control", "actuat", "sensor", "soft", "manipulat"]
    items = []
    for feed in cfg["sources"].get(feeds_key, []):
        try:
            r = requests.get(feed, timeout=30, headers={
                "User-Agent": "Mozilla/5.0 (compatible; RoboPost/1.0)"})
            root = ET.fromstring(r.content)
            for it in root.iter("item"):  # RSS 2.0
                title = (it.findtext("title") or "").strip()
                link = (it.findtext("link") or "").strip()
                desc = re.sub(r"<[^>]+>", " ", it.findtext("description") or "")
                desc = re.sub(r"\s+", " ", desc).strip()
                blob = f"{title} {desc}".lower()
                if not link or not any(k in blob for k in kw):
                    continue
                items.append({
                    "id": "rss-" + hashlib.sha1(link.encode()).hexdigest()[:10],
                    "title": title, "abstract": desc[:1500] or title,
                    "authors": [], "url": link,
                    "source": feed.split("/")[2].replace("www.", ""),
                    "item_type": item_type,
                })
        except Exception as e:
            print(f"RSS fetch failed for {feed} (non-fatal): {e}")
    return items


def enrich_youtube(items: list[dict]):
    """For each picked item, search YouTube for a project/demo video and
    attach it as video_url. Linked in captions, never re-uploaded.
    Requires YOUTUBE_API_KEY (free Data API v3 key); silently skips if unset."""
    import os
    key = os.environ.get("YOUTUBE_API_KEY", "")
    if not key:
        return
    for it in items:
        if it.get("video_url"):
            continue
        q = it["title"][:90]
        try:
            r = requests.get(
                "https://www.googleapis.com/youtube/v3/search",
                params={"part": "snippet", "q": q, "type": "video",
                        "maxResults": 3, "key": key}, timeout=30).json()
            for v in r.get("items", []):
                vt = v["snippet"]["title"].lower()
                # crude match: enough title-word overlap to be the same work
                words = [w for w in re.findall(r"\w{4,}", it["title"].lower())][:8]
                hits = sum(w in vt for w in words)
                if words and hits / len(words) >= 0.4:
                    it["video_url"] = f"https://www.youtube.com/watch?v={v['id']['videoId']}"
                    it["video_title"] = v["snippet"]["title"]
                    print(f"YouTube match for '{it['title'][:50]}': {it['video_title'][:60]}")
                    break
        except Exception as e:
            print(f"YouTube search failed (non-fatal): {e}")


def fetch_watch_pages(cfg) -> list[dict]:
    """News pages without RSS (e.g. Bristol Robotics Lab) — fetch the page,
    Claude extracts the recent items."""
    import hashlib
    from utils import fetch_url_text, claude_json
    items = []
    for url in cfg["sources"].get("watch_pages", []):
        try:
            page = fetch_url_text(url, limit=10000)
            found = claude_json(
                f"""Extract up to 5 of the most recent news items from this lab/news
page. JSON: [{{"title": "...", "summary": "2-4 sentences", "link": "absolute URL
if visible, else \"{url}\""}}]\n\nPAGE ({url}):\n{page}""",
                system="You extract structured news items from web pages.")
            for f in found:
                link = f.get("link") or url
                items.append({
                    "id": "watch-" + hashlib.sha1((f["title"] + link).encode()).hexdigest()[:10],
                    "title": f["title"], "abstract": f.get("summary", f["title"]),
                    "authors": [], "url": link,
                    "source": url.split("/")[2].replace("www.", ""),
                    "item_type": "article",
                })
        except Exception as e:
            print(f"Watch page failed for {url} (non-fatal): {e}")
    return items


def fetch_arxiv_ids(ids: list[str]) -> list[dict]:
    r = get_with_retries(f"http://export.arxiv.org/api/query?id_list={','.join(ids)}")
    out = []
    for e in ET.fromstring(r.text).findall("a:entry", NS):
        t = e.find("a:title", NS)
        if t is None or not (t.text or "").strip():
            continue
        pid = e.find("a:id", NS).text.split("/abs/")[-1].split("v")[0]
        out.append({
            "id": pid,
            "title": re.sub(r"\s+", " ", t.text).strip(),
            "abstract": re.sub(r"\s+", " ", e.find("a:summary", NS).text).strip(),
            "authors": [a.find("a:name", NS).text for a in e.findall("a:author", NS)][:6],
            "url": f"https://arxiv.org/abs/{pid}", "source": "arxiv",
        })
    return out


def suggest_evergreen(cfg, seen: set) -> list[dict]:
    """Older but landmark/underrated robotics papers, proposed by Claude and
    verified against arXiv. Skips anything already seen or posted."""
    from utils import claude_json
    posted_titles = [p["title"] for p in load_json("posted.json", [])][-50:]
    rejected = [r.get("title", "") for r in load_json("rejections.json", [])][-30:]
    try:
        cands = claude_json(
            f"""Suggest 4 robotics papers on arXiv that are NOT from the last few
months but are worth featuring on a robotics research account today:
landmark works, underrated gems, or classics newly relevant to current events
(e.g. RoboCup, humanoid progress, VLA models). Prefer visually rich papers.
Avoid anything resembling these already covered: {posted_titles}
And these rejected topics: {rejected}
Return JSON: [{{"arxiv_id": "XXXX.XXXXX", "why_now": "one line"}}]""",
            system="You are a robotics research historian and curator.")
        ids = [c["arxiv_id"] for c in cands if re.match(r"\d{4}\.\d{4,5}$", str(c.get("arxiv_id", "")))]
        why = {c["arxiv_id"]: c.get("why_now", "") for c in cands}
        verified = fetch_arxiv_ids(ids) if ids else []
        out = []
        for p in verified:
            if p["id"] not in seen:
                p["item_type"] = "paper"
                p["evergreen"] = True
                p["user_notes"] = f"Evergreen pick. Angle: {why.get(p['id'], '')}. Make clear it's not new work, and why it matters today."
                out.append(p)
        return out[: cfg["sources"].get("evergreen", {}).get("per_day", 1)]
    except Exception as e:
        print(f"Evergreen suggestion failed (non-fatal): {e}")
        return []


def rank_papers(papers: list[dict], cfg) -> list[dict]:
    """Ask Claude to score items for this account's audience (batched to
    keep each response small enough to never truncate)."""
    from conference_radar import conference_context
    feedback = get_feedback_notes()
    conf = conference_context(cfg)
    boost = ", ".join(cfg["sources"]["keywords_boost"])
    B = 25
    for lo in range(0, len(papers), B):
        batch = papers[lo:lo + B]
        listing = "\n".join(
            f"[{i}] {p['title']} — {p['abstract'][:300]}" for i, p in enumerate(batch)
        )
        try:
            _rank_batch(batch, listing, feedback, conf, boost)
        except Exception as e:
            print(f"Ranking batch {lo//B} failed (items skipped): {e}")
    return sorted(papers, key=lambda p: p.get("score", 0), reverse=True)


def _rank_batch(batch, listing, feedback, conf, boost):
    cfg = load_config()
    rej = load_json("rejections.json", [])[-10:]
    rejections = ""
    if rej:
        rejections = "The owner REJECTED these recently (avoid similar picks):\n" + "\n".join(
            f"- {r.get('title','')[:70]}: \"{r.get('reason','no reason given')}\"" for r in rej)
    result = claude_json(
        f"""You curate papers for a social account about: {cfg['account']['niche']}.
Priority topics: {boost}.

Lessons learned from past engagement data:
{feedback}

{conf}

{rejections}

Score each item (paper or news/competition story) 0-10 for how compelling a social post about it would be
(novelty, visual/story potential, audience fit). Return a compact JSON
array, nothing else: [{{"i": int, "s": float}}]

Items:
{listing}""",
        system="You are a sharp robotics research curator.",
    )
    for r in result:
        i = r.get("i", -1)
        if 0 <= i < len(batch):
            batch[i]["score"] = r.get("s", 0)


def main():
    cfg = load_config()
    seen = set(load_json("seen_papers.json", []))
    queue = load_json("draft_queue.json", [])

    # 1. Manual additions always jump the queue
    manual = load_json("manual_queue.json", [])
    for p in manual:
        if p["id"] not in seen:
            p["manual"] = True
            queue.append(p)
            seen.add(p["id"])
    save_json("manual_queue.json", [])

    # 2. Automatic fetch + rank (papers + news/competition feeds)
    try:
        papers = fetch_arxiv(cfg)
    except Exception as e:
        print(f"arXiv fetch failed after retries (non-fatal, other sources continue): {e}")
        papers = []
    if cfg["sources"]["hf_daily_papers"]:
        # keep HF entries that look robotics-adjacent
        kw = [k.lower() for k in cfg["sources"]["keywords_boost"]] + ["robot"]
        papers += [
            p for p in fetch_hf_daily()
            if any(k in (p["title"] + p["abstract"]).lower() for k in kw)
        ]
    papers += fetch_rss(cfg)
    papers += fetch_rss(cfg, "journal_feeds", "paper")
    if cfg["sources"].get("evergreen", {}).get("enabled"):
        papers += suggest_evergreen(cfg, seen)
    papers += fetch_watch_pages(cfg)
    from conference_radar import preview_items, active_windows
    papers += preview_items(cfg)
    if active_windows(cfg):
        print("Conference window active — widening the net.")
        cfg["pipeline"]["drafts_per_day"] = cfg["pipeline"]["drafts_per_day"] + 1
    papers = [p for p in papers if p["id"] not in seen]
    if papers:
        ranked = rank_papers(papers, cfg)
        n = cfg["pipeline"]["drafts_per_day"]
        floor = cfg["pipeline"]["min_relevance_score"]
        good = [p for p in ranked if p.get("score", 0) >= floor]
        # papers first; news capped so feeds never crowd out research
        max_news = cfg["pipeline"].get("max_news_per_day", 1)
        research = [p for p in good if p.get("item_type", "paper") == "paper"]
        news = [p for p in good if p.get("item_type", "paper") != "paper"]
        picked = research[:n]
        for item in news[:max_news]:
            if len(picked) < n or item.get("score", 0) > 8.5:
                picked.append(item)
        picked = picked[:n + 1]
        if cfg["sources"].get("youtube_enrichment"):
            enrich_youtube(picked)
        for p in picked:
            queue.append(p)
            seen.add(p["id"])
        print(f"Picked {len(picked)} of {len(papers)} new items.")

    save_json("draft_queue.json", queue)
    save_json("seen_papers.json", sorted(seen)[-5000:])  # cap history


if __name__ == "__main__":
    main()
