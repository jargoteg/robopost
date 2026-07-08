"""Shared helpers: config, JSON storage, Claude API client."""
import json
import os
import re
import yaml
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
MEDIA = ROOT / "media"
DATA.mkdir(exist_ok=True)
MEDIA.mkdir(exist_ok=True)


def load_config() -> dict:
    with open(ROOT / "config.yaml") as f:
        return yaml.safe_load(f)


def load_json(name: str, default):
    p = DATA / name
    if p.exists():
        with open(p) as f:
            return json.load(f)
    return default


def save_json(name: str, obj):
    with open(DATA / name, "w") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)


def claude(prompt: str, system: str = "", max_tokens: int = 4000) -> str:
    """Single-turn Claude call returning text."""
    import anthropic
    client = anthropic.Anthropic()  # ANTHROPIC_API_KEY from env
    cfg = load_config()
    msg = client.messages.create(
        model=cfg["pipeline"]["model"],
        max_tokens=max_tokens,
        system=system or "You are a concise assistant.",
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(b.text for b in msg.content if b.type == "text")


def claude_json(prompt: str, system: str = "", max_tokens: int = 4000):
    """Claude call that must return JSON; strips fences and parses."""
    text = claude(
        prompt + "\n\nRespond ONLY with valid JSON. No markdown fences, no prose.",
        system=system,
        max_tokens=max_tokens,
    )
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    # Tolerate leading/trailing junk by grabbing outermost braces/brackets
    m = re.search(r"[\[{].*[\]}]", text, flags=re.S)
    raw = m.group(0) if m else text
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Salvage a truncated/glitched ARRAY: trim to the last complete object
        start = raw.find("[")
        if start != -1:
            end = raw.rfind("}")
            while end > start:
                try:
                    return json.loads(raw[start:end + 1] + "]")
                except json.JSONDecodeError:
                    end = raw.rfind("}", start, end)
        raise


def get_feedback_notes() -> str:
    """Learned insights from the engagement feedback loop."""
    p = DATA / "feedback.md"
    return p.read_text() if p.exists() else "No engagement data yet."


def env(key: str, required: bool = False) -> str:
    v = os.environ.get(key, "")
    if required and not v:
        raise RuntimeError(f"Missing required env var / secret: {key}")
    return v


def fetch_url_text(url: str, limit: int = 8000) -> str:
    """Fetch a web page and return readable text (for Claude extraction)."""
    import requests
    from bs4 import BeautifulSoup
    r = requests.get(url, timeout=30, headers={
        "User-Agent": "Mozilla/5.0 (compatible; RoboPost/1.0)"})
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()
    title = soup.title.string.strip() if soup.title and soup.title.string else ""
    text = " ".join(soup.get_text(" ").split())
    return f"PAGE TITLE: {title}\n\n{text[:limit]}"
