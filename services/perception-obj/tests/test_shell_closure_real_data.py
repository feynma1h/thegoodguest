"""V1 closure pins on the first plane-carrying real capture (decision 0069
brief, chunk 1 verification): scene f3d70236, bundle 9fbe29b6 — 24 recorded
ARKit anchors committed at fixtures/scene_f3d70236/bundle.pb (24 KB of
geometry metadata, no pixels).

Runs under the production merge calibration, which is now simply the code
default — so this file no longer sets it, and the wall set pinned here is the
one the deployed closure sees.

What these pins mean (the V1 probe's assertions, made permanent):
  - the two floating unclassified fragments (members 16 and 12 — the
    curtain-plane patch 1.26 m above the floor and the 0.45x1.10 patch at
    +0.21 m) DROP: no classification, no floor contact, no seam with a
    structural wall inside the join gate;
  - the fragment at the floor (member 6 — the far-side wall patch behind
    the curtain) and the fragment cornering the classified wall (member 4)
    SURVIVE, with the recorded justification;
  - every surviving wall's rendered bottom reaches the floor plane;
  - the room's main corner (door-pair wall x main wall) closes;
  - the door pair survives as TWO door openings on its merged wall;
  - structural walls rise to the main wall's detected top (common top);
  - the floor polygon stays inside every surviving wall line.

A knob change that shifts this outcome should be a DELIBERATE
recalibration — update the pins with the reasoning, never silently.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from roomstudio_schemas import CaptureBundle
from shell_geometry import assemble_shell, close_shell

_FIXTURE = Path(__file__).parent / "fixtures" / "scene_f3d70236" / "bundle.pb"

# The recorded member-index composition of the production wall set (probe
# output, 2026-07-23). Ids are the deterministic sort's; member sets are
# the ground truth the pins key on.
_MAIN_WALL_MEMBERS = [3, 14]
_DOOR_PAIR_MEMBERS = [8, 15]
_SIDE_WALL_MEMBERS = [17]
_FLOOR_FRAGMENT_MEMBERS = [6]  # unclassified, detected bottom AT the floor
_CORNER_FRAGMENT_MEMBERS = [4]  # unclassified, seams the classified side wall
_DROPPED_MEMBERS = ([16], [12])  # floating; no participation


@pytest.fixture(scope="module")
def closure():
    bundle = CaptureBundle()
    bundle.ParseFromString(_FIXTURE.read_bytes())
    assert len(bundle.plane_anchors) == 24
    geometry = assemble_shell(bundle.plane_anchors)
    closed = close_shell(geometry)
    return geometry, closed


def _by_members(walls, members: list[int]):
    for cw in walls:
        if sorted(cw.geom.member_indices) == sorted(members):
            return cw
    raise AssertionError(f"no surviving wall with members {members}")


class TestRealCaptureClosure:
    def test_production_wall_set_is_seven(self, closure):
        geometry, _ = closure
        assert len(geometry.walls) == 7
        assert geometry.quality["floor_member_count"] == 1

    def test_floating_fragments_drop(self, closure):
        geometry, closed = closure
        assert len(closed.walls) == 5
        dropped_members = sorted(
            sorted(w.member_indices)
            for w in geometry.walls
            if w.wall_id in closed.dropped_wall_ids
        )
        assert dropped_members == sorted(list(m) for m in _DROPPED_MEMBERS)
        assert closed.quality["fragments_dropped"] == 2

    def test_floor_fragment_survives_via_contact(self, closure):
        _, closed = closure
        cw = _by_members(closed.walls, _FLOOR_FRAGMENT_MEMBERS)
        assert cw.geom.classification is None

    def test_corner_fragment_survives_via_structural_seam(self, closure):
        _, closed = closure
        cw = _by_members(closed.walls, _CORNER_FRAGMENT_MEMBERS)
        assert cw.geom.classification is None
        # Its rendered lateral edge meets the side wall's seam.
        side = _by_members(closed.walls, _SIDE_WALL_MEMBERS)
        states = [e.state for e in cw.edges.values()]
        assert f"extended_to_wall:{side.geom.wall_id}" in states

    def test_every_survivor_reaches_the_floor(self, closure):
        geometry, closed = closure
        floor_y = float(geometry.floor.origin[1])
        for cw in closed.walls:
            assert cw.rendered_corners[:, 1].min() <= floor_y + 1e-6, (
                f"{cw.geom.wall_id} does not reach the floor"
            )

    def test_main_corner_closes(self, closure):
        _, closed = closure
        main = _by_members(closed.walls, _MAIN_WALL_MEMBERS)
        door = _by_members(closed.walls, _DOOR_PAIR_MEMBERS)
        # The seam lies inside the door wall's detected extent; the main
        # wall extends to it.
        assert (
            main.edges["left"].state == f"extended_to_wall:{door.geom.wall_id}"
            or main.edges["right"].state == f"extended_to_wall:{door.geom.wall_id}"
        )

    def test_door_pair_preserved_as_openings(self, closure):
        _, closed = closure
        door = _by_members(closed.walls, _DOOR_PAIR_MEMBERS)
        assert door.geom.classification is None  # both members are doors
        kinds = sorted(o.classification for o in door.geom.openings)
        assert kinds == ["door", "door"]

    def test_structural_walls_share_the_main_top(self, closure):
        geometry, closed = closure
        main = _by_members(closed.walls, _MAIN_WALL_MEMBERS)
        main_top = float(main.geom.corners_world[:, 1].max())
        for members in (_DOOR_PAIR_MEMBERS, _SIDE_WALL_MEMBERS):
            cw = _by_members(closed.walls, members)
            assert cw.rendered_corners[:, 1].max() == pytest.approx(
                main_top, abs=1e-6
            )
            assert cw.edges["top"].state == "extended_to_common_height"
        assert main.edges["top"].state == "observed"

    def test_measured_quads_untouched_by_closure(self, closure):
        geometry, closed = closure
        by_id = {w.wall_id: w for w in geometry.walls}
        for cw in closed.walls:
            np.testing.assert_array_equal(
                cw.geom.corners_world, by_id[cw.geom.wall_id].corners_world
            )

    def test_floor_polygon_inside_all_surviving_walls(self, closure):
        _, closed = closure
        poly = closed.floor_polygon_rendered
        assert poly is not None and len(poly) >= 3
        # The MEASURED polygon keeps all 17 detected boundary vertices.
        assert len(closed.floor_polygon_measured) == 17
        for cw in closed.walls:
            n, p0 = cw.geom.normal, cw.geom.origin
            d = (poly - p0) @ n
            assert float(d.min()) >= -0.03, (
                f"floor pokes {-float(d.min()):.3f} m past {cw.geom.wall_id}"
            )
        assert len(closed.floor_edge_states) == len(poly)
        assert closed.quality["floor_vertices_snapped"] > 0

    def test_provenance_populated_everywhere(self, closure):
        _, closed = closure
        valid_prefixes = (
            "observed", "extended_to_floor", "extended_to_common_height",
            "extended_to_wall:",
        )
        for cw in closed.walls:
            assert set(cw.edges) == {"bottom", "top", "left", "right"}
            for e in cw.edges.values():
                assert e.state.startswith(valid_prefixes)
                assert e.extension_m >= 0.0
        for s in closed.floor_edge_states:
            assert s.startswith(("observed", "extended_to_wall:", "bounded_by_wall:"))
