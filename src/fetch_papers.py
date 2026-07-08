"""Fetch recent robotics papers (arXiv + HF daily papers), rank with Claude,
and enqueue the best ones as draft candidates. Manual additions in
data/manual_queue.json always take priority."""
import re
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from utils import load_config, load_json, save_json, claude_json, get_feedback_notes

NS = {"a": "http://www.w3.org/2005/Atom"}


def fetch_arxiv(cfg) -> list[dict]:
    cats = " OR ".join(f"cat:{c}" for c in cfg["sources"]["arxiv_categories"])
    url = (
        "http://export.arxiv.org/api/query"
        f"?search_query={cats}&sortBy=submittedDate&sortOrder=descending"
        f"&max_results={cfg['sources']['arxiv_max_results']}"
    )
    r = requests.get(url, timeout=30)
    r.raise_for_status()
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


def rank_papers(papers: list[dict], cfg) -> list[dict]:
    """Ask Claude to score papers for this account's audience."""
    feedback = get_feedback_notes()
    boost = ", ".join(cfg["sources"]["keywords_boost"])
    listing = "\n".join(
        f"[{i}] {p['title']} — {p['abstract'][:400]}" for i, p in enumerate(papers)
    )
    result = claude_json(
        f"""You curate papers for a social account about: {cfg['account']['niche']}.
Priority topics: {boost}.

Lessons learned from past engagement data:
{feedback}

Score each paper 0-10 for how compelling a social post about it would be
(novelty, visual/story potential, audience fit). Return JSON:
[{{"index": int, "score": float, "why": "one line"}}]

Papers:
{listing}""",
        system="You are a sharp robotics research curator.",
    )
    for r in result:
        i = r["index"]
        if 0 <= i < len(papers):
            papers[i]["score"] = r["score"]
            papers[i]["why_ranked"] = r["why"]
    return sorted(papers, key=lambda p: p.get("score", 0), reverse=True)


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

    # 2. Automatic fetch + rank
    papers = fetch_arxiv(cfg)
    if cfg["sources"]["hf_daily_papers"]:
        # keep HF entries that look robotics-adjacent
        kw = [k.lower() for k in cfg["sources"]["keywords_boost"]] + ["robot"]
        papers += [
            p for p in fetch_hf_daily()
            if any(k in (p["title"] + p["abstract"]).lower() for k in kw)
        ]
    papers = [p for p in papers if p["id"] not in seen]
    if papers:
        ranked = rank_papers(papers, cfg)
        n = cfg["pipeline"]["drafts_per_day"]
        floor = cfg["pipeline"]["min_relevance_score"]
        picked = [p for p in ranked if p.get("score", 0) >= floor][:n]
        for p in picked:
            queue.append(p)
            seen.add(p["id"])
        print(f"Picked {len(picked)} of {len(papers)} new papers.")

    save_json("draft_queue.json", queue)
    save_json("seen_papers.json", sorted(seen)[-5000:])  # cap history


if __name__ == "__main__":
    main()
