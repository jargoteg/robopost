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
    return json.loads(m.group(0) if m else text)


def get_feedback_notes() -> str:
    """Learned insights from the engagement feedback loop."""
    p = DATA / "feedback.md"
    return p.read_text() if p.exists() else "No engagement data yet."


def env(key: str, required: bool = False) -> str:
    v = os.environ.get(key, "")
    if required and not v:
        raise RuntimeError(f"Missing required env var / secret: {key}")
    return v
