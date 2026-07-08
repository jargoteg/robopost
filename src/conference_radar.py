"""Conference radar — keeps data/conferences.json current so the pipeline
knows when DARS, RSS, ICRA, MRS, IROS, CoRL, RoboCup etc. are near (paper
surges on arXiv, results announcements, competition coverage).

Runs weekly: Claude + its web_search tool look up the next edition of each
tracked conference and write dates/location/status to conferences.json.
"""
import json
import re
from datetime import datetime, timezone, timedelta, date
from utils import load_config, load_json, save_json


def refresh_calendar():
    import anthropic
    cfg = load_config()
    tracked = cfg["conferences"]["track"]
    today = date.today().isoformat()
    client = anthropic.Anthropic()
    msg = client.messages.create(
        model=cfg["pipeline"]["model"],
        max_tokens=3000,
        tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 8}],
        messages=[{"role": "user", "content":
            f"""Today is {today}. Find the NEXT upcoming edition (or currently
running / just-ended edition within the last 2 weeks) of each robotics
conference: {', '.join(tracked)}.
Notes: RSS = Robotics: Science and Systems. DARS = Distributed Autonomous
Robotic Systems. MRS = IEEE Multi-Robot Systems (DARS and MRS are biennial).
RoboCup = the annual RoboCup competition.

After searching, output ONLY a JSON array (no prose):
[{{"name": "ICRA", "year": 2027, "start": "YYYY-MM-DD", "end": "YYYY-MM-DD",
  "location": "City, Country", "confidence": "confirmed|estimated"}}]
Omit a conference only if you find nothing at all."""}],
    )
    text = "".join(b.text for b in msg.content if b.type == "text")
    m = re.search(r"\[.*\]", text, flags=re.S)
    if not m:
        print("Radar: no JSON in response; keeping previous calendar.")
        return
    cal = json.loads(m.group(0))
    save_json("conferences.json", {
        "updated": datetime.now(timezone.utc).isoformat(), "conferences": cal})
    print(f"Calendar updated: {[(c['name'], c.get('start')) for c in cal]}")


def active_windows(cfg) -> list[dict]:
    """Conferences currently inside their boost window."""
    cal = load_json("conferences.json", {}).get("conferences", [])
    before = timedelta(days=cfg["conferences"]["window_before_days"])
    after = timedelta(days=cfg["conferences"]["window_after_days"])
    today = date.today()
    out = []
    for c in cal:
        try:
            start = date.fromisoformat(c["start"])
            end = date.fromisoformat(c.get("end") or c["start"])
        except (KeyError, ValueError, TypeError):
            continue
        if start - before <= today <= end + after:
            c = dict(c)
            c["phase"] = ("upcoming" if today < start
                          else "running" if today <= end else "just_ended")
            c["days_to_start"] = (start - today).days
            out.append(c)
    return out


def conference_context(cfg) -> str:
    """One-paragraph context string injected into ranking & writing prompts."""
    wins = active_windows(cfg)
    if not wins:
        return ""
    lines = []
    for c in wins:
        if c["phase"] == "upcoming":
            lines.append(f"{c['name']} {c.get('year','')} ({c.get('location','')}) "
                         f"starts in {c['days_to_start']} days — expect accepted-paper "
                         f"announcements and previews; prioritize them.")
        elif c["phase"] == "running":
            lines.append(f"{c['name']} is HAPPENING NOW in {c.get('location','')} — "
                         f"prioritize results, awards, demos, competition outcomes.")
        else:
            lines.append(f"{c['name']} just ended — best-paper awards and highlight "
                         f"threads perform well right now.")
    return "CONFERENCE CONTEXT: " + " ".join(lines)


def preview_items(cfg) -> list[dict]:
    """Seed a 'conference preview' item once per conference, 7-14 days out."""
    seen = set(load_json("seen_papers.json", []))
    items = []
    for c in active_windows(cfg):
        cid = f"confprev-{c['name']}-{c.get('year')}"
        if c["phase"] == "upcoming" and 3 <= c["days_to_start"] <= 14 and cid not in seen:
            items.append({
                "id": cid,
                "title": f"{c['name']} {c.get('year','')} preview — what to watch",
                "abstract": (f"{c['name']} {c.get('year','')} runs {c.get('start')} to "
                             f"{c.get('end')} in {c.get('location','TBD')}. Create a "
                             f"preview post: what the conference is, why it matters, "
                             f"themes to watch this year."),
                "authors": [], "url": "", "source": "conference_radar",
                "item_type": "article",
            })
    return items


if __name__ == "__main__":
    refresh_calendar()
