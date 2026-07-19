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


def gh(method: str, path: str, body: dict | None = None, quiet_404: bool = False):
    r = requests.request(
        method, f"{API}/repos/{env('GITHUB_REPOSITORY', True)}{path}",
        headers={"Authorization": f"Bearer {env('GITHUB_TOKEN', True)}",
                 "Accept": "application/vnd.github+json"},
        json=body, timeout=30)
    if r.status_code >= 300 and not (quiet_404 and r.status_code == 404):
        print(f"GitHub {method} {path}: {r.status_code} {r.text[:200]}")
    return r.json() if r.text else {}


def comment(num: int, text: str):
    gh("POST", f"/issues/{num}/comments", {"body": text})


def close(num: int):
    gh("PATCH", f"/issues/{num}", {"state": "closed"})


# status labels (with colors) that make the Issues tab scannable at a glance
STATUS_LABELS = {
    "needs-review": "fbca04",   # yellow  — your attention needed
    "approved": "0e8a16",       # green   — okayed, waiting to post
    "queued-to-post": "1d76db", # blue    — scheduled, spacing out
    "posted": "5319e7",         # purple  — live
    "rejected": "b60205",       # red     — discarded
    "post-failed": "e11d21",    # bright red — needs a look
}


def ensure_labels():
    """Create the status labels once (idempotent)."""
    existing = {lb["name"] for lb in (gh("GET", "/labels?per_page=100") or [])}
    for name, color in STATUS_LABELS.items():
        if name not in existing:
            gh("POST", "/labels", {"name": name, "color": color})


def set_status_label(num: int, status: str):
    """Swap the issue's status label to `status`, removing other status labels.
    Keeps the 'draft' label intact."""
    if not num:
        return
    for name in STATUS_LABELS:
        if name != status:
            gh("DELETE", f"/issues/{num}/labels/{name}", quiet_404=True)
    gh("POST", f"/issues/{num}/labels", {"labels": [status]})


def maybe_topup():
    """Flag regeneration if the review buffer is running low. Called after
    every approve/reject so top-ups ride on YOUR actions, not the flaky
    GitHub scheduler."""
    from utils import load_config
    drafts = load_json("drafts.json", [])
    open_now = sum(1 for x in drafts if x.get("status") in
                   ("pending_media", "pending_video", "pending_review", "in_review"))
    target = load_config()["pipeline"].get("review_buffer", 6)
    if open_now < max(1, target - 2):
        print(f"Buffer low ({open_now}/{target}); flagging top-up.")
        flag_regen()
        return True
    return False


def flag_regen():
    """Tell the workflow to run the generation steps in this same run."""
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a") as f:
            f.write("regen=true\n")


# ── create draft issues ─────────────────────────────────────────────
def create_issues():
    cfg = load_config()
    ensure_labels()
    base = cfg["media_base_url"].rstrip("/")
    repo = env("GITHUB_REPOSITORY", True)
    drafts = load_json("drafts.json", [])
    for d in drafts:
        if d["status"] != "pending_review":
            continue
        if d.get("issue"):
            # re-rendered draft: issue already exists, refresh it in place
            d["status"] = "in_review"
            comment(d["issue"], "🔄 Cards re-rendered (media had failed to "
                                "upload). The images above should load now — "
                                "refresh if cached.")
            set_status_label(d["issue"], "needs-review")
            continue
        c, p = d["content"], d["paper"]
        v = d["paper"].get("verified") or {}
        vline = ""
        if v:
            icon = {"real": "🤖 real hardware", "sim": "⚠️ SIMULATION ONLY",
                    "mixed": "🤖 hardware + sim"}.get(v.get("hardware"), "")
            if icon:
                vline = f"**Verified from full text:** {icon}. {v.get('summary', '')}\n\n"
        slides = "\n".join(
            f"![slide {i}]({base}/{rel})" for i, rel in
            enumerate(d.get("media", {}).get("slides", []))
        )
        video = d.get("media", {}).get("video")
        video_md = (f"\n🎬 [Watch the generated video]"
                    f"(https://github.com/{repo}/blob/main/{video})\n" if video else "")
        body = vline + f"""**[{c.get('format','carousel').upper()}]** {p['title']}
{p['url']}

### 🪝 Hook
{c.get('hook', '(missing — will be filled at post time)')}

### 💬 Commentary
{c.get('commentary', '(missing — will be filled at post time)')}

### Bluesky post (the story lives here)
```
{c.get('post_bluesky', '(missing — will be filled at post time)')}
```
**Thread replies:**
```
{chr(10).join(c.get('bluesky_thread', []) or ['(none)'])}
```

### Instagram caption
```
{c.get('caption_instagram', '(missing — will be filled at post time)')}
```

### TikTok caption
```
{c.get('caption_tiktok', '(missing — will be filled at post time)')}
```
{video_md}
### Cards
{slides}

---
**Labels:** 🟡needs-review · 🟢approved · 🔵queued-to-post · 🟣posted · 🔴rejected
**Reply with a comment:** `/approve` · `/reject <why>` · `/redo <notes>` · `/refig` (re-hunt figures incl. open-access + YouTube)
"""
        issue = gh("POST", "/issues", {
            "title": f"[DRAFT {d['draft_id']}] {p['title'][:80]}",
            "body": body[:65000], "labels": ["draft", "needs-review"]})
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
        mark_processed(ev["comment"].get("id"))
        apply_command(d, text, num)
        save_json("drafts.json", drafts)
        # concurrency can cancel sibling comment-runs; catch their commands now
        try:
            sweep()
        except Exception as e:
            print(f"post-handle sweep failed (non-fatal): {e}")

    elif ev.get("action") == "opened" and "issue" in ev:  # manual item add
        handle_new_issue(ev["issue"])


def mark_processed(cid):
    if not cid:
        return
    st = load_json("state.json", {})
    done = st.get("processed_comments", [])
    if cid not in done:
        done.append(cid)
    st["processed_comments"] = done[-500:]
    save_json("state.json", st)


def is_processed(cid):
    return cid in load_json("state.json", {}).get("processed_comments", [])


def apply_command(d, text, num):
        if re.match(r"/approve\b", text):
            d["status"] = "approved"
            set_status_label(num, "approved")
            comment(num, "✅ Approved — posting shortly (spaced to avoid flooding "
                         "your feed). This issue closes once it's live.")
            maybe_topup()
        elif m := re.match(r"/reject\b\s*(.*)", text, re.S):
            d["status"] = "rejected"
            reason = m.group(1).strip()
            rej = load_json("rejections.json", [])
            rej.append({"title": d["paper"]["title"], "source": d["paper"].get("source"),
                        "item_type": d["paper"].get("item_type", "paper"),
                        "reason": reason or "no reason given",
                        "date": __import__("datetime").date.today().isoformat()})
            save_json("rejections.json", rej[-200:])
            set_status_label(num, "rejected")
            maybe_topup()
            if reason:
                comment(num, f"🗑 Rejected. Noted for future curation: \"{reason}\"")
            else:
                comment(num, "🗑 Rejected. Tip: add a reason (/reject too incremental) "
                             "and the system learns what to avoid.")
            close(num)
        elif re.match(r"/refig\b", text):
            # re-run figure extraction in place (uses the open-version fallback)
            try:
                from figures import get_figures
                import visuals
                cfg = load_config()
                # force a fresh figure hunt, ignoring any cached figures
                d.get("media", {}).pop("figures", None)
                figs = get_figures(d)
                if figs:
                    d.setdefault("media", {})["figures"] = figs
                    visuals.build_carousel(d, cfg)  # re-renders slides + bsky set
                    base = cfg["media_base_url"].rstrip("/")
                    cards = "\n".join(
                        f"![card {i}]({base}/{rel})"
                        for i, rel in enumerate(d["media"].get("bsky", [])))
                    src = d["paper"].get("open_version", "")
                    extra = f"\n\nFigures from open version: {src}" if src else ""
                    comment(num, f"🖼 Found {len(figs)} figure(s) and re-rendered the "
                                 f"cards:{extra}\n\n{cards}\n\n_Approve to post with these._")
                else:
                    comment(num, "🔍 No figures found even via open-access lookup or "
                                 "YouTube search. This one stays text-only.")
            except Exception as e:
                comment(num, f"refig failed (non-fatal): {e}")

        elif m := re.match(r"/redo\s*(.*)", text, re.S):
            d["status"] = "rejected"
            paper = dict(d["paper"], redo_notes=m.group(1).strip())
            queue = load_json("draft_queue.json", [])
            queue.insert(0, paper)
            save_json("draft_queue.json", queue)
            flag_regen()
            set_status_label(num, "rejected")
            comment(num, "🔁 Regenerating with your notes — a fresh draft issue "
                         "will appear here in a few minutes.")
            close(num)

def handle_new_issue(issue):
        if "[bot]" in issue["user"]["login"]:
            return
        if any(lb["name"] == "draft" for lb in issue.get("labels", [])):
            return
        num = issue["number"]
        item = resolve_item(issue["title"], issue.get("body") or "")
        if item:
            queue = load_json("draft_queue.json", [])
            queue.insert(0, item)
            save_json("draft_queue.json", queue)
            seen = set(load_json("seen_papers.json", []))
            seen.add(item["id"])
            save_json("seen_papers.json", sorted(seen))
            flag_regen()
            extra = " (+ YouTube video attached)" if item.get("video_url") else ""
            comment(num, f"➕ **{item['title']}**{extra} — drafting now, a draft "
                         f"issue will appear in a few minutes.")
        else:
            comment(num, "Couldn't find a usable link in this issue. Include an "
                         "arXiv link, or any article URL (Nature, IEEE Spectrum, "
                         "blog...). Optionally add a YouTube link and notes.")
        close(num)


def resolve_item(title: str, body: str):
    """Turn a manual-add issue into a content item. Accepts:
    - arXiv links (full metadata via arXiv API)
    - any other article URL (Nature, IEEE Spectrum, news, blogs) —
      page is fetched and Claude extracts title/summary/source
    - an optional YouTube link (attached as video_url, linked in captions)
    - any remaining text becomes user_notes for the writer."""
    import hashlib
    from utils import fetch_url_text, claude_json

    blob = f"{title}\n{body}"
    urls = re.findall(r"https?://[^\s)\]>\"']+", blob)
    yt = [u for u in urls if re.search(r"(youtube\.com|youtu\.be)/", u)]
    other = [u for u in urls if u not in yt]
    notes = re.sub(r"https?://[^\s)\]>\"']+", "", body).strip()

    item = None
    # arXiv first-class
    m = re.search(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})", blob) \
        or (not other and re.search(r"\b(\d{4}\.\d{4,5})\b", blob))
    if m:
        item = fetch_arxiv_by_id(m.group(1))
    elif other:
        url = other[0]
        try:
            page = fetch_url_text(url)
            meta = claude_json(
                f"""Extract metadata for a robotics social-media post from this page.
Return JSON: {{"title": "...", "summary": "4-8 sentence factual summary of the
work/announcement", "source_name": "e.g. Nature, IEEE Spectrum, Boston Dynamics blog",
"authors_or_org": ["..."], "is_robotics_relevant": true|false}}

URL: {url}
{page}""",
                system="You extract clean metadata from web pages.")
            jnames = load_config().get("sources", {}).get("journal_names", [])
            src_l = (meta.get("source_name", "") + " " + url).lower()
            is_journal = any(j in src_l for j in jnames)
            item = {
                "id": "web-" + hashlib.sha1(url.encode()).hexdigest()[:10],
                "title": meta["title"],
                "abstract": meta["summary"],
                "authors": meta.get("authors_or_org", [])[:6],
                "url": url,
                "source": meta.get("source_name", "web"),
                "item_type": "paper" if is_journal else "article",
                "journal": is_journal,
            }
        except Exception as e:
            print(f"Generic URL resolution failed for {url}: {e}")
            item = None
    elif yt:
        # video-only submission: use the YouTube page itself as the item
        url = yt[0]
        try:
            page = fetch_url_text(url)
            meta = claude_json(
                f"Extract from this YouTube page. JSON: {{\"title\": \"...\", "
                f"\"summary\": \"what the video shows, 3-6 sentences\", "
                f"\"authors_or_org\": [\"channel/lab\"]}}\n\nURL: {url}\n{page}",
                system="You extract clean metadata from web pages.")
            item = {
                "id": "yt-" + hashlib.sha1(url.encode()).hexdigest()[:10],
                "title": meta["title"], "abstract": meta["summary"],
                "authors": meta.get("authors_or_org", [])[:6],
                "url": url, "source": "youtube", "item_type": "video",
            }
        except Exception as e:
            print(f"YouTube resolution failed: {e}")

    if item:
        if yt and item.get("source") != "youtube":
            item["video_url"] = yt[0]
        if notes:
            item["user_notes"] = notes[:1500]
        item.setdefault("item_type", "paper")
        item["source"] = item.get("source") or "manual"
    return item


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
            def fmt(v):
                if v == "skipped":
                    return "⏭ skipped (platform not configured yet)"
                return f"✅ {v}" if v else "❌ failed (see run logs)"
            lines = "\n".join(f"- **{k}**: {fmt(v)}" for k, v in ids.items())
            comment(d["issue"], f"📤 Posted:\n{lines}")
            close(d["issue"])
            d["finalized"] = True
        elif (d["status"] == "approved" and d.get("issue")
              and d.get("scheduled_after") and not d.get("queue_notified")):
            comment(d["issue"], f"⏱ Approved and queued. Posting after "
                                f"{d['scheduled_after'][11:16]} UTC to space out "
                                f"your feed (queue drains every 30 min). "
                                f"Live queue: see the dashboard.")
            d["queue_notified"] = True
        elif (d["status"] == "approved" and d.get("issue")
              and d.get("post_failures", 0) > d.get("failures_notified", 0)):
            comment(d["issue"], "⚠️ Posting failed on all configured platforms. "
                                "It will retry automatically on the next review "
                                "action or daily run. Check the Actions logs if "
                                "it keeps failing.")
            d["failures_notified"] = d["post_failures"]
    save_json("drafts.json", drafts)


def sweep():
    """Scheduled safety net: process any command comments on open draft
    issues that the instant run missed (e.g. cancelled by concurrency)."""
    drafts = load_json("drafts.json", [])
    by_issue = {d.get("issue"): d for d in drafts if d.get("issue")}
    open_issues = gh("GET", "/issues?labels=draft&state=open&per_page=50")
    if not isinstance(open_issues, list):
        print(f"Sweep: unexpected issues response, skipping: {str(open_issues)[:120]}")
        return
    open_issues = [i for i in open_issues if "pull_request" not in i]
    acted = 0
    for issue in open_issues:
        num = issue["number"]
        d = by_issue.get(num)
        if not d or d["status"] != "in_review":
            continue
        comments = gh("GET", f"/issues/{num}/comments?per_page=30")
        if not isinstance(comments, list):
            continue
        for c in comments:
            text = (c.get("body") or "").strip()
            if not text.startswith("/"):
                continue
            if c.get("author_association") not in ALLOWED:
                continue
            if is_processed(c.get("id")):
                continue
            mark_processed(c.get("id"))
            print(f"Sweep: processing missed command on #{num}: {text[:40]}")
            apply_command(d, text, num)
            acted += 1
            break
    save_json("drafts.json", drafts)
    # also: manual-add issues whose 'opened' event was lost (no draft label,
    # created by a human, never acknowledged)
    st = load_json("state.json", {})
    done_issues = set(st.get("processed_issues", []))
    all_open = gh("GET", "/issues?state=open&per_page=50")
    if isinstance(all_open, list):
        for issue in all_open:
            if "pull_request" in issue:
                continue
            if any(lb["name"] == "draft" for lb in issue.get("labels", [])):
                continue
            if "[bot]" in issue["user"]["login"]:
                continue
            if issue["number"] in done_issues:
                continue
            body = (issue.get("body") or "") + " " + (issue.get("title") or "")
            if "http" not in body:
                continue
            print(f"Sweep: processing missed manual add #{issue['number']}")
            before = len(load_json("draft_queue.json", []))
            try:
                handle_new_issue(issue)
                after = len(load_json("draft_queue.json", []))
                if after > before:
                    done_issues.add(issue["number"])
                    acted += 1
                else:
                    print(f"  #{issue['number']} did not resolve; will retry next sweep.")
            except Exception as e:
                print(f"manual add #{issue['number']} failed (will retry): {e}")
    st["processed_issues"] = sorted(done_issues)[-300:]
    save_json("state.json", st)
    print(f"Sweep done, {acted} missed item(s) processed.")


def backfill_labels():
    """One-shot: apply status labels to existing open draft issues."""
    ensure_labels()
    drafts = load_json("drafts.json", [])
    by_issue = {d.get("issue"): d for d in drafts if d.get("issue")}
    open_issues = gh("GET", "/issues?labels=draft&state=open&per_page=100")
    if not isinstance(open_issues, list):
        return
    smap = {"in_review": "needs-review", "pending_review": "needs-review",
            "approved": "approved", "posted": "posted", "rejected": "rejected"}
    for issue in open_issues:
        if "pull_request" in issue:
            continue
        d = by_issue.get(issue["number"])
        if not d:
            continue
        label = smap.get(d["status"])
        if d["status"] == "approved" and d.get("scheduled_after"):
            label = "queued-to-post"
        if d.get("post_failures", 0) > 0:
            label = "post-failed"
        if label:
            set_status_label(issue["number"], label)
            print(f"#{issue['number']} -> {label}")


if __name__ == "__main__":
    {"create": create_issues, "handle": handle_event, "finalize": finalize, "sweep": sweep, "backfill": backfill_labels}[sys.argv[1]]()
