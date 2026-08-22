# 0230 — the skip is a plan-time statement

**Date:** 2026-08-23
**Status:** Decided (investigation; no behaviour change)

## Context

0227 found two boxes losing uncontested, family-compatible masks to
`box_covered_by_other_view` — rp6g2 b09 at overlap 0.5561 with nothing
competing for it, and spike b01 at 0.6836. A box marked covered by a view
that then produces nothing is a policy assuming the cover succeeded, which
reads like a straight bug.

Two questions were asked before touching it: is the skip evaluated before or
after the covering view's outcome is known, and is making it outcome-aware a
small change or a plan restructure.

## What we tried

**Question 1 is answerable from the code with certainty, and the answer is
BEFORE.** `plan_meta["skipped"]` is complete when `_build_reconstruction_plan`
returns, which is before the pass-2 loop begins. Nothing in that function can
see an outcome, because no reconstruction has run.

The reason string is therefore accurate and the assumption is in the reading
of it, not in the code: `box_covered_by_other_view` states **that another
view of this box is PLANNED**. It has never claimed the other view succeeded,
and at the moment it is written no code could know.

**Question 2 needed the warm path measured, not reasoned about.** Two
consecutive runs against the same stateful bucket, through the census
harness:

| | segmentations | reconstructions | plan |
|---|---|---|---|
| cold | 4 | 6 | 1 best, 1 second, 4 tail, **2 policy-skipped** |
| warm re-drive | **0** | **0** | all zero |

The frames are whole-frame cache hits, so `states` is empty, so the plan is
empty and the skipped views are never reconsidered. This reproduces 0160's
corollary from a different construction, and it sharpens it: a policy-skipped
view is not merely unretried, it is **structurally unreachable** — it is not
an observation (`ok` is false), not `done_ok`, and its frame is not in
`states`, so all three of the plan's ways of noticing a view miss it.

**How big is the defect?** Across the four preserved captures, 15
policy-skipped views resolve to a box at or above `_BOX_MATCH_MIN`. **Three
belong to a box that ended with no arm at all** — rp7 b03, rp6g2 b09, spike
b01. The other twelve skipped a view of a box that was covered exactly as the
plan intended.

## What we chose

**Report and stop, per the charter's own boundary.** Nothing is built.

Making the skip outcome-aware *within a request* — promoting a skipped view
once the covering view is known to have produced nothing — requires
re-entering reconstruction after the pass-2 loop with knowledge of outcomes.
**That is the retry loop the charter excludes**, and it is a restructure of
`_run_census_two_pass` rather than a change inside it. It is named in the
throughput charter's shape, not here.

## Why

The distinction that matters is between the two harms, because they have
different sizes and different fixes.

**The in-request harm is small and is bounded by the plan's own budget.**
Three boxes across four captures, and at most one of the three is even
attributable to the skip: spike b01's mask was legitimately outbid by b00 at
0.8442 (0227 filed it as COMPETITION), and rp7 b03's other two views both
died of CUDA OOM (0228), so promoting its third would have been the fourth
attempt at a box the GPU was refusing. **rp6g2 b09 is the only clean case**,
and even there the promotion buys one storage box a 0.5561-overlap cabinet.

**The durable harm is larger and is a different shape.** Because the skip is
cached and structurally unreachable, the box is not merely uncovered in this
request — it is uncoverable in every future one. A warm re-drive is the
documented coverage recipe, and for these three boxes it is measurably a
no-op. That is the half worth fixing, and it does not need the loop.

**The small adjacent change, named and NOT taken.** The finalization block
already runs after the pass-2 loop and already decides whether to cache a
frame, on `pending`. Extending that decision — do not cache a frame whose
skipped views belong to a box that ended with no successful arm — would make
the next drive re-segment that frame and re-plan its views as tier-1, with no
promotion inside this request and no change to the plan.

It is not taken here because it has a real cost that belongs to whoever owns
warm re-drives: it converts a free warm re-drive into one that re-segments N
frames, **every time, forever**, for any box that is genuinely uncoverable.
rp6g2 b09 may well be such a box. Trading "warm re-drives are free" for three
boxes across four rooms is a call about the coverage recipe, not an
implementation detail, and it should be made with the throughput charter's
numbers beside it rather than alone.

## What would change this decision

If the retry loop is ever built, this becomes one of its cases and needs no
separate treatment: an outcome-aware promotion subsumes the caching question
entirely.

If it is not built, the caching change above is the cheap half and should be
reconsidered the moment anyone measures how many frames a real room would
re-segment under it. That number is not in this note because it needs a cold
drive of each capture to measure honestly, and the four preserved captures
are all warm.

The three-box figure will move with 0226 and 0229. 0226 already changed the
association population, and any change to `_PLAN_VIEWS_PER_BOX` changes which
views are skipped at all — 0160 measured that raising it is inert on a warm
room, which is the same mechanism this note is about, seen from the other end.
