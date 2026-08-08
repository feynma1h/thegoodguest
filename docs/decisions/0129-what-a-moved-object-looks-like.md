# 0129 — Probe 1: what a real object actually looks like moved, and what actually breaks

**Date:** 2026-08-09
**Status:** Decided (reframes the board-9 brief's spine; supersedes nothing)

## Context

The board-9 scoping brief states the spine of conversational redesign as: *"the
room is a measurement of ONE arrangement. Changing the arrangement moves objects
into regions nothing was ever measured for."* It names three consequences —
a moved object turns its unobserved face toward the camera (class-6 truncation,
"the named bottleneck"), a removed object exposes surface 0069 knows was never
observed, and a catalog object is a clean asset among partial reconstructions —
and it warns, correctly, that if moved objects read as broken then "move the
furniture" may need ghosts, outlines or floor footprints rather than photoreal
relocation. It asked for this to be probed **first**, on real data, without
assuming the outcome.

## What we tried

Two instruments on the staged walk-room fixtures, deliberately not one.

**A. The real renderer.** A throwaway probe page rendered the spike room
(`a7e073ae`, the operator's reference room: 10 placed objects + a 14-plane v3
shell) through Spark with the shipped transforms and the shipped `splat_clip`
volumes, with a camera driven by azimuth/elevation/radius from JS — the pane
cannot drag OrbitControls. Objects were translated, spun, soloed, hidden, and
orbited.

**B. Measurement over the PLYs.** For nine objects across two rooms
(`a7e073ae`, `a71d125f`), spanning wall-adjacent/free-standing and
large/small/planar: read the INRIA-layout PLY, apply the shipped world
transform, express every Gaussian in the object's own RoomPlan-box frame (PCA
frame where no box exists), and measure per box face the areal density of
surface within 5 cm, the fraction of the face covered at 2 cm cells, and the
mean luminance of that surface. Plus splat extent versus box extent per axis,
and mass cut by the clip volume.

Two earlier instruments were built and thrown away for being blunt, which is
worth recording so nobody rebuilds them: face-slab *occupancy* counts interior
mass and reads a visibly-broken bed at 55–60%; orthographic first-hit
*recession* is direction-independent in its silhouette term and gave 0.38 for
both opposite sides of the same object.

## What we found

**1. A moved object reads correctly. This is the headline and it is the
opposite of the cautious assumption.**

The bed translated 1.9 m in X and 0.9 m in Z, viewed from the room's natural
camera, reads as a bed sitting in a new place. Spun 180° in place, it still
reads as a bed. The unclipped cabinet (`obj_000`) survives a full turnaround —
including a straight look at the face that stood against the wall — as a clean,
complete, crisp object. There was no observable "missing back".

**2. What DOES look broken is the clip cross-section, not missing observation.**

Orbiting the bed alone found two quadrants where it renders as a sparse,
see-through, dithered haze with no coherent surface. The decisive test was an
A/B at an identical camera with `splat_clip` disabled: **the haze vanishes and
the bed renders complete, with drawers, handles and fabric folds.** The
degradation is the 0104 clip volume cutting the Gaussian cloud mid-body, and a
cut cloud shows its sparse interior.

How much is cut, measured on the shipped clip volumes:

| object | cut away | max overshoot past the clip plane |
|---|---|---|
| spike `obj_003` bed | **30.7%** | 0.36 m |
| rp7 `obj_001` storage | **28.7%** | 0.15 m |
| rp7 `obj_000` chair | **16.5%** | 0.11 m |
| rp7 `obj_004` bed | 1.8% | 0.09 m |
| spike `obj_004` table | 2.1% | 0.01 m |

0104's finding that the clip is inert on most objects holds; where it is not
inert it removes about a third of the object, and that is where the cut face is.

**3. The empty faces are the splat being SMALLER than its box, not an
unobserved side.** Several objects measured literally zero surface within 5 cm
of a whole box face. Cause, measured per axis: the splat is short of the
measured box along one axis while overshooting it on another — spike bed, box
half-Z 1.079 m but splat reaching ±0.83 m (0.25 m short at each end) while
overshooting ±X by 0.46 m; spike cabinet 0.17 m short on Z; rp7 bed 0.12 m
short. That is class-6 truncation and the axis/scale mismatch `splat_clip`
papers over, seen from the other side. It is a *shortfall*, and a shortfall
inside a box is much less visible than a cut surface.

**4. Removal is visually free, and the brief's second consequence is
materially wrong for the shipped shell.** Hiding the bed in the full room
leaves a clean measured floor and a clean wall — no bed-shaped hole, no shadow,
no unobserved patch. The reason is that 0069 removed the photographic bake:
each plane ships one measured albedo, so the shell has no memory of what stood
in front of it. The brief's concern was true of 0066's baked textures and 0069
already solved it, incidentally, a year before anyone asked this question.

**5. Baked light is second-order.** Ratio of brightest to darkest side face,
across the nine objects: 1.02, 1.04, 1.10, 1.11, 1.18, 1.20, 1.39, 1.49, 1.51,
2.25, 2.55. Nothing in the browser looked wrong because of it at any azimuth
photographed. It is real and it is not the problem.

## What we chose

**Photoreal relocation is the design's default visual language. Ghosts,
outlines and floor footprints are NOT required as the primary treatment**, and
the feature should not be scoped around them.

The one visual defect a mutation feature must handle is the **clip cross-section
turning toward the camera**. Three things follow, in the order they should be
tried:

1. It is **known geometry**. The server ships the clip box; the client knows
   exactly which planes are cut and where. This is a solvable rendering problem,
   not a perception limit — unlike class-6, which it was previously conflated
   with.
2. **0104's rule stands and is not up for renegotiation**: never move, rescale
   or un-clip an object to make it look better. The bed without its clip is a
   convincing bed that is 2.78 m wide where the measurement says 1.85 m. That is
   the trade 0104 already adjudicated and it adjudicated it correctly.
3. Treatments worth trying, none decided here: an opacity ramp in the last few
   centimetres before the clip plane so the cut fades rather than shears; a
   capping surface in the object's own measured albedo; or a placement rule that
   prefers proposed positions keeping cut faces away from the room's centre.

**Collision is a separate, real problem the specification must own.** The moved
bed passed through the chair and the nightstand. That is not a rendering defect
and no rendering treatment fixes it.

## Why

The brief was right to demand this probe first and right about the mechanism in
general — moving an object does expose what its placement hid. It was wrong
about *which* defect dominates, and being wrong in that specific way would have
cost the most: designing a ghost/outline visual language around class-6
truncation, when class-6 turns out to hide inside the box and the thing that
actually shears is a clip plane whose geometry the product already holds.

Both errors in the brief's spine come from the same place — reasoning from the
defect list rather than looking. Consequence 2 was resolved by a decision made
for unrelated reasons (0069), and consequence 1 named the wrong culprit. That is
the argument for this project's verify-first habit, on a session where the cost
of getting it wrong would have been the shape of the whole feature.

## What would change this decision

- **An operator walk disagrees.** These are my eyes, not the operator's, and
  0080/0085 are the standard for what "reads right" means. The reproduction is
  cheap: the probe page took a fixture name, an object id and a camera triple.
- **A room whose objects were captured from fewer angles.** Nine objects across
  two LiDAR/RoomPlan rooms is a thin sample, and both rooms are ones the
  operator walked and largely accepted. An ARKIT_ONLY room, or one of the
  budget-starved captures, could look materially worse.
- **Class-6 truncation closes.** Then the splat stops being smaller than its
  box, the overshoot that makes clipping necessary is likely reduced too, and
  the cut-face problem may simply go away.
- **A catalog object ever enters the scene.** The brief's third consequence —
  a clean asset among baked reconstructions — was NOT probed at all. It is out
  of scope here (see 0133's scope split) and remains untested in either
  direction.
