"""Render carousel cards — v2 design.
- gradient background + accent glow (no more flat black)
- real paper figures placed on cards, with author attribution
- emoji stripped from card text (Pillow fonts can't render them; captions
  posted to the platforms keep their emojis, where they render natively)
"""
import re
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from utils import load_config, load_json, save_json, MEDIA, ROOT
from figures import get_figures

FONT_DIR = "/usr/share/fonts/truetype/dejavu"
FONT_BOLD = f"{FONT_DIR}/DejaVuSans-Bold.ttf"
FONT_REG = f"{FONT_DIR}/DejaVuSans.ttf"

EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF"
    "\U00002190-\U000021FF\U00002B00-\U00002BFF\uFE0F\u200D]+")


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", EMOJI.sub("", text or "")).strip()


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


def _hex(c):
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def canvas(cfg):
    """Vertical gradient background with a soft accent glow."""
    w, h = cfg["visuals"]["carousel_size"]
    top, bottom = _hex("#101725"), _hex("#0A0D14")
    img = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(img)
    for y in range(h):
        t = y / h
        d.line([(0, y), (w, y)], fill=tuple(
            int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    glow = Image.new("RGB", (w, h), "#000000")
    gd = ImageDraw.Draw(glow)
    gd.ellipse([w - 620, -420, w + 320, 380], fill=cfg["visuals"]["accent_color"])
    gd.ellipse([-380, h - 520, 420, h + 380],
               fill=cfg["visuals"].get("accent2_color", cfg["visuals"]["accent_color"]))
    glow = glow.filter(ImageFilter.GaussianBlur(200))
    img = Image.blend(img, glow, 0.17)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, w, 12], fill=cfg["visuals"]["accent_color"])
    return img, d


def paste_figure(img, fig_path, box):
    """Fit a figure into box on a soft white rounded panel. Returns bottom y."""
    x0, y0, x1, y1 = box
    bw, bh = x1 - x0, y1 - y0
    fig = Image.open(ROOT / fig_path).convert("RGB")
    fig.thumbnail((bw - 40, bh - 40))
    panel = Image.new("RGB", (fig.width + 40, fig.height + 40), "#FAFAF7")
    panel.paste(fig, (20, 20))
    mask = Image.new("L", panel.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, panel.width, panel.height], 28, fill=255)
    px = x0 + (bw - panel.width) // 2
    py = y0 + (bh - panel.height) // 2
    img.paste(panel, (px, py), mask)
    return py + panel.height


def footer(img, d, cfg, ref, attribution=False, page=None):
    w, h = img.size
    pad = 84
    f = _font(FONT_REG, 32)
    left = f"{cfg['account']['handle']}  ·  {ref}"
    if attribution:
        left += "  ·  figures © the authors"
    d.text((pad, h - 64), left, font=f, fill="#A89F94", anchor="la")
    if page:
        d.text((w - pad, h - 64), f"{page[0]}/{page[1]}",
               font=_font(FONT_BOLD, 32), fill=cfg["visuals"]["accent_color"], anchor="ra")


def hero_card(cfg, hook, title, ref, fig, page=None):
    w, h = cfg["visuals"]["carousel_size"]
    pad = 84
    img, d = canvas(cfg)
    d.text((pad, pad + 8), "NEW IN ROBOTICS", font=_font(FONT_BOLD, 30),
           fill=cfg["visuals"]["accent_color"])
    y = pad + 70
    tf = _font(FONT_BOLD, 78)
    for line in _wrap(d, clean(hook), tf, w - 2 * pad)[:4]:
        d.text((pad, y), line, font=tf, fill="#FFFFFF")
        y += 88
    y += 26
    sf = _font(FONT_REG, 40)
    for line in _wrap(d, clean(title), sf, w - 2 * pad)[:3]:
        d.text((pad, y), line, font=sf, fill="#B9C2D0")
        y += 52
    if fig and y < h - 460:
        paste_figure(img, fig, (pad, y + 30, w - pad, h - 120))
    footer(img, d, cfg, ref, attribution=bool(fig), page=page)
    return img


def figure_card(cfg, fig, caption, ref, page=None):
    w, h = cfg["visuals"]["carousel_size"]
    pad = 84
    img, d = canvas(cfg)
    bottom = paste_figure(img, fig, (pad, pad, w - pad, int(h * 0.66)))
    y = bottom + 44
    cf = _font(FONT_REG, 42)
    for line in _wrap(d, clean(caption), cf, w - 2 * pad)[:6]:
        d.text((pad, y), line, font=cf, fill="#EDEFF3")
        y += 56
    footer(img, d, cfg, ref, attribution=True, page=page)
    return img


def text_card(cfg, title, body, ref, page=None):
    w, h = cfg["visuals"]["carousel_size"]
    pad = 84
    img, d = canvas(cfg)
    y = pad + 30
    tf = _font(FONT_BOLD, 62)
    for line in _wrap(d, clean(title), tf, w - 2 * pad)[:3]:
        d.text((pad, y), line, font=tf, fill=cfg["visuals"]["accent_color"])
        y += 74
    d.rectangle([pad, y + 10, pad + 130, y + 18], fill=cfg["visuals"]["accent_color"])
    y += 60
    bf = _font(FONT_REG, 46)
    for line in _wrap(d, clean(body), bf, w - 2 * pad)[:10]:
        d.text((pad, y), line, font=bf, fill="#EDEFF3")
        y += 62
    footer(img, d, cfg, ref, page=page)
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

    figs = draft.get("media", {}).get("figures") or get_figures(draft)
    draft.setdefault("media", {})["figures"] = figs

    # if figures came from an open version, credit THAT exact source, not the
    # paywalled origin — so every card is traceable to where its figure is from
    ov = p.get("open_version", "")
    if figs and ov:
        from urllib.parse import urlparse
        m = re.search(r"arxiv\.org/abs/(\S+)", ov)
        ref = f"arXiv:{m.group(1)}" if m else ("fig: " + urlparse(ov).netloc.replace("www.", ""))

    # plan cards: hero, then slides (figure-backed where figures remain), takeaway
    plan = []
    fig_i = 1
    for s in c["slides"]:
        if fig_i < len(figs):
            plan.append(("fig", figs[fig_i], f"{s['title']} — {s['body']}"))
            fig_i += 1
        else:
            plan.append(("txt", s["title"], s["body"]))
    plan.append(("txt", "The takeaway", c["commentary"]))
    total = len(plan) + 1

    def render(item, page):
        if item[0] == "hero":
            return hero_card(cfg, c["hook"], p["title"], ref,
                             figs[0] if figs else None, page)
        if item[0] == "fig":
            return figure_card(cfg, item[1], item[2], ref, page)
        return text_card(cfg, item[1], item[2], ref, page)

    full_plan = [("hero",)] + plan

    # Instagram/full set: numbered i/total
    paths = []
    for i, item in enumerate(full_plan):
        img = render(item, (i + 1, total))
        path = out_dir / f"slide_{i:02d}.png"
        img.save(path)
        paths.append(str(path.relative_to(MEDIA.parent)))

    # Bluesky set: FIGURE-FIRST, max 4, no numbering. The post text carries
    # the story; these cards are the visuals. Figures with one-line captions
    # dominate; text cards only fill gaps when figures are scarce.
    bsky_plan = []
    if figs:
        bsky_plan.append(("hero",))  # hero already leads with the figure
        fig_cards = [it for it in plan if it[0] == "fig"]
        for it in fig_cards[:3]:
            cap = it[2].split(". ")[0][:110]  # one line, the figure speaks
            bsky_plan.append(("fig", it[1], cap))
        for it in plan:
            if len(bsky_plan) >= 4:
                break
            if it[0] == "txt" and it not in bsky_plan and it[1] != "The takeaway":
                bsky_plan.append(it)
    else:
        idxs = [0] + list(range(1, min(3, len(full_plan) - 1))) + [len(full_plan) - 1]
        bsky_plan = [full_plan[i] for i in sorted(dict.fromkeys(idxs))]
    bsky = []
    for j, item in enumerate(bsky_plan[:4]):
        img = render(item, None)
        path = out_dir / f"bsky_{j:02d}.png"
        img.save(path)
        bsky.append(str(path.relative_to(MEDIA.parent)))
    draft.setdefault("media", {})["bsky"] = bsky
    return paths


def main():
    cfg = load_config()
    drafts = load_json("drafts.json", [])
    for d in drafts:
        if d["status"] != "pending_media":
            continue
        d.setdefault("media", {})["slides"] = build_carousel(d, cfg)
        d["status"] = "pending_video" if d["content"]["format"] == "video" else "pending_review"
        print(f"Rendered {len(d['media']['slides'])} cards "
              f"({len(d['media'].get('figures', []))} figures) for {d['draft_id']}")
    save_json("drafts.json", drafts)


if __name__ == "__main__":
    main()
