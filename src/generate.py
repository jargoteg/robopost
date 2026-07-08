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
Voice: knowledgeable but accessible; opinionated commentary, not press-release
summaries. Point out what's genuinely clever, what's overhyped, limitations,
and why it matters. Never fabricate results not implied by the abstract.

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
  "post_bluesky": "<=280 chars incl. the arXiv link {paper['url']}, no hashtags spam (max 2)"
}}""",
        system="You are an expert robotics researcher and social media writer.",
        max_tokens=3000,
    )
    result["slides"] = result.get("slides", [])[: cfg["visuals"]["max_slides"]]
    return {
        "draft_id": uuid.uuid4().hex[:8],
        "paper": paper,
        "content": result,
        "status": "pending_media",
        "created": datetime.now(timezone.utc).isoformat(),
    }


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
