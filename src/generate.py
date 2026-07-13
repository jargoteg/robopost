"""Turn queued papers into platform-ready draft content using Claude.
Claude decides carousel vs video per paper, writes the review/commentary,
and produces captions tuned per platform — informed by feedback.md."""
import uuid
from datetime import datetime, timezone
from utils import load_config, load_json, save_json, claude_json, get_feedback_notes, get_trends


HOOK_STYLES = {
    "curiosity_gap": 'Open a curiosity gap the reader must resolve: "Ever wondered '
                     'how...", "Why does nobody...", "There is a reason robots '
                     'cannot..." The payoff comes in the thread/slides, not the hook.',
    "bold_claim": "Open with the single most surprising claim of the work, stated "
                  "flatly as fact. No hedging in the hook; nuance comes later.",
    "number_stat": "Open with the most striking NUMBER in the work and what it "
                   "beats or breaks. Concrete units, no adjectives.",
    "tension": "Open with the contradiction or tension the work resolves: what "
               "everyone believed vs what this shows, or the tradeoff it escapes.",
}


def pick_hook_style() -> str:
    """Rotate hook styles deterministically so the learning loop can compare."""
    from utils import load_json as _lj
    n = len(_lj("drafts.json", []))
    return list(HOOK_STYLES)[n % len(HOOK_STYLES)]


def generate_draft(paper: dict, cfg) -> dict:
    feedback = get_feedback_notes()
    hook_style = pick_hook_style()
    from conference_radar import conference_context
    conf = conference_context(cfg)
    # Resolve the code repo (and open-access version) BEFORE writing, so the
    # copy can link them. Best-effort and non-fatal.
    try:
        import re as _re
        from figures import find_open_version, find_github_repo
        aid = paper["id"] if _re.match(r"\d{4}\.\d{4,5}", str(paper.get("id", ""))) else None
        if not aid and paper.get("item_type") == "paper" and not paper.get("repo_url"):
            info = find_open_version(paper.get("title", ""), paper.get("authors"))
            if info and info.get("arxiv_id"):
                aid = info["arxiv_id"]
                paper["open_version"] = f"https://arxiv.org/abs/{aid}"
        if aid and not paper.get("repo_url"):
            repo = find_github_repo(paper.get("title", ""), aid)
            if repo:
                paper["repo_url"] = f"https://github.com/{repo}"
    except Exception as e:
        print(f"pre-generation repo lookup skipped: {e}")
    result = claude_json(
        f"""Today's date: {__import__('datetime').date.today().strftime('%B %d, %Y')}.
Use it: "this year" means {__import__('datetime').date.today().year}, recent
events are relative to today, never assume an older year.

You write content for a social media account: {cfg['account']['niche']}.
This account has a special interest in FIELD and INSPECTION robotics: real
robots doing real work (subsea, mining, construction, agriculture, nuclear,
search and rescue, infrastructure inspection, legged/all-terrain). When an
item is in that space, lean into the practical deployment story, the harsh
real-world conditions, and why lab results don't always survive the field.

If this item has a VIDEO (video_url present), the post is built AROUND the
footage: the hook describes the most striking thing you can SEE happening
("watch it recover mid-slip", "the arm threads a bolt underwater"), the
video link goes in the main post, and the thread explains how it works and
links the paper. Footage first, mechanism second, paper third.

Voice: a researcher talking to peers over coffee. Opinionated, specific,
concrete numbers over adjectives. Point out what's genuinely clever, what's
overhyped, limitations, and why it matters. Never fabricate results not
implied by the abstract.

STYLE RULES (hard requirements):
- NEVER use em dashes or en dashes anywhere. Use commas, periods, or colons.
- No AI cliches: never "delve", "groundbreaking", "game-changer",
  "revolutionize", "landscape", "unleash", "it's not just X, it's Y",
  "isn't just about". No breathless hype.
- Short sentences. Contractions are fine. Write like a sharp human, not a
  press release.
- Where it genuinely fits, connect the work to related landmark research or
  current events the audience knows (e.g. a multi-agent paper to this year's
  RoboCup results, a manipulation paper to a famous benchmark). One line max,
  only when the connection is real.

Lessons from past engagement (apply them):
{feedback}

{conf}

{get_trends()}

Item type: {paper.get('item_type', 'paper')} (paper = arXiv preprint; article =
journal/news/blog piece e.g. Nature or IEEE Spectrum; video = lab/company video).
Adapt: papers get review-style rigor; articles get context on why the news
matters; videos get commentary on what the demo does and doesn't prove.

Title: {paper['title']}
Source: {paper.get('source', 'arxiv')}
Authors/Org: {', '.join(paper.get('authors', []))}
Summary/Abstract: {paper.get('abstract', paper.get('title', ''))}
Link: {paper['url']}
{"Official code repository (link it in a thread reply — devs love this, and it drives saves/reposts): " + paper['repo_url'] if paper.get('repo_url') else ""}
{"Open-access version of this paper (link it so followers can read it, since the primary source may be paywalled): " + paper['open_version'] if paper.get('open_version') else ""}
{"Related YouTube video (title: " + paper.get('video_title','?') + "): " + paper['video_url'] + " — LINK it in captions (e.g. 'full video linked in comments/bio'); never re-upload footage. If the video title looks unrelated to this work, IGNORE it entirely." if paper.get('video_url') else ""}
{"Curator's notes (from the account owner — follow these): " + paper['user_notes'] if paper.get('user_notes') else ""}
{"Redo notes from previous rejection (must address): " + paper['redo_notes'] if paper.get('redo_notes') else ""}

RULES: no emojis in "hook" or "slides" (they render on image cards without
emoji fonts); emojis ARE fine in the platform captions. Slide bodies should
read like figure captions when possible — concrete, specific.

Produce JSON:
{{
  "format": "carousel" | "video",   // video only if the story has strong narrative punch
  "hook": "scroll-stopping first line, <90 chars. STYLE FOR THIS POST ({hook_style}): {HOOK_STYLES[hook_style]} The first 3 words decide everything. One idea only.",
  "commentary": "3-5 sentence sharp review: what it does, why it matters, one honest caveat",
  "slides": [                        // 4-{cfg['visuals']['max_slides']} slides for the carousel (always provide; video also uses them as frames)
    {{"title": "<=6 words", "body": "<=45 words, plain language"}}
  ],
  "video_script": "60-90 word narration for a short video, spoken style, ends with a question to the audience",
  "caption_instagram": "caption with hook, 3-4 short paragraphs, line breaks, 5-8 niche hashtags, cites the paper title + arXiv id",
  "caption_tiktok": "punchy 1-2 line caption + 4-6 hashtags",
  "post_bluesky": "THE MAIN POST, <=240 chars incl. the link {paper['url']}: hook plus the overarching story in miniature. This text carries the narrative; the images are support.",
  "bluesky_thread": ["1-2 reply posts, each <=270 chars: your sharp analysis, the honest caveat, and a question or take that invites replies. Conversational, no link repetition."]
}}""",
        system="You are an expert robotics researcher and social media writer.",
        max_tokens=4000,
    )
    result = strip_dashes(result)
    result = ensure_complete(result, paper)
    result["slides"] = result.get("slides", [])[: cfg["visuals"]["max_slides"]]
    result["hook_style"] = hook_style
    # format is decided by CODE, not model whim (119 drafts, zero videos):
    # any draft with real footage is a video post built around that footage
    if paper.get("video_url"):
        result["format"] = "video"
    return {
        "draft_id": uuid.uuid4().hex[:8],
        "paper": paper,
        "content": result,
        "status": "pending_media",
        "created": datetime.now(timezone.utc).isoformat(),
    }


def fit_post(text: str, limit: int = 300, keep_link: str = "") -> str:
    """Fit text within Bluesky's limit at a word boundary, never cropping
    the link. Trims the prose, keeps the URL whole."""
    text = text.strip()
    if len(text) <= limit:
        return text
    if keep_link and keep_link in text:
        prose = text.replace(keep_link, "").strip()
        room = limit - len(keep_link) - 2
        prose = prose[:room].rsplit(" ", 1)[0].rstrip(" ,.;:") + "…"
        return f"{prose}\n{keep_link}"
    return text[:limit - 1].rsplit(" ", 1)[0].rstrip(" ,.;:") + "…"


def strip_dashes(obj):
    """Hard-enforce the no-em/en-dash rule on all generated text."""
    if isinstance(obj, str):
        return (obj.replace(" \u2014 ", ", ").replace("\u2014", ", ")
                   .replace(" \u2013 ", ", ").replace("\u2013", "-"))
    if isinstance(obj, list):
        return [strip_dashes(x) for x in obj]
    if isinstance(obj, dict):
        return {k: strip_dashes(v) for k, v in obj.items()}
    return obj


def ensure_complete(c: dict, paper: dict) -> dict:
    """Guarantee every field downstream code relies on exists."""
    hook = c.get("hook") or paper["title"][:88]
    commentary = c.get("commentary") or paper["abstract"][:400]
    c["hook"] = hook
    c["commentary"] = commentary
    c.setdefault("format", "carousel")
    if not c.get("slides"):
        c["slides"] = [{"title": "What it is", "body": paper["abstract"][:220]}]
    c.setdefault("video_script", f"{hook}. {commentary}")
    link = paper.get("url", "")
    if not c.get("post_bluesky"):
        room = 280 - len(link) - 2
        c["post_bluesky"] = f"{hook[:max(0, room)]}\n{link}".strip()
    if not c.get("bluesky_thread"):
        c["bluesky_thread"] = [commentary]
    c["post_bluesky"] = fit_post(c["post_bluesky"], 300, link)
    c["bluesky_thread"] = [fit_post(t, 300) for t in c["bluesky_thread"][:2]]
    if not c.get("caption_instagram"):
        c["caption_instagram"] = f"{hook}\n\n{commentary}\n\n{paper['title']} — {link}"
    if not c.get("caption_tiktok"):
        c["caption_tiktok"] = f"{hook} #robotics"
    return c


def main():
    cfg = load_config()
    queue = load_json("draft_queue.json", [])
    drafts = load_json("drafts.json", [])
    if not queue:
        print("No papers in queue.")
        return
    todo, remaining = queue[: cfg["pipeline"]["drafts_per_day"] + 2], queue[cfg["pipeline"]["drafts_per_day"] + 2:]
    for paper in todo:
        try:
            d = generate_draft(paper, cfg)
            drafts.append(d)
            print(f"Draft {d['draft_id']} [{d['content']['format']}]: {paper['title'][:60]}")
        except Exception as e:
            print(f"Generation failed for {paper['id']}: {e}")
            remaining.append(paper)  # retry tomorrow
    save_json("draft_queue.json", remaining)
    save_json("drafts.json", drafts)


if __name__ == "__main__":
    main()
