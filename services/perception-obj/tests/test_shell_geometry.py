"""Shell geometry invariants (decision 0066): floor selection, coplanar
wall merging, winding, and the no-invention degrade paths — all against
hand-built anchors with known ground truth.

Run: python -m pytest services/perception-obj/tests/test_shell_geometry.py
"""
from __future__ import annotations

import math

import numpy as np
import pytest
import shell_geometry
from roomstudio_schemas import PLANE_HORIZONTAL, PLANE_VERTICAL, CaptureBundle
from shell_geometry import assemble_shell

# ---------------------------------------------------------------------------
# Anchor builders
# ---------------------------------------------------------------------------

def _add_anchor(
    bundle: CaptureBundle,
    *,
    pos: tuple[float, float, float],
    quat_xyzw: tuple[float, float, float, float],
    extent: tuple[float, float],
    alignment: int,
    classification: str = "",
    center: tuple[float, float, float] = (0.0, 0.0, 0.0),
    boundary_xz: list[float] | None = None,
):
    a = bundle.plane_anchors.add()
    a.pose.pos_x, a.pose.pos_y, a.pose.pos_z = pos
    a.pose.quat_x, a.pose.quat_y, a.pose.quat_z, a.pose.quat_w = quat_xyzw
    a.center_x, a.center_y, a.center_z = center
    a.extent_width, a.extent_height = extent
    a.alignment = alignment
    a.classification = classification
    if boundary_xz:
        a.boundary_xz.extend(boundary_xz)
    return a


_R = 1.0 / math.sqrt(2.0)
_IDENTITY = (0.0, 0.0, 0.0, 1.0)
# +90 deg about X: anchor +Y (plane normal) -> world +Z.
_NORMAL_PLUS_Z = (_R, 0.0, 0.0, _R)
# -90 deg about Z: anchor +Y -> world +X.
_NORMAL_PLUS_X = (0.0, 0.0, -_R, _R)


def _room_bundle() -> CaptureBundle:
    """Canonical synthetic room: two coplanar floor pieces at y≈-1.4, a
    table at -0.7 (must NOT join the floor), one wall split into two
    overlapping vertical anchors (must merge), one perpendicular wall
    (must NOT merge), and a speck (must drop)."""
    b = CaptureBundle()
    # Floor piece 1: 4x3 m at y=-1.4.
    _add_anchor(
        b, pos=(0, -1.4, 0), quat_xyzw=_IDENTITY, extent=(4.0, 3.0),
        alignment=PLANE_HORIZONTAL, classification="floor",
    )
    # Floor piece 2: 2x2 m at y=-1.36, offset in x — same floor.
    _add_anchor(
        b, pos=(2.5, -1.36, 0), quat_xyzw=_IDENTITY, extent=(2.0, 2.0),
        alignment=PLANE_HORIZONTAL,
    )
    # Table: large horizontal at -0.7 — NOT the floor.
    _add_anchor(
        b, pos=(1.0, -0.7, 0.5), quat_xyzw=_IDENTITY, extent=(1.2, 0.9),
        alignment=PLANE_HORIZONTAL, classification="table",
    )
    # Wall A segment 1: normal +Z at z=-2, x span [-2, 0], y span [-1, 1].
    _add_anchor(
        b, pos=(-1.0, 0.0, -2.0), quat_xyzw=_NORMAL_PLUS_Z, extent=(2.0, 2.0),
        alignment=PLANE_VERTICAL, classification="wall",
    )
    # Wall A segment 2: same plane, x span [-0.4, 1.6], y span [-0.6, 1.0].
    _add_anchor(
        b, pos=(0.6, 0.2, -2.0), quat_xyzw=_NORMAL_PLUS_Z, extent=(2.0, 1.6),
        alignment=PLANE_VERTICAL,
    )
    # Wall B: perpendicular (normal +X) at x=-2.5.
    _add_anchor(
        b, pos=(-2.5, 0.0, -0.5), quat_xyzw=_NORMAL_PLUS_X, extent=(3.0, 2.2),
        alignment=PLANE_VERTICAL, classification="wall",
    )
    # Speck: vertical, area 0.04 m² — below SHELL_MIN_WALL_AREA_M2.
    _add_anchor(
        b, pos=(1.0, 0.0, -1.9), quat_xyzw=_NORMAL_PLUS_Z, extent=(0.2, 0.2),
        alignment=PLANE_VERTICAL,
    )
    return b


# ---------------------------------------------------------------------------
# Floor selection
# ---------------------------------------------------------------------------

class TestFloorSelection:
    def test_floor_is_lowest_cluster_not_the_table(self):
        shell = assemble_shell(_room_bundle().plane_anchors)
        assert shell.floor is not None
        assert shell.floor.member_indices == [0, 1]  # both pieces, no table

    def test_floor_height_is_area_weighted_mean(self):
        shell = assemble_shell(_room_bundle().plane_anchors)
        # areas 12 and 4 at y -1.4 / -1.36 -> (12*-1.4 + 4*-1.36)/16 = -1.39
        assert shell.floor.origin[1] == pytest.approx(-1.39, abs=1e-6)

    def test_floor_quad_spans_member_bbox(self):
        shell = assemble_shell(_room_bundle().plane_anchors)
        xs = shell.floor.corners_world[:, 0]
        zs = shell.floor.corners_world[:, 2]
        # Piece 1 x in [-2, 2]; piece 2 x in [1.5, 3.5] -> union [-2, 3.5].
        assert xs.min() == pytest.approx(-2.0, abs=1e-6)
        assert xs.max() == pytest.approx(3.5, abs=1e-6)
        # z: piece 1 [-1.5, 1.5]; piece 2 [-1, 1] -> union [-1.5, 1.5].
        assert zs.min() == pytest.approx(-1.5, abs=1e-6)
        assert zs.max() == pytest.approx(1.5, abs=1e-6)

    def test_floor_winding_fronts_up(self):
        shell = assemble_shell(_room_bundle().plane_anchors)
        c = shell.floor.corners_world
        front = np.cross(c[1] - c[0], c[3] - c[0])
        assert front[1] > 0, "floor front face must point up (+Y)"

    def test_floor_classification_carried(self):
        shell = assemble_shell(_room_bundle().plane_anchors)
        assert shell.floor.classification == "floor"

    def test_ceiling_never_selected(self):
        """A big horizontal plane ABOVE with a downward normal (ARKit
        ceiling: anchor +Y away from the room) must not become the floor
        when no real floor exists."""
        b = CaptureBundle()
        # 180 deg about X: anchor +Y -> world -Y.
        _add_anchor(
            b, pos=(0, 1.2, 0), quat_xyzw=(1.0, 0.0, 0.0, 0.0),
            extent=(4.0, 3.0), alignment=PLANE_HORIZONTAL,
            classification="ceiling",
        )
        shell = assemble_shell(b.plane_anchors)
        assert shell.floor is None

    def test_speck_cannot_hijack_lowest(self):
        """A tiny horizontal anchor below the real floor is filtered by
        area before the lowest-cluster rule runs."""
        b = _room_bundle()
        _add_anchor(
            b, pos=(0.5, -1.9, 0.5), quat_xyzw=_IDENTITY, extent=(0.3, 0.3),
            alignment=PLANE_HORIZONTAL,
        )
        shell = assemble_shell(b.plane_anchors)
        assert shell.floor.origin[1] == pytest.approx(-1.39, abs=1e-6)


# ---------------------------------------------------------------------------
# Wall merging
# ---------------------------------------------------------------------------

class TestWallMerging:
    def test_coplanar_overlapping_walls_merge(self):
        shell = assemble_shell(_room_bundle().plane_anchors)
        assert len(shell.walls) == 2  # A (merged) + B; speck dropped

    def test_merged_wall_extent_is_union_of_detected(self):
        shell = assemble_shell(_room_bundle().plane_anchors)
        wall_a = next(w for w in shell.walls if abs(w.normal[2]) > 0.9)
        assert wall_a.width_m == pytest.approx(3.6, abs=1e-6)  # [-2, 1.6]
        assert wall_a.height_m == pytest.approx(2.0, abs=1e-6)  # [-1, 1]
        ys = wall_a.corners_world[:, 1]
        assert ys.min() == pytest.approx(-1.0, abs=1e-6)
        assert ys.max() == pytest.approx(1.0, abs=1e-6)

    def test_height_is_detected_not_extrapolated(self):
        """The merged wall's bottom stays at the DETECTED -1.0, above the
        floor at -1.39 — no extrapolation down to the floor."""
        shell = assemble_shell(_room_bundle().plane_anchors)
        wall_a = next(w for w in shell.walls if abs(w.normal[2]) > 0.9)
        assert wall_a.corners_world[:, 1].min() > shell.floor.origin[1] + 0.3

    def test_perpendicular_walls_do_not_merge(self):
        shell = assemble_shell(_room_bundle().plane_anchors)
        normals = sorted(
            (round(float(w.normal[0])), round(float(w.normal[2])))
            for w in shell.walls
        )
        assert normals == [(0, 1), (1, 0)]

    def test_parallel_far_walls_do_not_merge(self):
        """Two walls with the same normal on OPPOSITE sides of the room
        (offsets 4 m apart) stay separate."""
        b = CaptureBundle()
        _add_anchor(
            b, pos=(0, 0, -2.0), quat_xyzw=_NORMAL_PLUS_Z, extent=(3.0, 2.0),
            alignment=PLANE_VERTICAL,
        )
        _add_anchor(
            b, pos=(0, 0, 2.0), quat_xyzw=_NORMAL_PLUS_Z, extent=(3.0, 2.0),
            alignment=PLANE_VERTICAL,
        )
        shell = assemble_shell(b.plane_anchors)
        assert len(shell.walls) == 2

    def test_wall_winding_fronts_interior(self):
        """cross(c1-c0, c3-c0) must equal the wall's detected normal (the
        interior side — ARKit vertical normals face the camera)."""
        shell = assemble_shell(_room_bundle().plane_anchors)
        for w in shell.walls:
            c = w.corners_world
            front = np.cross(c[1] - c[0], c[3] - c[0])
            front = front / np.linalg.norm(front)
            assert float(np.dot(front, w.normal)) > 0.99

    def test_wall_ids_deterministic(self):
        s1 = assemble_shell(_room_bundle().plane_anchors)
        s2 = assemble_shell(_room_bundle().plane_anchors)
        assert [w.wall_id for w in s1.walls] == [w.wall_id for w in s2.walls]
        assert [w.wall_id for w in s1.walls] == ["wall_00", "wall_01"]

    def test_bake_frame_matches_corners(self):
        """corners[1] == origin + width*axis_u and corners[3] == origin +
        height*axis_v — the contract shell_texture's grid relies on."""
        shell = assemble_shell(_room_bundle().plane_anchors)
        for geom in [shell.floor, *shell.walls]:
            np.testing.assert_allclose(
                geom.corners_world[1],
                geom.origin + geom.width_m * geom.axis_u,
                atol=1e-9,
            )
            np.testing.assert_allclose(
                geom.corners_world[3],
                geom.origin + geom.height_m * geom.axis_v,
                atol=1e-9,
            )


# ---------------------------------------------------------------------------
# Boundary polygons
# ---------------------------------------------------------------------------

class TestBoundaryPolygons:
    def test_boundary_polygon_used_for_floor_shape(self):
        """When the client ships boundary_xz, the floor member polygon is
        the boundary (in world frame), not the extent rectangle."""
        b = CaptureBundle()
        # Triangle boundary in anchor space.
        _add_anchor(
            b, pos=(0, -1.4, 0), quat_xyzw=_IDENTITY, extent=(4.0, 4.0),
            alignment=PLANE_HORIZONTAL, classification="floor",
            boundary_xz=[-2.0, -2.0, 2.0, -2.0, 0.0, 2.0],
        )
        shell = assemble_shell(b.plane_anchors)
        assert len(shell.floor_member_polygons) == 1
        poly = shell.floor_member_polygons[0]
        assert poly.shape == (3, 3)
        # World y flattened onto the merged floor height.
        np.testing.assert_allclose(poly[:, 1], -1.4, atol=1e-6)

    def test_extent_rectangle_when_no_boundary(self):
        shell = assemble_shell(_room_bundle().plane_anchors)
        assert all(p.shape == (4, 3) for p in shell.floor_member_polygons)


# ---------------------------------------------------------------------------
# Degrade paths (no invention)
# ---------------------------------------------------------------------------

class TestDegrade:
    def test_no_anchors_yields_empty_shell(self):
        b = CaptureBundle()
        shell = assemble_shell(b.plane_anchors)
        assert shell.floor is None
        assert shell.walls == []
        assert shell.quality["planes_in_bundle"] == 0

    def test_only_specks_yields_empty_shell(self):
        b = CaptureBundle()
        _add_anchor(
            b, pos=(0, -1.4, 0), quat_xyzw=_IDENTITY, extent=(0.3, 0.3),
            alignment=PLANE_HORIZONTAL,
        )
        _add_anchor(
            b, pos=(0, 0, -2), quat_xyzw=_NORMAL_PLUS_Z, extent=(0.2, 0.2),
            alignment=PLANE_VERTICAL,
        )
        shell = assemble_shell(b.plane_anchors)
        assert shell.floor is None
        assert shell.walls == []

    def test_walls_without_floor_ship_as_detected(self):
        """An open shell (walls, no floor) is the honest presentation —
        not gated on completeness."""
        b = CaptureBundle()
        _add_anchor(
            b, pos=(0, 0, -2), quat_xyzw=_NORMAL_PLUS_Z, extent=(3.0, 2.0),
            alignment=PLANE_VERTICAL,
        )
        shell = assemble_shell(b.plane_anchors)
        assert shell.floor is None
        assert len(shell.walls) == 1

    def test_quality_counts(self):
        shell = assemble_shell(_room_bundle().plane_anchors)
        assert shell.quality == {
            "planes_in_bundle": 7,
            "horizontal_anchors": 3,
            "vertical_anchors": 4,
            "floor_member_count": 2,
            "wall_count": 2,
        }


# ---------------------------------------------------------------------------
# Anchor parsing details
# ---------------------------------------------------------------------------

class TestAnchorParsing:
    def test_center_offset_shifts_plane(self):
        """ARPlaneAnchor.center is anchor-space and NOT the anchor origin;
        the world plane must honor it."""
        b = CaptureBundle()
        _add_anchor(
            b, pos=(0, -1.4, 0), quat_xyzw=_IDENTITY, extent=(2.0, 2.0),
            alignment=PLANE_HORIZONTAL, center=(3.0, 0.0, 1.0),
        )
        shell = assemble_shell(b.plane_anchors)
        xs = shell.floor.corners_world[:, 0]
        assert xs.min() == pytest.approx(2.0, abs=1e-6)
        assert xs.max() == pytest.approx(4.0, abs=1e-6)

    def test_rotation_on_y_rotates_extent(self):
        """A 90-degree extent rotation swaps which world axis the width
        runs along."""
        b = CaptureBundle()
        _add_anchor(
            b, pos=(0, -1.4, 0), quat_xyzw=_IDENTITY, extent=(4.0, 2.0),
            alignment=PLANE_HORIZONTAL,
        )
        shell_plain = assemble_shell(b.plane_anchors)

        b2 = CaptureBundle()
        a = _add_anchor(
            b2, pos=(0, -1.4, 0), quat_xyzw=_IDENTITY, extent=(4.0, 2.0),
            alignment=PLANE_HORIZONTAL,
        )
        a.rotation_on_y_rad = math.pi / 2
        shell_rot = assemble_shell(b2.plane_anchors)

        assert shell_plain.floor.width_m == pytest.approx(4.0, abs=1e-6)
        assert shell_plain.floor.height_m == pytest.approx(2.0, abs=1e-6)
        # Rotated 90°: the 4 m span now runs along Z.
        assert shell_rot.floor.width_m == pytest.approx(2.0, abs=1e-6)
        assert shell_rot.floor.height_m == pytest.approx(4.0, abs=1e-6)

    def test_env_knobs_read_once_documented(self):
        """The tunables exist and carry sane defaults (a rename here breaks
        deploy env files silently — pin the names)."""
        assert shell_geometry.SHELL_FLOOR_MIN_AREA_M2 > 0
        assert shell_geometry.SHELL_WALL_NORMAL_TOL_DEG > 0
        assert shell_geometry.SHELL_WALL_COPLANAR_TOL_M > 0
        assert shell_geometry.SHELL_WALL_MERGE_GAP_M > 0
        assert shell_geometry.SHELL_MIN_WALL_AREA_M2 > 0
