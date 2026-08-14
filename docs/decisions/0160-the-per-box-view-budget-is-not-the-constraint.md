# 0160 — the per-box view budget is not the constraint

**Date:** 2026-08-14
**Status:** Decided — `PERCEPTION_PLAN_VIEWS_PER_BOX` stays at 2

## Context

0153 and 0154 both end at the same experiment: the frames the pipeline
reconstructs from are a median 0.50 of the best available sharpness and see
a median 0.48 of the surface the best available frame does, but none of the
better frames was ever segmented, so nothing is known about whether
reconstructing from them produces a better object. The named way to find
out was to raise the per-box view budget from 2 to 4 and re-drive one room
warm — env-only, no build, and it does not touch the capture ceiling.

## What we tried

**The lever is inert on a warm room, and this is measured rather than
argued.** Driving production's own `_build_reconstruction_plan` over each
preserved room's real cached `objects.json` at budgets 2, 4 and 8 produces
an empty plan every time — 0 box best views, 0 second views, 0 long tail,
on all four rooms at all three budgets.

The mechanism is one line. `_build_reconstruction_plan` admits a cached
frame's entries as observations only when `ok` is true
(`process_receiver.py:1018`). A view the previous attempt policy-skipped is
cached with `ok: False` and `skipped_reason`, so it is not an observation,
cannot be associated, and cannot be planned at any budget. Once a frame's
`objects.json` exists, the only views of it that the planner can still see
are the ones it already reconstructed.

Production had already recorded this without anyone reading it that way:
lane C's re-drive of rp6g1 shipped
`plan: {box_best_views: 0, box_second_views: 0, long_tail: 0}`.

**Budget 4 is not merely the granted value, it is the saturating one.**
Reconstructing a fresh pass-1 state from the per-frame masks and replanning,
`policy_skipped` falls to 0 at budget 4 in all four rooms — every associated
view is already admitted. Association depth per box is 1 to 4 views, median
2 to 3, and no box in rp7 or rp6g1 has as many as 4. Raising the budget from
2 to 4 adds **3 to 4 reconstructions in an entire room**; raising it to 8
adds nothing at all beyond that.

**And a third of what it does add is not another viewpoint.** The
association list is a list of (frame, mask) pairs, not of viewpoints, so a
duplicate detection of one object in one frame occupies its own rank. Of the
10 rank-2-or-later views across three rooms, 3 come from a frame the box was
already reconstructed from — same camera, same instant, identical sharpness,
0.0 degrees apart. That is 0146's decisive spike box_05 datum showing up as
a structural property of the ranking rather than a curiosity.

## What we chose

`PERCEPTION_PLAN_VIEWS_PER_BOX` stays at 2. It was raised to 4 on the
serving revision for the experiment and reverted.

The constraint is one level up, and 0146 had already located it without
naming this consequence: the census sampler picks 12 frames object-blind,
so a box lands in only 2 to 4 of them, and the per-box budget of 2 is
already close to consuming everything the sampler supplied. A capture holds
22 to 156 frames that see each box. The budget was never what stood between
the pipeline and those frames — the sampler is.

## Why

Spending the per-box budget is like widening a doorway into an empty room.
The evidence that would justify the wider doorway — that a fourth view of a
box is worth reconstructing — cannot be gathered by widening it, because
the fourth view mostly does not exist in the sampled set, and where it does
it is often the same photograph.

## For 0151: the budget does not widen the baseline either

0151 recorded that today's two views per box sit a median 33.8 degrees
apart, never over 90, with one pair literally the same frame — so its
registration probe has never been tested at a useful baseline, and a natural
hope was that more views per box would supply one.

They do not. Measuring the angle between view directions at the box centre:

    pairs among today's ranks 0-1        n=15   median 35.5   max 88.3
    pairs involving a rank-2+ view       n=22   median 36.2   max 82.5

Identical distributions, and the maximum does not move. This is what should
have been expected once the candidates are all drawn from the same twelve
pose-diverse frames and then filtered to those whose footprint overlaps the
box well: the survivors are angularly similar by construction. A wider
baseline needs different FRAMES, not more views per box, which puts it
behind the same sampler this note is about.

## A consequence worth recording separately

The same `ok` filter means a view whose reconstruction FAILED is also
invisible to every later attempt. A frame caches once every planned mask has
been attempted, and an OOM soft-fail counts as attempted, so the failed
entry is cached with `ok: False` and can never be replanned. rp7 carries 8
CUDA-OOM soft-fails; none of them will be retried by any warm re-drive.

This is defensible — 0061 measured large objects OOMing on both attempts, so
retrying is likely to fail again and cost a full object's budget doing it —
but it is the opposite of the protection 0062 gives a budget cut, where a
frame with a budget-cut mask is deliberately never cached so the stop cannot
become permanent. The asymmetry is real, undocumented until now, and is why
a room can ship fewer objects than it detected with no budget stop recorded.

## What would change this decision

A sampler that chooses frames per object rather than object-blind. Then a
box would have more than 2 to 4 associated views, the budget would start to
bind, and this decision would need re-taking against a supply that actually
exists. That is the same conclusion 0146 reached from the other direction.

Or a planner that enumerates candidates from the per-frame masks rather than
from the observation list, which would make policy-skipped and failed views
replannable and turn the budget into a live lever on a warm room. Worth
doing only if there is a reason to want those specific views — see 0161,
which measures what they are worth.
