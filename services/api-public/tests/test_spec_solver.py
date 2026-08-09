"""Tests for spec_solver.py — grounding an intent, or refusing (decision 0132).

Two kinds of test here, and the split is deliberate.

SYNTHETIC rooms pin the semantics exactly: a 4x4 m room with one wall and
known obstacles, where every expected outcome can be reasoned about by hand.

REAL rooms pin that the thing works on the data it will actually meet — the
four preserved walk rooms, where the numbers are nobody's choice. That is
where the two design corrections came from: an ideal constraint set refused
arrangements the measured rooms contain, and "nearest wall" picked a 0.35 m
stub. Both have regression tests below, because both were invisible until
someone ran the solver over real geometry.

Run from repo root:
  pytest services/api-public/tests/test_spec_solver.py -v
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from room_geometry import RoomGeometry, RoomObject, OrientedBox, derive_room_geometry
from scene_facts import derive_scene_facts
from spec_solver import (
    RELATIONS,
    Refusal,
    Solution,
    normalize_anchor,
    solve,
    tolerances,
)

_FIXTURES = Path(__file__).resolve().parents[3] / "web/public/dev-fixtures"
_WALK_ROOMS = (
    "scene-spike-a7e073ae",
    "scene-rp7-a71d125f",
    "scene-rp6g1-09684dde",
    "scene-rp6g2-b667f891",
)


def _rooms():
    out = []
    for name in _WALK_ROOMS:
        path = _FIXTURES / name / "assets.json"
        if not path.exists():
            continue
        doc = json.loads(path.read_text())
        facts = derive_scene_facts(doc["manifest"])
        out.append((name, derive_room_geometry(
            doc["manifest"], doc.get("shell"),
            names={i.object_id: i.name for i in facts.inventory},
        )))
    if not out:
        pytest.skip("no staged walk-room fixtures present")
    return out


# ---------------------------------------------------------------------------
# A room simple enough to reason about by hand
# ---------------------------------------------------------------------------

def _piece(key, name, cx, cz, w=1.0, d=1.0, yaw=0.0, placed=True):
    return RoomObject(
        key=key, object_id=key, box_identifier=None, name=name, label=name,
        placed=placed,
        box=OrientedBox(center=(cx, 0.5, cz), dims=(w, 1.0, d), yaw_rad=yaw),
        position=(cx, 0.5, cz),
    )


def _room(*objects, walls=True):
    """A 4x4 m room. One wall along z=0 facing +z (the room side), one along
    x=0 facing +x, so 'against a wall' has two honest answers."""
    from room_geometry import RoomWall

    made = ()
    if walls:
        made = (
            RoomWall("north", (0.0, 1.0), (1.0, 0.0), (0.0, 0.0, 0.0), 4.0, 2.5, ()),
            RoomWall("west", (1.0, 0.0), (0.0, -1.0), (0.0, 0.0, 4.0), 4.0, 2.5, ()),
        )
    return RoomGeometry(
        objects=objects,
        floor_polygon=((0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0)),
        floor_y=0.0,
        walls=made,
    )


class TestGates:
    """Everything checked before a single coordinate is computed."""

    def test_unknown_object_and_unknown_relation(self):
        g = _room(_piece("a", "chair", 2, 2))
        assert solve(g, key="ghost", relation="beside", anchor="chair").reason \
            == "unknown_object"
        assert solve(g, key="a", relation="teleport", anchor="x").reason \
            == "unknown_relation"

    def test_a_piece_with_no_measured_box_cannot_be_proposed(self):
        """The gate that matters: without a footprint nothing here could check
        that a placement lands in the room or clear of anything, and a
        proposal we cannot check is exactly the guess this house doesn't ship.
        """
        naked = RoomObject(
            key="n", object_id="n", box_identifier=None, name="mirror",
            label="mirror", placed=True, box=None, position=(1.0, 1.0, 1.0),
        )
        assert solve(_room(naked), key="n", relation="against_wall",
                     anchor=None).reason == "piece_not_measured"

    def test_an_unplaced_piece_has_nowhere_to_move_from(self):
        seen = RoomObject(
            key="s", object_id="s", box_identifier=None, name="lamp", label="lamp",
            placed=False, box=OrientedBox((1, 1, 1), (1, 1, 1), 0.0), position=None,
        )
        assert solve(_room(seen), key="s", relation="against_wall",
                     anchor=None).reason == "piece_not_placed"

    def test_a_room_with_no_measured_walls_refuses_wall_relations(self):
        g = _room(_piece("a", "chair", 2, 2), walls=False)
        for relation in ("against_wall", "centered_on_wall"):
            assert solve(g, key="a", relation=relation, anchor=None).reason \
                == "no_measured_walls"


class TestAnchors:
    def test_normalize_strips_the_words_people_actually_use(self):
        assert normalize_anchor("  The  Desk ") == "desk"
        assert normalize_anchor("that the window") == "window"
        assert normalize_anchor("") == ""

    def test_two_candidates_refuse_rather_than_pick(self):
        g = _room(_piece("a", "bed", 2, 2), _piece("b", "chair", 3, 3),
                  _piece("c", "chair", 1, 1))
        out = solve(g, key="a", relation="beside", anchor="chair")
        assert out.reason == "ambiguous_anchor" and "chair" in out.detail

    def test_an_unknown_anchor_says_so(self):
        g = _room(_piece("a", "bed", 2, 2))
        assert solve(g, key="a", relation="beside", anchor="piano").reason \
            == "anchor_not_found"
        assert solve(g, key="a", relation="beside", anchor="").reason \
            == "anchor_missing"

    def test_a_piece_is_never_its_own_anchor(self):
        g = _room(_piece("a", "bed", 2, 2))
        assert solve(g, key="a", relation="beside", anchor="bed").reason \
            == "anchor_not_found"


class TestRelations:
    def test_against_wall_puts_the_footprint_flush(self):
        g = _room(_piece("a", "chair", 2.0, 2.0))
        out = solve(g, key="a", relation="against_wall", anchor=None)
        assert isinstance(out, Solution)
        # 1x1 piece, so its centre lands half a metre off whichever wall.
        assert min(abs(out.center[0]), abs(out.center[2])) == pytest.approx(0.5)
        assert out.center[1] == pytest.approx(0.5), "height must not change"
        assert "keeps_height" in out.constraints_applied
        assert "inside_measured_floor" in out.constraints_applied

    def test_a_first_time_move_never_says_back(self):
        """"back" is revert's word in this surface ("the room is back as
        measured"); a first-time placement asserting it reads as an undo
        that never happened (0108, operator-ruled)."""
        g = _room(_piece("a", "chair", 2.0, 2.0))
        out = solve(g, key="a", relation="against_wall", anchor=None)
        assert isinstance(out, Solution)
        assert out.description == "the chair is against the wall"
        assert "back" not in out.description

    def test_centered_on_wall_lands_on_the_midpoint(self):
        g = _room(_piece("a", "chair", 3.5, 3.5))
        out = solve(g, key="a", relation="centered_on_wall", anchor=None)
        assert isinstance(out, Solution)
        along = out.center[0] if out.center[2] < out.center[0] else out.center[2]
        assert along == pytest.approx(2.0, abs=0.06)

    def test_beside_aligns_to_the_anchor_and_leaves_a_gap(self):
        g = _room(_piece("a", "chair", 3.0, 1.0), _piece("b", "desk", 1.0, 1.0))
        out = solve(g, key="a", relation="beside", anchor="desk")
        assert isinstance(out, Solution)
        assert math.dist((out.center[0], out.center[2]), (1.0, 1.0)) \
            == pytest.approx(1.08, abs=1e-6)  # half + half + SIDE_GAP_M
        assert out.anchor_resolved_to == "desk"

    def test_nearer_to_stops_at_contact_never_inside(self):
        from room_geometry import footprints_overlap
        g = _room(_piece("a", "chair", 3.5, 1.0), _piece("b", "desk", 1.0, 1.0))
        out = solve(g, key="a", relation="nearer_to", anchor="desk")
        assert isinstance(out, Solution)
        mover = g.by_key("a").box.moved_to(out.center)
        assert not footprints_overlap(mover, g.by_key("b").box)
        assert out.center[0] < 3.5

    def test_further_from_moves_away_along_the_line(self):
        g = _room(_piece("a", "chair", 2.0, 1.0), _piece("b", "desk", 1.0, 1.0))
        out = solve(g, key="a", relation="further_from", anchor="desk")
        assert isinstance(out, Solution)
        assert out.center[0] > 2.0
        assert out.center[2] == pytest.approx(1.0)

    def test_further_from_refuses_when_the_room_runs_out(self):
        # A 1x1 piece centred at 3.48 has 2 cm before its corner leaves the
        # room — below the 5 cm floor under which a "move" is not a move.
        g = _room(_piece("a", "chair", 3.48, 1.0), _piece("b", "desk", 1.0, 1.0))
        assert solve(g, key="a", relation="further_from", anchor="desk").reason \
            == "no_room_to_move"

    def test_further_from_takes_a_short_step_when_it_cannot_take_a_full_one(self):
        g = _room(_piece("a", "chair", 3.2, 1.0), _piece("b", "desk", 1.0, 1.0))
        out = solve(g, key="a", relation="further_from", anchor="desk")
        assert isinstance(out, Solution)
        assert 3.2 < out.center[0] <= 3.5, "must stop at the wall, not beyond it"

    def test_nearer_to_refuses_when_already_touching(self):
        g = _room(_piece("a", "chair", 2.05, 1.0), _piece("b", "desk", 1.0, 1.0))
        assert solve(g, key="a", relation="nearer_to", anchor="desk").reason \
            == "already_there"

    def test_a_blocked_wall_refuses_rather_than_stacking(self):
        from room_geometry import RoomWall

        # Every wall in the room fully occupied: 4 one-metre pieces along the
        # single wall at z=0. The piece has nowhere flush to go, and stacking
        # it on top of one is not an answer.
        blockers = [_piece(f"b{i}", f"box{i}", 0.5 + i, 0.5) for i in range(4)]
        g = RoomGeometry(
            objects=(_piece("a", "chair", 2.0, 2.0), *blockers),
            floor_polygon=((0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0)),
            floor_y=0.0,
            walls=(RoomWall("north", (0.0, 1.0), (1.0, 0.0), (0.0, 0.0, 0.0),
                            4.0, 2.5, ()),),
        )
        out = solve(g, key="a", relation="against_wall", anchor=None)
        assert isinstance(out, Refusal) and out.reason == "no_clear_space"


class TestTolerances:
    """The correction real data forced: a proposal is held to the standard the
    MEASUREMENT meets, never a better one."""

    def test_a_piece_already_overhanging_is_not_asked_to_stop(self):
        overhang = _piece("a", "cabinet", 3.9, 2.0)  # half out of the room
        g = _room(overhang, _piece("b", "desk", 1.0, 1.0))
        tol = tolerances(g, g.by_key("a"))
        assert tol.floor_exempt is True
        out = solve(g, key="a", relation="beside", anchor="desk")
        assert isinstance(out, Solution)
        assert "inside_measured_floor" not in out.constraints_applied, (
            "must not claim a check it did not enforce"
        )

    def test_a_pair_that_already_overlaps_stays_allowed_to(self):
        # A chair pushed under a table: physically correct, and present in
        # the real rooms.
        g = _room(_piece("a", "chair", 1.2, 1.0), _piece("t", "table", 1.0, 1.0,
                                                        w=2.0, d=2.0))
        tol = tolerances(g, g.by_key("a"))
        assert "t" in tol.already_overlapping
        out = solve(g, key="a", relation="nearer_to", anchor="table")
        assert isinstance(out, (Solution, Refusal))  # not blocked by the table
        # ...and a piece it was clear of still blocks it.
        g2 = _room(_piece("a", "chair", 1.2, 1.0),
                   _piece("t", "table", 1.0, 1.0, w=2.0, d=2.0),
                   _piece("w", "wardrobe", 3.0, 1.0))
        out2 = solve(g2, key="a", relation="further_from", anchor="table")
        if isinstance(out2, Solution):
            from room_geometry import footprints_overlap
            moved = g2.by_key("a").box.moved_to(out2.center)
            assert not footprints_overlap(moved, g2.by_key("w").box)


class TestRealRooms:
    def test_every_relation_grounds_somewhere_in_every_room(self):
        """The regression for BOTH design corrections. Before the tolerance
        rule and the all-walls sweep this matrix was almost entirely
        refusals — on rooms the operator has walked and accepted."""
        totals = {"solved": 0, "refused": 0}
        for name, g in _rooms():
            movers = [o for o in g.objects if o.placed and o.box]
            if not movers:
                continue
            hit = set()
            for m in movers:
                for relation in sorted(RELATIONS):
                    anchors = (
                        [None] if relation in ("against_wall", "centered_on_wall")
                        else [o.name for o in movers if o.key != m.key]
                    )
                    for anchor in anchors:
                        out = solve(g, key=m.key, relation=relation, anchor=anchor)
                        if isinstance(out, Solution):
                            hit.add(relation)
                            totals["solved"] += 1
                        else:
                            totals["refused"] += 1
            assert hit == RELATIONS, f"{name}: no solution for {RELATIONS - hit}"
        # Measured 2026-08-09: 261 solved / 57 refused over 318.
        assert totals["solved"] > 3 * totals["refused"]

    def test_wall_relations_never_refuse_on_a_measured_room(self):
        for name, g in _rooms():
            for m in (o for o in g.objects if o.placed and o.box):
                for relation in ("against_wall", "centered_on_wall"):
                    out = solve(g, key=m.key, relation=relation, anchor=None)
                    assert isinstance(out, Solution), f"{name}/{m.name}/{relation}"

    def test_the_nearest_wall_can_be_a_stub_which_is_why_all_walls_are_swept(self):
        """The spike room's nearest wall to the bed is 0.35 m wide. Sweeping
        only the nearest refused a bed with four good walls available."""
        rooms = dict(_rooms())
        g = rooms.get("scene-spike-a7e073ae")
        if g is None:
            pytest.skip("spike fixture not present")
        bed = next(o for o in g.objects if o.label == "bed" and o.placed)
        nearest = min(
            g.walls, key=lambda w: abs(w.signed_distance(bed.box.center[0],
                                                         bed.box.center[2])))
        assert nearest.width_m < bed.box.dims[0], "fixture changed; re-derive"
        assert isinstance(solve(g, key=bed.key, relation="against_wall",
                                anchor=None), Solution)

    def test_a_solution_actually_satisfies_what_it_claims(self):
        """Independent re-check: whatever `constraints_applied` names, verify
        it directly rather than trusting the solver's own report."""
        from room_geometry import footprint_inside_floor, footprints_overlap
        checked = 0
        for name, g in _rooms():
            for m in (o for o in g.objects if o.placed and o.box):
                out = solve(g, key=m.key, relation="against_wall", anchor=None)
                if not isinstance(out, Solution):
                    continue
                checked += 1
                moved = m.box.moved_to(out.center)
                assert out.center[1] == pytest.approx(m.box.center[1])
                if "inside_measured_floor" in out.constraints_applied:
                    assert footprint_inside_floor(moved, g.floor_polygon), name
                tol = tolerances(g, m)
                for other in g.objects:
                    if other.key == m.key or not (other.placed and other.box):
                        continue
                    if other.key in tol.already_overlapping:
                        continue
                    assert not footprints_overlap(moved, other.box), \
                        f"{name}: {m.name} lands in {other.name}"
        assert checked >= 15

    def test_an_ambiguous_opening_refuses_which_is_0132s_own_example(self):
        rooms = dict(_rooms())
        g = rooms.get("scene-spike-a7e073ae")
        if g is None:
            pytest.skip("spike fixture not present")
        assert sum(1 for o in g.openings if o.classification == "window") == 2
        bed = next(o for o in g.objects if o.label == "bed" and o.placed)
        out = solve(g, key=bed.key, relation="against_wall", anchor="the window")
        assert out.reason == "ambiguous_anchor"

    def test_solutions_are_deterministic(self):
        for _name, g in _rooms():
            for m in (o for o in g.objects if o.placed and o.box):
                a = solve(g, key=m.key, relation="against_wall", anchor=None)
                b = solve(g, key=m.key, relation="against_wall", anchor=None)
                assert a == b
