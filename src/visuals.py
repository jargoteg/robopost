"""Render branded carousel cards (PNG) for each draft with Pillow."""
import textwrap
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from utils import load_config, load_json, save_json, MEDIA

FONT_DIR = "/usr/share/fonts/truetype/dejavu"
FONT_BOLD = f"{FONT_DIR}/DejaVuSans-Bold.ttf"
FONT_REG = f"{FONT_DIR}/DejaVuSans.ttf"


def _font(path, size):
    return ImageFont.truetype(path, size)


def _wrap(draw, text, font, max_w):
    lines, line = [], ""
    for word in text.split():
        test = f"{line} {word}".strip()
        if draw.textlength(test, font=font) <= max_w:
            line = test
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def render_card(idx, total, title, body, footer, cfg) -> Image.Image:
    w, h = cfg["visuals"]["carousel_size"]
    bg, accent, fg = (cfg["visuals"][k] for k in ("bg_color", "accent_color", "text_color"))
    img = Image.new("RGB", (w, h), bg)
    d = ImageDraw.Draw(img)
    pad = 90

    # accent bar + page marker
    d.rectangle([0, 0, w, 14], fill=accent)
    d.text((w - pad, h - 70), f"{idx + 1}/{total}", font=_font(FONT_REG, 34), fill=accent, anchor="ra")

    # title
    y = pad + 40
    tf = _font(FONT_BOLD, 72 if idx == 0 else 60)
    for line in _wrap(d, title, tf, w - 2 * pad):
        d.text((pad, y), line, font=tf, fill=accent if idx == 0 else fg)
        y += tf.size + 14

    # body
    y += 40
    bf = _font(FONT_REG, 44)
    for line in _wrap(d, body, bf, w - 2 * pad):
        d.text((pad, y), line, font=bf, fill=fg)
        y += bf.size + 18

    # footer (handle + arXiv id)
    d.text((pad, h - 70), footer, font=_font(FONT_REG, 34), fill="#9AA4B2", anchor="la")
    return img


def build_carousel(draft, cfg) -> list[str]:
    c, p = draft["content"], draft["paper"]
    out_dir = MEDIA / draft["draft_id"]
    out_dir.mkdir(parents=True, exist_ok=True)
    if p.get("source", "arxiv") in ("arxiv", "hf_daily", "manual"):
        ref = f"arXiv:{p['id']}"
    else:
        from urllib.parse import urlparse
        ref = p.get("source") or urlparse(p["url"]).netloc.replace("www.", "")
    footer = f"{cfg['account']['handle']}  ·  {ref}"

    slides = [{"title": c["hook"], "body": p["title"]}] + c["slides"]
    slides.append({"title": "The takeaway", "body": c["commentary"]})
    paths = []
    for i, s in enumerate(slides):
        img = render_card(i, len(slides), s["title"], s["body"], footer, cfg)
        path = out_dir / f"slide_{i:02d}.png"
        img.save(path)
        paths.append(str(path.relative_to(MEDIA.parent)))
    return paths


def main():
    cfg = load_config()
    drafts = load_json("drafts.json", [])
    for d in drafts:
        if d["status"] != "pending_media":
            continue
        d["media"] = {"slides": build_carousel(d, cfg)}
        if d["content"]["format"] == "video":
            d["status"] = "pending_video"
        else:
            d["status"] = "pending_review"
        print(f"Rendered {len(d['media']['slides'])} cards for {d['draft_id']}")
    save_json("drafts.json", drafts)


if __name__ == "__main__":
    main()
