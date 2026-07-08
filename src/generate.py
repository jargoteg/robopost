"""Turn queued papers into platform-ready draft content using Claude.
Claude decides carousel vs video per paper, writes the review/commentary,
and produces captions tuned per platform — informed by feedback.md."""
import uuid
from datetime import datetime, timezone
from utils import load_config, load_json, save_json, claude_json, get_feedback_notes


def generate_draft(paper: dict, cfg) -> dict:
    feedback = get_feedback_notes()
    from conference_radar import conference_context
    conf = conference_context(cfg)
    result = claude_json(
        f"""You write content for a social media account: {cfg['account']['niche']}.
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

Item type: {paper.get('item_type', 'paper')} (paper = arXiv preprint; article =
journal/news/blog piece e.g. Nature or IEEE Spectrum; video = lab/company video).
Adapt: papers get review-style rigor; articles get context on why the news
matters; videos get commentary on what the demo does and doesn't prove.

Title: {paper['title']}
Source: {paper.get('source', 'arxiv')}
Authors/Org: {', '.join(paper.get('authors', []))}
Summary/Abstract: {paper['abstract']}
Link: {paper['url']}
{"Related YouTube video (title: " + paper.get('video_title','?') + "): " + paper['video_url'] + " — LINK it in captions (e.g. 'full video linked in comments/bio'); never re-upload footage. If the video title looks unrelated to this work, IGNORE it entirely." if paper.get('video_url') else ""}
{"Curator's notes (from the account owner — follow these): " + paper['user_notes'] if paper.get('user_notes') else ""}
{"Redo notes from previous rejection (must address): " + paper['redo_notes'] if paper.get('redo_notes') else ""}

RULES: no emojis in "hook" or "slides" (they render on image cards without
emoji fonts); emojis ARE fine in the platform captions. Slide bodies should
read like figure captions when possible — concrete, specific.

Produce JSON:
{{
  "format": "carousel" | "video",   // video only if the story has strong narrative punch
  "hook": "scroll-stopping first line, <90 chars",
  "commentary": "3-5 sentence sharp review: what it does, why it matters, one honest caveat",
  "slides": [                        // 4-{cfg['visuals']['max_slides']} slides for the carousel (always provide; video also uses them as frames)
    {{"title": "<=6 words", "body": "<=45 words, plain language"}}
  ],
  "video_script": "60-90 word narration for a short video, spoken style, ends with a question to the audience",
  "caption_instagram": "caption with hook, 3-4 short paragraphs, line breaks, 5-8 niche hashtags, cites the paper title + arXiv id",
  "caption_tiktok": "punchy 1-2 line caption + 4-6 hashtags",
  "post_bluesky": "THE MAIN POST, <=280 chars incl. the link {paper['url']}: hook plus the overarching story in miniature. This text carries the narrative; the images are support.",
  "bluesky_thread": ["1-2 reply posts, each <=290 chars: your sharp analysis, the honest caveat, and a question or take that invites replies. Conversational, no link repetition."]
}}""",
        system="You are an expert robotics researcher and social media writer.",
        max_tokens=4000,
    )
    result = strip_dashes(result)
    result = ensure_complete(result, paper)
    result["slides"] = result.get("slides", [])[: cfg["visuals"]["max_slides"]]
    return {
        "draft_id": uuid.uuid4().hex[:8],
        "paper": paper,
        "content": result,
        "status": "pending_media",
        "created": datetime.now(timezone.utc).isoformat(),
    }


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
        c["bluesky_thread"] = [commentary[:290]]
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
