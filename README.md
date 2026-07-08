# RoboPost — automated robotics paper reviews for Instagram, TikTok & Bluesky

A GitHub-Actions-only system (no server) that every day: pulls recent robotics papers (arXiv + Hugging Face daily papers), ranks them with Claude, writes sharp review commentary, renders branded carousel cards and short narrated videos, opens a GitHub Issue per draft for your approval, posts approved drafts to Bluesky / Instagram / TikTok, then collects engagement metrics and feeds lessons back into future content.

## How it works

```
06:00 UTC  daily_pipeline   fetch → rank → generate → render → opens one
                            GitHub Issue per draft (cards embedded)
instant    review_actions   fires when you comment /approve, /reject, or
                            /redo <notes> on a draft issue → posts immediately
22:00 UTC  metrics          collect stats → Claude writes data/feedback.md
                            feedback.md is injected into ranking + writing prompts
```

All state lives in `data/*.json`, committed to the repo. `data/feedback.md` is the learning loop: the analyst step summarizes what performed well, and both the paper ranker and the copywriter read it on every run.

## Review workflow (your control panel = GitHub Issues)

Each draft arrives as an issue labeled `draft` with all cards, captions, and video link embedded. Comment on it:

- `/approve` — posts within ~1 minute; results and links reported back on the issue, then it closes
- `/reject` — discard
- `/redo your notes here` — regenerate with your feedback in the next daily run

**Manually add anything:** open a new issue containing a link. Supported:
- **arXiv links** → full paper metadata pulled from the arXiv API
- **any article URL** (Nature, Science Robotics, IEEE Spectrum, lab blogs, news) → page fetched, Claude extracts title/summary/source
- **YouTube link alongside** → attached and linked in the captions ("full video linked") — third-party footage is never re-uploaded, only linked
- **YouTube link alone** → the video itself becomes the item
- **any extra text** in the body → curator's notes the writer must follow

Example issue body:
```
https://www.nature.com/articles/s41586-025-xxxxx
https://youtu.be/xxxx
Emphasize the actuator design; be skeptical of the battery-life claim.
```
Items are queued instantly, jump the automatic queue, and the issue closes with a confirmation.

Install the GitHub mobile app and enable notifications for this repo — drafts land as push notifications. Only comments from the repo owner/collaborators are honored.

## Setup

### 1. Repo
Create a **public** GitHub repo (public matters: Instagram's API fetches images by URL, and `media_base_url` in `config.yaml` points at your repo's raw URLs — set your username/repo there). Push these files. Enable Actions.

If you need the repo private, host images elsewhere and change `media_base_url`.

### 2. Anthropic
API key from console.anthropic.com → secret `ANTHROPIC_API_KEY`. Expected cost at 2 drafts/day: a few dollars per month.

### 3. Bluesky (5 minutes)
Settings → App Passwords → create one. Secrets: `BLUESKY_HANDLE` (e.g. `you.bsky.social`), `BLUESKY_APP_PASSWORD`.

### 4. Instagram (the long one)
Requires an Instagram **Business or Creator** account linked to a Facebook Page.
1. developers.facebook.com → create an app → add **Instagram Graph API**
2. Generate a long-lived access token with `instagram_basic`, `instagram_content_publish`, `pages_show_list` (Graph API Explorer → extend token)
3. Get your IG user id: `GET /me/accounts` → page id → `GET /<page_id>?fields=instagram_business_account`
4. Secrets: `IG_ACCESS_TOKEN`, `IG_USER_ID`

Long-lived tokens last ~60 days — refresh and update the secret when it expires (the workflow logs will show auth failures).

### 5. TikTok
1. developers.tiktok.com → register app → request **Content Posting API**
2. Until your app passes TikTok's audit, the API only allows **upload to your inbox as a draft** — you tap publish in the app. That's what's implemented by default (and it pairs fine with your review-queue workflow). After audit approval, switch the endpoint in `src/post_all.py` to direct post.
3. Secret: `TIKTOK_ACCESS_TOKEN` (OAuth token with `video.upload` scope; TikTok tokens expire — refresh per their docs)

TikTok is the highest-friction platform here. The system degrades gracefully: if the token is missing/expired, other platforms still post.

### 6. GitHub secrets
Repo → Settings → Secrets and variables → Actions → add all of the above.

### 7. First run
Actions tab → "Daily content pipeline" → **Run workflow**. Draft issues appear in the Issues tab within ~5 minutes.

### 9. YouTube video enrichment (optional, recommended)
The pipeline searches YouTube for a project/demo video of each picked item and links it in the captions (videos are linked, never re-uploaded).
1. console.cloud.google.com → create project → enable **YouTube Data API v3** → Credentials → API key
2. Add secret `YOUTUBE_API_KEY`. Free quota easily covers daily use. If unset, the step is skipped silently.

## Content sources
Automatic daily pull now covers: arXiv (configurable categories), Hugging Face daily papers, and any RSS feeds in `config.yaml → sources.news_feeds` — preloaded with IEEE Spectrum robotics, The Robot Report, and Robohub, which carry RoboCup and other competition coverage. Add any feed URL (e.g. a specific competition's news feed) and it joins the ranking pool; `news_keywords` filters what's considered.

## Tuning
Everything lives in `config.yaml`: account voice, arXiv categories, boost keywords, drafts per day, colors, TTS voice, carousel/video sizes. The commentary style prompt is in `src/generate.py`.

## Notes & limits
- GitHub Actions free tier (2000 min/month) comfortably covers this (~15 min/day).
- Media accumulates in `media/`; prune old folders occasionally or add a cleanup step.
- Instagram Reels processing can take a couple of minutes; the poster waits up to 5.
- Disclose automation where platform rules require it; all content is human-approved by design.
