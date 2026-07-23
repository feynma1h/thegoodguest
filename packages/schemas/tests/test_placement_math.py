"""Unit tests for roomstudio_schemas.placement_math.

These pin the geometry that places SAM 3D object splats into the ARKit
world frame. A wrong transform here is silently wrong in production — the
scene still renders, just misassembled — so every operation is checked
against hand-computed or synthetically constructed ground truth, not
smoke-tested.

Run from repo root:

    python -m pytest packages/schemas/tests/test_placement_math.py -v
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pytest
from roomstudio_schemas.placement_math import (
    MIN_CLOUD_POINTS,
    DegenerateGeometryError,
    camera_to_world,
    fit_scale_translation,
    fit_similarity,
    footprint_bbox,
    mask_containment,
    prepare_mask,
    project_points,
    rasterize_mask_density,
    rasterize_point_density,
    ray_through_pixel,
    resize_mask_to,
    robust_cloud_stats,
    rotation_about_axis,
    soft_containment,
    soft_iou,
    triangulate_rays,
    union_bbox,
    unproject_depth,
)
from roomstudio_schemas.pose_math import quat_average, quat_to_rotmat, rotmat_to_quat

SQRT2_2 = math.sqrt(2) / 2


# -----------------------------------------------------------------------------
# Lightweight stand-ins for the proto messages (duck-typed like pose_math's
# helpers — only the attributes the math reads).
# -----------------------------------------------------------------------------

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


def _pose_from(R: np.ndarray, t) -> FakePose:
    qx, qy, qz, qw = rotmat_to_quat(R)
    return FakePose(t[0], t[1], t[2], qx, qy, qz, qw)


def _rotmat(axis, angle_deg) -> np.ndarray:
    axis = np.asarray(axis, dtype=float)
    axis = axis / np.linalg.norm(axis)
    theta = math.radians(angle_deg)
    K = np.array([
        [0, -axis[2], axis[1]],
        [axis[2], 0, -axis[0]],
        [-axis[1], axis[0], 0],
    ])
    return np.eye(3) + math.sin(theta) * K + (1 - math.cos(theta)) * (K @ K)


# -----------------------------------------------------------------------------
# quat_to_rotmat / quat_average (pose_math extensions)
# -----------------------------------------------------------------------------

def test_quat_to_rotmat_matches_rotate_vec_by_quat():
    """R @ v must equal rotate_vec_by_quat(v, q) — same rotation, two forms."""
    from roomstudio_schemas.pose_math import rotate_vec_by_quat

    q = (0.1, 0.2, 0.3, math.sqrt(1 - 0.01 - 0.04 - 0.09))
    R = quat_to_rotmat(q)
    for v in [(1, 0, 0), (0, 1, 0), (0, 0, 1), (1.5, -2.5, 3.5)]:
        via_mat = R @ np.array(v, dtype=float)
        via_quat = np.array(rotate_vec_by_quat(v, q))
        assert np.allclose(via_mat, via_quat, atol=1e-12)


def test_quat_to_rotmat_roundtrip():
    """rotmat_to_quat(quat_to_rotmat(q)) recovers q up to sign."""
    q = np.array([0.3, -0.2, 0.5, math.sqrt(1 - 0.09 - 0.04 - 0.25)])
    back = np.array(rotmat_to_quat(quat_to_rotmat(tuple(q))))
    if np.dot(back, q) < 0:
        back = -back
    assert np.allclose(back, q, atol=1e-9)


def test_quat_average_identical_inputs():
    q = (0, SQRT2_2, 0, SQRT2_2)
    avg = quat_average([q, q, q])
    assert np.allclose(avg, q, atol=1e-12)


def test_quat_average_sign_flip_invariant():
    """q and -q are the same rotation; averaging must not cancel them."""
    q = (0, SQRT2_2, 0, SQRT2_2)
    neg = tuple(-c for c in q)
    avg = quat_average([q, neg])
    assert np.allclose(avg, q, atol=1e-12)


def test_quat_average_two_rotations_bisects():
    """Average of 0° and 90° about +Y is 45° about +Y."""
    q0 = (0.0, 0.0, 0.0, 1.0)
    q90 = (0.0, SQRT2_2, 0.0, SQRT2_2)
    expected = (0.0, math.sin(math.radians(22.5)), 0.0, math.cos(math.radians(22.5)))
    avg = quat_average([q0, q90])
    assert np.allclose(avg, expected, atol=1e-9)


def test_quat_average_empty_raises():
    with pytest.raises(ValueError):
        quat_average([])


# -----------------------------------------------------------------------------
# unproject_depth — hand-computed pinhole back-projection
# -----------------------------------------------------------------------------

def test_unproject_single_pixel_hand_computed():
    """4x3 depth raster, fx=fy=100, cx=2, cy=1.5, one valid pixel at
    (u=3, v=0), depth 2m:
      x = (3 - 2)   * 2 / 100 =  0.02
      y = -(0 - 1.5)* 2 / 100 =  0.03
      z = -2
    """
    depth = np.full((3, 4), np.nan)
    depth[0, 3] = 2.0
    intr = FakeIntrinsics(fx=100.0, fy=100.0, cx=2.0, cy=1.5)
    pts = unproject_depth(depth, intr)
    assert pts.shape == (1, 3)
    assert np.allclose(pts[0], [0.02, 0.03, -2.0], atol=1e-12)


def test_unproject_principal_point_lands_on_axis():
    """The pixel at (cx, cy) back-projects straight down the -Z axis."""
    depth = np.full((5, 5), np.nan)
    depth[2, 2] = 3.0
    intr = FakeIntrinsics(fx=50.0, fy=50.0, cx=2.0, cy=2.0)
    pts = unproject_depth(depth, intr)
    assert np.allclose(pts[0], [0.0, 0.0, -3.0], atol=1e-12)


def test_unproject_reprojects_to_same_pixels():
    """Round trip: unproject a constant-depth raster, forward-project the
    points, recover exactly the original pixel grid."""
    h, w, d = 6, 8, 1.7
    depth = np.full((h, w), d)
    intr = FakeIntrinsics(fx=90.0, fy=110.0, cx=3.5, cy=2.5)
    pts = unproject_depth(depth, intr)
    assert pts.shape == (h * w, 3)
    assert np.allclose(pts[:, 2], -d)
    z_depth = -pts[:, 2]
    u = pts[:, 0] * intr.fx / z_depth + intr.cx
    v = -(pts[:, 1] * intr.fy / z_depth) + intr.cy
    vs, us = np.nonzero(np.ones((h, w), dtype=bool))
    assert np.allclose(u, us, atol=1e-9)
    assert np.allclose(v, vs, atol=1e-9)


def test_unproject_filters_nan_nonpositive_mask_confidence():
    depth = np.array([[1.0, np.nan], [0.0, 2.0]])
    intr = FakeIntrinsics(fx=10.0, fy=10.0, cx=0.5, cy=0.5)
    # NaN and <= 0 dropped: 2 valid pixels remain.
    assert unproject_depth(depth, intr).shape == (2, 3)
    # Mask keeps only (1,1).
    mask = np.array([[False, False], [False, True]])
    pts = unproject_depth(depth, intr, mask=mask)
    assert pts.shape == (1, 3)
    assert np.allclose(pts[0, 2], -2.0)
    # Confidence: (0,0) has low confidence -> dropped at min_confidence=1.
    conf = np.array([[0, 2], [2, 2]], dtype=np.uint8)
    pts = unproject_depth(depth, intr, confidence=conf, min_confidence=1)
    assert pts.shape == (1, 3)  # only (1,1) survives (NaN/0 kill the others)


def test_unproject_shape_mismatch_raises():
    depth = np.ones((3, 4))
    intr = FakeIntrinsics(fx=10.0, fy=10.0, cx=2.0, cy=1.5)
    with pytest.raises(ValueError):
        unproject_depth(depth, intr, mask=np.ones((4, 3), dtype=bool))
    with pytest.raises(ValueError):
        unproject_depth(depth, intr, confidence=np.ones((2, 2), dtype=np.uint8))


# -----------------------------------------------------------------------------
# camera_to_world
# -----------------------------------------------------------------------------

def test_camera_to_world_identity_pose_passthrough():
    pts = np.array([[1.0, 2.0, 3.0], [-1.0, 0.5, -2.0]])
    out = camera_to_world(pts, FakePose())
    assert np.allclose(out, pts, atol=1e-12)


def test_camera_to_world_hand_computed():
    """Camera yawed 90° about +Y (looking down world -X), 2m up.

    quat (0, √2/2, 0, √2/2) rotates camera +X to world -Z and camera -Z to
    world -X. Camera-local point (0, 0, -1) (1m straight ahead) lands at
    world (-1, 2, 0) for a camera at (0, 2, 0).
    """
    pose = FakePose(0.0, 2.0, 0.0, 0.0, SQRT2_2, 0.0, SQRT2_2)
    out = camera_to_world(np.array([[0.0, 0.0, -1.0]]), pose)
    assert np.allclose(out[0], [-1.0, 2.0, 0.0], atol=1e-9)


def test_unproject_then_world_recovers_synthetic_object():
    """End-to-end synthetic ground truth: a wall of points 2m in front of a
    posed camera must land at the world coordinates constructed by hand."""
    R = _rotmat([0, 1, 0], 30)
    t = np.array([0.5, 1.2, -0.7])
    pose = _pose_from(R, t)
    h, w, d = 4, 4, 2.0
    depth = np.full((h, w), d)
    intr = FakeIntrinsics(fx=100.0, fy=100.0, cx=1.5, cy=1.5)
    cam_pts = unproject_depth(depth, intr)
    world = camera_to_world(cam_pts, pose)
    expected = cam_pts @ R.T + t
    assert np.allclose(world, expected, atol=1e-9)


# -----------------------------------------------------------------------------
# resize_mask_to
# -----------------------------------------------------------------------------

def test_resize_mask_downscale_quadrants():
    """A 4x4 mask with the top-left 2x2 set, downscaled to 2x2, keeps
    exactly the top-left cell."""
    mask = np.zeros((4, 4), dtype=bool)
    mask[:2, :2] = True
    out = resize_mask_to(mask, (2, 2))
    assert out.shape == (2, 2)
    assert out[0, 0] and not out[0, 1] and not out[1, 0] and not out[1, 1]


def test_resize_mask_identity():
    mask = np.random.default_rng(7).random((6, 9)) > 0.5
    assert np.array_equal(resize_mask_to(mask, (9, 6)), mask)


def test_resize_mask_upscale_repeats():
    mask = np.array([[True, False]])
    out = resize_mask_to(mask, (4, 2))
    assert out.shape == (2, 4)
    assert np.array_equal(out, np.array([[True, True, False, False]] * 2))


# -----------------------------------------------------------------------------
# robust_cloud_stats
# -----------------------------------------------------------------------------

def test_robust_stats_axis_aligned_box():
    """Near-uniform grid filling a 2 x 1 x 0.5 box: center at the box
    center, principal extents ≈ box dims in descending order (the radial
    clip shaves the outermost samples, so compare with slack). Tiny jitter
    breaks the exact radius ties of a perfect grid, which would otherwise
    make the percentile threshold split a symmetric shell."""
    xs = np.linspace(-1.0, 1.0, 12)
    ys = np.linspace(-0.5, 0.5, 8)
    zs = np.linspace(-0.25, 0.25, 6)
    g = np.stack(np.meshgrid(xs, ys, zs, indexing="ij"), axis=-1).reshape(-1, 3)
    g = g + np.random.default_rng(23).normal(size=g.shape) * 1e-4
    g = g + np.array([10.0, 20.0, 30.0])
    stats = robust_cloud_stats(g)
    assert np.allclose(stats.center, [10.0, 20.0, 30.0], atol=0.02)
    assert stats.extents[0] >= stats.extents[1] >= stats.extents[2]
    assert abs(stats.extents[0] - 2.0) < 0.4
    assert abs(stats.extents[1] - 1.0) < 0.2
    assert abs(stats.extents[2] - 0.5) < 0.1
    assert abs(stats.axes[:, 0] @ np.array([1.0, 0, 0])) > 0.999
    assert np.linalg.det(stats.axes) > 0


def test_robust_stats_extents_rotation_invariant():
    """The same cloud observed under a rotation yields the same principal
    extents — the property fit_scale_translation's scale ratio relies on."""
    rng = np.random.default_rng(3)
    cloud = rng.normal(size=(500, 3)) * np.array([1.0, 0.4, 0.1])
    R = _rotmat([1, 1, 0], 40)
    stats_a = robust_cloud_stats(cloud)
    stats_b = robust_cloud_stats(cloud @ R.T)
    assert np.allclose(stats_a.extents, stats_b.extents, rtol=1e-6)


def test_robust_stats_clips_outliers():
    """A single 100m outlier must not drag the center or extents."""
    cloud = np.random.default_rng(5).normal(size=(200, 3)) * 0.1
    spiked = np.vstack([cloud, [[100.0, 100.0, 100.0]]])
    stats = robust_cloud_stats(spiked)
    assert np.linalg.norm(stats.center) < 0.5
    assert stats.extents[0] < 2.0


def test_robust_stats_too_few_points_raises():
    with pytest.raises(DegenerateGeometryError):
        robust_cloud_stats(np.zeros((MIN_CLOUD_POINTS - 1, 3)))


# -----------------------------------------------------------------------------
# fit_similarity (Umeyama)
# -----------------------------------------------------------------------------

def test_umeyama_recovers_known_transform():
    rng = np.random.default_rng(11)
    src = rng.normal(size=(50, 3))
    R = _rotmat([2, -1, 3], 55)
    s_true, t_true = 2.3, np.array([0.4, -1.1, 5.0])
    dst = s_true * src @ R.T + t_true
    s, R_fit, t = fit_similarity(src, dst)
    assert abs(s - s_true) < 1e-9
    assert np.allclose(R_fit, R, atol=1e-9)
    assert np.allclose(t, t_true, atol=1e-9)


def test_umeyama_never_returns_reflection():
    """Mirrored correspondences must still yield det(R) = +1."""
    rng = np.random.default_rng(13)
    src = rng.normal(size=(40, 3))
    dst = src * np.array([-1.0, 1.0, 1.0])  # reflection, not a rotation
    _, R_fit, _ = fit_similarity(src, dst)
    assert np.linalg.det(R_fit) > 0.99


def test_umeyama_degenerate_raises():
    with pytest.raises(DegenerateGeometryError):
        fit_similarity(np.zeros((2, 3)), np.zeros((2, 3)))
    with pytest.raises(DegenerateGeometryError):
        fit_similarity(np.zeros((10, 3)), np.ones((10, 3)))  # zero variance


# -----------------------------------------------------------------------------
# fit_scale_translation
# -----------------------------------------------------------------------------

def test_fit_scale_translation_recovers_known_transform():
    """Unit-normalized 'splat' cloud vs its scaled/rotated/translated world
    copy, rotation supplied: recover s and t."""
    rng = np.random.default_rng(17)
    src = rng.normal(size=(300, 3)) * np.array([0.5, 0.3, 0.2])
    R = _rotmat([0, 1, 0], 75)
    s_true, t_true = 1.8, np.array([2.0, 0.8, -3.0])
    dst = s_true * src @ R.T + t_true
    s, t = fit_scale_translation(
        robust_cloud_stats(src), robust_cloud_stats(dst), R
    )
    assert abs(s - s_true) < 1e-6
    assert np.allclose(t, t_true, atol=1e-5)


def test_fit_scale_translation_zero_extent_raises():
    pts = np.zeros((30, 3))
    pts[:, 0] = np.linspace(0, 1, 30)  # 1D cloud: two zero extents survive
    degenerate = np.zeros((30, 3))
    with pytest.raises(DegenerateGeometryError):
        fit_scale_translation(
            robust_cloud_stats(degenerate + np.random.default_rng(1).normal(size=(30, 3)) * 0),
            robust_cloud_stats(pts + np.random.default_rng(2).normal(size=(30, 3)) * 1e-3),
            np.eye(3),
        )


# -----------------------------------------------------------------------------
# refine_similarity_nn — the partial-view evaluation
# -----------------------------------------------------------------------------

def _ellipsoid_surface(n=1500, radii=(0.5, 0.35, 0.25), seed=29):
    """Deterministic points on an ellipsoid surface (the 'full splat')."""
    rng = np.random.default_rng(seed)
    v = rng.normal(size=(n, 3))
    v /= np.linalg.norm(v, axis=1, keepdims=True)
    return v * np.array(radii)


VIEW_DIR = np.array([1.0, 0.0, 0.0])  # camera at -X looking along +X


def _single_view_fixture(noise=0.0, bleed_fraction=0.0, seed=29):
    """A full 'splat' cloud and the true-visibility depth cloud a single
    camera would see: for a convex surface, exactly the points whose
    outward normal faces the camera. Optionally adds Gaussian depth noise
    and background-bleed outliers (silhouette-rim pixels whose depth
    lands far behind the object — the dominant real-world artifact of
    mask-restricted LiDAR unprojection)."""
    radii = np.array([0.5, 0.35, 0.25])
    src = _ellipsoid_surface(radii=tuple(radii), seed=seed)
    R = _rotmat([0, 1, 0], 35)
    s_true, t_true = 1.6, np.array([1.0, 0.7, -2.0])
    normals_local = src / radii ** 2
    visible = normals_local @ (R.T @ VIEW_DIR) < 0
    dst = (s_true * src @ R.T + t_true)[visible]
    assert 0.4 < visible.mean() < 0.6
    rng = np.random.default_rng(seed + 1)
    if noise > 0.0:
        dst = dst + rng.normal(size=dst.shape) * noise
    if bleed_fraction > 0.0:
        n_out = int(bleed_fraction * dst.shape[0])
        bleed = dst[rng.integers(0, dst.shape[0], n_out)] + VIEW_DIR * rng.uniform(
            1.0, 3.0, (n_out, 1)
        )
        dst = np.vstack([dst, bleed])
    return src, dst, s_true, R, t_true


def test_generic_fit_is_biased_on_single_view_clouds():
    """Documents WHY fit_single_view exists: the correspondence-free PCA
    fit, correct for full-coverage clouds, is structurally biased on a
    single-view visibility cut (front-surface centroid + reordered
    principal extents). If this ever starts passing with a tight bound,
    the single-view path can be simplified away."""
    src, dst, s_true, R_true, t_true = _single_view_fixture()
    s0, t0 = fit_scale_translation(
        robust_cloud_stats(src), robust_cloud_stats(dst), R_true
    )
    assert np.linalg.norm(t0 - t_true) > 0.1


def test_fit_single_view_recovers_transform():
    """Tolerances are pinned near the achieved accuracy (measured
    s_err ≈ 0.0017 on s=1.6, t_err ≈ 0.030 m with this deterministic
    fixture) so an accuracy regression fails the suite rather than hiding
    under a slack bound."""
    from roomstudio_schemas.placement_math import fit_single_view

    src, dst, s_true, R_true, t_true = _single_view_fixture()
    s, t = fit_single_view(src, dst, R_true, VIEW_DIR)
    assert abs(s - s_true) < 0.003
    assert np.linalg.norm(t - t_true) < 0.035


def test_fit_single_view_robust_to_noise_and_bleed():
    """5mm depth noise + 3% background-bleed outliers must not break the
    fit — the percentile bands exist precisely to absorb these. Bounds
    pinned near achieved accuracy (s_err ≈ 0.0033, t_err ≈ 0.029 m,
    deterministic seeds) for the same regression-guard reason as above."""
    from roomstudio_schemas.placement_math import fit_single_view

    src, dst, s_true, R_true, t_true = _single_view_fixture(
        noise=0.005, bleed_fraction=0.03
    )
    s, t = fit_single_view(src, dst, R_true, VIEW_DIR)
    assert abs(s - s_true) < 0.006
    assert np.linalg.norm(t - t_true) < 0.035


def test_fit_single_view_too_few_points_raises():
    from roomstudio_schemas.placement_math import fit_single_view

    src, dst, _, R_true, _ = _single_view_fixture()
    with pytest.raises(DegenerateGeometryError):
        fit_single_view(src[:5], dst, R_true, VIEW_DIR)
    with pytest.raises(DegenerateGeometryError):
        fit_single_view(src, dst[:5], R_true, VIEW_DIR)


def test_nn_translation_polish_improves_view_aware_fit():
    """The refinement evaluation's surviving use: from a good view-aware
    init, one translation-only NN pass tightens translation and must not
    touch scale/rotation. (Full-mode refits from a poor init were found to
    converge to shell-sliding local minima — see the placement decision
    note — so full mode is not wired into the pipeline.)"""
    from roomstudio_schemas.placement_math import fit_single_view, refine_similarity_nn

    src, dst, s_true, R_true, t_true = _single_view_fixture()
    s0, t0 = fit_single_view(src, dst, R_true, VIEW_DIR)
    err_before = np.linalg.norm(t0 - t_true)
    s, R, t, rms = refine_similarity_nn(src, dst, s0, R_true, t0, mode="translation")
    assert s == pytest.approx(s0)
    assert np.array_equal(R, R_true)
    assert np.linalg.norm(t - t_true) < err_before
    assert rms < 0.05


def test_nn_refinement_too_few_points_raises():
    from roomstudio_schemas.placement_math import refine_similarity_nn

    with pytest.raises(DegenerateGeometryError):
        refine_similarity_nn(
            np.zeros((2, 3)), np.zeros((5, 3)), 1.0, np.eye(3), np.zeros(3)
        )


# -----------------------------------------------------------------------------
# ray_through_pixel + triangulate_rays
# -----------------------------------------------------------------------------

def test_ray_through_principal_point_is_forward():
    """The ray through (cx, cy) is the camera's forward axis (-Z lifted to
    world)."""
    R = _rotmat([0, 1, 0], 90)
    pose = _pose_from(R, [1.0, 2.0, 3.0])
    intr = FakeIntrinsics(fx=100.0, fy=100.0, cx=64.0, cy=48.0)
    origin, direction = ray_through_pixel(64.0, 48.0, intr, pose)
    assert np.allclose(origin, [1.0, 2.0, 3.0])
    assert np.allclose(direction, R @ np.array([0.0, 0.0, -1.0]), atol=1e-9)


def test_triangulate_recovers_known_point():
    """Rays from three posed cameras through the pixel where a known world
    point projects must intersect at that point."""
    target = np.array([0.7, 1.1, -2.4])
    intr = FakeIntrinsics(fx=120.0, fy=120.0, cx=32.0, cy=32.0)
    origins, dirs = [], []
    for angle, pos in [(0, [0, 1, 0]), (25, [1.5, 1.0, 0.5]), (-30, [-1.2, 1.3, 0.2])]:
        R = _rotmat([0, 1, 0], angle)
        t = np.array(pos, dtype=float)
        # Project target into this camera to find its pixel.
        p_cam = R.T @ (target - t)
        assert p_cam[2] < 0, "target must be in front of the synthetic camera"
        d = -p_cam[2]
        u = p_cam[0] * intr.fx / d + intr.cx
        v = -(p_cam[1] * intr.fy / d) + intr.cy
        o, direction = ray_through_pixel(u, v, intr, _pose_from(R, t))
        origins.append(o)
        dirs.append(direction)
    point, rms = triangulate_rays(np.array(origins), np.array(dirs))
    assert np.allclose(point, target, atol=1e-9)
    assert rms < 1e-9


def test_triangulate_parallel_rays_raises():
    """A camera translating along its own viewing axis produces parallel
    rays — no baseline, no depth. Must refuse, not guess."""
    origins = np.array([[0.0, 0.0, 0.0], [0.0, 0.0, -1.0]])
    dirs = np.array([[0.0, 0.0, -1.0], [0.0, 0.0, -1.0]])
    with pytest.raises(DegenerateGeometryError):
        triangulate_rays(origins, dirs)


def test_triangulate_single_ray_raises():
    with pytest.raises(DegenerateGeometryError):
        triangulate_rays(np.zeros((1, 3)), np.array([[0.0, 0.0, -1.0]]))


# -----------------------------------------------------------------------------
# project_points (decision 0067)
# -----------------------------------------------------------------------------

def test_project_points_round_trips_through_unproject_and_camera_to_world():
    intr = FakeIntrinsics(fx=500.0, fy=500.0, cx=320.0, cy=240.0)
    pose = _pose_from(_rotmat([0, 1, 0], 20.0), [1.0, 2.0, 3.0])
    depth = np.full((480, 640), np.nan)
    depth[240, 320] = 2.0  # principal point
    depth[100, 500] = 1.5
    cam_pts = unproject_depth(depth, intr)
    world_pts = camera_to_world(cam_pts, pose)
    uv, d, valid = project_points(world_pts, intr, pose)
    assert np.all(valid)
    # unproject_depth walks nonzero() in row-major (v, u) order, so the
    # (v=100, u=500) pixel comes back before (v=240, u=320).
    assert np.allclose(uv, np.array([[500.0, 100.0], [320.0, 240.0]]), atol=1e-6)
    assert np.allclose(d, [1.5, 2.0], atol=1e-6)


def test_project_points_marks_behind_camera_invalid():
    intr = FakeIntrinsics(fx=500.0, fy=500.0, cx=320.0, cy=240.0)
    pose = FakePose()  # identity at origin, looks down -Z
    pts = np.array([[0.0, 0.0, -2.0], [0.0, 0.0, 2.0]])  # in front, behind
    uv, depth, valid = project_points(pts, intr, pose)
    assert list(valid) == [True, False]
    assert depth[0] == pytest.approx(2.0)
    assert np.isfinite(uv).all()  # never NaN/inf, even for the invalid point


# -----------------------------------------------------------------------------
# rotation_about_axis (decision 0067)
# -----------------------------------------------------------------------------

def test_rotation_about_axis_zero_angle_is_identity():
    R = rotation_about_axis([0.0, 1.0, 0.0], 0.0)
    assert np.allclose(R, np.eye(3), atol=1e-12)


def test_rotation_about_axis_is_proper_rotation():
    R = rotation_about_axis([1.0, 2.0, -1.0], 1.1)
    assert np.allclose(R @ R.T, np.eye(3), atol=1e-9)
    assert np.linalg.det(R) == pytest.approx(1.0, abs=1e-9)


def test_rotation_about_axis_90_about_y_matches_hand_rotation():
    R = rotation_about_axis([0.0, 1.0, 0.0], math.pi / 2)
    assert np.allclose(R @ np.array([1.0, 0.0, 0.0]), [0.0, 0.0, -1.0], atol=1e-9)


def test_rotation_about_axis_fixes_the_axis_direction():
    axis = np.array([0.3, 0.7, -0.2])
    R = rotation_about_axis(axis, 1.7)
    axis_unit = axis / np.linalg.norm(axis)
    assert np.allclose(R @ axis_unit, axis_unit, atol=1e-9)


def test_rotation_about_axis_zero_length_raises():
    with pytest.raises(ValueError):
        rotation_about_axis([0.0, 0.0, 0.0], 1.0)


# -----------------------------------------------------------------------------
# mask_containment (decision 0067 — same-frame duplicate-detection test)
# -----------------------------------------------------------------------------

def test_mask_containment_full_nesting_is_one():
    big = np.zeros((20, 20), dtype=bool)
    big[2:18, 2:18] = True
    small = np.zeros((20, 20), dtype=bool)
    small[5:10, 5:10] = True  # fully inside big
    assert mask_containment(big, small) == pytest.approx(1.0)
    assert mask_containment(small, big) == pytest.approx(1.0)  # symmetric


def test_mask_containment_disjoint_is_zero():
    a = np.zeros((10, 10), dtype=bool)
    a[0:4, 0:4] = True
    b = np.zeros((10, 10), dtype=bool)
    b[6:10, 6:10] = True
    assert mask_containment(a, b) == 0.0


def test_mask_containment_partial_overlap():
    a = np.zeros((10, 10), dtype=bool)
    a[0:6, 0:6] = True  # area 36
    b = np.zeros((10, 10), dtype=bool)
    b[3:9, 3:9] = True  # area 36, overlap [3:6,3:6] = 9
    assert mask_containment(a, b) == pytest.approx(9.0 / 36.0)


def test_mask_containment_empty_mask_is_zero():
    a = np.zeros((5, 5), dtype=bool)
    b = np.zeros((5, 5), dtype=bool)
    b[1:3, 1:3] = True
    assert mask_containment(a, b) == 0.0


def test_mask_containment_shape_mismatch_raises():
    with pytest.raises(ValueError):
        mask_containment(np.zeros((5, 5), dtype=bool), np.zeros((4, 4), dtype=bool))


# -----------------------------------------------------------------------------
# footprint_bbox / rasterize_* / soft_iou / soft_containment
# -----------------------------------------------------------------------------

def test_footprint_bbox_covers_mask_and_clips_to_frame():
    mask = np.zeros((100, 200), dtype=bool)
    mask[10:20, 190:200] = True  # touches the right edge
    u0, v0, u1, v1 = footprint_bbox(mask, pad_frac=0.0)
    assert u1 == pytest.approx(200.0)  # clipped, not overshooting the frame
    assert u0 <= 190.0 and v0 <= 10.0 and v1 >= 20.0


def test_footprint_bbox_expands_to_include_points():
    mask = np.zeros((100, 100), dtype=bool)
    mask[40:60, 40:60] = True
    uv = np.array([[5.0, 5.0], [90.0, 90.0]])
    valid = np.array([True, True])
    u0, v0, u1, v1 = footprint_bbox(mask, uv, valid, pad_frac=0.0)
    assert u0 <= 5.0 and v0 <= 5.0 and u1 >= 90.0 and v1 >= 90.0


def test_footprint_bbox_no_evidence_defaults_to_full_frame():
    mask = np.zeros((50, 80), dtype=bool)
    assert footprint_bbox(mask) == (0.0, 0.0, 80.0, 50.0)


def test_rasterize_mask_density_matches_exact_fraction():
    mask = np.zeros((10, 10), dtype=bool)
    mask[:, 5:10] = True  # right half exactly True
    grid = rasterize_mask_density(mask, (0.0, 0.0, 10.0, 10.0), grid_size=2)
    # Left column of cells: 0% true; right column: 100% true.
    assert np.allclose(grid[:, 0], 0.0, atol=1e-9)
    assert np.allclose(grid[:, 1], 1.0, atol=1e-9)


def test_rasterize_point_density_empty_outside_bbox():
    uv = np.array([[500.0, 500.0]])
    valid = np.array([True])
    grid = rasterize_point_density(uv, valid, (0.0, 0.0, 10.0, 10.0), grid_size=4)
    assert np.allclose(grid, 0.0)


def test_rasterize_point_density_places_mass_in_correct_cell():
    uv = np.array([[1.0, 1.0]] * 10)  # dense cluster near origin
    valid = np.ones(10, dtype=bool)
    grid = rasterize_point_density(uv, valid, (0.0, 0.0, 10.0, 10.0), grid_size=5)
    assert grid[0, 0] > 0.0
    assert np.allclose(grid[1:, :], 0.0)
    assert np.allclose(grid[:, 1:], 0.0)


def test_soft_iou_identical_grids_is_one():
    g = np.array([[0.2, 0.8], [1.0, 0.0]])
    assert soft_iou(g, g) == pytest.approx(1.0)


def test_soft_iou_disjoint_grids_is_zero():
    a = np.array([[1.0, 0.0], [0.0, 0.0]])
    b = np.array([[0.0, 0.0], [0.0, 1.0]])
    assert soft_iou(a, b) == 0.0


def test_soft_iou_both_empty_is_zero_not_perfect():
    z = np.zeros((3, 3))
    assert soft_iou(z, z) == 0.0


def test_soft_iou_shape_mismatch_raises():
    with pytest.raises(ValueError):
        soft_iou(np.zeros((2, 2)), np.zeros((3, 3)))


def test_soft_containment_partial_view_scores_high():
    # A cluster's full footprint (large) vs. a candidate frame that only
    # sees a subset of it (still real evidence, not a mismatch).
    full = np.ones((4, 4))
    partial = np.zeros((4, 4))
    partial[0:2, :] = 1.0  # exactly half of `full`, fully contained
    assert soft_containment(full, partial) == pytest.approx(1.0)
    # soft_iou would NOT be 1.0 here -- containment is the more tolerant test.
    assert soft_iou(full, partial) == pytest.approx(0.5)


def test_soft_containment_empty_is_zero():
    a = np.zeros((3, 3))
    b = np.ones((3, 3))
    assert soft_containment(a, b) == 0.0


def test_prepare_mask_evidence_fields():
    mask = np.zeros((8, 12), dtype=bool)
    mask[2:5, 3:9] = True
    ev = prepare_mask(mask)
    assert ev.shape == (8, 12)
    assert ev.area == 3 * 6
    assert ev.bounds == (3.0, 2.0, 8.0, 4.0)
    assert ev.integral[-1, -1] == pytest.approx(18.0)
    empty = prepare_mask(np.zeros((4, 4), dtype=bool))
    assert empty.bounds is None
    assert empty.area == 0


def test_rasterize_mask_density_evidence_matches_raw_mask_path():
    rng = np.random.RandomState(7)
    mask = rng.rand(40, 60) > 0.5
    ev = prepare_mask(mask)
    bbox = (3.7, 2.2, 55.1, 38.9)  # deliberately fractional
    via_mask = rasterize_mask_density(mask, bbox, grid_size=16)
    via_evidence = rasterize_mask_density(ev, bbox, grid_size=16)
    assert np.allclose(via_mask, via_evidence, atol=1e-12)


def test_rasterize_mask_density_fractional_box_is_exact():
    """One True pixel at (u=2..3, v=1..2); a query box covering exactly its
    left half must read 0.5 occupancy — the summed-area table's bilinear
    sampling is exact for axis-aligned boxes, not an approximation."""
    mask = np.zeros((4, 6), dtype=bool)
    mask[1, 2] = True
    grid = rasterize_mask_density(mask, (2.0, 1.0, 2.5, 2.0), grid_size=1)
    assert grid[0, 0] == pytest.approx(1.0)  # box fully inside the pixel
    grid = rasterize_mask_density(mask, (1.5, 1.0, 2.5, 2.0), grid_size=1)
    assert grid[0, 0] == pytest.approx(0.5)  # half the box covers the pixel


def test_union_bbox_matches_footprint_bbox():
    mask = np.zeros((50, 80), dtype=bool)
    mask[10:20, 30:60] = True
    uv = np.array([[5.0, 5.0], [70.0, 45.0]])
    valid = np.array([True, True])
    ev = prepare_mask(mask)
    assert union_bbox(mask.shape, ev.bounds, uv, valid) == footprint_bbox(mask, uv, valid)
