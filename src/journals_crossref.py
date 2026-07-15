"""Journal papers via the Crossref API — the publishers' RSS feeds
(Science, Nature, Wiley, IEEE) bot-block GitHub runners, but Crossref
indexes the same papers with no wall. Polite-pool usage with a mailto."""
import re
import requests

MAILTO = "robopost@users.noreply.github.com"
JOURNALS = {
    # ISSN: (name, robotics_filter_needed)
    "2470-9476": ("Science Robotics", False),
    "2522-5839": ("Nature Machine Intelligence", True),
    "2041-1723": ("Nature Communications", True),
    "1556-4967": ("Journal of Field Robotics", False),
    "2377-3766": ("IEEE Robotics and Automation Letters", False),
    "1941-0468": ("IEEE Transactions on Robotics", False),
    "1552-3098": ("IEEE Transactions on Robotics", False),
}
ROBO = ("robot", "manipulat", "locomotion", "gripper", "drone", "uav",
        "autonomous vehicle", "quadruped", "humanoid", "swarm", "soft actuat",
        "exoskeleton", "teleoperation", "slam", "underwater vehicle")


def crossref_journal_papers(days: int = 14, per_journal: int = 12) -> list[dict]:
    from datetime import date, timedelta
    since = (date.today() - timedelta(days=days)).isoformat()
    items = []
    for issn, (name, needs_filter) in JOURNALS.items():
        try:
            r = requests.get(
                f"https://api.crossref.org/journals/{issn}/works",
                params={"filter": f"from-pub-date:{since},type:journal-article",
                        "sort": "published", "order": "desc",
                        "rows": per_journal, "mailto": MAILTO,
                        "select": "DOI,title,abstract,author,URL,published"},
                timeout=30, headers={"User-Agent": f"RoboPost/1.0 (mailto:{MAILTO})"})
            works = r.json().get("message", {}).get("items", [])
        except Exception as e:
            print(f"Crossref {name} failed (non-fatal): {e}")
            continue
        got = 0
        for w in works:
            title = " ".join(w.get("title") or [])[:300]
            if not title:
                continue
            abstract = re.sub(r"<[^>]+>", " ", w.get("abstract") or "")
            abstract = re.sub(r"\s+", " ", abstract).strip()
            blob = (title + " " + abstract).lower()
            if needs_filter and not any(k in blob for k in ROBO):
                continue
            authors = [f"{a.get('given', '')} {a.get('family', '')}".strip()
                       for a in (w.get("author") or [])[:6]]
            items.append({
                "id": "doi-" + w["DOI"].replace("/", "_")[:40],
                "title": title,
                "abstract": abstract[:1500] or title,
                "authors": authors,
                "url": w.get("URL") or f"https://doi.org/{w['DOI']}",
                "doi": w["DOI"],
                "source": name,
                "item_type": "paper",
                "journal": True,
            })
            got += 1
        print(f"Crossref {name}: {got} recent papers")
    return items


if __name__ == "__main__":
    for it in crossref_journal_papers():
        print(it["source"], "|", it["title"][:60])
