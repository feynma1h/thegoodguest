# 0271 — nine of fourteen object kinds have no box, and every instrument needs one

**Date:** 2026-08-27
**Status:** Decided

## Context

0270 gives each RoomPlan box its best whole view and reproduces the operator's
own choice on all six boxes of a real room. The obvious next question — do the
same for everything else — turns out to be unanswerable as the pipeline stands,
and the reason generalises well beyond frame selection.

## What we tried

Segmenting 19 frames of one capture found **14 distinct object kinds**. Six
have a RoomPlan box. Nine do not:

| kind | detections in 19 frames | boxed |
|---|---|---|
| chair, desk, cabinet, bed, nightstand | 20, 16, 12, 8, 3 | **yes** |
| **monitor** | **16** | no |
| **door** | **13** | no |
| **speaker** | **12** | no |
| **tv** | **8** | no |
| artwork, table lamp, curtain, painting, window | 7, 5, 5, 3, 1 | no |

The monitor is detected in **16 of 19 sampled frames** — more often than every
boxed object except the chair — and is absent from the shipped room.

Every selection instrument this project has takes the box as its argument.
`box_visibility` projects it to score a view; `box_is_whole` projects it to ask
whether the object is cut; association matches a mask to it; `arm_fit` measures
a reconstruction against it; the splat clip volume is it. An object with no box
is invisible to all of them and reaches the pipeline only through the long
tail — which is the first thing a budget stop drops, and this room budget-stops
every run.

Substituting the mask for the box was considered and is **not** equivalent.
Border contact transfers: a mask touching the image boundary means the sensor
stopped before the object did, and that is answerable from the mask alone.
Relative ranking transfers: a larger, sharper mask is a better view than a
smaller, blurrier one. **Completeness does not transfer at all.** The box is
the only measurement of how big the object actually is, so without one there is
no answer to "is this the whole monitor or two-thirds of it" — and that
judgement is what makes the boxed analysis convincing rather than merely
plausible.

## What we chose

**Record the boundary, and stop treating unboxed objects as a smaller version
of the same problem.** They are a different problem: for boxed objects the
question is *which view*, and for unboxed ones it is *where is the object at
all*.

The route out is an object→frame map — a per-object, per-frame localisation
that does not depend on RoomPlan having measured the thing. SAM 3.1 produces
one in a single pass, with per-frame masks and stable instance IDs, which is
why the migration is worth its cost rather than being a version bump.

## Why

**The dependency is informational, not economic**, and that distinction was
worth measuring because it kills the obvious cheap fixes. Asking "is this
object cut off" requires knowing where the object is in the frame. Before
segmentation the only things whose position is known are the RoomPlan boxes and
the ARKit plane anchors; a monitor has no representation anywhere in the bundle.
No faster method helps, because there is nothing to be fast about.

Two cheaper routes were considered and both are partial. **Depth** would be
close to free — the bundle carries an optional per-frame depth map, already
downloaded for placement, and a surface running to the frame boundary at
consistent distance is visible in it without any model. It is untestable on the
capture that motivated this, which carries no depth at all (0267), and it
localises surfaces rather than objects. **Reduced-resolution segmentation** is
the other: border contact needs to know roughly where an object is, not its
precise outline, so the ~4 s per frame measured at 1920x1440 is mostly not
inference — it includes fetching and decoding a 1.5 MB JPEG. Neither was
measured; both are cheaper experiments than a migration and should be priced
before one is justified on cost grounds alone.

**And the operator's eyes have only ever judged boxed objects.** Every
validation in 0259 and 0270 — the six-box scorecard, the 11-of-11 hull proxy,
the blur threshold calibrated at the 88th and 93rd percentile — was taken on
objects with a measured box. None of it has been shown to hold for a monitor,
and it should not be assumed to.

## What would change this decision

If SAM 3.1's instance IDs prove stable enough to build an object→frame map,
every instrument above can be re-expressed against a tracked instance instead
of a box, and the six/nine split stops mattering. That is the migration's
actual acceptance test, and it is stronger than "3.1 runs": IDs that drift
between frames give a map that looks complete and silently conflates two
objects.

If they are not stable, the fallback is not nothing — border contact and
relative ranking still work per frame — but completeness stays boxed-only and
the unboxed nine remain long-tail citizens.
