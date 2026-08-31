"""Unit tests for reproject.py — the two-tier reprojection-scoring
instrument, in-plane candidate generation, the sign-flip diagnostic, and
the multi-view silhouette fit (decision 0067).

Synthetic ground truth throughout: a small flat "plate" splat with a
half-bright/half-dark paint job (so a 180-degree in-plane rotation is
visually detectable) observed by a hand-placed camera, so every score can
be reasoned about by hand rather than smoke-tested.

Run from repo root:

    python -m pytest services/perception-obj/tests/test_reproject.py -v
"""
from __future__ import annotations

import math
import struct
from dataclasses import dataclass

import numpy as np
import pytest
import reproject
from thegoodguest_schemas.pose_math import rotmat_to_quat


@dataclass
class FakeIntrinsics:
    fx: float
    fy: float
    cx: float
    cy: float


@dataclass
class FakePose:
    pos_x: float = 0.0
    pos_y: float = 0.0
    pos_z: float = 0.0
    quat_x: float = 0.0
    quat_y: float = 0.0
    quat_z: float = 0.0
    quat_w: float = 1.0


GAUSSIAN_PROPS = [
    "x", "y", "z",
    "nx", "ny", "nz",
    "f_dc_0", "f_dc_1", "f_dc_2",
    "opacity",
    "scale_0", "scale_1", "scale_2",
    "rot_0", "rot_1", "rot_2", "rot_3",
]


def make_gaussian_ply(positions: np.ndarray, colors: np.ndarray, opacity_logit: np.ndarray) -> bytes:
    """A minimal binary-LE 3DGS PLY with real color/opacity payloads.

    colors: (N, 3) in [0, 1] -> stored as f_dc = (color - 0.5) / C0 so
    load_splat_appearance's decode recovers `colors` back exactly.
    """
    n = positions.shape[0]
    header = ["ply", "format binary_little_endian 1.0", f"element vertex {n}"]
    header += [f"property float {name}" for name in GAUSSIAN_PROPS]
    header += ["end_header", ""]
    head = "\n".join(header).encode("ascii")
    body = b""
    f_dc = (colors - 0.5) / reproject._SH_C0
    for i in range(n):
        p = positions[i]
        c = f_dc[i]
        vals = [
            float(p[0]), float(p[1]), float(p[2]),
            0.0, 0.0, 0.0,
            float(c[0]), float(c[1]), float(c[2]),
            float(opacity_logit[i]),
            0.0, 0.0, 0.0,
            0.0, 0.0, 0.0, 1.0,
        ]
        body += struct.pack("<" + "f" * len(GAUSSIAN_PROPS), *vals)
    return head + body


def _flat_plate_ply(n_side: int = 20, thickness: float = 0.001):
    """A thin square plate in the XY plane (normal = local +Z), half
    bright (x < 0) half dark (x >= 0) -- an in-plane 180-degree rotation
    swaps which half is which, and a 90-degree rotation makes the split
    run the other axis. Bright/dark (not a hue swap) is deliberate: the
    instrument's tier-2 NCC scores LUMINANCE agreement, and complementary
    hues (e.g. red vs blue) can share identical per-channel-mean
    luminance, which would make this synthetic object invisible to the
    exact channel under test without saying anything about a real
    object's actual appearance."""
    xs = np.linspace(-0.5, 0.5, n_side)
    ys = np.linspace(-0.5, 0.5, n_side)
    xx, yy = np.meshgrid(xs, ys)
    zz = np.random.RandomState(0).uniform(-thickness, thickness, xx.shape)
    positions = np.column_stack([xx.ravel(), yy.ravel(), zz.ravel()])
    colors = np.zeros((positions.shape[0], 3))
    is_bright = positions[:, 0] < 0
    colors[is_bright] = [0.95, 0.95, 0.95]
    colors[~is_bright] = [0.08, 0.08, 0.08]
    opacity_logit = np.full(positions.shape[0], 4.0)  # sigmoid(4) ~= 0.982
    return positions, make_gaussian_ply(positions, colors, opacity_logit)


def _camera_looking_at_plate(distance: float = 3.0):
    """A camera on +Z looking down -Z at the plate (identity rotation),
    intrinsics wide enough to frame the whole 1x1 plate."""
    intr = FakeIntrinsics(fx=400.0, fy=400.0, cx=320.0, cy=240.0)
    pose = FakePose(pos_x=0.0, pos_y=0.0, pos_z=distance)
    return intr, pose


def _mask_for_plate_filled(local_points, rotation_xyzw, translation, scale, intr, pose, image_wh=(640, 480)):
    """A filled (bbox) silhouette mask from the plate's OWN ground-truth
    projection -- independent of reproject's own rasterizer, so tier-1
    tests aren't circular."""
    from thegoodguest_schemas.placement_math import project_points

    world = reproject.transform_points(local_points, rotation_xyzw, translation, scale)
    uv, _d, valid = project_points(world, intr, pose)
    w, h = image_wh
    pts = uv[valid]
    u0, u1 = pts[:, 0].min(), pts[:, 0].max()
    v0, v1 = pts[:, 1].min(), pts[:, 1].max()
    mask = np.zeros((h, w), dtype=bool)
    iu0, iu1 = max(int(u0), 0), min(int(u1) + 1, w)
    iv0, iv1 = max(int(v0), 0), min(int(v1) + 1, h)
    mask[iv0:iv1, iu0:iu1] = True
    return mask


def _rgb_for_plate(local_points, colors, rotation_xyzw, translation, scale, intr, pose, image_wh=(640, 480)):
    """A ground-truth RGB render (nearest color per pixel) -- independent
    of reproject.render_splat, so tier-2 tests aren't circular."""
    from thegoodguest_schemas.placement_math import project_points

    world = reproject.transform_points(local_points, rotation_xyzw, translation, scale)
    uv, depth, valid = project_points(world, intr, pose)
    w, h = image_wh
    rgb = np.full((h, w, 3), 0.5)  # neutral gray background
    order = np.argsort(-depth[valid])  # far to near -> near wins ties
    pts = uv[valid][order]
    cols = colors[valid][order]
    us = np.clip(pts[:, 0].astype(int), 0, w - 1)
    vs = np.clip(pts[:, 1].astype(int), 0, h - 1)
    rgb[vs, us] = cols
    return rgb


# -----------------------------------------------------------------------------
# load_splat_appearance / transform_points
# -----------------------------------------------------------------------------

def test_load_splat_appearance_recovers_colors_and_opacity():
    positions, ply = _flat_plate_ply(n_side=4)
    appearance = reproject.load_splat_appearance(ply)
    # sigmoid(4.0)
    assert appearance.opacity[0] == pytest.approx(1.0 / (1.0 + math.exp(-4.0)), abs=1e-5)
    assert appearance.colors.shape == (16, 3)
    assert np.all((appearance.colors >= 0.0) & (appearance.colors <= 1.0))


def test_transform_points_identity():
    pts = np.array([[1.0, 2.0, 3.0]])
    out = reproject.transform_points(pts, (0.0, 0.0, 0.0, 1.0), [10.0, 0.0, 0.0], 2.0)
    assert np.allclose(out, [[12.0, 4.0, 6.0]])


# -----------------------------------------------------------------------------
# Tier 1: soft IoU / containment
# -----------------------------------------------------------------------------

def test_score_tier1_high_for_correct_placement():
    positions, _ply = _flat_plate_ply()
    intr, pose = _camera_looking_at_plate()
    rot = (0.0, 0.0, 0.0, 1.0)
    world = reproject.transform_points(positions, rot, [0.0, 0.0, 0.0], 1.0)
    mask = _mask_for_plate_filled(positions, rot, [0.0, 0.0, 0.0], 1.0, intr, pose)
    score = reproject.score_tier1(world, mask, intr, pose)
    assert score > 0.5


def test_score_tier1_low_when_far_off_target():
    positions, _ply = _flat_plate_ply()
    intr, pose = _camera_looking_at_plate()
    rot = (0.0, 0.0, 0.0, 1.0)
    mask = _mask_for_plate_filled(positions, rot, [0.0, 0.0, 0.0], 1.0, intr, pose)
    # Shift the candidate world points far outside the mask's frame.
    world_wrong = reproject.transform_points(positions, rot, [50.0, 50.0, 0.0], 1.0)
    score = reproject.score_tier1(world_wrong, mask, intr, pose)
    assert score < 0.05


def test_score_tier1_containment_tolerates_partial_view():
    """A mask that only covers half the plate's true footprint should
    still score well under containment (unlike a strict IoU)."""
    positions, _ply = _flat_plate_ply()
    intr, pose = _camera_looking_at_plate()
    rot = (0.0, 0.0, 0.0, 1.0)
    world = reproject.transform_points(positions, rot, [0.0, 0.0, 0.0], 1.0)
    full_mask = _mask_for_plate_filled(positions, rot, [0.0, 0.0, 0.0], 1.0, intr, pose)
    half_mask = full_mask.copy()
    cols = np.nonzero(full_mask.any(axis=0))[0]
    mid = cols[len(cols) // 2]
    half_mask[:, mid:] = False  # keep only the left half of the true footprint
    containment = reproject.score_tier1_containment(world, half_mask, intr, pose)
    iou = reproject.score_tier1(world, half_mask, intr, pose)
    assert containment > iou


# -----------------------------------------------------------------------------
# Tier 2: crude render + masked NCC
# -----------------------------------------------------------------------------

def test_render_splat_recovers_color_split():
    positions, ply = _flat_plate_ply(n_side=110)
    appearance = reproject.load_splat_appearance(ply)
    intr, pose = _camera_looking_at_plate()
    rot = (0.0, 0.0, 0.0, 1.0)
    world = reproject.transform_points(positions, rot, [0.0, 0.0, 0.0], 1.0)
    mask = _mask_for_plate_filled(positions, rot, [0.0, 0.0, 0.0], 1.0, intr, pose)
    rendered = reproject.render_splat(world, appearance.colors, appearance.opacity, mask, intr, pose, grid_size=32)
    assert rendered is not None
    render, coverage, _bbox = rendered
    assert coverage.sum() > 0
    covered = coverage > 0
    left_bright = render[:, :16][covered[:, :16]]
    right_dark = render[:, 16:][covered[:, 16:]]
    # Left half of the frame should read brighter than the right half.
    assert left_bright.mean() > right_dark.mean() + 0.3


def test_score_tier2_true_orientation_beats_180_flip():
    positions, ply = _flat_plate_ply(n_side=110)
    appearance = reproject.load_splat_appearance(ply)
    intr, pose = _camera_looking_at_plate()
    rot = (0.0, 0.0, 0.0, 1.0)
    translation, scale = [0.0, 0.0, 0.0], 1.0
    mask = _mask_for_plate_filled(positions, rot, translation, scale, intr, pose)
    rgb = _rgb_for_plate(positions, appearance.colors, rot, translation, scale, intr, pose)

    true_result = reproject.score_placement(
        local_points=positions, rotation_xyzw=rot, translation=translation, scale=scale,
        mask=mask, intrinsics=intr, pose=pose, appearance=appearance, rgb=rgb,
    )
    # 180 degrees about the plate's local normal (+Z, world Z here).
    from thegoodguest_schemas.placement_math import rotation_about_axis
    from thegoodguest_schemas.pose_math import quat_to_rotmat
    R_flip = rotation_about_axis([0.0, 0.0, 1.0], math.pi) @ quat_to_rotmat(rot)
    flip_result = reproject.score_placement(
        local_points=positions, rotation_xyzw=tuple(rotmat_to_quat(R_flip)), translation=translation, scale=scale,
        mask=mask, intrinsics=intr, pose=pose, appearance=appearance, rgb=rgb,
    )
    assert true_result["tier2"] is not None
    assert flip_result["tier2"] is not None
    assert true_result["tier2"] > flip_result["tier2"] + 0.1


def test_score_tier2_none_without_appearance_or_rgb():
    positions, _ply = _flat_plate_ply()
    intr, pose = _camera_looking_at_plate()
    rot = (0.0, 0.0, 0.0, 1.0)
    mask = _mask_for_plate_filled(positions, rot, [0.0, 0.0, 0.0], 1.0, intr, pose)
    result = reproject.score_placement(
        local_points=positions, rotation_xyzw=rot, translation=[0.0, 0.0, 0.0], scale=1.0,
        mask=mask, intrinsics=intr, pose=pose, appearance=None, rgb=None,
    )
    assert result["tier2"] is None
    assert result["tiers_used"] == ["tier1"]


# -----------------------------------------------------------------------------
# In-plane candidates + is_planar
# -----------------------------------------------------------------------------

def test_is_planar_true_for_flat_plate_false_for_cube():
    positions, _ply = _flat_plate_ply()
    assert reproject.is_planar(positions) is True
    rng = np.random.RandomState(0)
    cube = rng.uniform(-0.5, 0.5, size=(200, 3))
    assert reproject.is_planar(cube) is False


def test_in_plane_candidates_first_is_identity_rotation():
    positions, _ply = _flat_plate_ply()
    rot = (0.0, 0.0, 0.0, 1.0)
    candidates = reproject.in_plane_candidates(rot, positions)
    assert len(candidates) == 4
    assert np.allclose(candidates[0], rot, atol=1e-9)


def test_in_plane_resolution_picks_true_orientation_via_tier2():
    positions, ply = _flat_plate_ply(n_side=110)
    appearance = reproject.load_splat_appearance(ply)
    intr, pose = _camera_looking_at_plate()
    true_rot = tuple(rotmat_to_quat(reproject.rotation_about_axis([0, 0, 1], 0.3)))  # arbitrary "true" layout
    translation, scale = [0.0, 0.0, 0.0], 1.0
    mask = _mask_for_plate_filled(positions, true_rot, translation, scale, intr, pose)
    rgb = _rgb_for_plate(positions, appearance.colors, true_rot, translation, scale, intr, pose)

    # Simulate a layout rotation that shipped 180 degrees off in-plane.
    from thegoodguest_schemas.placement_math import rotation_about_axis
    from thegoodguest_schemas.pose_math import quat_to_rotmat
    shipped_rot = tuple(rotmat_to_quat(rotation_about_axis([0, 0, 1], math.pi) @ quat_to_rotmat(true_rot)))

    candidates = reproject.in_plane_candidates(shipped_rot, positions)
    scores = []
    for cand in candidates:
        result = reproject.score_placement(
            local_points=positions, rotation_xyzw=cand, translation=translation, scale=scale,
            mask=mask, intrinsics=intr, pose=pose, appearance=appearance, rgb=rgb,
        )
        scores.append(reproject.combined_score(result))
    best_idx = int(np.argmax(scores))
    # Candidate k=2 (180 degrees from the shipped k=0) should recover the
    # true orientation and win clearly.
    assert best_idx == 2
    remaining = [s for i, s in enumerate(scores) if i != best_idx]
    assert scores[best_idx] - max(remaining) > 0.05


# -----------------------------------------------------------------------------
# Sign-flip diagnostic
# -----------------------------------------------------------------------------

def test_mirrored_twin_is_180_about_view_axis():
    rot = (0.0, 0.0, 0.0, 1.0)
    view_dir = np.array([0.0, 0.0, -1.0])
    twin = reproject.mirrored_twin(rot, view_dir)
    from thegoodguest_schemas.pose_math import quat_to_rotmat
    R_twin = quat_to_rotmat(twin)
    # 180 about Z: x,y flip sign, z fixed.
    assert np.allclose(R_twin @ np.array([1.0, 0.0, 0.0]), [-1.0, 0.0, 0.0], atol=1e-9)
    assert np.allclose(R_twin @ np.array([0.0, 0.0, 1.0]), [0.0, 0.0, 1.0], atol=1e-9)


def test_mirrored_twin_scores_worse_for_asymmetric_plate():
    positions, ply = _flat_plate_ply(n_side=110)
    appearance = reproject.load_splat_appearance(ply)
    intr, pose = _camera_looking_at_plate()
    rot = (0.0, 0.0, 0.0, 1.0)
    translation, scale = [0.0, 0.0, 0.0], 1.0
    mask = _mask_for_plate_filled(positions, rot, translation, scale, intr, pose)
    rgb = _rgb_for_plate(positions, appearance.colors, rot, translation, scale, intr, pose)

    view_dir = np.array([0.0, 0.0, -1.0])
    twin_rot = reproject.mirrored_twin(rot, view_dir)

    true_result = reproject.score_placement(
        local_points=positions, rotation_xyzw=rot, translation=translation, scale=scale,
        mask=mask, intrinsics=intr, pose=pose, appearance=appearance, rgb=rgb,
    )
    twin_result = reproject.score_placement(
        local_points=positions, rotation_xyzw=twin_rot, translation=translation, scale=scale,
        mask=mask, intrinsics=intr, pose=pose, appearance=appearance, rgb=rgb,
    )
    assert reproject.combined_score(true_result) > reproject.combined_score(twin_result)


# -----------------------------------------------------------------------------
# Multi-view silhouette fit
# -----------------------------------------------------------------------------

def test_fit_silhouette_corrects_a_deliberately_wrong_position():
    positions, _ply = _flat_plate_ply(n_side=16)
    rot = (0.0, 0.0, 0.0, 1.0)
    true_translation = [0.3, -0.2, 0.0]
    true_scale = 1.0

    cams = [
        _camera_looking_at_plate(distance=3.0),
        (_camera_looking_at_plate(distance=3.5)[0], FakePose(pos_x=0.4, pos_y=0.0, pos_z=3.2)),
    ]
    observations = []
    for intr, pose in cams:
        mask = _mask_for_plate_filled(positions, rot, true_translation, true_scale, intr, pose)
        observations.append((mask, intr, pose))

    # Deliberately off, but within a local search's reach -- silhouette
    # fit is a REFINEMENT of a reasonable triangulated init (decision
    # 0067), not a global search from an arbitrary starting point.
    wrong_translation = [0.8, 0.5, 0.0]
    result = reproject.fit_silhouette(
        positions, rot, true_scale, wrong_translation, observations,
        max_iters=60, max_points=4000, grid_size=24,
    )
    assert result["improved"] is True
    err_before = np.linalg.norm(np.array(wrong_translation) - np.array(true_translation))
    err_after = np.linalg.norm(np.array(result["translation"]) - np.array(true_translation))
    assert err_after < err_before


def test_fit_silhouette_scale_stays_within_bound():
    positions, _ply = _flat_plate_ply(n_side=12)
    rot = (0.0, 0.0, 0.0, 1.0)
    intr, pose = _camera_looking_at_plate()
    mask = _mask_for_plate_filled(positions, rot, [0.0, 0.0, 0.0], 1.0, intr, pose)
    result = reproject.fit_silhouette(
        positions, rot, 1.0, [0.0, 0.0, 0.0], [(mask, intr, pose)],
        max_iters=30, scale_bound_factor=1.2,
    )
    assert 1.0 / 1.2 - 1e-6 <= result["scale"] <= 1.0 * 1.2 + 1e-6


def test_fit_silhouette_no_observations_does_not_improve():
    positions, _ply = _flat_plate_ply(n_side=8)
    result = reproject.fit_silhouette(
        positions, (0.0, 0.0, 0.0, 1.0), 1.0, [0.0, 0.0, 0.0], [], max_iters=5
    )
    assert result["improved"] is False
    assert result["scale"] == pytest.approx(1.0)
    assert result["translation"] == [0.0, 0.0, 0.0]
