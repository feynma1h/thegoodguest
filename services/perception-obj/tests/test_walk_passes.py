"""Synthetic unit invariants for the post-fusion placement passes
(decision 0082): the cross-label 3D duplicate gate, wall back-face
anchoring + floor-class declip, door-geometry opening demotion, and the
box-top support snap. Real-data verification is the spike full-fusion run
(offline) + the deploy re-drives; these pin the DECISION semantics.

Run from repo root:
    python -m pytest services/perception-obj/tests/test_walk_passes.py -v
"""
from __future__ import annotations

from dataclasses import dataclass, field

import fusion
import numpy as np
import pytest
from room_planes import ShellPlaneGeom
from roomplan_room import RoomPlanBox, RoomPlanSurface
from roomstudio_schemas.pose_math import rotmat_to_quat


@dataclass
class StubCtx:
    splats: dict = field(default_factory=dict)

    def get_splat(self, uri):
        return self.splats.get(uri)


def _cube(n=400, ext=(1.0, 1.0, 1.0)):
    rng = np.random.default_rng(3)
    return rng.uniform(-0.5, 0.5, size=(n, 3)) * np.asarray(ext)


def _obj(oid, label, pos, uri, *, placed=True, score=0.5, source="depth_fit", **extra):
    return {
        "object_id": oid,
        "label": label,
        "placed": placed,
        "method": source,
        "position_source": source,
        "splat_gcs_uri": uri,
        "world_transform": {
            "position": list(pos), "rotation_xyzw": [0.0, 0.0, 0.0, 1.0],
            "scale": 1.0,
        },
        "quality": {"score": score, "frames_observed": 1},
        **extra,
    }


def _wall(origin, normal, axis_u, width=4.0, height=3.0):
    origin = np.asarray(origin, dtype=np.float64)
    normal = np.asarray(normal, dtype=np.float64)
    axis_u = np.asarray(axis_u, dtype=np.float64)
    axis_v = np.array([0.0, 1.0, 0.0])
    corners = np.stack([
        origin, origin + width * axis_u,
        origin + width * axis_u + height * axis_v, origin + height * axis_v,
    ])
    return ShellPlaneGeom(
        kind="wall", corners_world=corners, normal=normal, origin=origin,
        axis_u=axis_u, axis_v=axis_v, width_m=width, height_m=height,
        classification="wall", member_indices=[], area_m2=width * height,
    )


def _rp_box(center, dims, category="table"):
    T = np.eye(4)
    T[:3, 3] = np.asarray(center, dtype=np.float64)
    return RoomPlanBox(
        identifier=f"b-{category}", category=category, confidence="high",
        attributes={}, dimensions=np.asarray(dims, dtype=np.float64),
        transform=T, center_world=T[:3, 3].copy(), up_y=1.0, yaw_rad=0.0,
    )


def _door_surface(center, width=0.9, height=2.0, kind="door"):
    """A door/window surface facing +Z at `center`."""
    T = np.eye(4)
    T[:3, 3] = np.asarray(center, dtype=np.float64)
    hw, hh = width / 2.0, height / 2.0
    poly_local = np.array([[-hw, -hh, 0.0], [hw, -hh, 0.0], [hw, hh, 0.0], [-hw, hh, 0.0]])
    return RoomPlanSurface(
        identifier=f"{kind}-1", kind=kind, category=kind, confidence="high",
        dimensions=np.array([width, height, 0.0]), transform=T,
        polygon_local=poly_local, polygon_world=poly_local @ T[:3, :3].T + T[:3, 3],
        polygon_from_dimensions=True, normal_world=T[:3, :3][:, 2].copy(),
        parent_identifier="wall-x",
    )


# ---------------------------------------------------------------------------
# Class 2: cross-label 3D duplicate gate
# ---------------------------------------------------------------------------

class TestCrossLabel3D:
    def _pair(self, label_a, label_b, offset=0.05):
        ctx = StubCtx(splats={
            "gs://o/a.ply": _cube(ext=(0.6, 0.6, 0.6)),
            "gs://o/b.ply": _cube(ext=(0.6, 0.6, 0.6)),
        })
        fused = [
            _obj("obj_000", label_a, (0.0, 0.5, 0.0), "gs://o/a.ply", score=0.8),
            _obj("obj_001", label_b, (offset, 0.5, 0.0), "gs://o/b.ply", score=0.4),
        ]
        return ctx, fused

    def test_confusable_overlapping_pair_dedups_to_better(self):
        ctx, fused = self._pair("monitor", "tv")
        fusion._dedup_cross_label_3d(fused, ctx)
        assert fused[0]["placed"] is True
        assert fused[1]["placed"] is False
        assert fused[1]["reason"] == "cross_label_duplicate"
        assert fused[1]["suppressed_by"] == "obj_000"

    def test_same_label_pair_dedups(self):
        """rp7's two mirrors: same label, different clusters, one object."""
        ctx, fused = self._pair("mirror", "mirror")
        fusion._dedup_cross_label_3d(fused, ctx)
        assert [o["placed"] for o in fused] == [True, False]

    def test_contact_source_outranks_score(self):
        ctx, fused = self._pair("mirror", "mirror")
        fused[1]["position_source"] = "single_view_wall_contact"
        fused[1]["quality"]["score"] = 0.1
        fusion._dedup_cross_label_3d(fused, ctx)
        assert [o["placed"] for o in fused] == [False, True]

    def test_non_confusable_pair_untouched(self):
        ctx, fused = self._pair("bed", "monitor")
        fusion._dedup_cross_label_3d(fused, ctx)
        assert all(o["placed"] for o in fused)

    def test_disjoint_volumes_untouched(self):
        ctx, fused = self._pair("monitor", "tv", offset=3.0)
        fusion._dedup_cross_label_3d(fused, ctx)
        assert all(o["placed"] for o in fused)

    def test_two_boxes_never_dedup(self):
        """RoomPlan measured two boxes = two real objects."""
        ctx, fused = self._pair("table", "desk")
        for o in fused:
            o["roomplan_box"] = {"box_id": "x", "yaw_rad": 0.0,
                                 "center_world": o["world_transform"]["position"],
                                 "dims": [0.6, 0.6, 0.6]}
        fusion._dedup_cross_label_3d(fused, ctx)
        assert all(o["placed"] for o in fused)

    def test_box_object_wins_over_splat(self):
        ctx, fused = self._pair("table", "cabinet")
        fused[1]["roomplan_box"] = {
            "box_id": "box_00", "yaw_rad": 0.0,
            "center_world": fused[1]["world_transform"]["position"],
            "dims": [0.8, 0.8, 0.8],
        }
        fused[1]["quality"]["score"] = 0.1  # box still wins
        fusion._dedup_cross_label_3d(fused, ctx)
        assert [o["placed"] for o in fused] == [False, True]


# ---------------------------------------------------------------------------
# Class 3: wall back-face anchoring + floor declip
# ---------------------------------------------------------------------------

class TestWallSnap:
    def _scene(self, label="artwork", center_z=0.0, thin=0.06):
        """A wall at z=0 facing +Z (interior is +Z); a thin object whose
        center straddles it."""
        wall = _wall(origin=(-2.0, 0.0, 0.0), normal=(0.0, 0.0, 1.0),
                     axis_u=(1.0, 0.0, 0.0))
        ctx = StubCtx(splats={"gs://o/a.ply": _cube(ext=(0.6, 0.4, thin))})
        obj = _obj("obj_000", label, (0.0, 1.0, center_z), "gs://o/a.ply")
        return wall, ctx, obj

    def test_half_in_wall_snaps_back_face_to_plane(self):
        wall, ctx, obj = self._scene(center_z=0.0)
        out = fusion._snap_wall_class_object(obj, [wall], ctx)
        assert "wall_back_face" in out["constraints_applied"]
        pts = fusion._sampled_world_points(out, ctx)
        assert float(((pts - wall.origin) @ wall.normal).min()) >= -1e-6
        assert out["quality"]["wall_snap_m"] == pytest.approx(0.03, abs=0.02)

    def test_planar_object_aligns_to_wall_normal(self):
        wall, ctx, obj = self._scene(center_z=0.1)
        # Tilt the object 20° about X so its plane normal is off the wall's.
        c, s = np.cos(np.radians(20)), np.sin(np.radians(20))
        R = np.array([[1.0, 0, 0], [0, c, -s], [0, s, c]])
        obj["world_transform"]["rotation_xyzw"] = [float(v) for v in rotmat_to_quat(R)]
        out = fusion._snap_wall_class_object(obj, [wall], ctx)
        assert "wall_normal" in out["constraints_applied"]

    def test_non_wall_class_untouched(self):
        wall, ctx, obj = self._scene(label="bed")
        out = fusion._snap_wall_class_object(obj, [wall], ctx)
        assert out is obj

    def test_contact_source_exempt(self):
        wall, ctx, obj = self._scene()
        obj["position_source"] = "single_view_wall_contact"
        out = fusion._snap_wall_class_object(obj, [wall], ctx)
        assert out is obj

    def test_far_object_untouched(self):
        wall, ctx, obj = self._scene(center_z=1.5)
        out = fusion._snap_wall_class_object(obj, [wall], ctx)
        assert out is obj


class TestFloorDeclip:
    def test_clipping_furniture_pushed_into_room(self):
        wall = _wall(origin=(-2.0, 0.0, 0.0), normal=(0.0, 0.0, 1.0),
                     axis_u=(1.0, 0.0, 0.0))
        ctx = StubCtx(splats={"gs://o/t.ply": _cube(ext=(1.0, 0.7, 0.7))})
        obj = _obj("obj_000", "table", (0.0, 0.5, 0.2), "gs://o/t.ply")
        # points span z in [-0.15, 0.55]: 0.15 penetration > 0.08 tol
        out = fusion._declip_floor_class_object(obj, [wall], ctx)
        assert "wall_declip" in out["constraints_applied"]
        assert out["quality"]["wall_declip_m"] == pytest.approx(0.07, abs=0.02)
        pts = fusion._sampled_world_points(out, ctx)
        assert float(((pts - wall.origin) @ wall.normal).min()) >= -fusion._WALL_PENETRATION_TOL_M - 1e-6

    def test_tolerated_graze_untouched(self):
        wall = _wall(origin=(-2.0, 0.0, 0.0), normal=(0.0, 0.0, 1.0),
                     axis_u=(1.0, 0.0, 0.0))
        ctx = StubCtx(splats={"gs://o/t.ply": _cube(ext=(1.0, 0.7, 0.7))})
        obj = _obj("obj_000", "table", (0.0, 0.5, 0.31), "gs://o/t.ply")
        out = fusion._declip_floor_class_object(obj, [wall], ctx)
        assert out is obj

    def test_box_anchored_exempt(self):
        wall = _wall(origin=(-2.0, 0.0, 0.0), normal=(0.0, 0.0, 1.0),
                     axis_u=(1.0, 0.0, 0.0))
        ctx = StubCtx(splats={"gs://o/t.ply": _cube(ext=(1.0, 0.7, 0.7))})
        obj = _obj("obj_000", "table", (0.0, 0.5, 0.2), "gs://o/t.ply",
                   roomplan_box={"box_id": "box_00"})
        out = fusion._declip_floor_class_object(obj, [wall], ctx)
        assert out is obj


# ---------------------------------------------------------------------------
# Class 4: door-geometry opening demotion
# ---------------------------------------------------------------------------

class _Room:
    def __init__(self, doors=(), windows=()):
        self.doors = list(doors)
        self.windows = list(windows)


class TestOpeningGeometry:
    def test_cabinet_on_door_surface_demotes(self):
        room = _Room(doors=[_door_surface((0.0, 1.0, 0.0))])
        obj = _obj("obj_000", "cabinet", (0.1, 1.0, 0.1), "gs://o/c.ply")
        out = fusion._demote_on_opening_geometry(obj, room)
        assert out["placed"] is False
        assert out["reason"] == "represented_as_shell_opening"
        assert out["opening_surface"] == "door-1"

    def test_label_outside_set_survives(self):
        room = _Room(doors=[_door_surface((0.0, 1.0, 0.0))])
        obj = _obj("obj_000", "artwork", (0.1, 1.0, 0.1), "gs://o/c.ply")
        assert fusion._demote_on_opening_geometry(obj, room) is obj

    def test_off_surface_survives(self):
        room = _Room(doors=[_door_surface((0.0, 1.0, 0.0))])
        obj = _obj("obj_000", "cabinet", (0.0, 1.0, 1.0), "gs://o/c.ply")
        assert fusion._demote_on_opening_geometry(obj, room) is obj

    def test_beyond_rect_survives(self):
        room = _Room(doors=[_door_surface((0.0, 1.0, 0.0), width=0.9)])
        obj = _obj("obj_000", "cabinet", (1.2, 1.0, 0.0), "gs://o/c.ply")
        assert fusion._demote_on_opening_geometry(obj, room) is obj

    def test_box_anchored_exempt(self):
        room = _Room(doors=[_door_surface((0.0, 1.0, 0.0))])
        obj = _obj("obj_000", "cabinet", (0.0, 1.0, 0.0), "gs://o/c.ply",
                   roomplan_box={"box_id": "box_00"})
        assert fusion._demote_on_opening_geometry(obj, room) is obj


# ---------------------------------------------------------------------------
# Class 5: box-top support snap
# ---------------------------------------------------------------------------

class TestSupportSnap:
    def _scene(self, label="speaker", y=1.0, xz=(0.0, 0.0)):
        box = _rp_box(center=(0.0, 0.4, 0.0), dims=(1.2, 0.8, 0.6))  # top 0.8
        ctx = StubCtx(splats={"gs://o/s.ply": _cube(ext=(0.2, 0.3, 0.2))})
        obj = _obj("obj_000", label, (xz[0], y, xz[1]), "gs://o/s.ply")
        return box, ctx, obj

    def test_hovering_object_rests_on_box_top(self):
        box, ctx, obj = self._scene(y=1.05)  # bottom 0.9, top of box 0.8
        out = fusion._snap_onto_support(obj, [box], ctx)
        assert "on_top_of" in out["constraints_applied"]
        assert out["quality"]["support_box"] == "box_00"
        pts = fusion._sampled_world_points(out, ctx)
        assert float(pts[:, 1].min()) == pytest.approx(0.8, abs=1e-6)

    def test_sunk_object_lifted_onto_box_top(self):
        """The spike speaker: intersecting the table, lifted onto it."""
        box, ctx, obj = self._scene(y=0.75)  # bottom 0.6 < top 0.8
        out = fusion._snap_onto_support(obj, [box], ctx)
        assert out["quality"]["support_snap_m"] == pytest.approx(0.2, abs=0.02)
        pts = fusion._sampled_world_points(out, ctx)
        assert float(pts[:, 1].min()) == pytest.approx(0.8, abs=1e-6)

    def test_outside_footprint_untouched(self):
        box, ctx, obj = self._scene(y=1.05, xz=(1.0, 0.0))
        assert fusion._snap_onto_support(obj, [box], ctx) is obj

    def test_beyond_reach_untouched(self):
        box, ctx, obj = self._scene(y=1.6)
        assert fusion._snap_onto_support(obj, [box], ctx) is obj

    def test_non_support_class_untouched(self):
        box, ctx, obj = self._scene(label="chair")
        assert fusion._snap_onto_support(obj, [box], ctx) is obj
