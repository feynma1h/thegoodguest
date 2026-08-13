# 0154 — how much of the object a frame sees, measured properly

**Date:** 2026-08-13
**Status:** Decided — corrects a number in 0152

## Context

The operator's question after 0153: *"Is sharpness the only metric we
should be looking at? Isn't the amount of object visible in a frame a much
more important metric, sharpness being secondary?"*

0152 claimed to have measured that, reporting "a shipped view's mask
covers a median 40% of its object's footprint". That measure is wrong for
the question and the claim is withdrawn.

## What we tried

**Why the old measure was wrong.** It divided the object's SAM mask by its
projected box hull. The hull is the convex projection of a solid box, so
an open object cannot fill it from any viewpoint — a table is a top and
four thin legs inside a large quadrilateral. Grouping that measure by
category recovers exactly the porosity ordering and nothing else:

    storage 0.51  >  table 0.42  >  bed 0.37  >  chair 0.29

It was reading how solid the furniture is, not how much of it was seen.

**The measure the question deserves,** which needs no segmentation and so
can be computed on EVERY frame rather than the twelve that were processed:
backproject a frame's depth, keep the points landing inside the measured
box, voxelise at 3 cm. The union over every frame that sees the box is the
object's observed surface; one frame's share of that union is how much of
the object it saw. Porosity cancels — a chair's union is chair-shaped, and
a view seeing half of it scores 0.5 whatever shape it is.

**The result, with the robust part stated separately from the fragile
part.**

Robust, because the union cancels out of a ratio: **the shipped frame
contributes a median 0.48 of the surface the best available frame does —
minimum 0.12, and below 0.8 on 11 of 15 objects.** There is roughly a 2x
selection gap on exactly the axis the operator named.

Fragile in magnitude, solid in direction: the shipped frame's share of the
union reads 0.11 and the best available 0.22. Both are **deflated by depth
noise**, because the union over ~70 frames absorbs it. Measured: two
frames 8–16 mm apart, near-identical viewpoints, share only 0.17 to 0.60
of their voxels. So do not quote 11% as "the fraction of the object seen".
What survives is the shape of it — no single frame comes near covering an
object, and the best frame in a 722-frame capture is not close either.

**Against quality it does not predict**, and less well than sharpness:

    r(fraction seen, shape error)  = +0.145   (wrong sign)
    r(sharpness,     shape error)  = -0.298   (right sign)

Both weak at n = 15 across heterogeneous objects, and neither settles
anything.

## What we chose

Nothing built — the operator asked to pause. The ranking recorded, with
its uncertainty:

* **Amount visible is the larger deficiency.** The operator's instinct is
  right on magnitude: the gap between the frame used and the best frame
  available is about 2x, and it is on the axis that plausibly governs
  truncation.
* **Sharpness is the better-correlated one** on the evidence available,
  and it is a real gap too (median 0.50 of the best available, 0153).
* **Neither ranks the other out.** They are independent, both free to
  compute, and there is no reason to choose — a selection score should
  carry both.

## Why this does not resolve into "select better and be done"

The correlations are the wrong way round from the story, and the reason is
in the absolute numbers: every candidate is bad. Choosing among frames
that each see a small minority of an object, none of which is close to a
good look, is choosing between bad options — which is exactly the
condition under which no single view feature has predicted anything across
0146, 0152 and 0153.

That is the same conclusion 0152 reached, now on an instrument that is not
confounded by porosity: one frame is structurally insufficient, and
selection improves the input without fixing the regime.

## What would change this decision

The one GPU experiment, now with a two-term score instead of one: rank
candidate frames by surface seen AND sharpness, behind an env flag,
re-drive, compare. It is the only way to learn whether doubling the
surface a reconstruction is fed actually produces a better object — the
correlations here cannot answer it, because the better frames were never
segmented.

If it does help materially, selection is worth having and the multi-view
work (0151) gets a much better starting pair into the bargain. If it does
not, then nothing about single-frame input is worth further effort and
0151 or a multi-view model is the only road.
