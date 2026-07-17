# Engagement lessons (auto-updated 2026-07-17)

# Lessons Learned Brief

## 1. Topic Performance
**Over-performed:** Medical robotics (endovascular, 4 likes), novel locomotion mechanics (SAWbot, underwater glider, hexapod), and dexterity/manipulation challenges. Tangible "why can't X do Y" framings outperform abstract systems papers.
**Under-performed:** Policy/regulatory content (humanoid policy: 0), pure navigation/localization papers (IMU, planetary rover), and anything without strong visuals (14 rejections for missing figures — a pipeline bottleneck).

## 2. Hook Styles That Worked
Curiosity gap led on reply generation (consistent 1-reply posts). Bold claim produced the single highest-like post (endovascular, 4 likes) but also the most zeros.

## 3. Carousel vs. Video
Carousels dominate the published slate. Both videos scored 0 likes, 1 reply each. **Data too sparse to conclude** — but video is not outperforming carousel yet.

### 3a. Hook-Style Weighting
| Hook | Avg Likes | Avg Replies |
|---|---|---|
| curiosity_gap | 1.4 | 0.9 |
| bold_claim | 0.8 | 0.7 |
| number_stat | 0.8 | 0.3 |
| tension | 0.2 | 0.7 |

**Recommended weighting: curiosity_gap 45%, bold_claim 30%, number_stat 15%, tension 10%**

### 3b. Thread vs. Single
Threads average ~1.0 replies vs. singles ~0.5. Likes are comparable. Threads drive conversation.
**Recommended split: 60% thread, 40% single**

## 4. Concrete Recommendations
1. **Gate on visuals first** — reject papers pre-hook-writing if figures are unavailable; it's the top rejection cause.
2. **Lead with human stakes** — posts framing a human frustration ("why can't robots X") outperform pure spec flexing.
3. **Retire tension hook as default** — 0.2 avg likes; only deploy it when the contrast is genuinely dramatic (e.g., QuadBoat, amoeba robot).
