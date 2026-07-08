# RoboPost — automated robotics paper reviews for Instagram, TikTok & Bluesky

A GitHub-Actions-only system (no server) that every day: pulls recent robotics papers (arXiv + Hugging Face daily papers), ranks them with Claude, writes sharp review commentary, renders branded carousel cards and short narrated videos, sends drafts to your Telegram for approval, posts approved drafts to Bluesky / Instagram / TikTok, then collects engagement metrics and feeds lessons back into future content.

## How it works

```
06:00 UTC  daily_pipeline   fetch → rank → generate → render → Telegram drafts
every 30m  approvals        poll Telegram (/approve /reject /redo /add) → post
22:00 UTC  metrics          collect stats → Claude writes data/feedback.md
                            feedback.md is injected into ranking + writing prompts
```

All state lives in `data/*.json`, committed to the repo. `data/feedback.md` is the learning loop: the analyst step summarizes what performed well, and both the paper ranker and the copywriter read it on every run.

## Telegram commands (your control panel)

- `/approve <id>` — post the draft on the next 30-min cycle
- `/reject <id>` — discard it
- `/redo <id> your notes here` — regenerate with your feedback
- `/add https://arxiv.org/abs/XXXX.XXXXX` — manually queue any paper (jumps the queue)

## Setup

### 1. Repo
Create a **public** GitHub repo (public matters: Instagram's API fetches images by URL, and `media_base_url` in `config.yaml` points at your repo's raw URLs — set your username/repo there). Push these files. Enable Actions.

If you need the repo private, host images elsewhere and change `media_base_url`.

### 2. Telegram bot (5 minutes)
1. Message **@BotFather** → `/newbot` → copy the token → secret `TELEGRAM_BOT_TOKEN`
2. Message your new bot anything, then open `https://api.telegram.org/bot<TOKEN>/getUpdates` and copy your `chat.id` → secret `TELEGRAM_CHAT_ID`

### 3. Anthropic
API key from console.anthropic.com → secret `ANTHROPIC_API_KEY`. Expected cost at 2 drafts/day: a few dollars per month.

### 4. Bluesky (5 minutes)
Settings → App Passwords → create one. Secrets: `BLUESKY_HANDLE` (e.g. `you.bsky.social`), `BLUESKY_APP_PASSWORD`.

### 5. Instagram (the long one)
Requires an Instagram **Business or Creator** account linked to a Facebook Page.
1. developers.facebook.com → create an app → add **Instagram Graph API**
2. Generate a long-lived access token with `instagram_basic`, `instagram_content_publish`, `pages_show_list` (Graph API Explorer → extend token)
3. Get your IG user id: `GET /me/accounts` → page id → `GET /<page_id>?fields=instagram_business_account`
4. Secrets: `IG_ACCESS_TOKEN`, `IG_USER_ID`

Long-lived tokens last ~60 days — refresh and update the secret when it expires (the workflow logs will show auth failures).

### 6. TikTok
1. developers.tiktok.com → register app → request **Content Posting API**
2. Until your app passes TikTok's audit, the API only allows **upload to your inbox as a draft** — you tap publish in the app. That's what's implemented by default (and it pairs fine with your review-queue workflow). After audit approval, switch the endpoint in `src/post_all.py` to direct post.
3. Secret: `TIKTOK_ACCESS_TOKEN` (OAuth token with `video.upload` scope; TikTok tokens expire — refresh per their docs)

TikTok is the highest-friction platform here. The system degrades gracefully: if the token is missing/expired, other platforms still post.

### 7. GitHub secrets
Repo → Settings → Secrets and variables → Actions → add all of the above.

### 8. First run
Actions tab → "Daily content pipeline" → **Run workflow**. Drafts arrive in Telegram within ~5 minutes.

## Tuning
Everything lives in `config.yaml`: account voice, arXiv categories, boost keywords, drafts per day, colors, TTS voice, carousel/video sizes. The commentary style prompt is in `src/generate.py`.

## Notes & limits
- GitHub Actions free tier (2000 min/month) comfortably covers this (~15 min/day).
- Media accumulates in `media/`; prune old folders occasionally or add a cleanup step.
- Instagram Reels processing can take a couple of minutes; the poster waits up to 5.
- Disclose automation where platform rules require it; all content is human-approved by design.
