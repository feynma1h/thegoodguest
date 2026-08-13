# 0146 — view selection does not predict reconstruction quality

**Date:** 2026-08-13
**Status:** Decided

## Context

The 2026-08-12 walk named class-6 truncation as the top remaining defect,
and the room-quality brief opened on a specific mechanism for it: the view
whose splat becomes an object is chosen by CORRESPONDENCE, never by view
quality. `associate_observations` sorts a box's candidate views by
`(-overlap, frame_index, mask_index)`, and `overlap` is the projected box
footprint against the SAM mask — it answers *is this the same object*, not
*does this view show it well*. `BoxAssociation` already carries
`in_frame_fraction`, which speaks directly to truncation, gates scoring
admissibility at `box_placement.py:873`, and plays no part in that ranking.

The brief asked for this to be measured against the walk's known-bad
objects rather than assumed. It was, on all four preserved rooms, through
production's own code with a trust gate first: the offline replica
reproduces every shipped view choice exactly.

## What we tried

**The lever exists.** In-frame-first ranking changes the chosen view on 3
of 31 boxes, and the worst case is stark: rp7's desk shipped the view with
in-frame 0.513 over one at 1.000, both at overlap 1.000, so the tie broke
on frame index alone.

**It does not improve the reconstruction.** Every box with two
reconstructed views (8 pairs) was scored on two mapping-independent
completeness instruments — the splat's sorted extents against the measured
box's sorted dims under the best uniform scale, and the tier-1 silhouette
of each splat reprojected into the OTHER view's mask, evidence it was
never fit to. The higher-in-frame view is better on shape agreement in
3 of 8 and on cross-view silhouette in 5 of 8. Coin flips.

**Nor does any other view feature.** Seven candidates were computed from
geometry the server already has — in-frame fraction, mask overlap, how
many box faces are front-facing, the projected-area balance of the two
largest visible faces (a corner view versus a dead-on one), total
projected area, mask pixel count, splat point count — and paired within
each box so object identity cancels. Best agreement with either instrument
was 5 of 8; several were 1 of 4.

The decisive single data point is spike box_05: its two candidate views are
**the same frame**, f171, differing only in which mask SAM produced. Shape
error 0.206 against 0.661, point count 499,008 against 191,232. Same
camera, same image, same instant — so that difference is not view geometry
at all.

## What we chose

No view-ranking change. `in_frame_fraction` stays where it is (a scoring
admissibility gate) and out of the association ranking.

What was measured instead is recorded here because it reframes the whole
thread: **the capture is not the constraint, and the sampler barely uses
it.** Projecting every box into every keyframe of each preserved capture —
pure geometry, no masks, no GPU — every box in every non-starved room has
22 to 156 frames that see it at the census cover bar, and a view with
in-frame fraction 1.000 exists for 20 of 25. Of the good (frame, box)
pairs a capture contains, the sampled twelve frames hold 3.5% on rp7,
3.9% on rp6g1 and 1.6% on the spike room. The cover pass reaches every box
in 2 to 3 picks and the remaining 9 or 10 slots go to pose-diverse
residue, which is object-blind by construction.

## Why

An instrument that is right 3 times in 8 is not an instrument, and this
project has a standing rule against shipping one. The mechanism is also
now visible rather than inferred: the variance between two reconstructions
of one object is dominated by SAM 3D's own behaviour — the same-frame pair
proves it — so a selector built on how the CAMERA was placed is reaching
for a variable that is not driving the outcome.

This is the same shape as 0081 and 0104: an appealing hypothesis about
which view to trust, refuted by paired measurement. It belongs with them
rather than being rediscovered.

The supply finding matters more than the refutation. "Capture more
carefully" and "choose the view better" were the two candidate attacks on
class-6 truncation, and the measurement says the first has already been
done by the user and thrown away by the sampler, while the second does not
work. What has never been tried is USING more than one of the views a
capture already contains for a single object — SAM 3D reconstructs from
one view and the pipeline picks one splat and discards the rest.

## What would change this decision

A completeness instrument that separates good reconstructions from bad
ones reliably — this measured two and neither did, so the refutation is
partly a statement about the instruments. If one appears, re-run the
paired comparison before concluding anything about views.

A reconstruction path that consumes more than one view of an object, at
which point "which views" replaces "which view" and the supply finding
becomes the operative number rather than a curiosity.

Decision 0052's standing trigger also applies: a model exposing calibrated
metric scale or pose would let measurement graduate from prior to
authority, and the question changes shape entirely.
