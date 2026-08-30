# 0285 — the volume merges what a point and a colour could not

**Date:** 2026-08-31
**Status:** Decided (measured; the box-free merge is viable, not finished)

## Context

0279 measured SAM 3.1's ids as UNSTABLE and named the RoomPlan box as the only
available repair. 0280 killed the obvious box-free alternative — pooled
mask-CENTROID ray convergence, 1.8x separation with heavy overlap — and named
two untried signals. 0284 ran the first, appearance: it calibrated at 3.74x with
1 error in 78 and then merged `artwork + door` and `chair + window`, because a
calibration set of six mutually distinct objects says nothing about a room full
of brown doors.

**The operator's constraint is the binding one: the whole point of moving to
SAM 3.1 was to stop depending on RoomPlan.** A box-keyed merge is not an answer.

This is 0280's second untried signal, and 0284's stated method fix.

## What we tried

**The visual hull.** Each (frame, mask) is a cone from the camera through the
mask outline; the object lies inside it. Intersect a fragment's cones over a
6 cm voxel grid and what remains is a VOLUME — with a size and a shape, not a
location. Two fragments are the same object if their volumes coincide, by IoU.
The instrument sees no box; `project_points` is the shipped primitive.

**Calibrated on DISJOINT-WINDOW pairs only**, both populations, which is 0284's
correction: a co-occurring pair is separable for free, and including such pairs
flatters the instrument on the cases it is not needed for.

| | n | median | min | max |
|---|---|---|---|---|
| known-same | 10 | **0.1461** | 0.0403 | 0.4695 |
| known-different | 44 | **0.0000** | 0.0000 | 0.0528 |

**39 of 44 known-different pairs share no volume at all**, and the best
threshold makes **1 error in 54**. All three registered predictions were right
in direction and the first was far too pessimistic: the separation is not "3x",
it is a median of 0.1461 against zero.

**Then the first application failed, and the mechanism is the finding.** At that
threshold, transitive closure produced a group of TEN — the whole chair, the
whole desk, a monitor and a tv — because one weak edge, `chair#2 + desk#2` at
0.0528 (the single calibration error), bridged two real objects and union-find
did the rest. Checked against the frames, that group held **19 pairs that are
provably different objects**, and two other groups held 3 more.

**The fix is to treat co-occurrence as a cannot-link constraint at GROUP level.**
Two instances detected as separate, non-nested objects in one frame cannot be
one object — a logical fact, not a score. Applied pairwise it does nothing,
because closure merges A-B and B-C without ever asking about A-C. Applied
between groups, strongest edges first:

**48 instances → 23 objects, 12 merges blocked, ZERO contradictions.** And
`chair#0, chair#2, chair#3` comes out as its own group, which is the question
the operator actually asked, answered without a box.

## What we chose

**Volume IoU with co-occurrence as a group-level cannot-link constraint is the
box-free merge. Ship it as the grouping key for selection; do not present 23 as
the true object count.**

## Why

**Extent is the information the other two instruments threw away.** A centroid
is one point and drifts across the object as the view angle changes (0280); a
colour histogram has no geometry at all (0284). A hull knows a desk is 1.3 m
wide and a nightstand is 0.5 m, which is exactly what separates two objects
9 cm apart — the case 0280 named as its own defeat.

**The two instruments are complementary rather than redundant, and both are
needed.** Volume says "same space, same size" and is fooled by a chair tucked
under a desk. Co-occurrence says "cannot be the same" and is silent on
everything that never shares a frame. Neither works alone: volume alone gave a
group of ten; co-occurrence alone merges nothing.

**Transitive closure is the trap, and 1-error-in-54 hid it.** A pairwise error
rate says nothing about a clustering built on it, because one false edge merges
two whole groups and everything already attached to them. Any future pairwise
identity instrument here must be reported with its CLUSTERING error, not only
its pairwise error.

## What would change this decision

**Two known residual errors, both from the same cause.** `desk#2` lands with
`chair#1, chair#4` because the greedy strongest-first order takes
`chair#4 + desk#2` (0.0947) before `desk#1 + desk#2` (0.0821), and the
constraint then blocks the correction. And the screens over-split into three
groups. Both are the weak tail of the threshold, and both would be addressed by
a mutual-best-edge rule rather than plain greedy — untested.

**23 is not the true count and must not be reported as one.** It is an
over-count with the contradictions removed. The operator's eye on the groups is
what would settle it, and the contact sheets already exist per instance.

**The calibration is still 10 known-same pairs from 4 objects.** That is the
same thinness 0284 carried. A second capture with different furniture is the
honest widening, and the cannot-link population — which needs no box at all —
can be built on any capture immediately.
