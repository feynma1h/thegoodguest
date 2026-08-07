# 0082 — RP-8 walk classes 2–5: placement post-passes + the kink fix

**Date:** 2026-08-07
**Status:** Decided

## Context

Decision 0080 ranked the remaining operator-visible defect classes after
class 1: cross-label duplicates surviving at partial overlap (class 2),
wall-mounted splats centered IN walls + furniture clipping walls (class
3), door-label misses escaping the opening demotion (class 4), absent
support relations (class 5), and the envelope segment-kink nit. All are
policy/geometry work over evidence fusion already holds.

## What we chose

Four post-fusion passes in `fusion.py` (run inside the refined pass,
budget-gated as a block; `PLACEMENT_REFINE=0` bypasses everything):

* **Class 2 — cross-label 3D duplicate gate.** Placed objects whose
  volumes coincide (sampled-point containment ≥ 0.5 either way) under
  confusable labels (env-overridable groups: monitor/tv/television,
  desk/table/nightstand/cabinet/…, artwork/painting/poster/frame/mirror,
  bed/sofa/couch; same-label pairs always qualify — rp7's two mirrors)
  collapse to one. Priority: RoomPlan box > measured-surface contact >
  detection score. Two box-anchored objects never dedup (two measured
  boxes are two real objects). This is the 3D, cross-frame sibling of the
  f242 same-frame mask gate; always-on for refined scenes (the fork-(a)
  precedent).
* **Class 3 — wall back-face anchoring + floor declip.** Wall-class free
  placements (depth_fit/triangulated/silhouette; contact and box sources
  exempt) snap so the rearmost splat point touches the nearest measured
  wall plane (search ≤ 0.6 m, shift ≤ 0.5 m; planar splats also align
  their normal within 60° — `solve_wall_contact`'s own convention).
  Floor-class free placements penetrating a wall beyond 8 cm are pushed
  back into the room (≤ 0.35 m). Walls come from the CapturedRoom adapter
  when a parsed room exists, anchor planes otherwise — so the pass also
  serves LIDAR_ARKIT scenes. `clock` joins the wall class map (the walk:
  "should sit flat against the wall"); the chunk-D evidence gate still
  protects a desk clock from a wall solve.
  **Box-anchored splat overflow is deliberately NOT corrected**: box
  positions are RoomPlan measurement, and uniform scale + box-dims-truth
  (the RP-8 A/B resolution) means an ill-proportioned splat can overhang
  its box into a wall. Moving or shrinking it would falsify a measurement
  to hide a splat artifact — recorded as class-6 residue instead.
* **Class 4 — door-geometry opening demotion.** A placed storage-ish
  object (cabinet/dresser/wardrobe/…/door/window) whose center sits ON a
  RoomPlan door/window surface (≤ 0.35 m to plane, inside the rect + 0.25
  m) demotes to `represented_as_shell_opening` — the label rule keyed on
  measured geometry, so the walk's five "cabinet is actually a door"
  misses demote too. Note this also demotes door/window splats the
  contact path placed (previously exempt via the sanity-gate carve-out):
  the walk itself supplies the direction — "I can see a contour of the
  door placed right but the splat is slightly off of it" — the measured
  opening IS the room's representation; a splat on top is redundant.
* **Class 5 — box-top support snap (v1).** Small-class objects (speaker,
  table lamp, monitor, tv, plant, …) whose bottom hovers or sinks within
  0.35 m of a RoomPlan box top, over that box's footprint (+0.15 m pad),
  rest ON the top (vertical shift only). Box tops are measured; splat-top
  supports (lamp on a non-box nightstand) are deliberately v2 — an
  unmeasured support surface would move one estimate onto another.

Plus the **kink fix** in `shell_receiver.py`: adjacent near-coplanar
RoomPlan wall segments (≤ 4°, mutual offset ≤ 8 cm, lateral gap ≤ 15 cm,
union-find chained) co-planarize at RENDER time onto the group's
area-weighted mean plane; `measured_polygon` ships beside the rendered
polygon with `provenance.coplanarized_with` (the 0069 honesty invariant).
Calibrated + pinned on the spike: exactly {02,10}, {07,08}, {04,11,12}
group, max vertex slide 4.8 cm.

**Descoped with reasons:** the window's 30° in-plane skew stays
0068-population — the cloud instrument is structurally blind to in-plane
spin on near-square planar objects (a plane nests into its own cloud at
any spin), same as every appearance instrument measured before it.
Support-on-splat surfaces (v2 above). Per-axis scale remains unbuilt
(RP-8 A/B).

## Why

Each pass consumes only measured geometry (RoomPlan boxes/surfaces,
anchor walls, the splat's own points) and demotes or nudges bounded
amounts, with the offline spike run confirming every intended target and
no bystanders: bed + office chair rotations resolve (0081), both
mislabeled-door cabinets demote, the mirror leaves the wall (9.5 cm), the
speaker lands on the table (14.8 cm), the window splat yields to its
measured opening, the rug and every unplaced entry ship unchanged.

## What would change this decision

- Class-2 escalation: if partial-overlap duplicates still survive on the
  re-driven rooms, 0080 already names the next step — RoomPlan-box-keyed
  exclusivity for covered categories.
- Class-5 v2 trigger: an operator walk that misses lamp-on-nightstand
  placements enough to accept splat-top support surfaces.
- The class-4 contact-source demotion reverses if a future walk prefers
  door/window SPLATS over openings (e.g. once splat quality stops
  truncating them).
