# 0269 — the click loop deleted the leg, and the guard called it progress

**Date:** 2026-08-28
**Status:** Decided (measured; the loop does not ship)

## Context

The operator proposed refining an incomplete mask by seeding SAM 3's visual path
with the mask we have, clicking in its own leftover, and repeating — SAM's own
training procedure, and the best-aimed idea in this investigation. Their step
was "take the largest candidate"; I changed it to take the HIGHEST-SCORING,
citing upstream's "the model's predicted quality score can be used to select the
best mask" and 0198's measured merge at 113,465 px.

It ran on the study table, frame 50, seeded from the 342,215 px desk mask that
0266 established as the right input, for four rounds.

## What we tried

**The loop deleted the leg in round 0 and never recovered it.**

| round | result | added | removed | scores |
|---|---|---|---|---|
| seed | 342,215 | — | — | — |
| 0 | 289,485 (**−52,730**) | 4,572 | **57,302** | 0.9766 / 0.9727 / 0.9336 |
| 1 | 290,234 | 749 | 0 | 0.9805 / 0.9414 / 0.9336 |
| 2 | 291,601 | 1,367 | 0 | 0.9805 / 0.9766 / 0.9688 |
| 3 | 292,444 | 843 | 0 | 0.9805 / 0.9766 / 0.9766 |

The leg region — what mask 6 adds over mask 3, 58,676 px — was **100% present in
the seed and 1.3% present in the result**. The 57,302 px round 0 removed is
essentially exactly the leg, at mean luma 152 and 45% inside the measured box:
the leg's own signature.

**Every round passed the guard I had written, four times running**, because that
guard measured GROWTH — `best & ~accepted` — and round 0's growth was a genuine
4,572 px of edge. It never asked what had been removed. A round that trades
58,083 px of leg for 4,572 px of edge scored as an improvement on every axis
tested: growth positive, spill 0.4%, material within 24 luma.

**And the operator's original rule would have done better here.** Round 0's
largest candidate was **350,937 px — larger than the seed** — and it lost by
**0.0039 of score** (0.9727 against 0.9766). Whether it contains the leg is
untested: `click_refine` stacked only the chosen mask, so the other two
candidates are not on disk. That is an instrumentation gap, not a finding.

## What we chose

**The loop does not ship, and the guard gains a net-change test as its FIRST
check** — a round that removes more than 2% of what it had is a replacement, not
a refinement, however good the new mask looks alone. Re-run over the same
recording, that check rejects round 0 and the guard keeps the seed: the correct
answer, arrived at by refusing everything on offer.

**The highest-scoring rule is not vindicated and not refuted.** Its one measured
outcome here is worse than the alternative, on a 0.4% score difference, on one
object. Both readings of that are available and neither is supported: that the
score is too flat to select on, or that this object is one draw.

## Why

**A mask-quality score ranks masks; it does not rank masks against a mask you
already have.** 0.9766 says the desktop-only reading is an excellent mask, and it
is — it is a clean, confident, correct segmentation of the desktop. It is simply
a segmentation of less of the object. Nothing in the score expresses "and the
thing you gave me had more of the object in it", so selecting on it can silently
trade extent for tidiness. That is the same shape as 0261's finding one layer
down, and it is why the seed has to be defended by the harness rather than by
the model.

**The guard failing is the more useful half of this.** Its three tests were
written against the failures this investigation had already seen — a mask
running onto a neighbour, a mask made of the wrong material — and it was
airtight against both. It had no test for the failure that actually happened,
because that failure had not happened yet. Four guards, four different weak
links, and each one was strong against the previous round's problem.

**Nothing here indicts the operator's method.** The loop mechanically did what it
was asked, the model answered every prompt, the scores were high and stable, and
the pipeline recorded enough to see exactly what went wrong. What failed was the
acceptance rule, which is the part that was mine.

## What would change this decision

**Save all three candidates, not the chosen one.** The single most valuable
missing number is whether round 0's 350,937 px candidate contains the leg. It
costs a route change and one run, and it decides whether "take the largest"
should simply be restored.

**A seed-preserving prompt.** Every round here re-derived the mask from clicks,
so the seed was never defended: the model was free to answer with a different
segmentation. Negative clicks on what should be excluded, or requiring the
result to CONTAIN the seed, would change the question from "segment this object"
to "extend this mask" — which is what the method wanted and not what was asked.

**And the standing constraint has not moved.** `accept_refined` still requires
60% of added pixels inside the measured box while this leg is 30-47% inside, so
even a loop that recovered the leg would have it discarded one stage later.
