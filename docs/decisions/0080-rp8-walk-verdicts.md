# 0080 — RP-8 operator walk: verdicts, defect classes, fork resolutions

**Date:** 2026-08-06
**Status:** Decided

## Context

RP-8 deployed the full RoomPlan pipeline (RP-2..5 image, `perception-obj-00036-xer`)
and ran the tier's acceptance gate: the operator scored all four staged LiDAR
rooms per furniture piece (extent / location / rotation) against reality, in
`/viewer?fixture=` with in-scene badge labels. Verbatim verdicts:
`outputs/rp8-walk/operator-verdicts-verbatim.md` (gitignored, preserved).
Rooms: the spike reference bedroom (0076's 9/9 ground truth; 25 objects /
13 placed, 13-wall v3 roomplan shell), RP-7 `a71d125f` (18/14, 4 walls),
RP-6 G1 `09684dde` (21/16, 4 walls), G2 abort partial `b667f891` (33/14).

## What the walk measured

**Holds up.** Locations are broadly accepted — the 0075 baseline's headline
class (a bed 0.79 m displaced) did not recur; box footprints read right
("both chairs look okay", "the big and small tables look okay", "the rug is
okay", "position of the curtains is okay"). Envelopes are real: "this room
is really 4 plain walls, that is correct"; door/window OPENINGS sit where
reality has them ("the opening near the curtains is the window", "doors and
window contours okay"). The G2 abort partial "looks okay" apart from the
shared classes. The v3env contrast confirmed 0075's split: shell corrected,
old depth_fit objects still "oriented wrongly apart from the door".

**Ranked defect classes (the tier's quality-iteration list):**

1. **Splat-axis mapping inside boxes — the dominant failure.** Tables "lying
   on its side" (two rooms), bed 90/180° about vertical (two rooms), storage
   front facing the wall, chair ~90° off. Mechanism was visible before the
   walk: all box placements shipped `splat_axis_resolved=false` — live axis
   margins 0.0018–0.089 vs the 0.10 gate with mostly ONE scoreable view per
   box (P1's offline 0.0999 never materialized live) — so extent-best
   default mappings shipped, and for elongated furniture the default is
   often wrong by construction. The margin gate did its job (refused
   coin-flips); the default beneath it is the gap.
2. **Cross-label duplication survives the gate on census scenes.**
   desk+nightstand, monitor+tv ("there is no TV, probably a
   misinterpretation of the monitor"), table+cabinet, mirror×2 — partial-
   overlap duplicates the near-identity clique rule doesn't reach. The f242
   gate is the floor, not the fix; gate geometry (overlap threshold /
   3D-volume test) is the work item.
3. **Wall-mounted depth: splats centered IN the wall.** Artwork, clock,
   door splats "half inside and half outside" — wall-contact placement puts
   the CENTER on the plane; the back face should touch it (offset by half
   depth). Systematic and mechanical to fix. Related: tables/storage
   "penetrating the wall" slightly — the room-boundary margin admits it.
4. **Door-label misses place doors as furniture.** Five instances of
   "cabinet N is actually a door" — the shell-opening demotion keys on the
   SAM label "door"; a door labeled "cabinet" escapes. RoomPlan's own
   parented door geometry is sitting right there to cross-check against.
5. **Support relations absent.** Speaker inside the table, lamp beside the
   nightstand, monitor mid-air: "should have been cleanly placed on" — no
   on-top-of contact prior exists (floor/wall only, by design). First
   needed for believable rooms per this walk.
6. **Partial splat generation.** Storage top missing, curtains "half
   generated", cabinet splat "very small" — SAM 3D visible-region limits,
   amplified by stretch (see A/B). Model capability, not placement.
7. **Envelope nit:** the spike's B-C-D-E wall run "should be a straight
   line" (RoomPlan segment stitching renders kinks).
8. **In-plane skew on wall contact:** the window "on the surface of the
   wall but skewed by about 30 degrees" — the 0068 in-plane fork's
   population, now on the wall-contact path too.
9. **Product note (not a defect):** mirror splats bake the reflection
   captured at scan time; the operator wants mirrors to read as mirrors.

## What we chose (operator resolutions, at the walk)

- **A/B: UNIFORM ships.** Stretch changed almost nothing visibly except the
  storage, where it amplified the missing-top truncation ("only the storage
  looks much bigger, probably because its top portion isn't rendered").
  The per-axis knob stays unbuilt; `PositionedSplat.scale`'s union type is
  its landing shape if ever revisited. Box dims remain measurement truth.
- **Fork (a): long-tail gates ALWAYS-ON** (commit `f442ef7`): the three
  measured gates now run for every refined scene, not just census scenes;
  pins revised (543 green). Box passes stay census-gated.
- **Fork (b): facing_flag flag-only BLESSED.** Both flagged chairs read
  okay; the rotation problem lives in the axis-mapping default (class 1),
  not in the 180° facing clause.
- **Reveal:** pacing verdict = "coming down at high speed then slows as a
  spring"; operator wants graceful settling and questions the drop-from-
  above for floor/walls ("maybe a boundary contour with moving dots inside
  first followed by the actual wall/floor — we can brainstorm"). The
  long-standing reveal-watch item CLOSES; a reveal-choreography design
  session is the recorded follow-up. Constants deliberately untouched —
  the ask is a redesign, not a retune.

## Why

The walk is the acceptance metric. Recording the verdicts verbatim with the
mechanism-level adjudication keeps the next session from re-diagnosing by
eye what telemetry already explains (axis margins, dedup records,
`splat_axis_resolved`), and the ranked classes give board 7's successor its
ordering. The uniform-vs-stretch call and both forks were deliberately
operator decisions; they are now closed with evidence attached.

## What would change this decision

- Class 1: a better axis instrument (more scoreable views per box via
  census second-view planning, or a stronger-than-NCC scorer) that clears
  the 0.10 margin on real rooms would let scored mappings replace
  extent-best defaults — re-open then.
- Class 2: if gate-geometry work (3D-volume overlap) still can't kill the
  duplicate pairs, escalate to RoomPlan-box-keyed exclusivity for covered
  categories.
- Uniform-vs-stretch: revisit only if splat generation stops truncating
  visible regions (class 6) — stretch amplifies exactly that damage.
