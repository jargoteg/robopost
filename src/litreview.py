"""Literature review drafts: themed deep-dives synthesizing 4-6 papers into
one thread — cover card + one figure card per paper. Themes live in
data/litreview_themes.json; each run consumes the first unfinished theme.
Reviews occupy EXTRA slots beyond drafts_per_day."""
import re
import uuid
import hashlib
import requests
from utils import load_json, save_json, load_config, claude_json


def arxiv_search(query: str, n: int = 8) -> list[dict]:
    try:
        q = requests.utils.quote(f"all:{query}")
        r = requests.get(
            f"http://export.arxiv.org/api/query?search_query={q}"
            f"&max_results={n}&sortBy=relevance",
            timeout=30, headers={"User-Agent": "RoboPost/1.0"})
        import xml.etree.ElementTree as ET
        ns = {"a": "http://www.w3.org/2005/Atom"}
        out = []
        for e in ET.fromstring(r.text).findall("a:entry", ns):
            aid = e.findtext("a:id", "", ns).split("/abs/")[-1].split("v")[0]
            title = re.sub(r"\s+", " ", e.findtext("a:title", "", ns)).strip()
            summary = re.sub(r"\s+", " ", e.findtext("a:summary", "", ns)).strip()
            year = (e.findtext("a:published", "", ns) or "")[:4]
            out.append({"id": aid, "title": title,
                        "abstract": summary[:800], "year": year})
        return out
    except Exception as ex:
        print(f"arXiv search failed '{query[:30]}': {ex}")
        return []


def gather_pool(theme: dict) -> list[dict]:
    import time
    pool, seen = [], set()
    for p in theme.get("extra_papers", []):
        if p.get("id") and p["id"] not in seen:
            seen.add(p["id"])
            pool.append(p)
    queries = [theme.get("seed", "")] + theme.get("keywords", [])
    for q in [q for q in queries if q]:
        got = arxiv_search(q, 8)
        if not got:  # arXiv rate limit: wait and retry once
            time.sleep(4)
            got = arxiv_search(q, 8)
        print(f"  litreview query '{q[:40]}': {len(got)} results")
        for p in got:
            if p["id"] not in seen:
                seen.add(p["id"])
                pool.append(p)
        time.sleep(3)  # arXiv API etiquette
    # enrich with Semantic Scholar recommendations from the anchor paper
    anchor = next((p for p in pool if theme.get("seed", "").lower()[:40]
                   in p["title"].lower()), pool[0] if pool else None)
    if anchor:
        try:
            r = requests.get(
                "https://api.semanticscholar.org/recommendations/v1/papers/"
                f"forpaper/arXiv:{anchor['id']}",
                params={"limit": 10, "fields": "title,abstract,externalIds,year"},
                timeout=30, headers={"User-Agent": "RoboPost/1.0"})
            recs = r.json().get("recommendedPapers", [])
            added = 0
            for w in recs:
                aid = (w.get("externalIds") or {}).get("ArXiv")
                if aid and aid not in seen:
                    seen.add(aid)
                    pool.append({"id": aid, "title": w.get("title", ""),
                                 "abstract": (w.get("abstract") or "")[:800],
                                 "year": str(w.get("year", ""))})
                    added += 1
            print(f"  S2 recommendations: +{added} related papers")
        except Exception as e:
            print(f"  S2 recommendations failed: {e}")
    return pool


def build_review(theme: dict, cfg) -> dict | None:
    pool = gather_pool(theme)
    if len(pool) < 4:
        print(f"Litreview: pool too small ({len(pool)}) for '{theme['topic']}'")
        return None
    listing = "\n".join(
        f"[{i}] ({p['year']}) {p['title']} — {p['abstract'][:220]}"
        for i, p in enumerate(pool[:30]))
    sel = claude_json(f"""You are curating a literature deep-dive thread for a
robotics account. Theme: {theme['topic']}.
{('Anchor paper (MUST be included if present in the list): ' + theme['seed']) if theme.get('seed') else ''}
{('Bonus preference: ' + theme['bonus']) if theme.get('bonus') else ''}

Candidate papers:
{listing}

Select 4-6 papers that together tell a coherent story of this subfield
(origins -> key ideas -> state of the art). Write the thread. Style rules:
never use em dashes or en dashes; no AI-sounding phrasing; a researcher
talking to peers over coffee; specifics over hype.

Return JSON:
{{"title": "review title, <70 chars",
 "hook": "scroll-stopping opening for the main post, <200 chars, frames the theme as a question or tension",
 "picks": [{{"i": <index>, "take": "<220 chars: what THIS paper contributed to the story, concrete>"}}],
 "synthesis": "<250 chars: where the subfield is heading, one open question>"}}""")
    idx = [p["i"] for p in sel.get("picks", []) if 0 <= p.get("i", -1) < len(pool)]
    if len(idx) < 3:
        print("Litreview: selection too small; skipping.")
        return None
    chosen = [pool[i] for i in idx]
    takes = [p["take"] for p in sel["picks"]][:len(chosen)]

    # one vetted figure per selected paper
    from figures import arxiv_figures, vet_figures
    from utils import MEDIA
    rid = "review-" + hashlib.sha1(sel["title"].encode()).hexdigest()[:8]
    draft_id = uuid.uuid4().hex[:8]
    out_dir = MEDIA / draft_id
    out_dir.mkdir(parents=True, exist_ok=True)
    figures, kept_papers, kept_takes = [], [], []
    for p, take in zip(chosen, takes):
        sub = out_dir / p["id"].replace(".", "_")
        sub.mkdir(exist_ok=True)
        figs = arxiv_figures({"id": p["id"]}, sub, max_figs=3)
        best = vet_figures(figs, p["title"], max_keep=1)
        if best:
            figures.append(best[0])
            kept_papers.append(p)
            kept_takes.append(take)
    if len(kept_papers) < 3:
        print("Litreview: fewer than 3 papers with clean figures; skipping.")
        return None

    thread = [f"{t} arxiv.org/abs/{p['id']}"[:290]
              for p, t in zip(kept_papers, kept_takes)]
    thread.append(sel.get("synthesis", "")[:290])
    return {
        "draft_id": draft_id,
        "status": "pending_review",
        "paper": {
            "id": rid, "title": sel["title"],
            "abstract": sel.get("synthesis", ""),
            "authors": [],
            "url": f"https://arxiv.org/abs/{kept_papers[0]['id']}",
            "source": "litreview", "item_type": "litreview",
            "review_papers": [p["id"] for p in kept_papers],
        },
        "content": {
            "format": "carousel",
            "hook": sel["hook"],
            "post_bluesky": sel["hook"][:290],
            "bluesky_thread": thread,
            "caption_instagram": sel["hook"] + "\n\n" + "\n".join(thread),
            "hook_style": "litreview",
        },
        "media": {"figures": figures},
    }


def maybe_build(cfg) -> bool:
    lit = cfg["pipeline"].get("litreview", {})
    if not lit.get("enabled"):
        return False
    themes = load_json("litreview_themes.json", [])
    pending = [t for t in themes if not t.get("done")]
    if not pending:
        return False
    drafts = load_json("drafts.json", [])
    open_reviews = [d for d in drafts if d["paper"].get("item_type") == "litreview"
                    and d["status"] in ("pending_media", "pending_review", "in_review")]
    if open_reviews:
        return False  # one review in flight at a time
    from datetime import datetime, timezone, timedelta
    last = max((d.get("created", "") for d in drafts
                if d["paper"].get("item_type") == "litreview"), default="")
    every = timedelta(days=lit.get("every_days", 3))
    now = datetime.now(timezone.utc)
    if last:
        try:
            if now - datetime.fromisoformat(last) < every:
                return False
        except Exception:
            pass
    theme = pending[0]
    print(f"Litreview: building '{theme['topic']}'")
    d = build_review(theme, cfg)
    if not d:
        return False
    d["created"] = now.isoformat()
    drafts.append(d)
    save_json("drafts.json", drafts)
    theme["done"] = True
    save_json("litreview_themes.json", themes)
    from visuals import build_carousel
    d["media"]["slides"] = build_carousel(d, cfg)
    save_json("drafts.json", drafts)
    print(f"Litreview draft {d['draft_id']}: {len(d['media']['figures'])} papers with figures")
    return True


if __name__ == "__main__":
    # standalone run (workflow_dispatch): force-build the next pending theme
    cfg = load_config()
    themes = load_json("litreview_themes.json", [])
    pending = [t for t in themes if not t.get("done")]
    if not pending:
        print("No pending litreview themes.")
    else:
        d = build_review(pending[0], cfg)
        if d:
            from datetime import datetime, timezone
            d["created"] = datetime.now(timezone.utc).isoformat()
            drafts = load_json("drafts.json", [])
            drafts.append(d)
            save_json("drafts.json", drafts)
            pending[0]["done"] = True
            save_json("litreview_themes.json", themes)
            from visuals import build_carousel
            d["media"]["slides"] = build_carousel(d, cfg)
            save_json("drafts.json", drafts)
            print(f"Review draft {d['draft_id']} built: "
                  f"{len(d['media']['figures'])} papers with figures")
