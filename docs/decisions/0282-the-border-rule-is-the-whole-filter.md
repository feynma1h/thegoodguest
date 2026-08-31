# 0282 — the border rule is the whole filter, and its margin is an operator call

**Date:** 2026-08-31
**Status:** Decided (measured; the threshold ships as specified, with its cost written down)

## Context

`track_selection.py` disqualifies a frame for an object on three rules — the
mask reaches the image border, the mask is under 0.5% of the frame, or more than
10% of it is covered by other objects. 0259 reached the first of those from the
operator's own eye and had to approximate it with a projected box hull, because
before segmentation there is no mask. The tracked segments make the exact test
available, for every object including the unboxed nine (0271).

The three rules are not comparable in weight, and the difference is large enough
that calling them "three filters" misdescribes what the stage does.

## What we tried

The selector run over all 1,241 detections of `capture-90eebfc4`, then the border
margin swept while the other two rules held fixed.

| rule | detections rejected | of 1,241 |
|---|---|---|
| **border** | **768** | **61.9%** |
| too_small | 79 | 6.4% |
| occluded | 55 | 4.4% |

| margin | band (px, at 480×360) | border rejects | objects on fallback | `bed#0` |
|---|---|---|---|---|
| 0.000 (touching) | 0, 0 | 716 | 8 | keeps 4/87 → **f0** |
| 0.005 | 2, 2 | 725 | 8 | keeps 4/87 → **f0** |
| 0.010 | 5, 4 | 728 | 8 | keeps 4/87 → **f0** |
| **0.025 (shipped)** | 12, 9 | **768** | **9** | **keeps 0/87 → fallback f23** |
| 0.040 | 19, 14 | 790 | 12 | keeps 0/87 → fallback |

**Two of the three objects 0259 recorded the operator naming — before they had
seen any score — come back exactly.** The operator said table 50/51/109 and
chair 41/42; this selector returns `desk#0` → **50** and `chair#0` → **42**,
from tracked masks rather than from the projected box hulls 0259 and 0270 used.

**The third is the disagreement.** The operator said bed 0 and 1. The bed's mask
reaches x=474 of 479 in frame 0 and x=470 in frame 1, so at a 12 px band both
are refused, all 87 of its frames are refused, and the bed lands on the
fallback. At a 5 px band frames 0 and 1 survive and **f0 wins on score**.

## What we chose

**Ship the margin as specified at 0.025, and record what it costs rather than
quietly tuning it to match the one case we can check.** The comparison is
inclusive at both ends, so a margin of 0 means "touches the edge" — with a
strict comparison it could never fire at all, because a mask bounding box is
clipped to the raster by construction.

## Why

**Stage 1 is the border rule; the other two are hygiene.** At 61.9% against 6.4%
and 4.4%, any argument about this stage's behaviour is an argument about one
number, and a reader who treats the three as peers will tune the wrong one. That
is worth stating plainly because the three read as equals in the specification.

**A high rejection rate is the room, not a defect.** 0273 measured this capture
as rotation-paced — a person pivoting rather than walking — so large furniture
runs off the frame edge in most views of it. 0259 saw the same shape from the
other side: eight of eleven table candidates disqualified. Even the strictest
possible reading of the rule, mask-touches-edge with no band at all, refuses
57.7% of detections.

**The margin's real cost is concentrated, not spread.** Between touching and
2.5% the rejection count moves 716 → 768, which is small; but the objects it
moves are the ones the frame cannot contain, and for those it is the difference
between a scored answer and the fallback. The bed is that case, and the bed is
the one object here where the operator's recorded choice can be checked.

**It is not this lane's call to move it.** The threshold was specified, the
disagreement is a single object, and the direction that would fix the bed —
loosening — is the direction that admits cut objects for everything else, which
is exactly what 0259 built the rule to stop. So it ships as given with the
number written down. **What would be wrong is tuning to the bed and reporting
the agreement as validation**, since the bed is then no longer evidence.

**And the fallback is doing its job.** An object larger than any frame that sees
it has no uncut view, so the honest answer is "here is the best of a bad set,
flagged", which is what nine objects get.

## What would change this decision

**The operator's eye on the nine fallback objects.** They are `bed#0`,
`cabinet#6`, `ceiling fan#0`, `chair#2`, `clock#0`, `desk#2`, `door#11`,
`door#12`, `door#8`, and the question is narrow: is the returned frame an
acceptable photograph despite being cut? If it usually is, the margin is too
strict and 0.005–0.010 is the measured alternative. If it usually is not, the
fallback needs something better than "best of the refused set".

**A completeness rule would change the arithmetic.** `_hard_filter_reasons`
carries a TODO where one would go, deliberately unimplemented: the natural
version compares a frame's mask area against the object's peak area across its
track, and the peak is the largest OBSERVED extent, not the true one. 0197
measured that class of ranking as large and bidirectional. It needs a registered
prediction before it goes in, not an implementation.

**Do not re-open this by re-running one object.** The bed is the only object in
this capture whose operator-recorded choice the margin changes, so a
single-object re-check will always look like the margin is the problem. The
number that matters is the fallback count across all objects with the rejection
rate beside it.
