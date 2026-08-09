"""The solver: an intent in the guest's vocabulary → a transform, or a refusal.

Decision 0132 splits stage 2 down the line of who can source a claim. The
guest owns language and states an INTENT ("against the wall", "beside the
desk"); this module owns geometry and turns that into a measured transform —
or declines. Neither is asked for the other's job.

REFUSAL IS THE FEATURE. `{applied: false, reason}` is the same shape as
`placed: false` with a reason, which this pipeline has shipped since 0052 and
the single-view contact priors (0067) restated as THE EVIDENCE RULE: a
proposed transform ships only if it is grounded; a guessed transform is never
emitted. Every path out of here is either a transform that satisfies every
constraint below, or a machine reason the guest can say out loud.

THE CONSTRAINTS, all measured:
  - the piece's whole footprint lands inside the measured floor polygon
  - it overlaps no other placed piece's footprint (0129 watched a moved bed
    pass through a chair and a nightstand; no rendering treatment fixes that,
    so the specification owns it)
  - it keeps its height: proposals translate in the floor plane and never
    lift a piece off the surface it was measured on

...each held to the standard the MEASURED ROOM ITSELF MEETS, not an ideal one
— see `Tolerances`, which exists because the first version of this module
refused arrangements the real rooms actually contain.

MEASURED, on the four preserved walk rooms (2026-08-09): 318 solves over
every placed piece × every relation × every anchor. 261 grounded, 57 refused
(27 no_clear_space, 23 no_room_to_move, 7 already_there); wall relations
21/21; 3.9 ms per solve, so the shell read 0132 flagged as a new cost on the
turn's hot path is the part worth measuring, not this. Rooms with no
RoomPlan boxes ship 0 movable pieces and every relation refuses — the honest
degrade, since without a measured footprint nothing here could check
anything.

TRANSLATION ONLY, and this is a scope cut with evidence behind it. v1 never
rotates a piece. Every box placement in production ships
`splat_axis_resolved: false` (0080, re-measured in 0104), live axis margins
run 0.002–0.089 against a 0.10 gate, and 0104 killed four separate attacks on
that DOF — a cloud instrument, per-view appearance aggregation, the 180°
partner test and a truncation-direction prior. "Turn it to face the room" is
therefore a claim the pipeline cannot ground today, and turning a piece whose
own axis mapping is a default would make the room worse, not better. Re-open
when splat axis resolution does.

Consumers: guest_tools.py (the tool runner), tests/test_spec_solver.py.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from room_geometry import (
    OrientedBox,
    RoomGeometry,
    RoomObject,
    RoomOpening,
    RoomWall,
    Vec3,
    footprint_inside_floor,
    footprints_overlap,
)

# The closed relation vocabulary. Free text is deliberately excluded: it makes
# the refusal path unenumerable, which is 0132's stated reason for a closed
# set. Anything outside this is `unknown_relation`.
WALL_RELATIONS = frozenset({"against_wall", "centered_on_wall"})
OBJECT_RELATIONS = frozenset({"beside", "nearer_to", "further_from"})
RELATIONS = WALL_RELATIONS | OBJECT_RELATIONS

# Breathing room kept between two pieces that a proposal puts side by side.
# Not a clearance claim — a placement margin, and the description never
# quotes it as a measurement.
SIDE_GAP_M = 0.08
# How far "further from" moves in one step.
STEP_M = 0.5
# Lateral sampling resolution when sliding a piece along a wall to find a
# clear spot. Deterministic count, not a step size, so the search is the same
# on a 2 m wall and a 6 m one.
_WALL_SAMPLES = 81
_LINE_SAMPLES = 64


@dataclass(frozen=True)
class Solution:
    """A grounded proposal. Every field is server-authored; the guest may
    quote `description` verbatim and nothing else (0132's rule-2 extension:
    transforms are verbatim too)."""
    center: Vec3            # the box centre the proposal puts the piece at
    position: Vec3          # the world_transform position that follows
    relation: str
    anchor_resolved_to: str
    constraints_applied: tuple[str, ...]
    reasoning: str
    description: str


@dataclass(frozen=True)
class Refusal:
    """A proposal that could not be grounded. `reason` is machine vocabulary;
    the guest turns it into its own sentence, in voice."""
    reason: str
    detail: str = ""


Outcome = Solution | Refusal


# ---------------------------------------------------------------------------
# Anchors
# ---------------------------------------------------------------------------

_STOPWORDS = ("the ", "a ", "an ", "my ", "that ", "this ")


def normalize_anchor(text: str) -> str:
    out = " ".join(str(text or "").strip().lower().split())
    changed = True
    while changed:
        changed = False
        for word in _STOPWORDS:
            if out.startswith(word):
                out = out[len(word):]
                changed = True
    return out


def resolve_object_anchor(
    geometry: RoomGeometry, anchor: str, *, exclude_key: str
) -> RoomObject | Refusal:
    """Resolve the person's own words to a placed piece.

    Matching is deliberately shallow — exact spoken name, then label, then a
    containment fallback — because a clever matcher that guesses is the same
    failure as a solver that guesses. Two candidates refuse rather than pick.
    """
    want = normalize_anchor(anchor)
    if not want:
        return Refusal("anchor_missing")
    candidates = [
        o for o in geometry.objects
        if o.key != exclude_key and o.placed and o.box is not None
    ]
    for match in (
        lambda o: normalize_anchor(o.name) == want,
        lambda o: normalize_anchor(o.label) == want,
        lambda o: want in normalize_anchor(o.name)
        or normalize_anchor(o.label) in want,
    ):
        hits = [o for o in candidates if match(o)]
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:
            return Refusal(
                "ambiguous_anchor",
                ", ".join(sorted(o.name for o in hits)),
            )
    return Refusal("anchor_not_found", want)


def resolve_wall_anchor(
    geometry: RoomGeometry, anchor: str | None, mover: OrientedBox
) -> tuple[RoomWall, RoomOpening | None] | Refusal:
    """Resolve a wall-seeking anchor to a wall, and to an opening on it when
    the person named one ("under the window").

    A wall relation with no anchor takes the wall the piece is ALREADY
    nearest — a measurable reading of "push it back against the wall",
    rather than a wall picked by taste. The description does NOT echo the
    idiom's "back": that word is revert's here (0108), so it only appears
    when the user themselves supplied it.
    """
    if not geometry.walls:
        return Refusal("no_measured_walls")
    want = normalize_anchor(anchor or "")
    if not want or want in ("wall", "walls"):
        nearest = min(
            geometry.walls,
            key=lambda w: (abs(w.signed_distance(*_xz(mover.center))), w.wall_id),
        )
        return (nearest, None)

    openings = [
        o for o in geometry.openings
        if want == normalize_anchor(o.classification)
        or normalize_anchor(o.classification) in want
    ]
    if len(openings) > 1:
        # 0132's own example of the refusal that matters: the guest never
        # claimed to see a window, so "which one" is not something it can
        # answer either.
        return Refusal("ambiguous_anchor", f"{len(openings)} {want}s")
    if len(openings) == 1:
        opening = openings[0]
        for wall in geometry.walls:
            if wall.wall_id == opening.wall_id:
                return (wall, opening)
        return Refusal("anchor_not_found", want)
    return Refusal("anchor_not_found", want)


def _xz(v: Vec3) -> tuple[float, float]:
    return (v[0], v[2])


# ---------------------------------------------------------------------------
# Constraints
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Tolerances:
    """What the MEASURED room already does.

    A proposal is held to the room's own standard, not to an ideal one, and
    this is not a softening — it is the same rule as everywhere else here:
    never falsify a measurement, and never hold a proposal to a bar the
    measurement fails. Measured on the four preserved walk rooms
    (2026-08-09), and the reason this class exists rather than a plain
    "no overlaps, stay in the room" pair of checks:

      - 4 placed boxes across 3 rooms have footprints that leave the measured
        floor polygon. Real: RoomPlan boxes reach into alcoves and under
        walls, and the single-view contact priors already carry a floor-hit
        MARGIN (PLACEMENT_FLOOR_HIT_MARGIN_M) for the same reason.
      - 4 pairs across 3 rooms already overlap in footprint — a chair pushed
        under a table is the clearest, and it is physically correct.

    So `outside_room` is only a refusal for a piece that was measured fully
    inside, and `would_overlap` is only a refusal for a pair that was not
    already overlapping. Anything else would refuse to reproduce arrangements
    the room actually contains.
    """
    floor_exempt: bool
    already_overlapping: frozenset[str]


def _others(geometry: RoomGeometry, mover_key: str) -> list[RoomObject]:
    return [
        o for o in geometry.objects
        if o.key != mover_key and o.placed and o.box is not None
    ]


def tolerances(geometry: RoomGeometry, obj: RoomObject) -> Tolerances:
    assert obj.box is not None
    exempt = bool(geometry.floor_polygon) and not footprint_inside_floor(
        obj.box, geometry.floor_polygon
    )
    overlapping = {
        other.key
        for other in _others(geometry, obj.key)
        if other.box is not None and footprints_overlap(obj.box, other.box)
    }
    return Tolerances(floor_exempt=exempt, already_overlapping=frozenset(overlapping))


def _violation(
    geometry: RoomGeometry,
    mover_key: str,
    candidate: OrientedBox,
    tol: Tolerances,
) -> str | None:
    """The first constraint this candidate breaks, or None."""
    if (
        geometry.floor_polygon
        and not tol.floor_exempt
        and not footprint_inside_floor(candidate, geometry.floor_polygon)
    ):
        return "outside_room"
    for other in _others(geometry, mover_key):
        assert other.box is not None
        if other.key in tol.already_overlapping:
            continue
        if footprints_overlap(candidate, other.box):
            return "would_overlap"
    return None


def _constraints(geometry: RoomGeometry, tol: Tolerances) -> tuple[str, ...]:
    """Which constraints were actually ENFORCED — never a claim that a check
    ran when the geometry to run it did not exist, or when the measured room
    itself failed it."""
    out = ["keeps_height"]
    if geometry.floor_polygon and not tol.floor_exempt:
        out.append("inside_measured_floor")
    out.append("clear_of_pieces_it_was_clear_of")
    return tuple(out)


def _at(mover: OrientedBox, x: float, z: float) -> OrientedBox:
    return mover.moved_to((x, mover.center[1], z))


def _solution(
    obj: RoomObject,
    candidate: OrientedBox,
    geometry: RoomGeometry,
    tol: Tolerances,
    *,
    relation: str,
    anchor_resolved_to: str,
    reasoning: str,
    description: str,
) -> Solution:
    assert obj.box is not None and obj.position is not None
    delta = (
        candidate.center[0] - obj.box.center[0],
        candidate.center[2] - obj.box.center[2],
    )
    return Solution(
        center=candidate.center,
        # The splat's own transform moves by the same delta as its box: the
        # two were measured together and a proposal must never separate them.
        position=(
            obj.position[0] + delta[0],
            obj.position[1],
            obj.position[2] + delta[1],
        ),
        relation=relation,
        anchor_resolved_to=anchor_resolved_to,
        constraints_applied=_constraints(geometry, tol),
        reasoning=reasoning,
        description=description,
    )


# ---------------------------------------------------------------------------
# Relations
# ---------------------------------------------------------------------------

def _wall_depth(box: OrientedBox, wall: RoomWall) -> float:
    """How far the box's footprint reaches from its centre toward the wall —
    its support-width along the wall normal, exactly, from the four corners.
    Using the circumradius here would leave every piece standing off the wall
    by a gap nobody asked for."""
    return max(
        abs((cx - box.center[0]) * wall.normal[0] + (cz - box.center[2]) * wall.normal[1])
        for cx, cz in box.footprint_corners()
    )


def _solve_wall(
    obj: RoomObject,
    geometry: RoomGeometry,
    tol: Tolerances,
    relation: str,
    anchor: str | None,
) -> Outcome:
    """Stand the piece flush against a wall it actually fits against.

    Candidate walls are EVERY wall when the person did not name one, not the
    nearest — measured on the spike room, whose nearest wall to the bed is a
    0.35 m stub (RoomPlan splits walls at every corner and opening, so a 15 m²
    room ships 13 of them). Sweeping only the nearest refused a bed that has
    four perfectly good walls to stand against, which is a solver failing at
    its job while sounding principled about it.
    """
    assert obj.box is not None
    resolved = resolve_wall_anchor(geometry, anchor, obj.box)
    if isinstance(resolved, Refusal):
        return resolved
    named_wall, opening = resolved
    # A named opening pins the wall. Otherwise every wall is a candidate and
    # the cost function below picks — which, for a plain "against the wall",
    # means the smallest honest move.
    walls = [named_wall] if opening is not None else list(geometry.walls)

    best: tuple[float, OrientedBox, RoomWall, float] | None = None
    for wall in walls:
        depth = _wall_depth(obj.box, wall)
        if opening is not None:
            target = _xz(opening.center)
        elif relation == "centered_on_wall":
            mid = wall.point_at(0.5)
            target = (mid[0] + wall.normal[0] * depth, mid[2] + wall.normal[1] * depth)
        else:
            target = _xz(obj.box.center)
        # Slide along the wall for the free spot nearest the target. Sampling
        # rather than solving: the obstacle set is arbitrary, and a
        # deterministic sweep that reports honestly beats a closed form that
        # only works when the wall is empty.
        for i in range(_WALL_SAMPLES):
            u = i / (_WALL_SAMPLES - 1)
            base = wall.point_at(u)
            candidate = _at(
                obj.box,
                base[0] + wall.normal[0] * depth,
                base[2] + wall.normal[1] * depth,
            )
            if _violation(geometry, obj.key, candidate, tol) is not None:
                continue
            cost = math.dist(_xz(candidate.center), target)
            if best is None or (cost, wall.wall_id) < (best[0], best[2].wall_id):
                best = (cost, candidate, wall, u)
    if best is None:
        return Refusal(
            "no_clear_space",
            "nothing fits against that wall"
            if opening is not None
            else "no wall in this room has room for it",
        )
    _, candidate, wall, _u = best
    moved = math.dist(_xz(candidate.center), _xz(obj.box.center))

    if opening is not None:
        where = f"under the {opening.classification}"
        anchor_name = opening.classification
    elif relation == "centered_on_wall":
        where = "centred on the wall"
        anchor_name = wall.wall_id
    else:
        where = "against the wall"
        anchor_name = wall.wall_id
    return _solution(
        obj, candidate, geometry, tol,
        relation=relation,
        anchor_resolved_to=anchor_name,
        reasoning=(
            f"Stood the {obj.name} flush against wall {wall.wall_id}, {where}, "
            f"{moved:.2f} m from where it was measured — the nearest spot on "
            f"any wall that satisfies every constraint. Checked: "
            + ", ".join(_constraints(geometry, tol)) + "."
        ),
        description=(
            f"the {obj.name} is against the wall, {where}"
            if opening is not None or relation == "centered_on_wall"
            # No "back": in this surface that word belongs to revert ("the
            # room is back as measured"), and a first-time placement must not
            # read as an undo (0108).
            else f"the {obj.name} is against the wall"
        ),
    )


def _solve_beside(
    obj: RoomObject, geometry: RoomGeometry, tol: Tolerances, anchor: str | None
) -> Outcome:
    assert obj.box is not None
    other = resolve_object_anchor(geometry, anchor or "", exclude_key=obj.key)
    if isinstance(other, Refusal):
        return other
    assert other.box is not None

    # Four sides of the anchor, in its own frame — a piece put "beside" the
    # desk should line up with the desk, not with the room's grid.
    axes = other.box.local_axes_xz()
    reach = (
        other.box.dims[0] / 2.0 + obj.box.dims[0] / 2.0 + SIDE_GAP_M,
        other.box.dims[2] / 2.0 + obj.box.dims[2] / 2.0 + SIDE_GAP_M,
    )
    best: tuple[float, OrientedBox] | None = None
    for i, axis in enumerate(axes):
        for sign in (1.0, -1.0):
            candidate = _at(
                obj.box,
                other.box.center[0] + axis[0] * reach[i] * sign,
                other.box.center[2] + axis[1] * reach[i] * sign,
            )
            if _violation(geometry, obj.key, candidate, tol) is not None:
                continue
            # Prefer the side it is already on: the smallest move that
            # satisfies the request is the one the person meant.
            cost = math.dist(_xz(candidate.center), _xz(obj.box.center))
            if best is None or cost < best[0]:
                best = (cost, candidate)
    if best is None:
        return Refusal("no_clear_space", f"no free side of the {other.name}")
    return _solution(
        obj, best[1], geometry, tol,
        relation="beside",
        anchor_resolved_to=other.name,
        reasoning=(
            f"Placed the {obj.name} on the free side of the {other.name} "
            f"closest to where it already stood, aligned to the "
            f"{other.name}'s own frame. Checked: "
            + ", ".join(_constraints(geometry, tol)) + "."
        ),
        description=f"the {obj.name} is beside the {other.name}",
    )


def _solve_along_line(
    obj: RoomObject,
    geometry: RoomGeometry,
    tol: Tolerances,
    relation: str,
    anchor: str | None,
) -> Outcome:
    assert obj.box is not None
    other = resolve_object_anchor(geometry, anchor or "", exclude_key=obj.key)
    if isinstance(other, Refusal):
        return other
    assert other.box is not None

    ax, az = _xz(obj.box.center)
    bx, bz = _xz(other.box.center)
    dx, dz = ax - bx, az - bz
    length = math.hypot(dx, dz)
    if length < 1e-6:
        return Refusal("already_there", "the two centres coincide")
    ux, uz = dx / length, dz / length

    if relation == "further_from":
        # One honest step outward, and if the room will not take a full step,
        # the furthest it will take.
        best: OrientedBox | None = None
        for i in range(_LINE_SAMPLES, 0, -1):
            step = STEP_M * i / _LINE_SAMPLES
            candidate = _at(obj.box, ax + ux * step, az + uz * step)
            if _violation(geometry, obj.key, candidate, tol) is None:
                best = candidate
                break
        if best is None:
            return Refusal("no_room_to_move", "nothing clear in that direction")
        moved = math.dist(_xz(best.center), (ax, az))
        if moved < 0.05:
            return Refusal("no_room_to_move", "nothing clear in that direction")
        verb, word = "away from", "further from"
    else:
        # As close as the measured shapes allow, approaching along the line
        # and stopping at the last clear sample — the gap that results is a
        # consequence of the two footprints, never a number we chose.
        best = None
        for i in range(1, _LINE_SAMPLES + 1):
            step = length * i / (_LINE_SAMPLES + 1)
            candidate = _at(obj.box, ax - ux * step, az - uz * step)
            if _violation(geometry, obj.key, candidate, tol) is not None:
                break
            best = candidate
        if best is None:
            return Refusal("already_there", f"as close to the {other.name} as it fits")
        moved = math.dist(_xz(best.center), (ax, az))
        if moved < 0.05:
            return Refusal("already_there", f"as close to the {other.name} as it fits")
        verb, word = "toward", "nearer to"

    return _solution(
        obj, best, geometry, tol,
        relation=relation,
        anchor_resolved_to=other.name,
        reasoning=(
            f"Moved the {obj.name} {moved:.2f} m {verb} the {other.name} along "
            f"the line between their centres — the furthest that direction "
            f"stays clear. Checked: " + ", ".join(_constraints(geometry, tol)) + "."
        ),
        description=f"the {obj.name} is {word} the {other.name}",
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def solve(
    geometry: RoomGeometry,
    *,
    key: str,
    relation: str,
    anchor: str | None,
) -> Outcome:
    """Ground one stated intent, or refuse with a reason.

    The gates before any geometry runs are as load-bearing as the geometry:
    a piece with no measured box has no footprint, so nothing here could
    check that it lands in the room or clear of anything — and a proposal we
    cannot check is exactly the guess this house does not ship.
    """
    obj = geometry.by_key(key)
    if obj is None:
        return Refusal("unknown_object", key)
    if relation not in RELATIONS:
        return Refusal("unknown_relation", relation)
    if not obj.placed or obj.position is None:
        return Refusal("piece_not_placed", obj.name)
    if obj.box is None:
        return Refusal("piece_not_measured", obj.name)

    tol = tolerances(geometry, obj)
    if relation in WALL_RELATIONS:
        return _solve_wall(obj, geometry, tol, relation, anchor)
    if relation == "beside":
        return _solve_beside(obj, geometry, tol, anchor)
    return _solve_along_line(obj, geometry, tol, relation, anchor)
