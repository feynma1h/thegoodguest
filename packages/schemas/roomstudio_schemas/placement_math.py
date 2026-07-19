"""Geometry for placing per-object reconstructions into the ARKit world frame.

The perception pipeline receives each object from SAM 3D as an
origin-centered, unit-normalized Gaussian splat in its own local frame.
This module holds the pure math that anchors those objects into the room:
back-projecting LiDAR depth through the frame's intrinsics and camera pose
into world-space point clouds, fitting similarity transforms (rotation +
translation + scale) between clouds, and triangulating object centers from
posed camera rays when no depth exists (ARKIT_ONLY tier).

Everything here is pure numpy over the proto contract's conventions — no
GCS, no models, no service imports — so the schemas test suite can pin the
math against hand-computed ground truth.

Frame conventions (see capture_bundle.proto's header):
  - World: ARKit-native, right-handed, +Y up, meters.
  - Camera-local: +X right, +Y up, camera looks down -Z.
  - Image: origin top-left, u right, v down. So for a pixel (u, v) at
    z-depth d (meters along the viewing axis, ARKit sceneDepth semantics),
    the camera-local point is
        ( (u - cx) * d / fx,  -(v - cy) * d / fy,  -d )
    — the v/Y sign flips because image v grows down while camera Y grows
    up, and Z is negative because the camera looks down -Z.

Quaternion operations come from pose_math (the single Python home for
quaternion math); this module never reimplements them.

Consumers: services/perception-obj/placement.py (the placement
orchestrator) and the schemas test suite.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np

from roomstudio_schemas.pose_math import pose_position, pose_quat, quat_to_rotmat

# Below this many points a cloud is too sparse for a trustworthy fit; the
# caller should mark the object unplaced rather than fit garbage.
MIN_CLOUD_POINTS = 20


class DegenerateGeometryError(ValueError):
    """Raised when the input geometry cannot support a meaningful result
    (too few points, near-parallel rays, zero-extent clouds). Callers are
    expected to catch this and record the object as unplaced — it must
    never be silently converted into a guessed transform."""


# -----------------------------------------------------------------------------
# Depth back-projection
# -----------------------------------------------------------------------------

def unproject_depth(
    depth: np.ndarray,
    intrinsics,
    mask: Optional[np.ndarray] = None,
    confidence: Optional[np.ndarray] = None,
    min_confidence: int = 1,
) -> np.ndarray:
    """Back-project a depth raster into camera-local 3D points.

    depth: (H, W) float raster, z-depth in meters along the viewing axis,
        NaN (or <= 0) for invalid pixels — the proto Depth contract.
    intrinsics: object with fx/fy/cx/cy attributes AT THE DEPTH RASTER'S
        resolution (Depth.intrinsics in the bundle, not the RGB frame's).
    mask: optional (H, W) bool — keep only these pixels (an object's
        segmentation mask resized to depth resolution).
    confidence: optional (H, W) uint8, ARKit ARConfidenceLevel semantics
        (0=low, 1=medium, 2=high); pixels below min_confidence are dropped.

    Returns (N, 3) float64 camera-local points (see module header for the
    sign conventions). N may be zero; callers gate on MIN_CLOUD_POINTS.
    """
    if depth.ndim != 2:
        raise ValueError(f"unproject_depth: expected (H, W) depth, got {depth.shape}")
    h, w = depth.shape
    keep = np.isfinite(depth) & (depth > 0.0)
    if mask is not None:
        if mask.shape != depth.shape:
            raise ValueError(
                f"unproject_depth: mask shape {mask.shape} != depth shape {depth.shape}"
            )
        keep &= mask.astype(bool)
    if confidence is not None:
        if confidence.shape != depth.shape:
            raise ValueError(
                f"unproject_depth: confidence shape {confidence.shape} != depth shape {depth.shape}"
            )
        keep &= confidence >= min_confidence

    vs, us = np.nonzero(keep)
    d = depth[vs, us].astype(np.float64)
    x = (us.astype(np.float64) - intrinsics.cx) * d / intrinsics.fx
    y = -(vs.astype(np.float64) - intrinsics.cy) * d / intrinsics.fy
    z = -d
    return np.column_stack([x, y, z])


def camera_to_world(points: np.ndarray, pose) -> np.ndarray:
    """Transform (N, 3) camera-local points into world coordinates.

    pose: a Pose message (world_from_camera, per the proto contract).
    Vectorized form of p_world = position + rotate(quat, p_cam).
    """
    pts = np.asarray(points, dtype=np.float64)
    if pts.ndim != 2 or pts.shape[1] != 3:
        raise ValueError(f"camera_to_world: expected (N, 3), got {pts.shape}")
    R = quat_to_rotmat(pose_quat(pose))
    return pts @ R.T + pose_position(pose)


def resize_mask_to(mask: np.ndarray, size_wh: Tuple[int, int]) -> np.ndarray:
    """Nearest-neighbor resize of a (H, W) bool mask to (height, width) =
    (size_wh[1], size_wh[0]).

    Used to bring an RGB-resolution segmentation mask down to the depth
    raster's resolution (e.g. 1920x1440 -> 256x192). Pure numpy index
    mapping — samples the source pixel whose center is nearest, which for
    integer downscale factors is the standard nearest-neighbor result.
    """
    if mask.ndim != 2:
        raise ValueError(f"resize_mask_to: expected (H, W) mask, got {mask.shape}")
    dst_w, dst_h = size_wh
    if dst_w <= 0 or dst_h <= 0:
        raise ValueError(f"resize_mask_to: invalid target size {size_wh}")
    src_h, src_w = mask.shape
    rows = np.minimum(((np.arange(dst_h) + 0.5) * src_h / dst_h).astype(int), src_h - 1)
    cols = np.minimum(((np.arange(dst_w) + 0.5) * src_w / dst_w).astype(int), src_w - 1)
    return mask.astype(bool)[np.ix_(rows, cols)]


# -----------------------------------------------------------------------------
# Robust cloud statistics
# -----------------------------------------------------------------------------

@dataclass(frozen=True)
class CloudStats:
    """Robust summary of a 3D point cloud.

    center:  (3,) mean of percentile-inlier points.
    extents: (3,) full extent (max - min) of inliers along each principal
             axis, ordered to match `axes` columns (descending variance).
    axes:    (3, 3) right-handed principal axes as columns, descending
             variance order.
    inlier_count: points surviving the percentile clip.
    """
    center: np.ndarray
    extents: np.ndarray
    axes: np.ndarray
    inlier_count: int


def robust_cloud_stats(
    points: np.ndarray,
    clip_percentile: float = 95.0,
) -> CloudStats:
    """Radially-clipped center + principal-axis extents of a point cloud.

    Discards the points farthest from the cloud mean (radius above the
    clip_percentile), then computes mean center, PCA axes, and extents on
    the inliers. The radial clip suppresses mask-bleed outliers (background
    pixels caught at object silhouettes) that would otherwise stretch the
    extents.

    The clip is radial rather than per-axis deliberately: distances from
    the mean are invariant under rotation of the cloud, so the same
    physical object yields the same inlier set — and therefore identical
    (sorted) principal extents — regardless of the frame it was observed
    in. A per-axis percentile clip does not have this property, and
    fit_scale_translation's extent-ratio scale would inherit the
    orientation-dependent bias.

    Raises DegenerateGeometryError below MIN_CLOUD_POINTS input points or
    if clipping leaves fewer than 4 inliers.
    """
    pts = np.asarray(points, dtype=np.float64)
    if pts.ndim != 2 or pts.shape[1] != 3:
        raise ValueError(f"robust_cloud_stats: expected (N, 3), got {pts.shape}")
    if pts.shape[0] < MIN_CLOUD_POINTS:
        raise DegenerateGeometryError(
            f"robust_cloud_stats: {pts.shape[0]} points < MIN_CLOUD_POINTS={MIN_CLOUD_POINTS}"
        )
    radii = np.linalg.norm(pts - pts.mean(axis=0), axis=1)
    inliers = pts[radii <= np.percentile(radii, clip_percentile)]
    if inliers.shape[0] < 4:
        raise DegenerateGeometryError(
            f"robust_cloud_stats: only {inliers.shape[0]} inliers after percentile clip"
        )
    center = inliers.mean(axis=0)
    centered = inliers - center
    cov = centered.T @ centered / inliers.shape[0]
    eigvals, eigvecs = np.linalg.eigh(cov)  # ascending
    order = np.argsort(eigvals)[::-1]
    axes = eigvecs[:, order]
    if np.linalg.det(axes) < 0:
        axes = axes.copy()
        axes[:, 2] = -axes[:, 2]
    proj = centered @ axes
    extents = proj.max(axis=0) - proj.min(axis=0)
    return CloudStats(
        center=center,
        extents=extents,
        axes=axes,
        inlier_count=int(inliers.shape[0]),
    )


# -----------------------------------------------------------------------------
# Similarity fits
# -----------------------------------------------------------------------------

def fit_similarity(
    src_points: np.ndarray, dst_points: np.ndarray
) -> Tuple[float, np.ndarray, np.ndarray]:
    """Closed-form similarity fit (Umeyama 1991) for corresponding points.

    Returns (s, R, t) minimizing sum ||dst_i - (s R src_i + t)||². Requires
    row-wise correspondence between src_points and dst_points (same shape,
    N >= 3). The reflection case is handled with the determinant-sign
    correction, so R is always a proper rotation.

    Raises DegenerateGeometryError for N < 3 or a zero-variance source.
    """
    src = np.asarray(src_points, dtype=np.float64)
    dst = np.asarray(dst_points, dtype=np.float64)
    if src.shape != dst.shape or src.ndim != 2 or src.shape[1] != 3:
        raise ValueError(
            f"fit_similarity: need matching (N, 3) arrays, got {src.shape} vs {dst.shape}"
        )
    n = src.shape[0]
    if n < 3:
        raise DegenerateGeometryError(f"fit_similarity: {n} correspondences < 3")
    mu_src = src.mean(axis=0)
    mu_dst = dst.mean(axis=0)
    src_c = src - mu_src
    dst_c = dst - mu_dst
    var_src = float((src_c ** 2).sum() / n)
    if var_src <= 0.0:
        raise DegenerateGeometryError("fit_similarity: source cloud has zero variance")
    cov = dst_c.T @ src_c / n
    U, D, Vt = np.linalg.svd(cov)
    S = np.eye(3)
    if np.linalg.det(U) * np.linalg.det(Vt) < 0:
        S[2, 2] = -1.0
    R = U @ S @ Vt
    s = float(np.trace(np.diag(D) @ S) / var_src)
    t = mu_dst - s * R @ mu_src
    return s, R, t


def fit_scale_translation(
    src_stats: CloudStats, dst_stats: CloudStats, R_fixed: np.ndarray
) -> Tuple[float, np.ndarray]:
    """Correspondence-free scale + translation with an externally supplied
    rotation.

    Scale is the median ratio of principal-axis extents (both stats carry
    extents in descending-variance order, so the ratio is orientation-
    invariant — largest-to-largest, middle-to-middle, smallest-to-smallest).
    Translation aligns the robust centers under (s, R_fixed).

    Raises DegenerateGeometryError if the source extents are all ~zero.
    """
    eps = 1e-9
    valid = src_stats.extents > eps
    if not np.any(valid):
        raise DegenerateGeometryError(
            "fit_scale_translation: source cloud has no measurable extent"
        )
    ratios = dst_stats.extents[valid] / src_stats.extents[valid]
    s = float(np.median(ratios))
    if s <= 0.0:
        raise DegenerateGeometryError(f"fit_scale_translation: non-positive scale {s}")
    t = dst_stats.center - s * np.asarray(R_fixed, dtype=np.float64) @ src_stats.center
    return s, t


# -----------------------------------------------------------------------------
# Posed camera rays (the no-depth path)
# -----------------------------------------------------------------------------

def ray_through_pixel(
    u: float, v: float, intrinsics, pose
) -> Tuple[np.ndarray, np.ndarray]:
    """World-space ray from a camera through image pixel (u, v).

    intrinsics: fx/fy/cx/cy at the resolution (u, v) is expressed in.
    pose: the frame's camera Pose (world_from_camera).

    Returns (origin, direction): the camera position and a unit direction
    in world coordinates. Camera-local direction is
    ((u-cx)/fx, -(v-cy)/fy, -1) normalized — same sign conventions as
    unproject_depth with d = 1.
    """
    dir_cam = np.array(
        [
            (float(u) - intrinsics.cx) / intrinsics.fx,
            -(float(v) - intrinsics.cy) / intrinsics.fy,
            -1.0,
        ],
        dtype=np.float64,
    )
    dir_cam /= np.linalg.norm(dir_cam)
    R = quat_to_rotmat(pose_quat(pose))
    return pose_position(pose), R @ dir_cam


def triangulate_rays(
    origins: np.ndarray, directions: np.ndarray
) -> Tuple[np.ndarray, float]:
    """Least-squares intersection of >= 2 world-space rays.

    Solves for the point minimizing the sum of squared perpendicular
    distances to all rays: A p = b with A = sum(I - d dᵀ), b = A-weighted
    origins. Directions are renormalized defensively.

    Returns (point, rms_distance) where rms_distance is the root-mean-square
    perpendicular distance from the solution to the rays — the caller's
    triangulation-quality signal.

    Raises DegenerateGeometryError for < 2 rays or near-parallel geometry
    (ill-conditioned A: rays from a stationary or purely-rotating camera
    cannot fix a depth).
    """
    o = np.asarray(origins, dtype=np.float64)
    d = np.asarray(directions, dtype=np.float64)
    if o.ndim != 2 or o.shape[1] != 3 or o.shape != d.shape:
        raise ValueError(
            f"triangulate_rays: need matching (N, 3) arrays, got {o.shape} vs {d.shape}"
        )
    n = o.shape[0]
    if n < 2:
        raise DegenerateGeometryError(f"triangulate_rays: {n} rays < 2")
    d = d / np.linalg.norm(d, axis=1, keepdims=True)
    A = np.zeros((3, 3), dtype=np.float64)
    b = np.zeros(3, dtype=np.float64)
    eye = np.eye(3)
    for i in range(n):
        P = eye - np.outer(d[i], d[i])
        A += P
        b += P @ o[i]
    eigvals = np.linalg.eigvalsh(A)
    # Each (I - d dᵀ) contributes eigenvalues {0, 1, 1}; a well-conditioned
    # bundle of rays keeps min(eig) well above zero. Near-parallel rays
    # collapse it toward zero and the solve would amplify noise into an
    # arbitrary depth along the shared direction.
    if eigvals[0] < 1e-6 * n:
        raise DegenerateGeometryError(
            "triangulate_rays: near-parallel rays (no baseline) — cannot fix depth"
        )
    p = np.linalg.solve(A, b)
    # Perpendicular distance of p to each ray.
    rel = p - o
    along = (rel * d).sum(axis=1)
    perp = rel - along[:, None] * d
    rms = float(np.sqrt((perp ** 2).sum(axis=1).mean()))
    return p, rms
