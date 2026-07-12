# Engagement lessons (auto-updated 2026-07-12)

# Content Team: Lessons Learned Brief

## 1. Topic Performance

**Over-performed:** Humanoid locomotion/speed ("Marathon" post: 3L/1R/2Re), novel sensory modalities ("sonar drone": 3L/1R/1Re), and unusual/quirky applications ("cockroach suit": 1L/1Re, "vine robot": 2L/1Re, "STEMbot": 2L/1Re). Papers with a clear mechanical surprise outperform incremental improvement papers.

**Under-performed:** Mapping/localization (RLPR: 0 engagement), manipulation datasets (DynaMimicGen: 0), and agricultural soft grippers (0). Perception infrastructure papers consistently flatline.

---

## 2. Hook Styles That Worked

Conversational bold claims with a physical image ("Faster than a human. The secret is boring physics.") outperformed abstract tension setups. Hooks naming a concrete, surprising *object or action* performed better than hooks framing an unsolved problem.

---

## 3. Carousel vs. Video

All posts are carousels. No video data exists. **Cannot compare.**

### 3a. Hook-Style A/B

| Style | Total Likes | Reposts | Replies | Posts |
|---|---|---|---|---|
| bold_claim | 10 | 1 | 5 | 7 |
| curiosity_gap | 2 | 0 | 4 | 6 |
| tension | 2 | 0 | 3 | 7 |
| number_stat | 1 | 0 | 0 | 3 |

**Bold_claim leads on likes and reposts.** Curiosity_gap and tension drive comparable replies but almost no likes. Number_stat underperforms across all metrics despite seeming concrete.

**Recommended weighting: bold_claim 50% / tension 25% / curiosity_gap 20% / number_stat 5%**

### 3b. Bluesky Thread vs. Single

| Format | Avg Likes | Avg Reposts | Avg Replies |
|---|---|---|---|
| thread | 1.27 | 0.13 | 0.87 |
| single | 0.27 | 0.00 | 0.07 |

Threads outperform singles on every metric, roughly 3–5× on likes and ~12× on replies. The reply-thread structure likely creates a second impression surface.

**Recommended split: 70% thread / 30% single**

---

## 4. Concrete Recommendations

1. **Lead with the physical surprise, not the problem.** The two highest-performing hooks ("Faster than a human" / "sonar drone") name a concrete, counterintuitive outcome immediately. Rewrite any hook that opens with "Why does X still fail at Y" — convert it to what the paper *actually achieved* in physical terms.

2. **Prioritize quirky embodiment papers for thread slots.** Cockroach suit, STEMbot, vine robot, sonar drone all punched above their weight. When a paper involves an unusual organism, environment, or form factor, assign it a thread + bold_claim. Reserve singles for follow-up or lower-priority content.

3. **Data is too sparse for confident conclusions — run a controlled hook test.** With ~30 posts averaging <1 like each, variance dominates. For the next 10 posts, fix *topic tier* (locomotion or unusual embodiment only) and rotate only hook style. That will isolate hook effect from topic effect, which is currently confounded.
