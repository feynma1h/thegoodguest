# 0136 — A proposal is held to the standard the measurement meets, not a better one

**Date:** 2026-08-09
**Status:** Decided and built (`spec_solver.Tolerances`)

## Context

Decision 0132 gives the solver the job of refusing: "a proposal that cannot be
grounded in measured geometry should not exist". The obvious constraint set
followed from 0129, which watched a moved bed pass through a chair and a
nightstand and recorded that no rendering treatment fixes that:

- the piece's whole footprint lands inside the measured floor polygon
- it overlaps no other placed piece's footprint
- it keeps its height

That set was built, and then run over the four preserved walk rooms.

## What we found

**The measured rooms fail it.** Across the four rooms the operator has walked
and largely accepted:

- **4 placed boxes across 3 rooms** have footprints that leave the measured
  floor polygon. Real: RoomPlan boxes reach into alcoves and under walls, and
  0067 chunk D already carries `PLACEMENT_FLOOR_HIT_MARGIN_M` for the same
  reason.
- **4 pairs across 3 rooms** already overlap in footprint. The clearest is a
  chair pushed under a table, which is not an error — it is what chairs do.

So the first version of the solver would refuse to produce arrangements the
rooms actually contain. Ask it to move a chair nearer a table it is already
tucked under and it refuses on the grounds that the chair would be under the
table.

## What we chose

**Each constraint is enforced only where the measurement itself satisfies it.**
`Tolerances`, computed per mover before any geometry runs:

- `outside_room` refuses only for a piece measured fully inside. A piece that
  already overhangs is exempt — and `constraints_applied` then does NOT list
  `inside_measured_floor`, because claiming a check that did not run is the
  same class of lie as the rest of this.
- `would_overlap` refuses only for a pair not already overlapping. A piece
  stays clear of everything it was clear of, and stays allowed to be where it
  already was.

The constraint name shipped in the trace is `clear_of_pieces_it_was_clear_of`,
which is ugly and exactly right.

## Why

This is not a softening. It is the same rule as everywhere else in this
codebase, applied one layer up: **never falsify a measurement, and never hold
a proposal to a bar the measurement fails.** 0069 ships `measured_quad` beside
the rendered quad rather than pretending closure did not happen. 0082 refuses
to move an object to hide a splat artifact. 0104 declares a clip volume rather
than rescaling. 0136 refuses to pretend the room is tidier than it is.

The alternative — enforce the ideal and refuse — looks principled and is
actually a solver failing at its job while sounding rigorous about it. That
distinction is worth naming because it is easy to mistake refusal-rate for
integrity. Refusing something the room contains is not honesty; it is being
wrong in a flattering direction.

Measured after the change, over every placed piece × every relation × every
anchor in all four rooms: **318 solves, 261 grounded, 57 refused** (27
`no_clear_space`, 23 `no_room_to_move`, 7 `already_there`), wall relations
21/21, 3.9 ms each. The refusals that remain are real: a 1.85 × 2.16 m bed in
a 15 m² room genuinely has nowhere else to go.

## The sibling finding: "nearest wall" is not a wall

The same run exposed a second wrong assumption. `against_wall` with no anchor
originally took the wall the piece was already nearest — a defensible reading
of "push it back against the wall". On the spike room, the nearest wall to the
bed is **0.35 m wide**: RoomPlan splits walls at every corner and opening, so
a 15 m² room ships 13 of them, most of them stubs.

Sweeping only the nearest refused a bed that has four perfectly good walls
available. Every wall is now a candidate and the cost function picks — for a
plain "against the wall", the smallest honest move.

Both corrections have regression tests over the real fixtures
(`TestRealRooms`), because both were invisible until the solver met real
geometry and would be invisible again if they regressed.

## What would change this decision

- **Perception stops shipping overlapping boxes.** The 0080 walk lists
  cross-label duplicates as a defect class; if that closes, the overlap
  exemption stops firing and can be reconsidered — though the chair-under-table
  case is physically real and will survive any dedup.
- **A user complains that a proposal made an existing overlap worse.** The
  exemption is currently binary per pair. A "may not increase the overlap"
  rule is the obvious next refinement and was deliberately not built, because
  nothing yet says it is needed.
