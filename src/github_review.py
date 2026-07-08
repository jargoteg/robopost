"""Review queue on GitHub Issues — event-driven, no polling, no extra tokens.

create   : opens one issue per pending_review draft (cards embedded)
handle   : processes an Actions event (issue comment or new issue):
             /approve                → mark approved (posted in same run)
             /reject                 → discard, close issue
             /redo <notes>           → regenerate with your notes
           a NEW issue containing an arXiv link → paper queued manually
finalize : after posting, comments results on the issue and closes it
Only comments from the repo owner/collaborators are honored.
"""
import json
import os
import re
import sys
import requests
from utils import load_config, load_json, save_json, env

API = "https://api.github.com"
ALLOWED = {"OWNER", "MEMBER", "COLLABORATOR"}


def gh(method: str, path: str, body: dict | None = None):
    r = requests.request(
        method, f"{API}/repos/{env('GITHUB_REPOSITORY', True)}{path}",
        headers={"Authorization": f"Bearer {env('GITHUB_TOKEN', True)}",
                 "Accept": "application/vnd.github+json"},
        json=body, timeout=30)
    if r.status_code >= 300:
        print(f"GitHub {method} {path}: {r.status_code} {r.text[:200]}")
    return r.json() if r.text else {}


def comment(num: int, text: str):
    gh("POST", f"/issues/{num}/comments", {"body": text})


def close(num: int):
    gh("PATCH", f"/issues/{num}", {"state": "closed"})


# ── create draft issues ─────────────────────────────────────────────
def create_issues():
    cfg = load_config()
    base = cfg["media_base_url"].rstrip("/")
    repo = env("GITHUB_REPOSITORY", True)
    drafts = load_json("drafts.json", [])
    for d in drafts:
        if d["status"] != "pending_review":
            continue
        c, p = d["content"], d["paper"]
        slides = "\n".join(
            f"![slide {i}]({base}/{rel})" for i, rel in
            enumerate(d.get("media", {}).get("slides", []))
        )
        video = d.get("media", {}).get("video")
        video_md = (f"\n🎬 [Watch the generated video]"
                    f"(https://github.com/{repo}/blob/main/{video})\n" if video else "")
        body = f"""**[{c['format'].upper()}]** {p['title']}
{p['url']}

### 🪝 Hook
{c['hook']}

### 💬 Commentary
{c['commentary']}

### Bluesky post
```
{c['post_bluesky']}
```

### Instagram caption
```
{c['caption_instagram']}
```

### TikTok caption
```
{c['caption_tiktok']}
```
{video_md}
### Cards
{slides}

---
**Reply with a comment:** `/approve` · `/reject` · `/redo <your notes>`
"""
        issue = gh("POST", "/issues", {
            "title": f"[DRAFT {d['draft_id']}] {p['title'][:80]}",
            "body": body[:65000], "labels": ["draft"]})
        d["issue"] = issue.get("number")
        d["status"] = "in_review"
        print(f"Issue #{d['issue']} for draft {d['draft_id']}")
    save_json("drafts.json", drafts)


# ── handle comment / new-issue events ───────────────────────────────
def handle_event():
    with open(os.environ["GITHUB_EVENT_PATH"]) as f:
        ev = json.load(f)
    drafts = load_json("drafts.json", [])
    by_issue = {d.get("issue"): d for d in drafts if d.get("issue")}

    if "comment" in ev:  # issue_comment event
        num = ev["issue"]["number"]
        text = ev["comment"]["body"].strip()
        assoc = ev["comment"].get("author_association", "")
        d = by_issue.get(num)
        if not d or assoc not in ALLOWED or d["status"] != "in_review":
            print("Comment ignored (no matching draft / not authorized).")
            return
        if re.match(r"/approve\b", text):
            d["status"] = "approved"
            comment(num, "✅ Approved — posting now. Results will follow here.")
        elif re.match(r"/reject\b", text):
            d["status"] = "rejected"
            comment(num, "🗑 Rejected.")
            close(num)
        elif m := re.match(r"/redo\s*(.*)", text, re.S):
            d["status"] = "rejected"
            paper = dict(d["paper"], redo_notes=m.group(1).strip())
            queue = load_json("draft_queue.json", [])
            queue.insert(0, paper)
            save_json("draft_queue.json", queue)
            comment(num, "🔁 Will regenerate with your notes in the next daily run.")
            close(num)

    elif ev.get("action") == "opened" and "issue" in ev:  # manual paper add
        issue = ev["issue"]
        if "[bot]" in issue["user"]["login"]:
            return
        if any(l["name"] == "draft" for l in issue.get("labels", [])):
            return
        blob = f"{issue['title']} {issue.get('body') or ''}"
        m = re.search(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})", blob) \
            or re.search(r"\b(\d{4}\.\d{4,5})\b", blob)
        if not m:
            return
        paper = fetch_arxiv_by_id(m.group(1))
        num = issue["number"]
        if paper:
            manual = load_json("manual_queue.json", [])
            manual.append(paper)
            save_json("manual_queue.json", manual)
            comment(num, f"➕ Queued for the next daily run: **{paper['title']}**")
        else:
            comment(num, f"Couldn't resolve arXiv id `{m.group(1)}`.")
        close(num)

    save_json("drafts.json", drafts)


def fetch_arxiv_by_id(pid: str):
    import xml.etree.ElementTree as ET
    ns = {"a": "http://www.w3.org/2005/Atom"}
    r = requests.get(f"http://export.arxiv.org/api/query?id_list={pid}", timeout=30)
    try:
        e = ET.fromstring(r.text).find("a:entry", ns)
        if e is None or e.find("a:title", ns) is None:
            return None
        return {
            "id": pid,
            "title": re.sub(r"\s+", " ", e.find("a:title", ns).text).strip(),
            "abstract": re.sub(r"\s+", " ", e.find("a:summary", ns).text).strip(),
            "authors": [a.find("a:name", ns).text for a in e.findall("a:author", ns)][:6],
            "url": f"https://arxiv.org/abs/{pid}",
            "source": "manual",
        }
    except Exception:
        return None


# ── post-run cleanup ────────────────────────────────────────────────
def finalize():
    posted = {p["draft_id"]: p for p in load_json("posted.json", [])}
    drafts = load_json("drafts.json", [])
    for d in drafts:
        if d["status"] == "posted" and d.get("issue") and not d.get("finalized"):
            ids = posted.get(d["draft_id"], {}).get("platform_ids", {})
            lines = "\n".join(
                f"- **{k}**: {'✅ ' + str(v) if v else '❌ failed (see run logs)'}"
                for k, v in ids.items())
            comment(d["issue"], f"📤 Posted:\n{lines}")
            close(d["issue"])
            d["finalized"] = True
    save_json("drafts.json", drafts)


if __name__ == "__main__":
    {"create": create_issues, "handle": handle_event, "finalize": finalize}[sys.argv[1]]()
