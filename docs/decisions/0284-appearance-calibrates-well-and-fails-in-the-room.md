# 0284 — appearance separates the objects that have boxes, and merges the ones that do not

**Date:** 2026-08-31
**Status:** Decided (measured; the box-free merge is still open, and the reason is now specific)

## Context

0279 measured SAM 3.1's tracked ids as UNSTABLE — one nightstand arrives as
three ids in disjoint frame windows — and named the box as the only thing that
could repair them, while noting that the nine unboxed kinds are exactly the
objects the map exists to serve. 0280 then tried the obvious box-free repair,
pooled mask-centroid ray triangulation, and measured it insufficient (1.8x
median separation, heavy overlap). It named two untried signals: full
back-projected extents rather than a single point, and **appearance**.

The operator's requirement is the binding constraint and it is correct:
**the whole purpose of moving to SAM 3.1 was to stop depending on RoomPlan.**
A merge keyed on the box satisfies the letter of 0279's repair and defeats the
point of the migration.

## What we tried

**A box-free appearance descriptor**, validated against the box. Per instance, a
hue/saturation/value histogram over its masked pixels pooled across every frame
it appears in, L2-normalised, compared by chi-squared. The instrument never
sees a box; the box only labels the calibration pairs, which is the same shape
0280 used.

Calibration — fragments dominating the same box (family-gated per 0226) are
known-same, fragments dominating different boxes are known-different:

| | n | median | min | max |
|---|---|---|---|---|
| known-same | 10 | **0.2047** | 0.0374 | 0.3244 |
| known-different | 68 | **0.7649** | 0.2565 | 0.9693 |

**3.74x separation, and the best threshold makes 1 error in 78 pairs.** Against
0280's 1.8x with no usable threshold, that is a large improvement, and the
registered prediction — that a room of white and cream furniture would defeat
colour — was **wrong**.

**Then it was applied to the 35 instances that have no box, and it collapsed.**
At a threshold inside the calibrated gap it proposes **53 merges**, including
`artwork#0 + door#4`, `chair#4 + window#0`, `cabinet#3 + ceiling fan#0` and
`door#11 + mirror#0`.

**A free hard constraint recovers some of it and not enough.** Two instances
detected as SEPARATE, non-nested objects in the SAME frame cannot be one object
— no box, no geometry, no model, just the frame list. It refuses **10 of the 53**,
correctly killing `curtain#0 + curtain#1` (43 shared frames), `door#3 + door#4`
(18) and `tv#0 + tv#1` (9). **43 survive**, and the absurd ones are all among
them, because they sit in disjoint windows where appearance is the only evidence.

## What we chose

**Keep the co-occurrence refusal, which is sound on its own. Do not ship the
appearance merge. Record why the calibration was misleading.**

## Why

**The calibration set is not representative of the application domain, and that
is the finding.** The six boxed objects are mutually distinct — a cream chair, a
white desk, a white nightstand, a grey cabinet, a wooden bed. The unboxed set is
the opposite: several readings of the same brown door, several white cabinets,
picture frames the same tone as the door. An instrument tuned where every object
looks different will score well and then meet a room where many genuinely do
look alike. **1 error in 78 is a true number about the wrong population.**

**This is 0280's failure wearing new clothes.** That note's diagnosis was that
ray convergence measures "same neighbourhood" rather than "same object". This
one measures "same colour" rather than "same object". Both are real signals and
neither is identity, and in a bedroom the confounds are dense.

**The co-occurrence rule is different in kind and that is why it survives.** It
is not a similarity score with a threshold; it is a logical impossibility. If
the tracker reports two separate non-nested detections in one frame, they are
two objects, and no amount of resemblance changes that. It can only ever refuse,
never assert — the discipline 0234 imposed on the visibility veto, except sound
here rather than heuristic, and it costs nothing to compute.

**And appearance is not worthless — it is unfinished.** 3.74x with one error is
far more signal than 0280 found. What it lacks is any notion of WHERE, which is
what makes a door frame indistinguishable from a picture frame of the same wood.

## What would change this decision

**0280's other untried signal, which is still untried: full back-projected
extents rather than a mask centroid.** 0280 was explicit that this is a
different instrument and not a threshold change — the centroid throws the mask
away, and a fragment's back-projected extent under known camera motion uses far
more evidence. Composed with appearance and the co-occurrence refusal, that is
three instruments failing in three different ways, which is the shape that
usually works here.

**Register the prediction before running it, and calibrate on a population that
contains near-identical objects** — several doors, several cabinets — not only
on the six mutually distinct boxed ones. That second point is the transferable
lesson and it applies to whatever instrument comes next.

**Do NOT re-run this appearance probe with a tighter threshold.** The failures
are not near the boundary: `chair#4 + window#0` at 0.2785 sits below the median
of the known-same pairs. There is no threshold that keeps the true merges and
drops that one.
