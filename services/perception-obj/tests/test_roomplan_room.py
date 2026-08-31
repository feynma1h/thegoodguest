"""CapturedRoom parser pins for roomplan_room — the JSON parser +
room_planes adapters (decision 0077).

The fixture is the REAL RoomBuilder [.beautifyObjects] output of the co-run
spike's probe run (probe-20260728-143602, decision 0076), committed
byte-verbatim at tests/fixtures/roomplan_spike/captured_room_built.json —
the same document the 0077 design session's parser probe read. The pin set
is that probe's measured numbers, exact, at achieved accuracy:

  * 13 walls, all pure-up (|up_y - 1| <= 1e-4; achieved 2e-7), two
    perpendicular families (max deviation 2.65 deg), every bottom on the
    floor; 9 walls 3.05 m tall + four 1.95 m door-height segments (the
    shorthand "3.05 top / 1.95 segments" — heights above the floor; the
    absolute world tops are 1.631 / 0.532 with the floor at y = -1.418).
  * Floor: one polygon, 10 corners, 14.98 m^2, perfectly planar.
  * 9 objects, all pure-yaw (worst |up_y - 1| = 1e-7), incl. the dining
    chair 40.8 deg off the room's wall-family grid (yaw +84.3 vs the
    43.5-deg family heading — 0076's "genuinely-angled chair").
  * Doors/windows/openings (2/2/2) all parent-resolve to walls.
  * polygonCorners is EMPTY on 12 of 13 walls and every door/window/
    opening — the rect-from-dimensions fallback is the dominant real path;
    only wall_00 carries an explicit (6-corner) polygon.

The adapter gate proves the single-view contact priors and the room-sanity
gate consume RoomPlan-derived planes UNCHANGED: the same fusion path that
places single-view objects against ARKit anchor planes places them against
these (floor contact to <= 1 cm / bottom-on-floor <= 3 mm, wall contact
with the normal aligned to dot >= 0.99 — the priors' achieved tolerances), and
_position_outside_room gates against the RoomPlan floor rect + wall top.

Run from repo root:

    python -m pytest services/perception-obj/tests/test_roomplan_room.py -v
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import box_placement
import contact_priors
import fusion
import numpy as np
import pytest
import roomplan_room as rr
from thegoodguest_schemas.placement_math import (
    minimal_rotation,
    project_points,
    robust_cloud_stats,
)
from thegoodguest_schemas.pose_math import quat_to_rotmat, rotmat_to_quat

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "roomplan_spike" / "captured_room_built.json"

_UP = np.array([0.0, 1.0, 0.0])

# P2's measured room constants (see module docstring).
_FLOOR_Y = -1.4178
_TALL_WALL_H = 3.049
_DOOR_SEG_H = 1.951


@pytest.fixture(scope="module")
def room() -> rr.RoomPlanRoom:
    return rr.parse_captured_room(FIXTURE.read_bytes())


@pytest.fixture(scope="module")
def planes(room) -> contact_priors.RoomPlanes:
    return contact_priors.RoomPlanes(
        floor=rr.roomplan_floor_geom(room),
        walls=rr.roomplan_wall_geoms(room),
    )


# ---------------------------------------------------------------------------
# P2 pin set — walls
# ---------------------------------------------------------------------------

class TestP2Walls:
    def test_thirteen_walls_all_pure_up(self, room):
        assert len(room.walls) == 13
        for w in room.walls:
            up_y = float(w.transform[1, 1])
            assert abs(up_y - 1.0) <= 1e-4  # achieved 2e-7

    def test_two_perpendicular_families(self, room):
        normals = [w.normal_world for w in room.walls]
        n0 = normals[0]
        for n in normals[1:]:
            a = np.degrees(np.arccos(np.clip(abs(float(n0 @ n)), 0.0, 1.0)))
            dev = min(a, abs(90.0 - a))
            assert dev <= 2.7  # achieved max 2.65

    def test_wall_heights_and_floor_bottoms(self, room):
        heights = []
        for w in room.walls:
            ys = w.polygon_world[:, 1]
            assert abs(float(ys.min()) - _FLOOR_Y) < 0.01  # bottoms on the floor
            heights.append(float(ys.max() - ys.min()))
        tall = sum(1 for h in heights if abs(h - _TALL_WALL_H) < 0.01)
        door_seg = sum(1 for h in heights if abs(h - _DOOR_SEG_H) < 0.01)
        assert tall == 9
        assert door_seg == 4

    def test_polygon_fallback_is_the_dominant_real_path(self, room):
        from_dims = [w for w in room.walls if w.polygon_from_dimensions]
        explicit = [w for w in room.walls if not w.polygon_from_dimensions]
        assert len(from_dims) == 12
        assert len(explicit) == 1
        assert explicit[0] is room.walls[0]
        assert explicit[0].polygon_local.shape[0] == 6

    def test_wall_category_confidence(self, room):
        assert all(w.category == "wall" for w in room.walls)
        assert all(w.confidence == "high" for w in room.walls)


# ---------------------------------------------------------------------------
# P2 pin set — floor
# ---------------------------------------------------------------------------

class TestP2Floor:
    def test_one_floor_ten_corners(self, room):
        assert len(room.floors) == 1
        fl = room.floors[0]
        assert fl.polygon_local.shape[0] == 10
        assert not fl.polygon_from_dimensions

    def test_floor_area_exact(self, room):
        area = rr._polygon_area(room.floors[0].polygon_local)
        assert area == pytest.approx(14.9815, abs=1e-3)

    def test_floor_planar_at_measured_height(self, room):
        ys = room.floors[0].polygon_world[:, 1]
        assert float(np.ptp(ys)) < 1e-6  # achieved 0.0
        assert float(ys.mean()) == pytest.approx(_FLOOR_Y, abs=1e-3)


# ---------------------------------------------------------------------------
# P2 pin set — objects
# ---------------------------------------------------------------------------

class TestP2Objects:
    def test_nine_objects_all_pure_yaw(self, room):
        assert len(room.objects) == 9
        for ob in room.objects:
            assert abs(ob.up_y - 1.0) <= 1e-6  # achieved 1e-7

    def test_categories(self, room):
        cats = sorted(ob.category for ob in room.objects)
        assert cats == [
            "bed", "chair", "chair", "refrigerator",
            "storage", "storage", "table", "table", "table",
        ]

    def test_bed_box_extents(self, room):
        """0077 collateral: the RoomPlan bed box is 1.85 x 2.16 m (the
        shipped depth_fit had halved the real bed) — and the local long
        axis is Z, pinning 'long axis may be X or Z'."""
        bed = next(ob for ob in room.objects if ob.category == "bed")
        assert bed.dimensions[0] == pytest.approx(1.85, abs=0.005)
        assert bed.dimensions[2] == pytest.approx(2.16, abs=0.005)
        assert bed.dimensions[2] > bed.dimensions[0]

    def test_the_40_8_degree_chair(self, room):
        """0076's genuinely-angled chair: the dining chair's yaw sits 40.8
        deg off the room's wall-family grid (84.3 deg absolute vs the
        43.5-deg family heading), mod-90."""
        dining = next(
            ob for ob in room.objects
            if ob.category == "chair" and ob.attributes.get("ChairType") == "dining"
        )
        assert np.degrees(dining.yaw_rad) == pytest.approx(84.30, abs=0.05)

        # Family heading from the first wall's normal, mod 90.
        n0 = room.walls[0].normal_world
        family = np.degrees(np.arctan2(n0[2], n0[0])) % 90.0
        off = abs(np.degrees(dining.yaw_rad) % 90.0 - family)
        off = min(off, 90.0 - off)
        assert off == pytest.approx(40.8, abs=0.1)

    def test_swivel_chair_and_attributes(self, room):
        swivel = next(
            ob for ob in room.objects
            if ob.category == "chair" and ob.attributes.get("ChairType") == "swivel"
        )
        assert np.degrees(swivel.yaw_rad) == pytest.approx(45.77, abs=0.05)
        assert swivel.attributes.get("ChairLegType") == "star"
        storages = sorted(
            ob.attributes.get("StorageType")
            for ob in room.objects if ob.category == "storage"
        )
        assert storages == ["cabinet", "shelf"]


# ---------------------------------------------------------------------------
# P2 pin set — parenting
# ---------------------------------------------------------------------------

class TestP2Parenting:
    def test_full_parenting(self, room):
        idx = room.wall_index_by_identifier()
        parents = {}
        for kind, entities in (
            ("door", room.doors), ("window", room.windows), ("opening", room.openings),
        ):
            assert len(entities) == 2
            for s in entities:
                assert s.parent_identifier in idx, f"{kind} {s.identifier} unparented"
                parents.setdefault(kind, []).append(idx[s.parent_identifier])
        assert sorted(parents["door"]) == [0, 2]
        assert sorted(parents["window"]) == [0, 1]
        assert sorted(parents["opening"]) == [10, 11]


# ---------------------------------------------------------------------------
# Parse contract — degrade, drift pin, opacity
# ---------------------------------------------------------------------------

class TestParseContract:
    def test_garbage_bytes_raise_typed_error(self):
        with pytest.raises(rr.RoomPlanParseError):
            rr.parse_captured_room(b"\xff\x00 not json")

    def test_try_parse_never_raises(self):
        parsed, reason = rr.try_parse_captured_room(b"{ corrupt")
        assert parsed is None
        assert reason

    def test_try_parse_success(self):
        parsed, reason = rr.try_parse_captured_room(FIXTURE.read_bytes())
        assert reason is None
        assert parsed is not None and parsed.has_geometry

    def test_unsupported_version_is_the_drift_pin(self):
        doc = json.loads(FIXTURE.read_text())
        doc["version"] = 3
        with pytest.raises(rr.RoomPlanParseError, match="version"):
            rr.parse_captured_room(json.dumps(doc))

    def test_missing_entity_list_fails(self):
        doc = json.loads(FIXTURE.read_text())
        del doc["walls"]
        with pytest.raises(rr.RoomPlanParseError):
            rr.parse_captured_room(json.dumps(doc))

    def test_non_object_top_level_fails(self):
        parsed, reason = rr.try_parse_captured_room(b"[1, 2, 3]")
        assert parsed is None and reason

    def test_malformed_transform_fails(self):
        doc = json.loads(FIXTURE.read_text())
        doc["walls"][0]["transform"] = doc["walls"][0]["transform"][:15]
        with pytest.raises(rr.RoomPlanParseError, match="transform"):
            rr.parse_captured_room(json.dumps(doc))

    def test_empty_category_dict_fails(self):
        doc = json.loads(FIXTURE.read_text())
        doc["objects"][0]["category"] = {}
        with pytest.raises(rr.RoomPlanParseError, match="category"):
            rr.parse_captured_room(json.dumps(doc))

    def test_core_model_is_opaque(self):
        """coreModel is carried on the wire but NEVER read: replacing the
        178 KB Apple blob with junk of any type changes nothing."""
        doc = json.loads(FIXTURE.read_text())
        baseline = rr.parse_captured_room(FIXTURE.read_bytes())
        for junk in (12345, None, "not base64 at all", {"nested": "junk"}):
            doc["coreModel"] = junk
            parsed = rr.parse_captured_room(json.dumps(doc))
            assert len(parsed.walls) == len(baseline.walls)
            assert len(parsed.objects) == len(baseline.objects)

    def test_empty_room_has_no_geometry(self):
        doc = json.loads(FIXTURE.read_text())
        for k in ("walls", "floors", "doors", "windows", "openings", "objects"):
            doc[k] = []
        parsed = rr.parse_captured_room(json.dumps(doc))
        assert not parsed.has_geometry  # -> tier LIDAR_ARKIT at conversion


# ---------------------------------------------------------------------------
# Adapters — the room_planes surface
# ---------------------------------------------------------------------------

class TestFloorAdapter:
    def test_frame_contract(self, room):
        fg = rr.roomplan_floor_geom(room)
        assert fg is not None and fg.kind == "floor"
        assert np.allclose(fg.origin, fg.corners_world[0])
        assert np.allclose(np.cross(fg.axis_u, fg.axis_v), _UP)
        assert float(fg.corners_world[0][1]) == pytest.approx(_FLOOR_Y, abs=1e-3)

    def test_local_dims_are_the_local_bbox(self, room):
        """RoomPlan's dimensions field [4.273, 3.989] is the LOCAL polygon
        bbox — pinned at the parse level. The geom rect is the WORLD-axis
        XZ bbox instead (select_floor's exact semantics; this room sits
        ~43.5 deg off the world axes, so that rect is larger — 5.62 x 5.33
        — and must CONTAIN the polygon)."""
        fl = room.floors[0]
        local_spans = sorted([
            float(np.ptp(fl.polygon_local[:, 0])),
            float(np.ptp(fl.polygon_local[:, 1])),
        ])
        assert local_spans == pytest.approx(sorted(fl.dimensions[:2]), abs=0.02)

        fg = rr.roomplan_floor_geom(room)
        poly = fl.polygon_world
        for p in poly:
            rel = p - fg.origin
            u = float(np.dot(rel, fg.axis_u))
            v = float(np.dot(rel, fg.axis_v))
            assert -1e-9 <= u <= fg.width_m + 1e-9
            assert -1e-9 <= v <= fg.height_m + 1e-9

    def test_area_is_polygon_area_not_bbox(self, room):
        fg = rr.roomplan_floor_geom(room)
        assert fg.area_m2 == pytest.approx(14.9815, abs=1e-3)
        assert fg.area_m2 < fg.width_m * fg.height_m  # 10-corner polygon < bbox

    def test_no_floor_returns_none(self, room):
        doc = json.loads(FIXTURE.read_text())
        doc["floors"] = []
        parsed = rr.parse_captured_room(json.dumps(doc))
        assert rr.roomplan_floor_geom(parsed) is None


class TestWallAdapter:
    def test_thirteen_geoms_in_array_order(self, room):
        geoms = rr.roomplan_wall_geoms(room)
        assert len(geoms) == 13
        assert [g.wall_id for g in geoms] == [f"wall_{i:02d}" for i in range(13)]

    def test_normals_horizontal_and_interior_facing(self, room):
        geoms = rr.roomplan_wall_geoms(room)
        ref = rr.interior_reference(room)
        for g in geoms:
            assert abs(float(np.dot(g.normal, _UP))) < 1e-6
            anchor = g.corners_world.mean(axis=0)
            assert float(np.dot(g.normal, ref - anchor)) > 0.0, g.wall_id

    def test_exactly_two_normals_flipped(self, room):
        """RoomPlan makes no interior guarantee: 2 of the probe's 13 walls
        have local +Z pointing away from the room (measured), and the
        adapter flips exactly those."""
        geoms = rr.roomplan_wall_geoms(room)
        flips = 0
        for w, g in zip(room.walls, geoms, strict=True):
            raw_h = np.array([w.normal_world[0], 0.0, w.normal_world[2]])
            raw_h /= np.linalg.norm(raw_h)
            if float(np.dot(raw_h, g.normal)) < 0.0:
                flips += 1
        assert flips == 2

    def test_winding_contract(self, room):
        """cross(c1-c0, c3-c0) points along the front-face normal — the
        room_planes contract shell rendering and _wall_hit rely on."""
        for g in rr.roomplan_wall_geoms(room):
            c = g.corners_world
            front = np.cross(c[1] - c[0], c[3] - c[0])
            front /= np.linalg.norm(front)
            assert float(np.dot(front, g.normal)) > 0.999
            assert np.allclose(g.axis_v, _UP)
            assert np.allclose(g.origin, c[0])

    def test_openings_attached_in_plane_frame(self, room):
        geoms = rr.roomplan_wall_geoms(room)
        by_id = {g.wall_id: g for g in geoms}
        counts = {g.wall_id: len(g.openings) for g in geoms if g.openings}
        assert counts == {"wall_00": 2, "wall_01": 1, "wall_02": 1,
                          "wall_10": 1, "wall_11": 1}
        for g in geoms:
            for op in g.openings:
                assert op.classification in ("door", "window", "opening")
                assert op.u1 > op.u0 and op.v1 > op.v0
                assert op.u0 > -0.15 and op.u1 < g.width_m + 0.15
                assert op.v0 > -0.15 and op.v1 < g.height_m + 0.15
        # The wall_00 door's rect height reproduces the door's dimensions.
        door = next(s for s in room.doors
                    if room.wall_index_by_identifier()[s.parent_identifier] == 0)
        rects = by_id["wall_00"].openings
        door_rect = next(o for o in rects if o.classification == "door")
        assert (door_rect.v1 - door_rect.v0) == pytest.approx(
            float(door.dimensions[1]), abs=0.02
        )

    def test_deterministic(self, room):
        a = rr.roomplan_wall_geoms(room)
        b = rr.roomplan_wall_geoms(rr.parse_captured_room(FIXTURE.read_bytes()))
        for ga, gb in zip(a, b, strict=True):
            assert np.array_equal(ga.corners_world, gb.corners_world)
            assert np.array_equal(ga.normal, gb.normal)
            assert [
                (o.classification, o.u0, o.v0, o.u1, o.v1) for o in ga.openings
            ] == [
                (o.classification, o.u0, o.v0, o.u1, o.v1) for o in gb.openings
            ]


# ---------------------------------------------------------------------------
# Chunk D + sanity gate consume RoomPlan planes UNCHANGED
# ---------------------------------------------------------------------------

@dataclass
class FakeIntrinsics:
    fx: float
    fy: float
    cx: float
    cy: float


@dataclass
class FakePose:
    pos_x: float
    pos_y: float
    pos_z: float
    quat_x: float
    quat_y: float
    quat_z: float
    quat_w: float


def _box(half, n=15) -> np.ndarray:
    hx, hy, hz = half
    g = np.linspace(-1.0, 1.0, n)
    xx, yy, zz = np.meshgrid(g * hx, g * hy, g * hz, indexing="ij")
    return np.column_stack([xx.ravel(), yy.ravel(), zz.ravel()])


def _look_at(cam: np.ndarray, target: np.ndarray):
    up = np.array([0.0, 1.0, 0.0])
    fwd = target - cam
    fwd = fwd / np.linalg.norm(fwd)
    z = -fwd
    x = np.cross(up, z)
    x = x / np.linalg.norm(x)
    y = np.cross(z, x)
    R = np.column_stack([x, y, z])
    qx, qy, qz, qw = rotmat_to_quat(R)
    return FakePose(cam[0], cam[1], cam[2], qx, qy, qz, qw), fwd


def _scaled_intrinsics(scale=0.25):
    intr = FakeIntrinsics(1527.75 * scale, 1527.75 * scale, 923.94 * scale, 721.29 * scale)
    return intr, int(1440 * scale), int(1920 * scale)


def _bbox_mask(world_pts, intr, pose, H, W) -> np.ndarray:
    uv, _depth, valid = project_points(world_pts, intr, pose)
    uv = uv[valid]
    mask = np.zeros((H, W), dtype=bool)
    if uv.shape[0] == 0:
        return mask
    u0, v0 = int(max(0, uv[:, 0].min())), int(max(0, uv[:, 1].min()))
    u1, v1 = int(min(W, uv[:, 0].max())), int(min(H, uv[:, 1].max()))
    mask[v0:v1 + 1, u0:u1 + 1] = True
    return mask


def _frame_results(label, world_rot_xyzw, splat_max, cam, fwd, angular):
    return [{
        "frame_index": 0, "ok": True,
        "objects": [{
            "label": label, "score": 0.9, "mask_index": 0, "ok": True,
            "splat_gcs_uri": "gs://bucket/obj.ply",
            "placement": {
                "placed": False, "method": None,
                "reason": "no_depth_pending_triangulation",
                "world_transform": None, "quality": {},
                "world_rotation_xyzw": list(world_rot_xyzw),
                "rotation_source": "sam3d_layout",
                "splat_max_extent": float(splat_max),
            },
            "view_ray": {
                "origin": list(cam), "direction": list(fwd),
                "angular_extent_rad": float(angular),
            },
        }],
    }]


def _ctx(pose, intr, mask, splat, planes):
    return fusion.RefinementContext(
        get_camera=lambda fi: (pose, intr),
        get_mask_stack=lambda fi: mask[None, :, :],
        get_splat=lambda uri: splat,
        get_room_planes=lambda: planes,
    )


class TestChunkDConsumesRoomPlanPlanes:
    def test_floor_contact_places_on_roomplan_floor(self, planes):
        """The full fusion single-view path places a floor-class object on
        the RoomPlan floor — same code, same achieved tolerances as the
        anchor-plane pins in test_contact_priors_real_data."""
        floor_y = planes.floor_y
        splat = _box((0.4, 0.3, 0.35))
        stats = robust_cloud_stats(splat)
        splat_max, c_local = float(stats.extents[0]), stats.center
        yaw = 0.5
        c, s = np.cos(yaw), np.sin(yaw)
        R_gt = np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])
        q = (splat - c_local) @ R_gt.T
        m = float(q[:, 1].min())
        s_gt = 0.8
        # Room interior, near the floor centroid.
        fl = planes.floor
        interior = fl.origin + 0.5 * fl.width_m * fl.axis_u + 0.5 * fl.height_m * fl.axis_v
        centroid = np.array([interior[0], floor_y - s_gt * m, interior[2]])
        t_gt = centroid - s_gt * (R_gt @ c_local)
        world_gt = s_gt * splat @ R_gt.T + t_gt
        cam = centroid + np.array([0.6, 1.2, -1.5])
        pose, fwd = _look_at(cam, centroid)
        dist = float(np.linalg.norm(centroid - cam))
        angular = s_gt * splat_max / dist
        intr, H, W = _scaled_intrinsics()
        mask = _bbox_mask(world_gt, intr, pose, H, W)
        fr = _frame_results("chair", rotmat_to_quat(R_gt), splat_max, cam, fwd, angular)

        obj = fusion.fuse_scene_objects_with_meta(fr, _ctx(pose, intr, mask, splat, planes))[0][0]
        assert obj["placed"] is True
        assert obj["method"] == "single_view_floor_contact"
        assert obj["position_source"] == "single_view_floor_contact"
        assert np.allclose(obj["world_transform"]["position"], t_gt, atol=1e-2)
        wt = obj["world_transform"]
        recon = wt["scale"] * splat @ quat_to_rotmat(tuple(wt["rotation_xyzw"])).T + np.asarray(wt["position"])
        assert float(recon[:, 1].min()) == pytest.approx(floor_y, abs=3e-3)

    def test_wall_contact_places_on_roomplan_wall(self, planes):
        """A thin wall-class object hangs on a RoomPlan wall via the wall-
        contact prior; the object's plane normal aligns to the adapter's
        interior-oriented wall normal."""
        wall = max(planes.walls, key=lambda w: w.width_m)  # the 3.67 m wall
        n = wall.normal
        splat = _box((0.35, 0.5, 0.02))
        stats = robust_cloud_stats(splat)
        splat_max, thin, c_local = float(stats.extents[0]), float(stats.extents[2]), stats.center
        R_gt = minimal_rotation(stats.axes[:, 2], n)
        wc = wall.origin + 0.5 * wall.width_m * wall.axis_u + 0.5 * wall.height_m * wall.axis_v
        s_gt = 1.0
        center = wc + 0.5 * s_gt * thin * n
        t_gt = center - s_gt * (R_gt @ c_local)
        world_gt = s_gt * splat @ R_gt.T + t_gt
        cam = wc + n * 2.0
        pose, fwd = _look_at(cam, center)
        dist = float(np.linalg.norm(center - cam))
        angular = s_gt * splat_max / dist
        intr, H, W = _scaled_intrinsics()
        mask = _bbox_mask(world_gt, intr, pose, H, W)
        fr = _frame_results("door", rotmat_to_quat(R_gt), splat_max, cam, fwd, angular)

        obj = fusion.fuse_scene_objects_with_meta(fr, _ctx(pose, intr, mask, splat, planes))[0][0]
        assert obj["placed"] is True
        assert obj["method"] == "single_view_wall_contact"
        assert np.allclose(obj["world_transform"]["position"], t_gt, atol=1e-2)
        R = quat_to_rotmat(tuple(obj["world_transform"]["rotation_xyzw"]))
        assert float(np.dot(R @ stats.axes[:, 2], n)) > 0.99

    def test_sanity_gate_reads_roomplan_planes(self, planes):
        """_position_outside_room gates against the RoomPlan floor rect and
        wall top exactly as against anchor-derived planes."""
        fl = planes.floor
        inside = fl.origin + 0.5 * fl.width_m * fl.axis_u + 0.5 * fl.height_m * fl.axis_v
        inside = inside + np.array([0.0, 0.5, 0.0])
        assert fusion._position_outside_room(inside, planes) is False
        beyond = fl.origin - 3.0 * fl.axis_u
        assert fusion._position_outside_room(beyond, planes) is True
        above = inside + np.array([0.0, 4.0, 0.0])  # above the 1.63 wall top
        assert fusion._position_outside_room(above, planes) is True
        below = inside - np.array([0.0, 3.0, 0.0])
        assert fusion._position_outside_room(below, planes) is True

    def test_has_geometry_and_floor_y(self, planes):
        assert planes.has_geometry
        assert planes.floor_y == pytest.approx(_FLOOR_Y, abs=1e-3)


class TestExtentAxesOnRealBoxes:
    """`extent_axes_m` against the real spike room (decision 0096's trigger).

    0096 recorded that the shipped dims triple was "descending-sorted in all
    six real boxes", and concluded the axis semantics were unrecoverable.
    Measured here on the committed fixture, that is not what the data says:
    `dimensions` is Apple's own local (x, y, z) order, index 1 is the
    vertical extent, and it is NOT the largest on 6 of 9 boxes — so the
    ordering carries real information. (The descending triple 0096 saw is
    `extent_m_sorted`, a different field.) These pins hold the corrected
    reading in place: the up extent is the LARGEST on 4 of 9 boxes, the
    middle on 3 and the smallest on 2, so no sort order can stand in for it.
    """

    # Apple's own category per box, with the height a human would measure.
    _EXPECTED_UP_M = [
        ("storage", 0.8152),
        ("storage", 1.9119),   # tall shelf
        ("table", 0.4662),
        ("bed", 0.6109),       # NOT its 2.16 m length
        ("table", 0.5704),
        ("table", 0.7322),
        ("chair", 0.6819),
        ("chair", 0.9570),
        ("refrigerator", 1.6351),  # the low-confidence wardrobe
    ]

    def test_every_real_box_names_its_up_extent(self, room):
        got = [
            (b.category, box_placement.box_extent_axes(b)["up_m"])
            for b in room.objects
        ]
        assert got == [(c, pytest.approx(v)) for c, v in self._EXPECTED_UP_M]

    def test_up_extent_is_physically_plausible_for_its_category(self, room):
        """The independent check: every named up extent is a height a
        person would accept for that piece of furniture. This is what
        would fail loudly if the axis convention ever flipped."""
        plausible = {
            "bed": (0.3, 1.2),
            "table": (0.3, 1.3),
            "chair": (0.5, 1.4),
            "storage": (0.3, 2.6),
            "refrigerator": (0.8, 2.2),
        }
        for b in room.objects:
            lo, hi = plausible[b.category]
            up = box_placement.box_extent_axes(b)["up_m"]
            assert lo <= up <= hi, f"{b.category} up extent {up} m"

    def test_the_vertical_extent_is_not_recoverable_by_sorting(self, room):
        """The measurement that justifies the field existing at all: on
        most real boxes the up extent is neither the largest nor the
        smallest, so no sort order can stand in for it."""
        ranks = []
        for b in room.objects:
            dims = sorted((round(float(d), 4) for d in b.dimensions), reverse=True)
            ranks.append(dims.index(box_placement.box_extent_axes(b)["up_m"]))
        # Largest on 4 (the tall pieces), middle on 3, smallest on 2.
        assert ranks == [1, 0, 1, 2, 2, 1, 0, 0, 0]

    def test_real_boxes_are_upright_far_inside_the_gate(self, room):
        """Every real box is exactly upright to float precision, so the
        5-degree gate is nowhere near real data.

        Note the stored `up_y` reads 1e-7 SHORT of 1 on 8 of 9 boxes.
        That is column-norm error, not tilt: `box_extent_axes` normalizes
        the up column before taking the angle, which is why it reports a
        true zero where a bare `arccos(up_y)` would invent ~0.026 deg of
        lean that is not in the data.
        """
        tilts = [box_placement.box_extent_axes(b)["up_tilt_deg"] for b in room.objects]
        assert max(tilts) == 0.0
        assert min(float(b.up_y) for b in room.objects) < 1.0

    def test_footprint_pair_matches_the_other_two_dims(self, room):
        for b in room.objects:
            axes = box_placement.box_extent_axes(b)
            dims = [round(float(d), 4) for d in b.dimensions]
            assert axes["horizontal_m"] == sorted([dims[0], dims[2]], reverse=True)
