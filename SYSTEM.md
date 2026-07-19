# RoboPost — System Invariants

Rules distilled from real production incidents. **Any modification must be
checked against this document before pushing.** Mechanically checkable rules
are enforced by `tests/test_invariants.py`, which CI runs on every push.

## Architecture (30 seconds)

Workflows: `daily_pipeline` (06:00 + dispatch) · `review_actions` (issue
events + sweep) · `post_queue` drainer (workflow_run chains + cron
best-effort) · `metrics` (nightly) · `trends` (6h) · `conference_radar`
(weekly) · `litreview` (dispatch) · `ack` (instant 👀) · `ci`.

Draft lifecycle: `pending_media → pending_review → in_review → approved →
posted`, with `rejected` from anywhere. `post_all` posts ONLY `approved`.

State: `data/*.json`, semantically merged by `src/merge_state.py` on
conflict. Media: `media/<draft_id>/`. Reports: `data/fetch_report.json`.

## Hard invariants (each caused a real failure)

### Git & state
1. **Never `git rebase --skip`** — it discards a run's commit (lost media →
   404 cards). Fallback is abort + `git pull --no-rebase -X ours`.
2. **Commit `data media docs`, never just `data`** — drainer once committed
   only data; issues embedded card URLs whose files never landed.
3. **Media commits BEFORE any issue references it.**
4. **Posting persists state IMMEDIATELY after each successful post** — before
   labels, finalize, anything. A crash after posting must never lose the
   record (that loss caused duplicate posting).
5. All state-writing workflows share `concurrency: robopost-data`. A separate
   group let two runs post the same drafts simultaneously.

### Events & scheduling
6. **GitHub cron and event delivery are unreliable.** Nothing may depend on a
   single event or a cron firing: every command/manual-add must be
   sweep-recoverable, and time-sensitive work rides `workflow_run` chains or
   user-triggered runs.
7. Concurrency cancels sibling runs: any surviving run must process ALL
   pending work (sweep after handle), not only its own trigger.
8. Sweeps mark items processed ONLY on success — failures must retry.

### Workflow env
9. Any step calling the GitHub API needs `GITHUB_TOKEN` +
   `GITHUB_REPOSITORY` env (missing env crashed posting AFTER Bluesky
   posted → repost bug).
10. Any step that renders cards needs `fonts-dejavu` installed and
    `ANTHROPIC_API_KEY` (vision vetting).
11. Cosmetic operations (labels, acks, comments) must NEVER be able to crash
    the money path — wrap non-fatally.

### Content correctness
12. **Never alter an image's aspect ratio.** Fit/letterbox only.
13. **An arXiv id may only be used after title verification**
    (`verify_arxiv_id`) — a stale id once pulled figures from the WRONG
    paper.
14. Figures pass Claude vision vetting before use; prefer arXiv source
    tarballs > repo assets > caption-anchored page render.
15. Full-text verification (`verify_paper_facts`) runs before writing;
    sim-only status must be stated plainly and shown on the issue.
16. Video/repo links are enforced at POST time (appended reply), never
    trusted to the writer.
17. Bluesky posting is idempotent: identical recent post text → skip.

### Selection & filters
18. Filters must degrade to "best available", never to "nothing" (adaptive
    floor). An empty queue is a worse failure than a mediocre draft.
19. News budget is per-DAY across runs (count open + posted today), not
    per-run.
20. Journal papers are exempt from the no-figure auto-reject.
21. Dedup is by id AND normalized title against FULL draft history (same
    content arrives under arXiv/RSS/manual id namespaces).
22. Manual adds / redos in the queue ALWAYS generate, regardless of buffer.

### Process (for the assistant making changes)
23. **Every text patch must `assert` its match and verify the written
    result.** Silent no-op replaces shipped at least four broken "fixes".
24. Structural claims get verified against parsed output (YAML load, grep of
    the actual file), not assumed from patch success.
25. New failure modes get a test in `tests/` the same day they're fixed.
26. After changing workflow topology (locks, triggers), trace EVERY posting
    path before pushing.
27. Run `ruff` + full test suite before every push.
