"""Shell texture baking: project the capture's own RGB onto each shell
plane (decision 0066).

For every plane from shell_geometry, an orthographic texel grid
(~SHELL_METERS_PER_TEXEL m/texel, long edge capped at
SHELL_TEXTURE_MAX_PX) is sampled from the scene's COMPLETE frames only —
the frames whose SAM 3 masks are cached — with pixels under any object
mask excluded, so furniture never bakes into the room's surfaces (bounded
by the prompt vocabulary; accepted v1 residue per 0066). Samples are
incidence/distance-weighted and blended by weighted median (per-texel:
the sample at the weighted median of luminance contributes its full RGB —
robust to transient bake-in, no channel mixing). Texels no frame observed
are holes: filled by the injected texture-continuation inpaint_fn and
accounted in inpainted_fraction. A plane observed below
SHELL_MIN_OBSERVED_FRACTION ships untextured (source "unobserved") — a
neutral client-side treatment beats texturing from nothing.

The floor's SHAPE (member-polygon union, clipped at walls) is carried in
the PNG's alpha channel so the client renders only quads; wall textures
are fully opaque.

Camera model: exact inverse of placement_math.unproject_depth — ARKit
camera looks down -Z, u = cx + fx*x/(-z), v = cy - fy*y/(-z). World→camera
uses the Pose contract (world_from_camera) inverted.

Texture orientation contract: texel (row j, col i) sits at
origin + (i+0.5)*step_u*axis_u + (j+0.5)*step_v*axis_v; the PNG is
written with row 0 at MAX axis_v (standard image top), so a client
mapping corner0→uv(0,0), corner1→(1,0), corner2→(1,1), corner3→(0,1)
with bottom-origin UV (three.js flipY default) samples correctly.

Pure numpy/PIL; no GCS, no torch. The inpaint model lives behind the
injected callable (shell_inpaint.inpaint in production, fakes in tests).

Consumers: shell_receiver.py, tests/test_shell_texture.py.
"""
from __future__ import annotations

import io
import os
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from room_planes import ShellPlaneGeom
from roomstudio_schemas.pose_math import pose_position, pose_quat, quat_to_rotmat

# ---------------------------------------------------------------------------
# Tunables (env-overridable)
# ---------------------------------------------------------------------------

SHELL_METERS_PER_TEXEL = float(os.environ.get("SHELL_METERS_PER_TEXEL", "0.02"))
SHELL_TEXTURE_MAX_PX = int(os.environ.get("SHELL_TEXTURE_MAX_PX", "2048"))
SHELL_MIN_OBSERVED_FRACTION = float(
    os.environ.get("SHELL_MIN_OBSERVED_FRACTION", "0.2")
)

# Sampling gates: reject grazing incidence (unstable projection) and
# implausibly close cameras; weight = cos_incidence / distance².
_MIN_COS_INCIDENCE = 0.2
_MIN_CAMERA_DISTANCE_M = 0.15
# Texel rows processed per band — bounds peak memory at
# frames × band × width samples regardless of plane size.
_BAND_ROWS = 256

InpaintFn = Callable[[np.ndarray, np.ndarray], np.ndarray]


# ---------------------------------------------------------------------------
# Inputs / outputs
# ---------------------------------------------------------------------------

@dataclass
class FrameSample:
    """One complete frame's bake inputs.

    exclusion_mask is the union of the frame's SAM 3 object masks at RGB
    resolution (True = never sample here). pose/intrinsics are the frame's
    proto messages from the bundle.
    """

    frame_index: int
    rgb: np.ndarray  # (H, W, 3) uint8
    exclusion_mask: np.ndarray  # (H, W) bool
    pose: object  # roomstudio_schemas.Pose (world_from_camera)
    intrinsics: object  # roomstudio_schemas.Intrinsics


@dataclass
class BakeResult:
    png_bytes: bytes | None  # None when source == "unobserved"
    source: str  # "baked" | "unobserved"
    observed_fraction: float
    inpainted_fraction: float
    texture_px: tuple[int, int]  # (width, height) of the texel grid


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def _texel_grid(geom: ShellPlaneGeom) -> tuple[int, int, float, float]:
    """(width_px, height_px, step_u_m, step_v_m) for the plane's grid,
    at SHELL_METERS_PER_TEXEL capped so the long edge <= max px."""
    mpt = SHELL_METERS_PER_TEXEL
    long_edge_m = max(geom.width_m, geom.height_m)
    if long_edge_m / mpt > SHELL_TEXTURE_MAX_PX:
        mpt = long_edge_m / SHELL_TEXTURE_MAX_PX
    w = max(1, int(np.ceil(geom.width_m / mpt)))
    h = max(1, int(np.ceil(geom.height_m / mpt)))
    return w, h, geom.width_m / w, geom.height_m / h


def _points_in_polygon_xz(px: np.ndarray, pz: np.ndarray, polygon: np.ndarray) -> np.ndarray:
    """Vectorized even-odd (ray casting) point-in-polygon test on the world
    XZ plane. polygon is (N, 3); px/pz are flat arrays of equal length."""
    x0 = polygon[:, 0]
    z0 = polygon[:, 2]
    x1 = np.roll(x0, -1)
    z1 = np.roll(z0, -1)
    inside = np.zeros(px.shape, dtype=bool)
    for i in range(len(x0)):
        crosses = (z0[i] > pz) != (z1[i] > pz)
        if not np.any(crosses):
            continue
        t = (pz - z0[i]) / (z1[i] - z0[i])
        x_at = x0[i] + t * (x1[i] - x0[i])
        inside ^= crosses & (px < x_at)
    return inside


def _floor_shape_mask(
    points_world: np.ndarray,
    member_polygons: list[np.ndarray],
    wall_planes: list[tuple[np.ndarray, np.ndarray]],
) -> np.ndarray:
    """In-shape mask for floor texels: inside the union of member polygons,
    and not beyond any wall (walls' front normals point into the room; a
    small tolerance keeps the floor meeting the wall line)."""
    px, pz = points_world[:, 0], points_world[:, 2]
    inside = np.zeros(len(points_world), dtype=bool)
    for poly in member_polygons:
        inside |= _points_in_polygon_xz(px, pz, poly)
    for normal, point in wall_planes:
        inside &= (points_world - point) @ normal >= -0.02
    return inside


# ---------------------------------------------------------------------------
# Frame sampling
# ---------------------------------------------------------------------------

def _sample_frame(
    points_world: np.ndarray,
    plane_normal: np.ndarray,
    frame: FrameSample,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Project texel centers into one frame.

    Returns (colors (N, 3) float32, weights (N,) float32, luminance (N,)
    float32); weight 0 marks an invalid sample (behind camera, outside the
    image, masked, grazing, or viewing the plane's back face).
    """
    n_pts = len(points_world)
    colors = np.zeros((n_pts, 3), dtype=np.float32)
    weights = np.zeros(n_pts, dtype=np.float32)

    R = quat_to_rotmat(pose_quat(frame.pose))
    cam_pos = pose_position(frame.pose)
    # world -> camera: R.T @ (p - t), vectorized.
    p_cam = (points_world - cam_pos) @ R
    d = -p_cam[:, 2]  # depth along the view axis; camera looks down -Z
    valid = d > _MIN_CAMERA_DISTANCE_M

    # Front-face check: the camera must be on the side the normal fronts
    # (interior). Grazing check via incidence cosine.
    to_cam = cam_pos - points_world
    dist = np.linalg.norm(to_cam, axis=1)
    valid &= dist > _MIN_CAMERA_DISTANCE_M
    cos_inc = np.zeros(n_pts)
    nz = dist > 1e-9
    cos_inc[nz] = (to_cam[nz] @ plane_normal) / dist[nz]
    valid &= cos_inc > _MIN_COS_INCIDENCE

    if not np.any(valid):
        return colors, weights, np.zeros(n_pts, dtype=np.float32)

    intr = frame.intrinsics
    u = np.zeros(n_pts)
    v = np.zeros(n_pts)
    u[valid] = intr.cx + intr.fx * p_cam[valid, 0] / d[valid]
    v[valid] = intr.cy - intr.fy * p_cam[valid, 1] / d[valid]

    img_h, img_w = frame.rgb.shape[:2]
    # Bilinear neighborhood must be fully inside the image.
    valid &= (u >= 0) & (u <= img_w - 1.001) & (v >= 0) & (v <= img_h - 1.001)
    if not np.any(valid):
        return colors, weights, np.zeros(n_pts, dtype=np.float32)

    ui = np.floor(u[valid]).astype(np.int64)
    vi = np.floor(v[valid]).astype(np.int64)
    fu = (u[valid] - ui).astype(np.float32)
    fv = (v[valid] - vi).astype(np.float32)

    # Exclusion: conservative — any of the 4 bilinear neighbors under a SAM
    # mask disqualifies the sample (no furniture bleed at mask edges).
    m = frame.exclusion_mask
    excluded = m[vi, ui] | m[vi, ui + 1] | m[vi + 1, ui] | m[vi + 1, ui + 1]
    keep = ~excluded

    idx = np.nonzero(valid)[0][keep]
    ui, vi, fu, fv = ui[keep], vi[keep], fu[keep], fv[keep]

    img = frame.rgb.astype(np.float32)
    c00 = img[vi, ui]
    c01 = img[vi, ui + 1]
    c10 = img[vi + 1, ui]
    c11 = img[vi + 1, ui + 1]
    w00 = ((1 - fu) * (1 - fv))[:, None]
    w01 = (fu * (1 - fv))[:, None]
    w10 = ((1 - fu) * fv)[:, None]
    w11 = (fu * fv)[:, None]
    colors[idx] = c00 * w00 + c01 * w01 + c10 * w10 + c11 * w11
    weights[idx] = (cos_inc[idx] / np.maximum(dist[idx], 0.5) ** 2).astype(np.float32)

    lum = (
        0.2126 * colors[:, 0] + 0.7152 * colors[:, 1] + 0.0722 * colors[:, 2]
    ).astype(np.float32)
    return colors, weights, lum


def _weighted_median_select(
    colors: np.ndarray, weights: np.ndarray, lums: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Per texel: pick the sample at the weighted median of luminance.

    colors (F, N, 3), weights (F, N) with 0 = invalid, lums (F, N).
    Returns (selected colors (N, 3) float32, observed (N,) bool).
    Deterministic: ties resolve to the lowest-luminance qualifying sample
    via the strict cumulative-weight threshold.
    """
    total = weights.sum(axis=0)
    observed = total > 0

    # Sort samples per texel by luminance (invalid samples pushed last by
    # +inf), then take the first whose cumulative weight reaches half.
    lum_sort = np.where(weights > 0, lums, np.inf)
    order = np.argsort(lum_sort, axis=0, kind="stable")
    w_sorted = np.take_along_axis(weights, order, axis=0)
    cum = np.cumsum(w_sorted, axis=0)
    reach = cum >= (total[None, :] / 2.0)
    # First True along F; argmax finds it (all-False only where unobserved).
    pick_sorted = np.argmax(reach, axis=0)
    pick = np.take_along_axis(order, pick_sorted[None, :], axis=0)[0]

    selected = colors[pick, np.arange(colors.shape[1])]
    selected[~observed] = 0.0
    return selected.astype(np.float32), observed


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def bake_plane_texture(
    geom: ShellPlaneGeom,
    frames: list[FrameSample],
    *,
    inpaint_fn: InpaintFn,
    floor_member_polygons: list[np.ndarray] | None = None,
    wall_planes: list[tuple[np.ndarray, np.ndarray]] | None = None,
    min_observed_fraction: float | None = None,
) -> BakeResult:
    """Bake one plane's RGBA texture from the complete frames.

    floor_member_polygons + wall_planes shape the floor's alpha (ignored
    for walls, which are fully opaque). wall_planes entries are
    (front_normal, point_on_plane) in world frame. Deterministic for
    identical inputs: frames are processed in the given order, all
    reductions are order-stable.
    """
    min_obs = (
        SHELL_MIN_OBSERVED_FRACTION
        if min_observed_fraction is None
        else min_observed_fraction
    )
    w_px, h_px, step_u, step_v = _texel_grid(geom)

    rgb_img = np.zeros((h_px, w_px, 3), dtype=np.float32)
    observed = np.zeros((h_px, w_px), dtype=bool)
    in_shape = np.ones((h_px, w_px), dtype=bool)

    frames = sorted(frames, key=lambda f: f.frame_index)

    for row0 in range(0, h_px, _BAND_ROWS):
        rows = np.arange(row0, min(row0 + _BAND_ROWS, h_px))
        cols = np.arange(w_px)
        jj, ii = np.meshgrid(rows, cols, indexing="ij")
        pts = (
            geom.origin[None, :]
            + (ii.ravel()[:, None] + 0.5) * step_u * geom.axis_u[None, :]
            + (jj.ravel()[:, None] + 0.5) * step_v * geom.axis_v[None, :]
        )

        if geom.kind == "floor" and floor_member_polygons:
            band_shape = _floor_shape_mask(
                pts, floor_member_polygons, wall_planes or []
            )
            in_shape[rows[0]: rows[-1] + 1, :] = band_shape.reshape(len(rows), w_px)

        if not frames:
            continue  # zero frames: everything stays unobserved

        band_colors = np.zeros((len(frames), len(pts), 3), dtype=np.float32)
        band_weights = np.zeros((len(frames), len(pts)), dtype=np.float32)
        band_lums = np.zeros((len(frames), len(pts)), dtype=np.float32)
        for fi, frame in enumerate(frames):
            band_colors[fi], band_weights[fi], band_lums[fi] = _sample_frame(
                pts, geom.normal, frame
            )

        sel, obs = _weighted_median_select(band_colors, band_weights, band_lums)
        rgb_img[rows[0]: rows[-1] + 1, :] = sel.reshape(len(rows), w_px, 3)
        observed[rows[0]: rows[-1] + 1, :] = obs.reshape(len(rows), w_px)

    in_count = int(in_shape.sum())
    if in_count == 0:
        return BakeResult(
            png_bytes=None,
            source="unobserved",
            observed_fraction=0.0,
            inpainted_fraction=0.0,
            texture_px=(w_px, h_px),
        )

    observed_in = observed & in_shape
    observed_fraction = float(observed_in.sum()) / in_count

    if observed_fraction < min_obs:
        return BakeResult(
            png_bytes=None,
            source="unobserved",
            observed_fraction=round(observed_fraction, 4),
            inpainted_fraction=0.0,
            texture_px=(w_px, h_px),
        )

    holes = in_shape & ~observed
    inpainted_fraction = float(holes.sum()) / in_count
    img_u8 = np.clip(np.round(rgb_img), 0, 255).astype(np.uint8)
    if np.any(holes):
        img_u8 = inpaint_fn(img_u8, holes)

    alpha = np.where(in_shape, 255, 0).astype(np.uint8)
    rgba = np.dstack([img_u8, alpha])
    # PNG row 0 = far edge of +V (image top); see the orientation contract.
    rgba = np.flipud(rgba)

    from PIL import Image  # deferred: keep module import light

    buf = io.BytesIO()
    Image.fromarray(rgba, mode="RGBA").save(buf, format="PNG")
    return BakeResult(
        png_bytes=buf.getvalue(),
        source="baked",
        observed_fraction=round(observed_fraction, 4),
        inpainted_fraction=round(inpainted_fraction, 4),
        texture_px=(w_px, h_px),
    )
