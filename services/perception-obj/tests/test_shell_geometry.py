"""Shell geometry invariants (decision 0066): floor selection, coplanar
wall merging, winding, and the no-invention degrade paths — all against
hand-built anchors with known ground truth.

Run: python -m pytest services/perception-obj/tests/test_shell_geometry.py
"""
from __future__ import annotations

import math

import numpy as np
import pytest
import room_planes
import shell_geometry
from thegoodguest_schemas import PLANE_HORIZONTAL, PLANE_VERTICAL, CaptureBundle
from shell_geometry import assemble_shell, close_shell

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
# Envelope closure (decision 0069): joints, never loops
# ---------------------------------------------------------------------------

def _closure_bundle() -> CaptureBundle:
    """Floor at y=-1.4; wall A (+Z at z=-2, x in [-2, 0], y in [-1, 1]);
    wall B (+X at x=-2.5, z in [-1.8, 0.2], y in [-1.4, 1.4]). Their seam
    is the vertical line at (-2.5, -2): 0.5 beyond A's left edge and 0.2
    beyond B's right edge — both inside the default join gate."""
    b = CaptureBundle()
    _add_anchor(
        b, pos=(0, -1.4, 0), quat_xyzw=_IDENTITY, extent=(6.0, 5.0),
        alignment=PLANE_HORIZONTAL, classification="floor",
    )
    _add_anchor(
        b, pos=(-1.0, 0.0, -2.0), quat_xyzw=_NORMAL_PLUS_Z, extent=(2.0, 2.0),
        alignment=PLANE_VERTICAL, classification="wall",
    )
    _add_anchor(
        b, pos=(-2.5, 0.0, -0.8), quat_xyzw=_NORMAL_PLUS_X, extent=(2.8, 2.0),
        alignment=PLANE_VERTICAL, classification="wall",
    )
    return b


class TestClosure:
    def _closed(self):
        geo = assemble_shell(_closure_bundle().plane_anchors)
        return geo, close_shell(geo)

    def _wall(self, closure, normal_axis: int):
        return next(
            cw for cw in closure.walls if abs(cw.geom.normal[normal_axis]) > 0.9
        )

    def test_wall_bottom_extends_to_floor(self):
        geo, closure = self._closed()
        wall_a = self._wall(closure, 2)  # +Z normal; detected bottom -1.0
        assert wall_a.rendered_corners[:, 1].min() == pytest.approx(-1.4, abs=1e-6)
        assert wall_a.edges["bottom"].state == "extended_to_floor"
        assert wall_a.edges["bottom"].extension_m == pytest.approx(0.4, abs=1e-6)

    def test_wall_already_at_floor_stays_observed(self):
        geo, closure = self._closed()
        wall_b = self._wall(closure, 0)  # bottom -1.4 == floor
        assert wall_b.edges["bottom"].state == "observed"
        assert wall_b.rendered_corners[:, 1].min() == pytest.approx(-1.4, abs=1e-6)

    def test_bottom_above_drop_gate_stays_unextended(self, monkeypatch):
        monkeypatch.setattr(shell_geometry, "SHELL_FLOOR_DROP_MAX_M", 0.3)
        geo = assemble_shell(_closure_bundle().plane_anchors)
        closure = close_shell(geo)
        wall_a = self._wall(closure, 2)  # drop 0.4 > 0.3 gate
        assert wall_a.edges["bottom"].state == "observed"
        assert wall_a.rendered_corners[:, 1].min() == pytest.approx(-1.0, abs=1e-6)

    def test_seam_extension_meets_exactly_never_past(self):
        geo, closure = self._closed()
        wall_a = self._wall(closure, 2)
        wall_b = self._wall(closure, 0)
        # A's left edge extends 0.5 to the seam at x=-2.5, exactly.
        assert wall_a.rendered_corners[:, 0].min() == pytest.approx(-2.5, abs=1e-6)
        assert wall_a.edges["left"].state == f"extended_to_wall:{wall_b.geom.wall_id}"
        assert wall_a.edges["left"].extension_m == pytest.approx(0.5, abs=1e-6)
        # B's edge extends 0.2 to the seam at z=-2, exactly.
        assert wall_b.rendered_corners[:, 2].min() == pytest.approx(-2.0, abs=1e-6)
        assert wall_b.edges["right"].state == f"extended_to_wall:{wall_a.geom.wall_id}"
        assert wall_b.edges["right"].extension_m == pytest.approx(0.2, abs=1e-6)

    def test_open_sides_stay_open(self):
        geo, closure = self._closed()
        wall_a = self._wall(closure, 2)
        # No wall beyond A's right edge (x=0): stays detected.
        assert wall_a.edges["right"].state == "observed"
        assert wall_a.rendered_corners[:, 0].max() == pytest.approx(0.0, abs=1e-6)

    def test_seam_beyond_gate_not_made(self, monkeypatch):
        monkeypatch.setattr(shell_geometry, "SHELL_JOIN_MAX_GAP_M", 0.1)
        geo = assemble_shell(_closure_bundle().plane_anchors)
        closure = close_shell(geo)
        for cw in closure.walls:
            assert cw.edges["left"].state == "observed"
            assert cw.edges["right"].state == "observed"

    def test_common_top_raises_shorter_structural_wall(self):
        geo, closure = self._closed()
        wall_a = self._wall(closure, 2)  # detected top 1.0
        wall_b = self._wall(closure, 0)  # detected top 1.4 (the max)
        assert wall_a.rendered_corners[:, 1].max() == pytest.approx(1.4, abs=1e-6)
        assert wall_a.edges["top"].state == "extended_to_common_height"
        assert wall_a.edges["top"].extension_m == pytest.approx(0.4, abs=1e-6)
        assert wall_b.edges["top"].state == "observed"

    def test_common_top_disabled(self, monkeypatch):
        monkeypatch.setattr(shell_geometry, "SHELL_COMMON_TOP_ENABLED", False)
        geo = assemble_shell(_closure_bundle().plane_anchors)
        closure = close_shell(geo)
        wall_a = self._wall(closure, 2)
        assert wall_a.rendered_corners[:, 1].max() == pytest.approx(1.0, abs=1e-6)
        assert wall_a.edges["top"].state == "observed"

    def test_measured_geometry_never_mutated(self):
        geo = assemble_shell(_closure_bundle().plane_anchors)
        before = [w.corners_world.copy() for w in geo.walls]
        floor_before = geo.floor.corners_world.copy()
        polys_before = [p.copy() for p in geo.floor_member_polygons]
        close_shell(geo)
        for w, b in zip(geo.walls, before, strict=True):
            np.testing.assert_array_equal(w.corners_world, b)
        np.testing.assert_array_equal(geo.floor.corners_world, floor_before)
        for p, b in zip(geo.floor_member_polygons, polys_before, strict=True):
            np.testing.assert_array_equal(p, b)

    def test_closure_never_adds_planes(self):
        geo, closure = self._closed()
        assert len(closure.walls) <= len(geo.walls)
        geo_empty = assemble_shell(CaptureBundle().plane_anchors)
        closure_empty = close_shell(geo_empty)
        assert closure_empty.walls == []
        assert closure_empty.floor_polygon_rendered is None

    def test_walls_only_no_floor(self):
        b = CaptureBundle()
        _add_anchor(
            b, pos=(0, 0, -2), quat_xyzw=_NORMAL_PLUS_Z, extent=(3.0, 2.0),
            alignment=PLANE_VERTICAL, classification="wall",
        )
        closure = close_shell(assemble_shell(b.plane_anchors))
        assert len(closure.walls) == 1
        assert closure.walls[0].edges["bottom"].state == "observed"
        assert closure.floor_polygon_rendered is None
        assert closure.floor_edge_states == []


class TestFragmentFilter:
    def _base(self) -> CaptureBundle:
        b = CaptureBundle()
        _add_anchor(
            b, pos=(0, -1.4, 0), quat_xyzw=_IDENTITY, extent=(6.0, 5.0),
            alignment=PLANE_HORIZONTAL, classification="floor",
        )
        # Structural wall (classified): +Z at z=-2.
        _add_anchor(
            b, pos=(0.0, 0.0, -2.0), quat_xyzw=_NORMAL_PLUS_Z, extent=(3.0, 2.0),
            alignment=PLANE_VERTICAL, classification="wall",
        )
        return b

    def test_floating_unclassified_fragment_drops(self):
        b = self._base()
        # Small, unclassified, 1 m above the floor, far from any seam.
        _add_anchor(
            b, pos=(2.0, -0.2, 1.5), quat_xyzw=_NORMAL_PLUS_X, extent=(0.8, 0.7),
            alignment=PLANE_VERTICAL,
        )
        geo = assemble_shell(b.plane_anchors)
        closure = close_shell(geo)
        assert len(geo.walls) == 2
        assert len(closure.walls) == 1
        assert len(closure.dropped_wall_ids) == 1
        assert closure.quality["fragments_dropped"] == 1

    def test_fragment_survives_via_floor_contact(self):
        b = self._base()
        # Small unclassified panel whose detected bottom touches the floor.
        _add_anchor(
            b, pos=(2.0, -1.05, 1.5), quat_xyzw=_NORMAL_PLUS_X, extent=(0.7, 0.8),
            alignment=PLANE_VERTICAL,
        )
        closure = close_shell(assemble_shell(b.plane_anchors))
        assert len(closure.walls) == 2
        assert closure.dropped_wall_ids == []

    def test_fragment_survives_via_seam_with_structural(self):
        b = self._base()
        # Floating fragment whose plane meets the structural wall within
        # the join gate: +X at x=-1.6, z in [-1.9, -1.2] (seam at z=-2 is
        # 0.3 past its edge), 1 m above the floor.
        _add_anchor(
            b, pos=(-1.6, -0.1, -1.55), quat_xyzw=_NORMAL_PLUS_X, extent=(0.8, 0.7),
            alignment=PLANE_VERTICAL,
        )
        closure = close_shell(assemble_shell(b.plane_anchors))
        assert len(closure.walls) == 2
        assert closure.dropped_wall_ids == []

    def test_fragments_cannot_justify_each_other(self):
        b = CaptureBundle()
        _add_anchor(
            b, pos=(0, -1.4, 0), quat_xyzw=_IDENTITY, extent=(6.0, 5.0),
            alignment=PLANE_HORIZONTAL, classification="floor",
        )
        # Two floating unclassified fragments whose planes seam EACH OTHER
        # within the gate — mutual justification must not save them.
        _add_anchor(
            b, pos=(-0.4, -0.2, -2.0), quat_xyzw=_NORMAL_PLUS_Z, extent=(0.8, 0.7),
            alignment=PLANE_VERTICAL,
        )
        _add_anchor(
            b, pos=(-1.0, -0.2, -1.6), quat_xyzw=_NORMAL_PLUS_X, extent=(0.8, 0.7),
            alignment=PLANE_VERTICAL,
        )
        closure = close_shell(assemble_shell(b.plane_anchors))
        assert closure.walls == []
        assert len(closure.dropped_wall_ids) == 2

    def test_large_unclassified_plane_is_structural(self):
        b = self._base()
        # 1.2 m² unclassified, floating, no seams — area makes it structural.
        _add_anchor(
            b, pos=(2.0, -0.2, 1.5), quat_xyzw=_NORMAL_PLUS_X, extent=(1.2, 1.0),
            alignment=PLANE_VERTICAL,
        )
        closure = close_shell(assemble_shell(b.plane_anchors))
        assert len(closure.walls) == 2
        assert closure.dropped_wall_ids == []


class TestOpenings:
    def test_door_member_becomes_opening_rect(self):
        b = CaptureBundle()
        _add_anchor(
            b, pos=(-1.0, 0.0, -2.0), quat_xyzw=_NORMAL_PLUS_Z, extent=(2.0, 2.0),
            alignment=PLANE_VERTICAL, classification="wall",
        )
        # Door member on the same plane: x in [-1.0, -0.2], y in [-1.0, 0.2].
        _add_anchor(
            b, pos=(-0.6, -0.4, -2.0), quat_xyzw=_NORMAL_PLUS_Z, extent=(0.8, 1.2),
            alignment=PLANE_VERTICAL, classification="door",
        )
        geo = assemble_shell(b.plane_anchors)
        assert len(geo.walls) == 1
        wall = geo.walls[0]
        # Classification is the majority of NON-opening members.
        assert wall.classification == "wall"
        assert len(wall.openings) == 1
        op = wall.openings[0]
        assert op.classification == "door"
        # Measured frame: origin at (x=-2, y=-1); u along +X, v along +Y.
        assert op.u0 == pytest.approx(1.0, abs=1e-6)
        assert op.u1 == pytest.approx(1.8, abs=1e-6)
        assert op.v0 == pytest.approx(0.0, abs=1e-6)
        assert op.v1 == pytest.approx(1.2, abs=1e-6)

    def test_all_door_members_wall_is_unclassified_with_openings(self):
        b = CaptureBundle()
        _add_anchor(
            b, pos=(-1.0, 0.0, -2.0), quat_xyzw=_NORMAL_PLUS_Z, extent=(1.0, 2.0),
            alignment=PLANE_VERTICAL, classification="door",
        )
        geo = assemble_shell(b.plane_anchors)
        wall = geo.walls[0]
        assert wall.classification is None
        assert len(wall.openings) == 1
        # Openings make it structural: the filter must not drop it.
        closure = close_shell(geo)
        assert len(closure.walls) == 1


class TestFloorClosure:
    def test_floor_vertex_snaps_outward_to_wall_line(self):
        b = CaptureBundle()
        # Floor detected to z=-1.7; wall line at z=-2 (0.3 away, in gate).
        _add_anchor(
            b, pos=(0, -1.4, 0.15), quat_xyzw=_IDENTITY, extent=(4.0, 3.7),
            alignment=PLANE_HORIZONTAL, classification="floor",
        )
        _add_anchor(
            b, pos=(0.0, 0.0, -2.0), quat_xyzw=_NORMAL_PLUS_Z, extent=(5.0, 2.0),
            alignment=PLANE_VERTICAL, classification="wall",
        )
        closure = close_shell(assemble_shell(b.plane_anchors))
        poly = closure.floor_polygon_rendered
        assert poly is not None
        assert poly[:, 2].min() == pytest.approx(-2.0, abs=1e-6)
        assert closure.quality["floor_vertices_snapped"] == 2
        wall_id = closure.walls[0].geom.wall_id
        assert f"extended_to_wall:{wall_id}" in closure.floor_edge_states
        # The far edge (no wall) keeps its detected position.
        assert poly[:, 2].max() == pytest.approx(2.0, abs=1e-6)
        assert "observed" in closure.floor_edge_states

    def test_floor_bounded_by_wall_line(self):
        b = CaptureBundle()
        # Floor detected THROUGH the wall (to z=-2.6); wall line at z=-2.
        _add_anchor(
            b, pos=(0, -1.4, -0.3), quat_xyzw=_IDENTITY, extent=(4.0, 4.6),
            alignment=PLANE_HORIZONTAL, classification="floor",
        )
        _add_anchor(
            b, pos=(0.0, 0.0, -2.0), quat_xyzw=_NORMAL_PLUS_Z, extent=(5.0, 2.0),
            alignment=PLANE_VERTICAL, classification="wall",
        )
        closure = close_shell(assemble_shell(b.plane_anchors))
        poly = closure.floor_polygon_rendered
        assert poly[:, 2].min() == pytest.approx(-2.0, abs=1e-6)
        wall_id = closure.walls[0].geom.wall_id
        assert f"bounded_by_wall:{wall_id}" in closure.floor_edge_states
        # Measured polygon keeps the detected overshoot.
        assert closure.floor_polygon_measured[:, 2].min() == pytest.approx(
            -2.6, abs=1e-6
        )

    def test_floor_polygon_winding_ccw_in_xz(self):
        closure = close_shell(assemble_shell(_closure_bundle().plane_anchors))
        for poly in (closure.floor_polygon_measured, closure.floor_polygon_rendered):
            assert shell_geometry._polygon_signed_area_xz(poly) > 0

    def test_edge_states_align_with_segments(self):
        closure = close_shell(assemble_shell(_closure_bundle().plane_anchors))
        assert len(closure.floor_edge_states) == len(closure.floor_polygon_rendered)


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
        deploy env files silently — pin the names). Merge knobs live in
        room_planes (the extraction, 0069 chunk 1); closure knobs in
        shell_geometry."""
        assert room_planes.SHELL_FLOOR_MIN_AREA_M2 > 0
        assert room_planes.SHELL_WALL_NORMAL_TOL_DEG > 0
        assert room_planes.SHELL_WALL_COPLANAR_TOL_M > 0
        assert room_planes.SHELL_WALL_MERGE_GAP_M > 0
        assert room_planes.SHELL_MIN_WALL_AREA_M2 > 0
        assert shell_geometry.SHELL_FLOOR_DROP_MAX_M > 0
        assert shell_geometry.SHELL_JOIN_MAX_GAP_M > 0
        assert shell_geometry.SHELL_STRUCTURAL_MIN_AREA_M2 > 0
        assert shell_geometry.SHELL_FLOOR_CONTACT_TOL_M > 0
        assert shell_geometry.SHELL_COMMON_TOP_ENABLED in (True, False)
