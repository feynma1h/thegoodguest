"""Tests for room_geometry.py — the solver's world (decisions 0131/0132).

The load-bearing tests here are the REAL-DATA ones. Two facts this module
rests on were measured rather than assumed, and both would fail silently if
they ever stopped holding:

  - `roomplan_box.identifier` survives re-drives (the spec key, 0131)
  - `yaw_rad` rotates (x, z) as an ordinary 2D plane, NOT the way three.js
    `setFromAxisAngle([0,1,0], yaw)` does

so both are pinned against committed fixtures with the instruments that
established them, not against numbers typed in by hand.

Run from repo root:
  pytest services/api-public/tests/test_room_geometry.py -v
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from room_geometry import (
    OrientedBox,
    derive_room_geometry,
    footprint_inside_floor,
    footprints_overlap,
    point_in_polygon,
    spec_key,
)

_FIXTURES = Path(__file__).resolve().parents[3] / "web/public/dev-fixtures"
_SPIKE_ROOM = (
    Path(__file__).resolve().parents[2]
    / "perception-obj/tests/fixtures/roomplan_spike/captured_room_built.json"
)

# The four preserved walk rooms (decisions 0080/0085/0104). Gitignored
# staged fixtures, so every real-data test skips cleanly without them.
_WALK_ROOMS = (
    "scene-spike-a7e073ae",
    "scene-rp7-a71d125f",
    "scene-rp6g1-09684dde",
    "scene-rp6g2-b667f891",
)


def _assets(name: str) -> dict:
    path = _FIXTURES / name / "assets.json"
    if not path.exists():
        pytest.skip(f"staged fixture {name} not present")
    return json.loads(path.read_text())


def _rooms():
    out = []
    for name in _WALK_ROOMS:
        path = _FIXTURES / name / "assets.json"
        if path.exists():
            doc = json.loads(path.read_text())
            out.append((name, derive_room_geometry(doc["manifest"], doc.get("shell"))))
    if not out:
        pytest.skip("no staged walk-room fixtures present")
    return out


# ---------------------------------------------------------------------------
# The spec key (decision 0131)
# ---------------------------------------------------------------------------

class TestSpecKey:
    def test_box_identifier_wins_over_object_id(self):
        assert spec_key({
            "object_id": "obj_003",
            "roomplan_box": {"identifier": "D22E8F5D"},
        }) == "box:D22E8F5D"

    def test_object_id_is_the_fallback_and_the_namespaces_never_collide(self):
        assert spec_key({"object_id": "obj_021"}) == "obj:obj_021"
        assert spec_key({"object_id": "obj_021", "roomplan_box": {}}) == "obj:obj_021"
        assert spec_key({"object_id": "obj_021", "roomplan_box": {"identifier": ""}}) \
            == "obj:obj_021"

    def test_box_identifiers_survive_re_drives(self):
        """THE KEY THE WHOLE SPEC HANGS ON.

        The spike room's LIVE manifest was staged after RP-8's warm rounds and
        again after the 0104 re-drive; `captured_room_built.json` is the
        capture's own RoomPlan artifact, committed 2026-07-28. If every
        identifier in the live manifest is still one of the capture's, the key
        belongs to the capture rather than to the pipeline — which is exactly
        why it survives a re-drive when `object_id` does not.
        """
        if not _SPIKE_ROOM.exists():
            pytest.skip("spike room.json fixture not present")
        captured = {
            o["identifier"] for o in json.loads(_SPIKE_ROOM.read_text())["objects"]
        }
        manifest = _assets("scene-spike-a7e073ae")["manifest"]
        live = {
            o["roomplan_box"]["identifier"]
            for o in manifest["objects"]
            if o.get("roomplan_box", {}).get("identifier")
        }
        assert live, "fixture carries no box identifiers"
        assert live <= captured
        assert len(live) == len(captured) == 9


# ---------------------------------------------------------------------------
# The yaw convention (measured 2026-08-09)
# ---------------------------------------------------------------------------

def _wrap90(deg: float) -> float:
    return abs(((deg % 90) + 45) % 90 - 45)


class TestYawConvention:
    """Both instruments that established the convention, kept as tests.

    They are written as SIGN COMPARISONS rather than as fixed numbers so that
    they say what they mean: this sign reproduces reality and the other one
    does not. A future change that flips the convention fails loudly instead
    of subtly mis-clipping every room.
    """

    def test_boxes_align_to_the_walls_they_stand_against(self):
        for name, g in _rooms():
            if len(g.walls) > 6:
                continue  # many wall directions: the test stops discriminating
            boxes = [o.box for o in g.objects if o.placed and o.box]
            if not boxes:
                continue
            def err(box, ours: bool):
                # ours: +x -> (cos, sin). The rejected sign: +x -> (cos, -sin).
                yaw = box.yaw_rad if ours else -box.yaw_rad
                a = math.degrees(yaw)
                return min(
                    _wrap90(a - math.degrees(math.atan2(w.axis_u[1], w.axis_u[0])))
                    for w in g.walls
                )
            ours = [err(b, True) for b in boxes]
            flipped = [err(b, False) for b in boxes]
            assert sum(ours) / len(ours) < 8.0, f"{name}: boxes not wall-aligned"
            assert sum(ours) / len(ours) < sum(flipped) / len(flipped), name

    def test_a_box_against_a_wall_presents_an_edge_not_a_corner(self):
        """The decisive instrument. A wall-standing box's two nearest
        footprint corners are equidistant from the wall plane; a mis-rotated
        one shows a corner and they spread."""
        spreads = []
        for _name, g in _rooms():
            for obj in g.objects:
                if not (obj.placed and obj.box and g.walls):
                    continue
                corners = obj.box.footprint_corners()
                for wall in g.walls:
                    d = sorted(abs(wall.signed_distance(x, z)) for x, z in corners)
                    if d[0] < 0.35:
                        spreads.append(d[1] - d[0])
        if not spreads:
            pytest.skip("no wall-adjacent boxes in the staged fixtures")
        # Measured 2026-08-09: 0.000 m on almost every box under this
        # convention, 0.02-0.55 m under the other sign.
        assert min(spreads) < 0.005
        assert sorted(spreads)[len(spreads) // 2] < 0.05

    def test_footprint_corners_are_the_box_rotated_in_plane(self):
        box = OrientedBox(center=(1.0, 0.5, 2.0), dims=(2.0, 1.0, 4.0), yaw_rad=0.0)
        assert box.footprint_corners()[0] == pytest.approx((0.0, 0.0))
        assert box.footprint_corners()[2] == pytest.approx((2.0, 4.0))
        turned = OrientedBox(center=(0.0, 0.0, 0.0), dims=(2.0, 1.0, 4.0),
                             yaw_rad=math.pi / 2)
        # +x maps to +z, +z maps to -x.
        (ax, az), (bx, bz) = turned.local_axes_xz()
        assert (ax, az) == pytest.approx((0.0, 1.0), abs=1e-9)
        assert (bx, bz) == pytest.approx((-1.0, 0.0), abs=1e-9)


class TestBoxAxisSemantics:
    def test_dims_are_width_height_depth_not_a_sorted_triple(self):
        """`scene_facts` SIZES states the triple is descending-sorted and its
        axis semantics unrecoverable, and limits the guest to a longest
        dimension on that basis. On the real rooms it is not sorted in any
        order and dims[1] is the height every time — every box over 1.5 m
        tall is a wardrobe or a refrigerator. Pinned here because it is the
        evidence board item 10(a) was waiting for; changing what the guest may
        SAY is 0096's call and needs its own voice evals."""
        largest_at = {0: 0, 1: 0, 2: 0}
        tall = []
        for _name, g in _rooms():
            for obj in g.objects:
                if obj.box is None:
                    continue
                dims = list(obj.box.dims)
                largest_at[dims.index(max(dims))] += 1
                if dims[1] > 1.5:
                    tall.append(obj.label)
        assert sum(largest_at.values()) >= 20
        # Not sorted: the largest lands on all three axes across real rooms.
        assert sum(1 for v in largest_at.values() if v > 0) == 3
        assert all(t in ("storage", "refrigerator", "wardrobe") for t in tall), tall

    def test_base_y_puts_the_box_on_its_own_floor(self):
        box = OrientedBox(center=(0, 1.0, 0), dims=(1, 2.0, 1), yaw_rad=0.3)
        assert box.base_y == pytest.approx(0.0)
        assert box.footprint_radius == pytest.approx(math.hypot(1, 1) / 2)


# ---------------------------------------------------------------------------
# Predicates
# ---------------------------------------------------------------------------

class TestPredicates:
    _SQUARE = ((0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0))

    def test_point_in_polygon(self):
        assert point_in_polygon((2.0, 2.0), self._SQUARE)
        assert not point_in_polygon((5.0, 2.0), self._SQUARE)
        assert not point_in_polygon((2.0, 2.0), ((0.0, 0.0), (1.0, 1.0)))

    def test_footprint_containment_uses_corners_not_the_centre(self):
        # A piece half out of the room has its CENTRE inside; corner
        # containment is the point (0067 chunk D's conservative posture).
        straddling = OrientedBox(center=(3.9, 0, 2.0), dims=(1.0, 1.0, 1.0), yaw_rad=0)
        assert point_in_polygon((3.9, 2.0), self._SQUARE)
        assert not footprint_inside_floor(straddling, self._SQUARE)
        inside = OrientedBox(center=(2.0, 0, 2.0), dims=(1.0, 1.0, 1.0), yaw_rad=0.7)
        assert footprint_inside_floor(inside, self._SQUARE)

    def test_no_floor_means_nothing_is_contained(self):
        box = OrientedBox(center=(0, 0, 0), dims=(1, 1, 1), yaw_rad=0)
        assert not footprint_inside_floor(box, ())

    def test_separating_axis_on_rotated_rectangles(self):
        a = OrientedBox(center=(0, 0, 0), dims=(2.0, 1.0, 1.0), yaw_rad=0.0)
        assert footprints_overlap(a, a)
        clear = OrientedBox(center=(3.0, 0, 0), dims=(2.0, 1.0, 1.0), yaw_rad=0.0)
        assert not footprints_overlap(a, clear)
        # 0.1 m apart edge to edge: clear on its own, overlapping under a gap.
        near = OrientedBox(center=(2.1, 0, 0), dims=(2.0, 1.0, 1.0), yaw_rad=0.0)
        assert not footprints_overlap(a, near)
        assert footprints_overlap(a, near, gap_m=0.2)
        # A 45-degree turn makes a previously-clear pair touch: the test that
        # a centre-distance or circumradius check would get wrong.
        turned = OrientedBox(center=(1.6, 0, 0), dims=(2.0, 1.0, 1.0),
                             yaw_rad=math.pi / 4)
        assert footprints_overlap(a, turned)


# ---------------------------------------------------------------------------
# Derivation and its degrades
# ---------------------------------------------------------------------------

class TestDerivation:
    def test_real_room_derives_walls_floor_and_openings(self):
        doc = _assets("scene-spike-a7e073ae")
        g = derive_room_geometry(doc["manifest"], doc["shell"])
        assert len(g.walls) == 13
        assert len(g.floor_polygon) == 10
        assert g.floor_y == pytest.approx(-1.4178, abs=1e-3)
        kinds = sorted(o.classification for o in g.openings)
        assert kinds == ["door", "door", "opening", "opening", "window", "window"]
        # Every opening sits ON its wall's plane, which is the only thing the
        # solver asks of it.
        walls = {w.wall_id: w for w in g.walls}
        for op in g.openings:
            w = walls[op.wall_id]
            assert abs(w.signed_distance(op.center[0], op.center[2])) < 1e-6

    def test_names_override_labels_so_a_tool_and_a_sentence_agree(self):
        doc = _assets("scene-spike-a7e073ae")
        g = derive_room_geometry(
            doc["manifest"], doc["shell"], names={"obj_003": "the big bed"}
        )
        assert g.by_key(spec_key({"object_id": "obj_003", "roomplan_box": {
            "identifier": "D22E8F5D-6875-4563-BB86-CD413AB97D6E"}})).name == "the big bed"

    def test_no_shell_yields_no_floor_and_no_walls(self):
        doc = _assets("scene-spike-a7e073ae")
        g = derive_room_geometry(doc["manifest"], None)
        assert g.walls == () and g.floor_polygon == () and g.floor_y is None
        assert len(g.objects) == len(doc["manifest"]["objects"])

    def test_unavailable_shell_is_not_read(self):
        doc = _assets("scene-spike-a7e073ae")
        g = derive_room_geometry(
            doc["manifest"], {"status": "unavailable", "walls": [{"polygon": []}]}
        )
        assert g.walls == ()

    def test_malformed_input_degrades_rather_than_raising(self):
        g = derive_room_geometry({}, {"status": "ready", "walls": ["nope", {}, 3]})
        assert g.objects == () and g.walls == ()
        g = derive_room_geometry(
            {"objects": [{"object_id": "o", "roomplan_box": {"dims": "bad"}}]}, None
        )
        assert g.objects[0].box is None
        g = derive_room_geometry({"objects": [{
            "object_id": "o", "placed": True,
            "world_transform": {"position": [float("nan"), 0, 0]},
        }]}, None)
        assert g.objects[0].position is None

    def test_degenerate_walls_are_skipped_never_guessed(self):
        floorish = {"status": "ready", "walls": [{
            "wall_id": "w", "polygon": [[0, 0, 0], [1, 0, 0], [1, 0, 1]],
        }]}
        assert derive_room_geometry({}, floorish).walls == ()
