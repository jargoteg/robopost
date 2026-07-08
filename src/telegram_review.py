"""Review queue over Telegram — no server needed.

send  : pushes pending_review drafts to your Telegram chat (media + captions)
poll  : reads your replies via getUpdates and acts on commands:
          /approve <id>            → mark approved (posted by post_all.py)
          /reject <id>             → discard
          /redo <id> <notes>       → regenerate content with your notes
          /add <arxiv url or id>   → add paper to manual queue
"""
import re
import sys
import requests
from utils import load_json, save_json, env, ROOT

API = "https://api.telegram.org/bot{token}/{method}"


def tg(method, token, **kwargs):
    files = kwargs.pop("files", None)
    r = requests.post(API.format(token=token, method=method),
                      data=kwargs, files=files, timeout=120)
    if not r.ok:
        print(f"Telegram {method} error: {r.text[:300]}")
    return r.json()


def send_drafts():
    token, chat = env("TELEGRAM_BOT_TOKEN", True), env("TELEGRAM_CHAT_ID", True)
    drafts = load_json("drafts.json", [])
    for d in drafts:
        if d["status"] != "pending_review":
            continue
        c, p = d["content"], d["paper"]
        head = (
            f"📄 DRAFT {d['draft_id']}  [{c['format'].upper()}]\n"
            f"{p['title']}\n{p['url']}\n\n"
            f"🪝 {c['hook']}\n\n💬 {c['commentary']}\n\n"
            f"— Bluesky —\n{c['post_bluesky']}\n\n"
            f"— IG caption —\n{c['caption_instagram'][:700]}\n\n"
            f"Reply:  /approve {d['draft_id']}  ·  /reject {d['draft_id']}  ·  "
            f"/redo {d['draft_id']} <notes>"
        )
        tg("sendMessage", token, chat_id=chat, text=head[:4000])
        # first 3 cards as preview
        for rel in d.get("media", {}).get("slides", [])[:3]:
            with open(ROOT / rel, "rb") as f:
                tg("sendPhoto", token, chat_id=chat, files={"photo": f})
        vid = d.get("media", {}).get("video")
        if vid:
            with open(ROOT / vid, "rb") as f:
                tg("sendVideo", token, chat_id=chat, files={"video": f})
        d["status"] = "in_review"
    save_json("drafts.json", drafts)


def poll():
    token = env("TELEGRAM_BOT_TOKEN", True)
    state = load_json("state.json", {"tg_offset": 0})
    updates = tg("getUpdates", token, offset=state["tg_offset"] + 1, timeout=0)
    drafts = load_json("drafts.json", [])
    manual = load_json("manual_queue.json", [])
    by_id = {d["draft_id"]: d for d in drafts}

    for u in updates.get("result", []):
        state["tg_offset"] = u["update_id"]
        text = (u.get("message", {}).get("text") or "").strip()
        chat = u.get("message", {}).get("chat", {}).get("id")

        if m := re.match(r"/approve\s+(\w+)", text):
            d = by_id.get(m.group(1))
            if d:
                d["status"] = "approved"
                tg("sendMessage", token, chat_id=chat, text=f"✅ {m.group(1)} approved — posting on next cycle.")
        elif m := re.match(r"/reject\s+(\w+)", text):
            d = by_id.get(m.group(1))
            if d:
                d["status"] = "rejected"
                tg("sendMessage", token, chat_id=chat, text=f"🗑 {m.group(1)} rejected.")
        elif m := re.match(r"/redo\s+(\w+)\s*(.*)", text, re.S):
            d = by_id.get(m.group(1))
            if d:
                d["status"] = "pending_media"
                d["redo_notes"] = m.group(2)
                d["paper"]["redo_notes"] = m.group(2)
                # push paper back through generation with notes
                queue = load_json("draft_queue.json", [])
                queue.insert(0, d["paper"])
                save_json("draft_queue.json", queue)
                d["status"] = "rejected"
                tg("sendMessage", token, chat_id=chat, text=f"🔁 {m.group(1)} will be regenerated with your notes.")
        elif m := re.match(r"/add\s+(\S+)", text):
            raw = m.group(1)
            pid = raw.rstrip("/").split("/abs/")[-1].split("arxiv.org/")[-1]
            paper = fetch_arxiv_by_id(pid)
            if paper:
                manual.append(paper)
                tg("sendMessage", token, chat_id=chat, text=f"➕ Queued: {paper['title'][:80]}")
            else:
                tg("sendMessage", token, chat_id=chat, text=f"Couldn't resolve arXiv id from: {raw}")

    save_json("drafts.json", drafts)
    save_json("manual_queue.json", manual)
    save_json("state.json", state)


def fetch_arxiv_by_id(pid: str):
    import xml.etree.ElementTree as ET
    ns = {"a": "http://www.w3.org/2005/Atom"}
    r = requests.get(f"http://export.arxiv.org/api/query?id_list={pid}", timeout=30)
    try:
        e = ET.fromstring(r.text).find("a:entry", ns)
        title = e.find("a:title", ns)
        if title is None:
            return None
        return {
            "id": pid,
            "title": re.sub(r"\s+", " ", title.text).strip(),
            "abstract": re.sub(r"\s+", " ", e.find("a:summary", ns).text).strip(),
            "authors": [a.find("a:name", ns).text for a in e.findall("a:author", ns)][:6],
            "url": f"https://arxiv.org/abs/{pid}",
            "source": "manual",
        }
    except Exception:
        return None


if __name__ == "__main__":
    {"send": send_drafts, "poll": poll}[sys.argv[1]]()
