"""Real-data + synthetic-ground-truth pins for decision 0067 chunk D:
single-view object placement from measured plane-anchor contact priors.

The measured input is REAL: tests/fixtures/scene_f3d70236/bundle.pb carries
the 24 ARKit plane anchors of the first plane-carrying capture (floor +
merged walls), parsed through room_planes exactly as production does. The
OBJECTS are synthetic boxes with known ground-truth transforms — f3d70236's
per-frame SAM detections are not committed (and re-driving them needs the
GPU), so chunk D is validated as "recover a known object placed against the
real measured room", which is precisely what the contact solve claims to
do. The floor case is additionally exercised through a REAL f3d70236 camera
pose end-to-end.

Everything runs through the production fusion.fuse_scene_objects_with_meta
path (single-member ray cluster -> insufficient_observations ->
_try_single_view_prior -> contact_priors.solve_placement -> evidence gate),
so these pin the wiring, not just the geometry. Pure-geometry accuracy of
the solves themselves lives in packages/schemas/tests/test_placement_math.py.

Achieved tolerances (pinned below): floor/wall position recover to <=1 cm,
scale to <=2%, the object bottom sits on the measured floor to <=3 mm, and
the wall normal aligns to the measured wall to dot >= 0.99 — the solve is
exact up to the silhouette-scale approximation; the loose bounds only
absorb that.

Run from repo root:

    python -m pytest services/perception-obj/tests/test_contact_priors_real_data.py -v
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import contact_priors
import fusion
import numpy as np
import pytest
from roomstudio_schemas import CaptureBundle
from roomstudio_schemas.placement_math import (
    minimal_rotation,
    project_points,
    robust_cloud_stats,
)
from roomstudio_schemas.pose_math import (
    pose_position,
    pose_quat,
    quat_to_rotmat,
    rotmat_to_quat,
)

BUNDLE = Path(__file__).resolve().parent / "fixtures" / "scene_f3d70236" / "bundle.pb"


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


# ---------------------------------------------------------------------------
# Helpers: real planes, synthetic objects, synthetic evidence.
# ---------------------------------------------------------------------------

def _load_planes() -> contact_priors.RoomPlanes:
    bundle = CaptureBundle()
    bundle.ParseFromString(BUNDLE.read_bytes())
    return contact_priors.extract_room_planes(bundle.plane_anchors)


def _load_bundle() -> CaptureBundle:
    bundle = CaptureBundle()
    bundle.ParseFromString(BUNDLE.read_bytes())
    return bundle


def _box(half, n=15) -> np.ndarray:
    """Dense grid box (n**3 points) — dense like a real splat, so the tier-1
    density grid fills the way production's 100k-point splats do."""
    hx, hy, hz = half
    g = np.linspace(-1.0, 1.0, n)
    xx, yy, zz = np.meshgrid(g * hx, g * hy, g * hz, indexing="ij")
    return np.column_stack([xx.ravel(), yy.ravel(), zz.ravel()])


def _look_at(cam: np.ndarray, target: np.ndarray) -> tuple[FakePose, np.ndarray]:
    """Camera pose looking from `cam` at `target` (camera looks down -Z,
    +Y up), plus the world-frame forward direction."""
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


def _scaled_intrinsics(scale=0.25) -> tuple[FakeIntrinsics, int, int]:
    intr = FakeIntrinsics(1527.75 * scale, 1527.75 * scale, 923.94 * scale, 721.29 * scale)
    return intr, int(1440 * scale), int(1920 * scale)


def _bbox_mask(world_pts, intr, pose, H, W) -> np.ndarray:
    """A filled silhouette bbox of the object's projection — a synthetic SAM
    mask consistent with the ground-truth placement."""
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
        get_room_planes=(lambda: planes) if planes is not None else None,
    )


def _floor_scene(planes, *, label="chair", cam=None, half=(0.4, 0.3, 0.35), yaw=0.5, s_gt=0.8):
    """A box resting on the real floor, viewed from `cam` (defaults to an
    above-and-back synthetic pose). Returns (frame_results, ctx, t_gt, s_gt,
    splat, floor_y)."""
    floor_y = planes.floor_y
    splat = _box(half)
    stats = robust_cloud_stats(splat)
    splat_max, c_local = float(stats.extents[0]), stats.center
    c, s = np.cos(yaw), np.sin(yaw)
    R_gt = np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])
    q = (splat - c_local) @ R_gt.T
    m = float(q[:, 1].min())
    centroid = np.array([-0.3, floor_y - s_gt * m, 0.5])
    t_gt = centroid - s_gt * (R_gt @ c_local)
    world_gt = s_gt * splat @ R_gt.T + t_gt
    if cam is None:
        cam = centroid + np.array([0.6, 1.2, -1.5])
    pose, fwd = _look_at(cam, centroid)
    dist = float(np.linalg.norm(centroid - cam))
    angular = s_gt * splat_max / dist
    intr, H, W = _scaled_intrinsics()
    mask = _bbox_mask(world_gt, intr, pose, H, W)
    fr = _frame_results(label, rotmat_to_quat(R_gt), splat_max, cam, fwd, angular)
    return fr, _ctx(pose, intr, mask, splat, planes), t_gt, s_gt, splat, floor_y


def _wall_scene(planes, *, label="door", wall_id="wall_08", s_gt=1.0):
    """A thin planar box hung on a real detected wall, viewed head-on."""
    wall = next(w for w in planes.walls if w.wall_id == wall_id)
    n = wall.normal
    splat = _box((0.35, 0.5, 0.02))
    stats = robust_cloud_stats(splat)
    splat_max, thin, c_local = float(stats.extents[0]), float(stats.extents[2]), stats.center
    R_gt = minimal_rotation(stats.axes[:, 2], n)
    wc = wall.origin + 0.5 * wall.width_m * wall.axis_u + 0.5 * wall.height_m * wall.axis_v
    center = wc + 0.5 * s_gt * thin * n
    t_gt = center - s_gt * (R_gt @ c_local)
    world_gt = s_gt * splat @ R_gt.T + t_gt
    cam = wc + n * 2.0
    pose, fwd = _look_at(cam, center)
    dist = float(np.linalg.norm(center - cam))
    angular = s_gt * splat_max / dist
    intr, H, W = _scaled_intrinsics()
    mask = _bbox_mask(world_gt, intr, pose, H, W)
    fr = _frame_results(label, rotmat_to_quat(R_gt), splat_max, cam, fwd, angular)
    return fr, _ctx(pose, intr, mask, splat, planes), t_gt, s_gt, splat, n, stats


def _recon_world(obj, splat):
    wt = obj["world_transform"]
    R = quat_to_rotmat(tuple(wt["rotation_xyzw"]))
    return wt["scale"] * splat @ R.T + np.asarray(wt["position"])


# ---------------------------------------------------------------------------
# Class map
# ---------------------------------------------------------------------------

def test_prior_class_map():
    assert contact_priors.prior_class("chair") == "floor"
    assert contact_priors.prior_class("bed") == "floor"
    assert contact_priors.prior_class("Table") == "floor"  # case-insensitive
    assert contact_priors.prior_class("door") == "wall"
    assert contact_priors.prior_class("curtain") == "wall"
    assert contact_priors.prior_class("artwork") == "wall"
    # The RP-8 walk moved clock into the wall family ("clock ... should sit
    # flat against the wall" — decision 0082); the single-view evidence
    # gate still refuses a desk clock a wall-contact solve would misplace.
    assert contact_priors.prior_class("clock") == "wall"
    # Ambiguous / free-standing classes get NO prior (stay unplaced on 1 view).
    assert contact_priors.prior_class("table lamp") is None
    assert contact_priors.prior_class("speaker") is None
    assert contact_priors.prior_class("plant") is None
    assert contact_priors.prior_class(None) is None
    assert contact_priors.prior_class("") is None


# ---------------------------------------------------------------------------
# Real plane extraction
# ---------------------------------------------------------------------------

def test_extract_room_planes_real_bundle():
    planes = _load_planes()
    assert planes.has_geometry
    assert planes.floor is not None
    # The recorded f3d70236 floor sits at y = -1.544 m.
    assert planes.floor_y == pytest.approx(-1.544, abs=0.01)
    assert len(planes.walls) >= 7  # merged vertical set


def test_extract_room_planes_empty_bundle():
    planes = contact_priors.extract_room_planes([])
    assert not planes.has_geometry
    assert planes.floor is None
    assert planes.walls == []
    assert planes.floor_y is None


# ---------------------------------------------------------------------------
# Floor contact placement (through the full fusion path)
# ---------------------------------------------------------------------------

def test_floor_prior_places_object_on_real_floor():
    planes = _load_planes()
    fr, ctx, t_gt, s_gt, splat, floor_y = _floor_scene(planes)
    objects, meta = fusion.fuse_scene_objects_with_meta(fr, ctx)
    assert len(objects) == 1
    obj = objects[0]
    assert obj["placed"] is True
    assert obj["method"] == "single_view_floor_contact"
    assert obj["position_source"] == "single_view_floor_contact"
    assert obj["constraints_applied"] == ["floor_contact"]
    assert np.allclose(obj["world_transform"]["position"], t_gt, atol=1e-2)
    assert obj["world_transform"]["scale"] == pytest.approx(s_gt, rel=2e-2)
    # The object bottom sits on the measured floor.
    recon = _recon_world(obj, splat)
    assert float(recon[:, 1].min()) == pytest.approx(floor_y, abs=3e-3)
    # Additive manifest fields present on the placed object.
    assert obj["reprojection_score"] is not None
    assert obj["quality"]["single_view_tier1"] >= fusion._SINGLE_VIEW_MIN_TIER1
    assert "extent_m_sorted" in obj


def test_floor_prior_with_real_camera_pose():
    """End-to-end with a REAL f3d70236 camera pose + intrinsics: place a box
    on the real floor 2 m in front of the real camera and recover it."""
    bundle = _load_bundle()
    planes = contact_priors.extract_room_planes(bundle.plane_anchors)
    frame = bundle.frames[40]
    intr = frame.intrinsics
    cam = pose_position(frame.camera_pose)
    R_wc = quat_to_rotmat(pose_quat(frame.camera_pose))
    fwd = R_wc @ np.array([0.0, 0.0, -1.0])

    splat = _box((0.4, 0.3, 0.3))
    stats = robust_cloud_stats(splat)
    splat_max, c_local = float(stats.extents[0]), stats.center
    R_gt = np.eye(3)
    m = float(((splat - c_local) @ R_gt.T)[:, 1].min())
    xz = cam + 1.8 * fwd
    centroid = np.array([xz[0], planes.floor_y - 0.8 * m, xz[2]])
    t_gt = centroid - 0.8 * (R_gt @ c_local)
    world_gt = 0.8 * splat @ R_gt.T + t_gt
    # The view ray points at the object centroid (production derives it from
    # the mask centroid), not down the camera's optical axis.
    view_dir = centroid - cam
    view_dir = view_dir / np.linalg.norm(view_dir)
    dist = float(np.linalg.norm(centroid - cam))
    angular = 0.8 * splat_max / dist
    mask = _bbox_mask(world_gt, intr, frame.camera_pose, intr.height, intr.width)

    fr = _frame_results("chair", rotmat_to_quat(R_gt), splat_max, cam, view_dir, angular)
    ctx = fusion.RefinementContext(
        get_camera=lambda fi: (frame.camera_pose, intr),
        get_mask_stack=lambda fi: mask[None, :, :],
        get_splat=lambda uri: splat,
        get_room_planes=lambda: planes,
    )
    obj = fusion.fuse_scene_objects_with_meta(fr, ctx)[0][0]
    assert obj["placed"] is True
    assert obj["method"] == "single_view_floor_contact"
    assert np.allclose(obj["world_transform"]["position"], t_gt, atol=1e-2)
    recon = _recon_world(obj, splat)
    assert float(recon[:, 1].min()) == pytest.approx(planes.floor_y, abs=3e-3)


# ---------------------------------------------------------------------------
# Wall contact placement
# ---------------------------------------------------------------------------

def test_wall_prior_places_object_on_real_wall():
    planes = _load_planes()
    fr, ctx, t_gt, s_gt, splat, n_wall, stats = _wall_scene(planes)
    obj = fusion.fuse_scene_objects_with_meta(fr, ctx)[0][0]
    assert obj["placed"] is True
    assert obj["method"] == "single_view_wall_contact"
    assert obj["position_source"] == "single_view_wall_contact"
    assert "wall_contact" in obj["constraints_applied"]
    assert "wall_normal" in obj["constraints_applied"]  # object already faces the wall
    assert np.allclose(obj["world_transform"]["position"], t_gt, atol=1e-2)
    assert obj["world_transform"]["scale"] == pytest.approx(s_gt, rel=2e-2)
    # The object's plane normal aligns to the measured wall normal.
    R = quat_to_rotmat(tuple(obj["world_transform"]["rotation_xyzw"]))
    assert float(np.dot(R @ stats.axes[:, 2], n_wall)) > 0.99


# ---------------------------------------------------------------------------
# Degrade / inertness (the "no planes -> A-C unchanged" lock)
# ---------------------------------------------------------------------------

def test_no_planes_leaves_single_view_unplaced():
    """An empty RoomPlanes makes every prior inert; the single-view object
    stays insufficient_observations and carries no placed-object fields."""
    real = _load_planes()
    fr, _ctx_unused, _t, _s, splat, _fy = _floor_scene(real)
    empty = contact_priors.RoomPlanes(floor=None, walls=[])
    # Reuse the same evidence but with empty planes.
    pose, fwd = _look_at(np.array([0.3, 0.9, -1.0]), np.array([-0.3, real.floor_y + 0.3, 0.5]))
    intr, H, W = _scaled_intrinsics()
    ctx = fusion.RefinementContext(
        get_camera=lambda fi: (pose, intr),
        get_mask_stack=lambda fi: np.ones((1, H, W), dtype=bool),
        get_splat=lambda uri: splat,
        get_room_planes=lambda: empty,
    )
    obj = fusion.fuse_scene_objects_with_meta(fr, ctx)[0][0]
    assert obj["placed"] is False
    assert obj["reason"] == "insufficient_observations"
    assert "position_source" not in obj
    assert obj["world_transform"] is None


def test_priors_inert_without_room_planes_accessor():
    """A ctx with no get_room_planes (older callers) never attempts a prior."""
    planes = _load_planes()
    fr, ctx_full, _t, _s, splat, _fy = _floor_scene(planes)
    ctx = fusion.RefinementContext(
        get_camera=ctx_full.get_camera,
        get_mask_stack=ctx_full.get_mask_stack,
        get_splat=ctx_full.get_splat,
        get_room_planes=None,
    )
    obj = fusion.fuse_scene_objects_with_meta(fr, ctx)[0][0]
    assert obj["placed"] is False
    assert obj["reason"] == "insufficient_observations"


def test_placement_refine_off_disables_priors(monkeypatch):
    """PLACEMENT_REFINE=0 reproduces legacy fusion: no prior, unplaced."""
    monkeypatch.setenv("PLACEMENT_REFINE", "0")
    planes = _load_planes()
    fr, ctx, _t, _s, _splat, _fy = _floor_scene(planes)
    obj = fusion.fuse_scene_objects_with_meta(fr, ctx)[0][0]
    assert obj["placed"] is False
    assert obj["reason"] == "insufficient_observations"
    assert "position_source" not in obj


def test_unmapped_class_stays_unplaced_even_with_planes():
    """A free-standing class (speaker) has no measured-surface prior; planes
    present or not, one view can't place it."""
    planes = _load_planes()
    fr, ctx, _t, _s, _splat, _fy = _floor_scene(planes, label="speaker")
    obj = fusion.fuse_scene_objects_with_meta(fr, ctx)[0][0]
    assert obj["placed"] is False
    assert obj["reason"] == "insufficient_observations"


# ---------------------------------------------------------------------------
# Evidence gate + determinism
# ---------------------------------------------------------------------------

def test_evidence_gate_rejects_mismatched_mask():
    """A geometrically-valid contact solve whose transform does NOT reproject
    onto the object's own mask is dropped — a prior never overrides pixels."""
    planes = _load_planes()
    fr, _ctx_unused, _t, _s, splat, _fy = _floor_scene(planes)
    intr, H, W = _scaled_intrinsics()
    pose, _fwd = _look_at(np.array([0.3, 0.9, -1.0]), np.array([-0.3, planes.floor_y + 0.3, 0.5]))
    wrong = np.zeros((H, W), dtype=bool)
    wrong[0:4, 0:4] = True  # a tiny mask in the corner, nowhere near the object
    ctx = fusion.RefinementContext(
        get_camera=lambda fi: (pose, intr),
        get_mask_stack=lambda fi: wrong[None, :, :],
        get_splat=lambda uri: splat,
        get_room_planes=lambda: planes,
    )
    obj = fusion.fuse_scene_objects_with_meta(fr, ctx)[0][0]
    assert obj["placed"] is False
    assert obj["reason"] == "insufficient_observations"


def test_single_view_prior_deterministic():
    """Identical inputs -> byte-identical manifest fragment (no RNG)."""
    planes = _load_planes()
    fr, ctx, _t, _s, _splat, _fy = _floor_scene(planes)
    a = fusion.fuse_scene_objects_with_meta(fr, ctx)[0]
    fr2, ctx2, _t2, _s2, _sp2, _fy2 = _floor_scene(_load_planes())
    b = fusion.fuse_scene_objects_with_meta(fr2, ctx2)[0]
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
