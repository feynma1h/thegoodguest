# 0280 — ray convergence does not separate a fragment from its neighbour

**Date:** 2026-08-30
**Status:** Decided (measured; the obvious merge was tried and is insufficient)

## Context

0279 measured that SAM 3.1's tracker over-segments in time: one nightstand
arrives as `nightstand#1/#2/#3` in three disjoint frame windows, and four of
six RoomPlan boxes fragment the same way. It names the repair — merge fragments
that are the same object — and notes that the box can only repair the six it
measures, while the nine unboxed kinds are exactly the ones the map exists to
serve.

The obvious box-free merge is geometric and this repo already owns the parts:
every frame carries camera pose and intrinsics, `placement_math.py` has
`ray_through_pixel` and `triangulate_rays`, and **it needs no depth** — which
matters, because this capture has none (0267). Two fragments are the same
object if their masks look at the same place.

It was tried before being recommended.

## What we tried

For each fragment, the world ray through its mask centroid in every frame it
appears in. Pool two fragments' rays, triangulate, and take the RMS
perpendicular distance — small means the two look at one point in the room.

Calibrated on the six boxes, where the answer is already known: two fragments
that dominate the SAME box are known-same, two that dominate different boxes
are known-different.

| | n | median | min | max |
|---|---|---|---|---|
| **known-same** | 19 | **0.182 m** | 0.073 | 0.340 |
| **known-different** | 72 | **0.327 m** | 0.088 | 0.737 |

**The medians separate by 1.8x and the distributions overlap badly.** The three
nightstand fragments — the cleanest known-same case in the capture — score
0.073-0.086 m, the tightest in the whole set, which is the signal working. But
`cabinet#3 + chair#2`, a known-DIFFERENT pair, scores **0.088 m**: tighter than
the median true match. No single threshold separates the two populations.

## What we chose

**Record that the naive version is measured and insufficient, and do not
recommend it as the merge.**

## Why

**The confound is physical proximity, and a room is full of it.** The chair is
tucked under the desk beside the cabinet; objects tens of centimetres apart are
indistinguishable at this precision. The instrument is not measuring "same
object", it is measuring "same neighbourhood", and in a bedroom those differ by
less than the error.

**The error is inherent to what is being triangulated.** A mask CENTROID is not
a fixed point on an object — it moves across the object as the view angle
changes, so a large piece of furniture seen from two sides yields two different
"positions" for the same thing. Known-same at a 0.182 m median against objects
0.5-2 m across is centroid drift, not a bug.

**And the geometry is unfavourable here for a reason already recorded.** 0273
measured that this capture is paced by ROTATION — 165 of 188 gaps, median
translation 3.0 cm. `triangulate_rays` raises on near-parallel geometry
precisely because a rotating camera cannot fix a depth, and while the baseline
between two *visits* is real, the rays within each visit contribute almost
nothing. The capture style that makes the tracker applicable at all (0273) is
the one that makes triangulating from it weakest.

**This is worth a note rather than a silent negative** because it is the first
thing anyone will try after reading 0279, it looks obviously right, and it
costs a lane a day to discover it separates by less than it appears to.

## What would change this decision

**A merge that does not depend on a single point.** The centroid throws away
the mask; comparing the fragments' full back-projected extents, or their
overlap under the known camera motion, uses far more of the evidence. That is a
different instrument, not a threshold change on this one.

**Appearance, which is untouched here.** Two fragments of one object should
look alike, and nothing in this measurement uses colour or texture at all.
0225's warning applies in advance — coverage for visibility questions, purity
for orientation ones — but a same-object test is neither, and appearance is the
obvious unused signal.

**Or the box, for the six it can reach.** For boxed objects the merge is solved
already and needs none of this; the open problem is only the unboxed nine, and
0279 is the note that says why that is the half that matters.
