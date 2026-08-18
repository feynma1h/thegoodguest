# 0177 — the seating question is not answerable yet

**Date:** 2026-08-14
**Status:** Decided

## Context

0148 seats an under-filling splat against one face of its measured box: the
measured top for a category whose top is a surface, the floor otherwise.
rp7's desk fills 0.43 of its box height and rp6g1's table 0.41, so whichever
face they are seated against, the other end is wrong by ~0.24 m. The choice
is one vocabulary entry in `box_placement` and it governs every short
reconstruction, so it was banked for the operator.

It had already been asked once and gone unanswered, fairly: the walk showed
rp7's desk, whose legs are off the floor in *both* candidate versions, so
the picture could not show the choice being made.

## What we tried

Three variants, all staged as viewer fixtures against the deployed rooms and
walked in the browser at `/viewer?fixture=…&labels=1`:

* **floor anchor** — the reconstruction's bottom on the measured floor; the
  desk's surface then lands 0.24 m below where the measurement says it is,
  and the monitor resting on it floats.
* **top anchor** (serving, `perception-obj-00043-yiz`) — the surface at the
  measured height, where things actually rest on it; the legs stop 0.47 m
  short of the floor.
* **vertical stretch** (`-vfill`, built for this walk, never shipped) — the
  up axis alone scaled so both ends land, at the cost of the object's
  proportions. ×2.35 on rp7's desk, ×2.44 on rp6g1's table.

The operator walked all three and rejected all three: the first two on the
legs, the third "because of the stretch and the legs still not touching the
ground".

## What we chose

**Nothing changes.** The top anchor keeps serving, `vertical_seat_m`
semantics are untouched, no vocabulary entry was written and no perception
deploy was made. The question is re-asked once objects have legs — the
multi-view union (0151), which is the only live route left on class-6
truncation after 0146, 0152, 0155, 0162 and now 0181.

## Why

All three options are pictures of the same missing measurement. SAM 3D
reconstructs from one photograph, a desk in a furnished room is never fully
visible from one viewpoint, and 0155 puts the ceiling for *any* single
viewpoint at 0.50 of an object's surface — you see the front-facing half and
never the back. Picking where to hang a legless tabletop does not make it
less legless; it only decides which end of it lies.

Deferring is not costless — the legs stay wrong on every capture until the
union lands — but the alternative is spending a vocabulary entry, a
perception deploy and four warm re-drives to move the error from one end of
the object to the other, and then re-deciding it anyway against
reconstructions that behave differently.

The operator reached this by asking whether the splat itself could be
improved instead. The measured answers are worth keeping together, because
the question will be asked again: better captures are capped at 0.50 by
single-viewpoint geometry (0155); better frame selection is dead across
eleven measures (0146, 0152, 0162) and specifically dead here, since rp7's
table ships at 0.37 occluded and 0.37 is the best its whole capture offers
across 27 qualifying frames; and completing the unseen half is invention,
which 0156 already measured the cost of when SAM 3D fabricated a cupboard
back matching its front and blinded the facing instrument.

The one route not yet measured when this was asked has since been measured
and closed: 0181's bench fed SAM 3D a real LiDAR point map instead of the
monocular guess it normally reconstructs from, on a GPU, control and
treatment on the same image. The pre-registered prediction was that rp7's
desk would move its shape signature from 0.286 toward its box's 0.511. It
moved to 0.283 — 1.4% of the predicted magnitude, and the wrong way. The
legless desk stays legless even when the depth is measured rather than
guessed.

## The exhibit was not fair to the third option

Found while checking the verdict rather than while recording it, and
recorded because a future session will re-stage this A/B.

**The vertical stretch does reach the floor.** Measured through the
production clip volume on the staged fixtures: rp7's desk bottoms at
y = −1.477 against a room floor at −1.464, and rp6g1's table at −1.513
against −1.478 — 1.3 cm and 3.5 cm *below* the floor, with 3.3% and 26.2%
of their points inside 10 cm of it. Offline renders at a camera that draws
the room floor show the legs standing on it.

So what the browser showed disagrees with the geometry, and **the
discrepancy is unresolved.** The named hypothesis, untested: the stretch is
staged as a non-uniform scale on the mesh node (`PositionedSplat.scale`, a
triple rather than a scalar, consumed at `SplatViewer.tsx:134`), and how
Spark composes a non-uniform node scale into a Gaussian's covariance was
never checked. An affine map of a Gaussian is a Gaussian, so a correct
implementation stretches cleanly; an implementation that moves centres
without reshaping covariances turns a leg into a dotted column that thins
out on the way down, which is what was reported.

Settling it needs an orbitable browser — the automation pane cannot drive
OrbitControls, so the room renders at a fixed distant camera where a leg is
a few pixels. The cheap test is a screenshot diff of `-fixed` against
`-vfill` at one camera: if the desk region is identical the stretch is not
rendering at all, which is a viewer bug rather than a judgment about the
option.

Nobody should conclude from this walk that the stretch looks bad. What was
established is that it was not seen fairly, and that it is moot while the
reconstruction is truncated.

## What would change this decision

The multi-view union landing (lane D, 0151). Once an object's reconstruction
spans its measured height, most of this population stops under-filling and
the remainder is a real seating choice rather than a choice between two
lies — ask it then, against objects with legs.

Sooner, if a category is found where the top-anchor error is worse than
cosmetic: something whose *underside* is load-bearing for how the room reads.
Nothing in the four walked rooms is.
