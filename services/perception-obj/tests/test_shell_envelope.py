"""Envelope-only degrade shell invariants (decision 0077 tier ladder;
shell_envelope.py).

Two layers:

  * Synthetic ground truth: a hand-built 4 x 3 room whose four tall walls
    must — and whose furniture planes must NEVER — become the envelope,
    including the measured amendment to the brief's selection rule (an
    ARKit-"wall"-classified furniture face and an opening-carrying door
    leaf are both rejected because they don't reach the common top).
  * Real-data regression pins at ACHIEVED accuracy: both preserved LiDAR
    captures re-derive to the adjudication's validated envelopes
    (docs/briefs/lidar-first-rooms-adjudication.md §2a/§4 — 247003de
    operator-confirmed 4.20 x 3.29 m against the real room). Skipped
    cleanly when the preserved bundles aren't present.

Run from repo root:
    python -m pytest services/perception-obj/tests/test_shell_envelope.py -v
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import room_planes
from room_planes import Opening, ShellPlaneGeom
from roomstudio_schemas import CaptureBundle
from shell_envelope import (
    derive_envelope,
    envelope_floor_geom,
    envelope_wall_geom,
    select_envelope_candidates,
)
from shell_geometry import ShellGeometry, assemble_shell

_UP = np.array([0.0, 1.0, 0.0])

_CAPTURES = {
    "247003de": Path("/Users/aubrey/projects/roomstudio/outputs/real-capture-247003de/bundle.pb"),
    "13bae607": Path("/Users/aubrey/projects/roomstudio/outputs/real-capture-13bae607/bundle.pb"),
}

_needs_real_bundles = pytest.mark.skipif(
    not all(p.exists() for p in _CAPTURES.values()),
    reason="preserved LiDAR bundles only in the main checkout's outputs/",
)


# ---------------------------------------------------------------------------
# Synthetic room builders
# ---------------------------------------------------------------------------

def _wall(
    wall_id: str,
    center_xz: tuple[float, float],
    normal_xz: tuple[float, float],
    width: float,
    y_min: float,
    y_max: float,
    classification: str | None = "wall",
    openings: list[Opening] | None = None,
) -> ShellPlaneGeom:
    n = np.array([normal_xz[0], 0.0, normal_xz[1]], dtype=np.float64)
    n /= np.linalg.norm(n)
    lateral = np.cross(_UP, n)
    lateral /= np.linalg.norm(lateral)
    center = np.array([center_xz[0], 0.0, center_xz[1]])
    p_lo = center - (width / 2.0) * lateral
    p_hi = center + (width / 2.0) * lateral
    corners = np.stack([
        [p_lo[0], y_min, p_lo[2]],
        [p_hi[0], y_min, p_hi[2]],
        [p_hi[0], y_max, p_hi[2]],
        [p_lo[0], y_max, p_lo[2]],
    ])
    return ShellPlaneGeom(
        kind="wall",
        corners_world=corners,
        normal=n,
        origin=corners[0],
        axis_u=lateral,
        axis_v=_UP.copy(),
        width_m=width,
        height_m=y_max - y_min,
        classification=classification,
        member_indices=[],
        wall_id=wall_id,
        openings=list(openings or []),
        area_m2=width * (y_max - y_min),
    )


def _floor_geom(y: float = -1.4) -> ShellPlaneGeom:
    origin = np.array([0.0, y, 3.0])
    return ShellPlaneGeom(
        kind="floor",
        corners_world=np.stack([
            origin,
            origin + np.array([4.0, 0.0, 0.0]),
            origin + np.array([4.0, 0.0, -3.0]),
            origin + np.array([0.0, 0.0, -3.0]),
        ]),
        normal=_UP.copy(),
        origin=origin,
        axis_u=np.array([1.0, 0.0, 0.0]),
        axis_v=np.array([0.0, 0.0, -1.0]),
        width_m=4.0,
        height_m=3.0,
        classification="floor",
        member_indices=[0],
        area_m2=12.0,
    )


def _room_geometry(*, extra_walls=(), with_floor=True) -> ShellGeometry:
    """A 4 x 3 room (x in [0, 4], z in [0, 3]): four tall walls (top 2.4)
    whose normals face the interior, floor at y=-1.4."""
    walls = [
        _wall("wall_00", (2.0, 0.0), (0.0, 1.0), 4.4, -1.4, 2.4),
        _wall("wall_01", (2.0, 3.0), (0.0, -1.0), 4.4, -1.4, 2.4),
        _wall("wall_02", (0.0, 1.5), (1.0, 0.0), 3.4, -1.4, 2.4),
        _wall("wall_03", (4.0, 1.5), (-1.0, 0.0), 3.4, -1.4, 2.4),
        *extra_walls,
    ]
    floor = _floor_geom() if with_floor else None
    member_polys = [floor.corners_world.copy()] if floor is not None else []
    return ShellGeometry(
        floor=floor,
        walls=walls,
        floor_member_polygons=member_polys,
        quality={"planes_in_bundle": len(walls) + (1 if floor is not None else 0),
                 "wall_count": len(walls)},
    )


_FURNITURE = [
    # A bed rail: seat-classified, low — excluded on both grounds.
    _wall("wall_04", (2.0, 1.2), (0.0, -1.0), 2.0, -1.4, -0.9, "seat"),
    # An ARKit-misclassified wardrobe face: "wall" but stops 1 m short of
    # the common top — the measured amendment (classification alone must
    # NOT admit it; the brief's literal OR-rule would).
    _wall("wall_05", (1.0, 0.6), (0.0, 1.0), 0.9, -1.4, 1.4, "wall"),
    # An open door leaf carrying a door member: openings alone must not
    # admit it either.
    _wall("wall_06", (3.4, 0.8), (1.0, 0.0), 0.8, -1.2, 0.9, None,
          [Opening("door", 0.0, 0.0, 0.8, 1.9)]),
]


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------

class TestSelection:
    def test_reach_rule_selects_tall_walls_only(self):
        geometry = _room_geometry(extra_walls=_FURNITURE)
        candidates, common_top = select_envelope_candidates(geometry.walls)
        assert common_top == pytest.approx(2.4)
        assert {w.wall_id for w in candidates} == {
            "wall_00", "wall_01", "wall_02", "wall_03"
        }

    def test_seat_excluded_even_if_tall(self):
        tall_seat = _wall("wall_09", (2.0, 1.0), (0.0, 1.0), 2.0, -1.4, 2.4, "seat")
        geometry = _room_geometry(extra_walls=[tall_seat])
        candidates, _ = select_envelope_candidates(geometry.walls)
        assert "wall_09" not in {w.wall_id for w in candidates}

    def test_empty_walls(self):
        assert select_envelope_candidates([]) == ([], None)


# ---------------------------------------------------------------------------
# Derivation — synthetic ground truth
# ---------------------------------------------------------------------------

class TestDerivation:
    def test_closed_envelope_matches_room(self):
        env = derive_envelope(_room_geometry(extra_walls=_FURNITURE))
        assert env is not None and env.closed
        assert len(env.walls) == 4
        assert {w.source.wall_id for w in env.walls} == {
            "wall_00", "wall_01", "wall_02", "wall_03"
        }
        # Furniture is internal evidence, never rendered.
        assert set(env.interior_wall_ids) == {"wall_04", "wall_05", "wall_06"}
        sides = sorted(env.quality["envelope_side_lengths_m"])
        assert sides == pytest.approx([3.0, 3.0, 4.0, 4.0], abs=1e-3)
        assert env.quality["envelope_area_m2"] == pytest.approx(12.0, abs=0.01)
        assert env.floor_y == pytest.approx(-1.4)
        assert env.top_y == pytest.approx(2.4)

    def test_floor_corners_ccw_at_floor_height(self):
        env = derive_envelope(_room_geometry())
        pts = env.floor_corners
        assert pts.shape == (4, 3)
        assert np.allclose(pts[:, 1], -1.4, atol=1e-9)
        x, z = pts[:, 0], pts[:, 2]
        shoelace = 0.5 * float(np.dot(x, np.roll(z, -1)) - np.dot(np.roll(x, -1), z))
        assert shoelace > 0  # the pinned CCW-in-XZ winding

    def test_walls_front_interior_and_span_floor_to_top(self):
        env = derive_envelope(_room_geometry())
        center = env.floor_corners.mean(axis=0)
        for ew in env.walls:
            c = ew.corners_world
            front = np.cross(c[1] - c[0], c[3] - c[0])
            assert float(np.dot(front, ew.normal)) > 0  # winding contract
            anchor = c.mean(axis=0)
            assert float(np.dot(ew.normal, center - anchor)) > 0  # interior
            assert float(c[:, 1].min()) == pytest.approx(-1.4, abs=1e-9)
            assert float(c[:, 1].max()) == pytest.approx(2.4, abs=1e-9)

    def test_openings_map_into_rendered_frame(self):
        door = Opening("door", 1.0, 0.0, 1.9, 2.0)
        walls_with_door = _room_geometry().walls
        walls_with_door[0].openings = [door]
        geometry = _room_geometry()
        geometry.walls[0].openings = [door]
        env = derive_envelope(geometry)
        ew = next(w for w in env.walls if w.source.wall_id == "wall_00")
        assert len(ew.openings) == 1
        op = ew.openings[0]
        assert 0.0 <= op.u0 < op.u1 <= ew.width_m
        assert 0.0 <= op.v0 < op.v1 <= ew.height_m
        assert op.u1 - op.u0 == pytest.approx(0.9, abs=1e-6)
        assert op.v1 - op.v0 == pytest.approx(2.0, abs=1e-6)

    def test_not_closed_ships_detected_extents_only(self):
        """One family only (two parallel walls): nothing may be extended —
        rendered corners == measured corners, no floor rectangle."""
        geometry = _room_geometry()
        geometry.walls = [w for w in geometry.walls if w.wall_id in ("wall_00", "wall_01")]
        env = derive_envelope(geometry)
        assert env is not None and not env.closed
        assert env.floor_corners is None
        assert len(env.walls) == 2
        for ew in env.walls:
            assert np.allclose(ew.corners_world, ew.source.corners_world)
        assert env.quality["envelope_closed"] is False

    def test_no_candidates_no_floor_is_none(self):
        geometry = _room_geometry(with_floor=False)
        geometry.walls = []
        assert derive_envelope(geometry) is None

    def test_deterministic(self):
        g1 = derive_envelope(_room_geometry(extra_walls=_FURNITURE))
        g2 = derive_envelope(_room_geometry(extra_walls=_FURNITURE))
        assert np.allclose(g1.floor_corners, g2.floor_corners)
        for a, b in zip(g1.walls, g2.walls, strict=True):
            assert np.allclose(a.corners_world, b.corners_world)

    def test_observation_geoms(self):
        env = derive_envelope(_room_geometry())
        fg = envelope_floor_geom(env, _room_geometry())
        assert fg.kind == "floor"
        assert float(np.dot(np.cross(fg.axis_u, fg.axis_v), _UP)) > 0
        wg = envelope_wall_geom(env.walls[0])
        assert wg.kind == "wall"
        assert np.allclose(wg.corners_world, env.walls[0].corners_world)


# ---------------------------------------------------------------------------
# Real-data regression pins (achieved accuracy; adjudication §2a/§4)
# ---------------------------------------------------------------------------

def _derive_real(scene: str):
    b = CaptureBundle()
    b.ParseFromString(_CAPTURES[scene].read_bytes())
    geometry = assemble_shell(b.plane_anchors)
    return geometry, derive_envelope(geometry)


@_needs_real_bundles
class TestRealCaptures:
    def test_247003de_envelope(self):
        """The adjudication's validated derivation, operator-confirmed
        4.20 x 3.29 m against the real room; achieved offline values pinned
        (sides to 1 cm, area 13.81 m^2)."""
        _geometry, env = _derive_real("247003de")
        assert env is not None and env.closed
        assert len(env.walls) == 4
        sides = sorted(env.quality["envelope_side_lengths_m"])
        assert sides == pytest.approx([3.293, 3.319, 4.142, 4.212], abs=0.01)
        # Opposite sides agree to <= 7 cm (the adjudication's 3-6 cm class).
        assert abs(sides[1] - sides[0]) <= 0.07
        assert abs(sides[3] - sides[2]) <= 0.07
        assert env.quality["envelope_area_m2"] == pytest.approx(13.81, abs=0.05)
        # The four selected sources are the four big reach-walls (areas
        # 13.3 / 8.3 / 13.3 / 14.2 under code-default merge knobs) — no
        # furniture plane sneaks in.
        areas = sorted(round(w.source.area_m2, 1) for w in env.walls)
        assert areas == pytest.approx([8.3, 13.3, 13.3, 14.2], abs=0.15)

    def test_247003de_bed_rail_is_interior_evidence(self):
        """The seat-classified bed rail (the 0075 furniture-slab exhibit:
        2.00 x 0.53 m rendered as a 3.06 m wall by closure) must be interior
        evidence, never geometry."""
        geometry, env = _derive_real("247003de")
        seat_ids = {w.wall_id for w in geometry.walls if w.classification == "seat"}
        assert seat_ids  # the rail exists in the measured set
        assert seat_ids <= set(env.interior_wall_ids)
        rendered_sources = {w.source.wall_id for w in env.walls}
        assert not (seat_ids & rendered_sources)

    def test_13bae607_envelope(self):
        _geometry, env = _derive_real("13bae607")
        assert env is not None and env.closed
        assert len(env.walls) == 4
        sides = sorted(env.quality["envelope_side_lengths_m"])
        assert sides == pytest.approx([3.149, 3.200, 4.220, 4.287], abs=0.01)
        assert env.quality["envelope_area_m2"] == pytest.approx(13.50, abs=0.05)

    def test_247003de_under_serving_merge_knobs(self, monkeypatch):
        """The selection is downstream of the wall merge: under the SERVING
        knobs (SHELL_WALL_MERGE_GAP_M=1.0, NORMAL_TOL=15 — the e33d98a
        calibration) the derivation picks the adjudication's exact wall ids
        (02/05/09/12) and lands the same rectangle."""
        monkeypatch.setattr(room_planes, "SHELL_WALL_MERGE_GAP_M", 1.0)
        monkeypatch.setattr(room_planes, "SHELL_WALL_NORMAL_TOL_DEG", 15.0)
        _geometry, env = _derive_real("247003de")
        assert env is not None and env.closed
        assert sorted(w.source.wall_id for w in env.walls) == [
            "wall_02", "wall_05", "wall_09", "wall_12"
        ]
        assert env.quality["envelope_area_m2"] == pytest.approx(13.80, abs=0.05)
