# 0197 — the uncropped photograph is not a better photograph

**Date:** 2026-08-20
**Status:** Refuted

## Context

The operator's two standing room-quality complaints are legless tables — rp7's
desk and rp6g1's table. 0165 decomposed what those reconstructions are missing
and found their largest recoverable class is `clipped` at 38–40%: they run off
the edge of the frame rather than standing behind anything. 0146 had already
measured that a view at `in_frame_fraction` 1.000 exists for 20 of 25 objects,
and that rp7's desk shipped a view at 0.513 over one at 1.000 with the tie
breaking on frame index. Nobody had ever reconstructed one of those objects
from its uncropped view and looked at it.

## What we tried

Both alternatives turned out to be **already reconstructed and already in the
outputs bucket**, so the probe cost a download and a render rather than a GPU
run. Each was pushed through production's own `build_box_object` with the
association list reordered, so axis mapping, vertical seating and clipping are
production's code, not a re-implementation.

- **rp6g1 `box_00`**: fill 0.406 → 1.004. A floating slab becomes a table with
  four legs standing on its measured box floor. Confirmed by eye from two
  angles.
- **rp7 `box_02`**: fill 0.415 → 0.356. Stubby legs become no legs at all.

The photographs explain both without any instrument. rp6g1's shipped f57 is a
close-up in which the legs are *not in the picture*; f178 shows the whole desk.
rp7's f114 does contain the whole desk — small, dim, behind a chair and a stool.

Then: what separates the win from the loss? Nothing on the input side.
`in_frame_fraction` is 1.000 on both alternatives; mask-edge clipping is 0.000
on both; both are ~10× smaller in frame, ~2× further away, *more* occluded, and
carry 2.3–3.3× more Gaussians. The winning view is the more occluded one
(0.714 vs 0.503). "Take the splat with more Gaussians" picks the alternative on
both and is therefore wrong on rp7.

## What we chose

**Not to build a view-ranking key, and not to ship anything.** The charter
hoped the fix would be a sort key; the measurement says it must not be.

What is recorded instead is that two **output-side** checks against the
RoomPlan box separate the cases where every input feature fails: vertical fill
(the placed splat's span over the box's measured height) and `box_fit_residual`
(per-axis `|scale·extent − dim|`, already computed and shipped in every box
entry). Swept over the 8 boxes in the four preserved rooms that have a second
cached view, both agree with the eyes on both walked objects — including
keeping rp7's shipped view unprompted — agree with each other on 7 of 8, are
inert on 6 of 8, and produce bimodal gains: 0.000 ×6, then 0.017, then 0.590,
a 34.7× gap.

An operator sitting on two objects is the gate before any of it ships.

## Why

Every one of the eleven refuted view-quality measures (0146, 0152, 0162) scores
the **input** — where the camera was, how sharp the picture was, how much of
the footprint was covered. `in_frame_fraction` is the twelfth and fails the
same way, for a reason now visible: it is a property of the **box's projected
footprint**, not of how well the object was photographed. Backing the camera
off until the box fits drives it to 1.0 while changing three other things
nobody is looking at — apparent size, distance, and what stands in between —
and those changes are not the same sign in every room.

Scoring the output is a different kind of claim, and a cheap one. The RoomPlan
box is an independent measurement, not derived from the splat, and the pipeline
already trusts it this way: 0104 clips to it and 0148 seats against its faces.
A reconstruction spanning 0.41 of its measured height is missing mass that a
reconstruction spanning 1.00 of it is not, and that is true regardless of which
photograph produced it.

The bimodality is what makes the idea shippable rather than merely true. Six
boxes gain exactly nothing, one gains 0.017 — noise, and switching on it would
be bad — and one gains 0.590. A margin anywhere in a 34× window keeps the real
case and refuses the noise, which is the shape 0170 found for the facing sign
and the shape 0081's margin gate was built around.

Point count deserves its own sentence, because it is the obvious shortcut and
it is a trap: an object 2% of the frame wide produced 3.3× the Gaussians of one
filling 21% of it. Gaussian count tracks how much of the object is visible, not
how good the photograph is.

The honest cost of the one switch this would make: rp6g1's table gains legs, an
exact box fit, no vertical seating fudge and no `splat_clip` (0104 removes 16.4%
of the shipped one and nothing from the alternative) — and **loses axis
resolution**, `splat_axis_resolved` True → False, margin 0.1345 → 0.0656. A
complete table whose facing is unresolved, against a slab whose facing is not.

## Outcome — the chair round (same day, operator-directed)

The operator asked for a cleaner view of rp7's half-rendered chair — the one
object 0165 measured as genuinely occlusion-bound (0.49, 98% of it the desk).
Scanned all 31 frames seeing its box at in_frame ≥ 0.85, picked **f275 by
eyes** over the shortlist photographs (the far-side cluster shows backrest,
seat and wheel base clear of the desk), segmented and reconstructed it on a
bench candidate. Result: the shipped f7 arm is a hollow front shell; the
f275 arm is a **complete office chair** — backrest, armrests, seat,
cylinder, five-star base — extents' third axis 0.28 → 0.537 m.

Three things this adds to the note above:

- **The good view was never a candidate.** The chair had exactly one
  association because f275 was never sampled — the object-blind sampler,
  not the ranking, withheld it. The sort-key question this note refused is
  therefore still refused correctly: the binding constraint sits a stage
  earlier.
- **The box-on-box occlusion proxy read 0.000 for f7 itself**, the frame we
  know is half-blocked — it fails on tucked-under geometry. Another input
  measure down.
- The n=3 tally on "does a better photograph help": rp6g1's table (view),
  rp7's desk (mask, 0198), rp7's chair (view) — every one chosen by eyes
  plus an output-side check, never by an input score. 0162's negative
  stands; eyes-chosen is the qualifier that separates these wins from it.

## What would change this decision

- **The operator says A for rp6g1.** Then the output-side check is wrong on the
  one case it exists for, and the whole line closes.
- **A third and fourth eyes-verified object disagree with both instruments.**
  n = 2 with eyes is the real limit here; the 8-box sweep is instrument-only.
- **The axis mapping becomes resolved on most boxes.** Both instruments read
  extents under the chosen mapping. rp6g1's winner is nearly isotropic so the
  mapping barely matters there; on a strongly anisotropic object with an
  unresolved mapping, fill could be measuring the wrong axis, and today
  `splat_axis_resolved` is false on most box placements (0080, 0104).
- **Something makes SAM 3D produce a complete object from a partial view.**
  None of this reduces class-6 truncation; it picks better among what the model
  already produced. Decision 0052's standing trigger — a different model — is
  still the thing that would retire the question.

Outpainting (the charter's probe 2) was **not started**: it is gated on probe 1
failing, and probe 1 produced a win on one of two objects plus a cheaper
candidate fix. It re-opens if the operator's sitting kills the output-side
check, since the addressable share (38–40%) and the argument for it are
unchanged by anything measured here.
