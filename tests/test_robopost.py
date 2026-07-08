"""Offline tests for RoboPost — no network, no API keys.
Covers every piece of logic that has actually broken in production."""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


# ── generation safety ───────────────────────────────────────────────
def test_fit_post_keeps_link_whole():
    from generate import fit_post
    link = "https://arxiv.org/abs/2507.01234"
    long = ("robots coordinate at scale because " * 12) + "\n" + link
    out = fit_post(long, 300, link)
    assert len(out) <= 300
    assert link in out and out.count(link) == 1


def test_fit_post_short_untouched():
    from generate import fit_post
    link = "https://arxiv.org/abs/1"
    assert fit_post("Short.\n" + link, 300, link) == "Short.\n" + link


def test_strip_dashes():
    from generate import strip_dashes
    out = strip_dashes({"a": "fast \u2014 very \u2013 fast", "b": ["3\u20135"]})
    flat = json.dumps(out)
    assert "\u2014" not in flat and "\u2013" not in flat


def test_ensure_complete_fills_everything():
    from generate import ensure_complete
    c = ensure_complete({}, {"title": "T", "abstract": "A", "url": "https://x.y/z"})
    for k in ("hook", "commentary", "slides", "video_script",
              "post_bluesky", "bluesky_thread", "caption_instagram",
              "caption_tiktok", "format"):
        assert c.get(k), k
    assert len(c["post_bluesky"]) <= 300


# ── ranking robustness ──────────────────────────────────────────────
def test_claude_json_salvages_truncation(monkeypatch):
    import utils
    monkeypatch.setattr(utils, "claude",
                        lambda *a, **k: '[{"i":0,"s":8.5},{"i":1,"s":7')
    assert utils.claude_json("x") == [{"i": 0, "s": 8.5}]


# ── manual add parsing ──────────────────────────────────────────────
def test_url_split_and_notes():
    import re
    blob = ("https://www.nature.com/articles/abc\n"
            "https://youtu.be/xyz\nEmphasize the hardware.")
    urls = re.findall(r"https?://[^\s)\]>\"']+", blob)
    yt = [u for u in urls if re.search(r"(youtube\.com|youtu\.be)/", u)]
    other = [u for u in urls if u not in yt]
    assert other == ["https://www.nature.com/articles/abc"]
    assert yt == ["https://youtu.be/xyz"]


# ── state merge (the git-conflict resolver) ─────────────────────────
def test_merge_drafts_status_precedence():
    from merge_state import merge
    ours = [{"draft_id": "a", "status": "in_review"},
            {"draft_id": "c", "status": "pending_review"}]
    theirs = [{"draft_id": "a", "status": "posted"}]
    out = {d["draft_id"]: d["status"] for d in merge("data/drafts.json", ours, theirs)}
    assert out == {"a": "posted", "c": "pending_review"}


def test_merge_seen_union():
    from merge_state import merge
    assert merge("data/seen_papers.json", ["p1", "p3"], ["p1", "p2"]) == ["p1", "p2", "p3"]


# ── bluesky image compression ───────────────────────────────────────
def test_compress_under_limit(tmp_path):
    from post_all import compress_for_bluesky
    from PIL import Image
    import random
    img = Image.frombytes("RGB", (1080, 1350),
                          bytes(random.getrandbits(8) for _ in range(1080 * 1350 * 3)))
    p = tmp_path / "card.png"
    img.save(p)
    assert len(compress_for_bluesky(p)) <= 950_000


# ── everything compiles ─────────────────────────────────────────────
def test_all_modules_compile():
    src = Path(__file__).resolve().parent.parent / "src"
    for f in src.glob("*.py"):
        subprocess.run([sys.executable, "-m", "py_compile", str(f)], check=True)
