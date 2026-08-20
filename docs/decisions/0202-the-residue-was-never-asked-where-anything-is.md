# 0202 — the residue was never asked where anything is

**Date:** 2026-08-21
**Status:** Decided

## Context

0197's chair round ended on a sentence that named a bottleneck nobody had
attacked: rp7's half-rendered chair had exactly one association, because
the view that reconstructs it whole — f275, from the other side of the room
— was never sampled or segmented at all. Not mis-ranked. Absent.

The census sampler (0077) selects frames in two passes: a greedy set-cover
that guarantees every RoomPlan box is seen well, then farthest-point
sampling over camera pose for whatever slots remain. The second pass is
object-blind by construction, and it is where most of the budget goes.

## What we tried

First, measuring the claim rather than repeating it. The four preserved
captures' shipped selections replay byte-identically offline
(`test_sampling_lock_real_data.py`), so the residue could be checked
directly: drop the boxes entirely, run 0062's sampler from the cover picks
as seed, and compare. It returns **exactly the residue that shipped**, on
all four rooms. The residue is not merely object-blind in principle; it is
literally the box-free answer.

Two corrections to the numbers everyone was carrying, both from the same
replay:

- **"2-3 cover picks, 9-10 residue" is true of half the rooms.** rp7 is 6
  boxes at 3 + 9 and rp6g1 is 5 boxes at 2 + 10, but spike is 9 boxes at
  7 + 5 and rp6g2 is 11 boxes at 8 + 4. Cover picks track box count, so the
  residue available to spend is 75-83% on two rooms and 33-42% on the other
  two. A design that assumes ten free slots has none on a cluttered room.
- **Most of what the sampler buys, the plan throws away.** The
  reconstruction plan reconstructs at most `PERCEPTION_PLAN_VIEWS_PER_BOX`
  (2) views of a box and records the rest as policy skips. Counting
  qualifying views per box against that cap, the shipped selections buy 48
  usable views across the four rooms while **14 boxes have at most one** —
  no alternative arm at all — and other boxes carry three, four and five
  views that are recorded and never reconstructed.

Then the change, behind `PERCEPTION_OBJECT_AWARE_RESIDUE`: spend residue
slots on second views of boxes we already cover. Round-robin over the
boxes, fewest-views-first; each box takes the qualifying frame **farthest
in camera pose from the frames that already see it**; a box stops asking
once it has the plan's cap; leftover slots fall through to the pose-diverse
residue so the long tail of objects RoomPlan never boxed keeps its spread.
Deterministic, because a Cloud Tasks retry must re-sample the same subset
to hit its own per-frame cache (0062's law).

Measured, same frame count, no box uncovered on any room:

| | boxes | starved before/after | usable before/after |
|---|---|---|---|
| rp7 | 6 | 2 / 0 | 10 / 12 |
| rp6g1 | 5 | 1 / 0 | 9 / 10 |
| rp6g2 | 11 | 6 / 2 | 16 / 20 |
| spike | 9 | 5 / 0 | 13 / 18 |

Boxes with no alternative view fall 14 to 2; views the plan can actually
reconstruct rise 48 to 60.

## What we chose

Ship it behind a flag defaulting off, and record its limit as plainly as
its effect: **it does not land on the views the hand-fixes used.** 0197
picked f275 for rp7's chair and f178 for rp6g1's table by eye; this residue
picks neither. It is pinned as a test, not left implicit.

Bounding it at the plan's own cap was not cosmetic. Without that bound the
round-robin keeps going — rp6g1 buys fifteen views the plan discards
against three with it — which would have spent frame slots, and therefore
segmentation calls, on records nothing reads.

## Why

The instinct after 0197 is to find the good view. That is refused, and
sharply: eleven view-quality measures have failed (0146, 0152, 0162) and
0197 is the twelfth, where the same swap gained one table a full set of
legs and cost another the ones it had with every input measure pointing the
same way on both. The effect is large and BIDIRECTIONAL, so no sort key is
buildable.

What survives that finding is a weaker claim that is still worth acting on:
you cannot tell in advance which of two views reconstructs better, but a
box with one view offers nothing to choose between. Diversity is the only
property that can be asked for honestly here — how far a candidate stands
from what the box already has is a fact about geometry, not a prediction
about the model — and 0146 already measured that the supply is there: every
box in a non-starved room has 22-156 frames that see it, and the sampled
twelve hold 1.6-3.9% of the good (frame, box) pairs.

Tying the sampler to `PERCEPTION_PLAN_VIEWS_PER_BOX` rather than to a knob
of its own is the same discipline: the two numbers describe the same
quantity from opposite ends, and a lane that raises one without the other
gets either wasted frames or planned views it never sampled.

The reason this ships off, and the reason it is not yet an improvement to
anything, is 0203: nothing downstream chooses among an object's arms on the
output side. Read that note before turning this on.

## What would change this decision

- **Output-side arm selection lands (0203).** Then this stops being a
  supply change and starts being a quality change, and the flag has a
  reason to default on.
- **A GPU round on a re-driven room.** Everything here is offline
  geometry — no reconstruction was run, so no claim is made about what the
  extra arms look like. The natural test is one non-starved room re-driven
  with the flag on and the arms walked.
- **A room where the long tail grows.** Frames chosen because they see
  furniture may carry more detections than frames chosen for pose spread,
  and the long tail reconstructs every unassociated mask. That term cannot
  be measured without segmenting frames nobody has segmented. b667f891
  already budget-stops with a 51-item tail, so it is the wrong room to try
  this on first.
- **`PERCEPTION_PLAN_VIEWS_PER_BOX` rises.** The residue target follows it
  automatically, which is intended — but 0160 measured that raising it is
  inert on a warm room, so the two changes want the same cold room.
