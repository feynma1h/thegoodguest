"""Shell observation layer: project the capture's own RGB onto each shell
plane and report what was OBSERVED (decision 0069 — the demotion of 0066's
texture bake; the projection/sampling/weighted-median core survives as
inference evidence, the PNG/alpha/inpaint emission is deleted).

For every plane from room_planes/shell_geometry, an orthographic texel
grid (~SHELL_METERS_PER_TEXEL m/texel, long edge capped at
SHELL_OBS_MAX_PX) is sampled from the scene's COMPLETE frames only — the
frames whose SAM 3 masks are cached — with pixels under any object mask
excluded, so furniture never contaminates surface evidence (bounded by
the prompt vocabulary; accepted residue per 0066). Samples are
incidence/distance-weighted; per texel, the sample at the weighted median
of luminance contributes its full RGB (robust to transient bake-in, no
channel mixing).

Outputs per plane (all in-memory; NOTHING is written to GCS):
  - observation stats: observed fraction over the plane's measured region
    (floor: the member-polygon union; walls: the detected quad),
    observed-texel count, frames used;
  - the observed texels' median-selected colors + total weights — the
    albedo evidence shell_material's weighted-median chroma reads;
  - up to SHELL_EVIDENCE_MAX_CROPS rectified evidence crops: the
    highest-total-weight tiles of the plane, each re-sampled at
    SHELL_EVIDENCE_CROP_PX from the single frame that observed that tile
    best (~2.5 mm/px at the defaults — real material texture, not 2 cm
    texels). Residual unobserved crop pixels are filled with the crop's
    median observed color and accounted in fill_fraction; a tile below
    SHELL_EVIDENCE_MIN_OBS observation is never a crop.

Camera model: exact inverse of placement_math.unproject_depth — ARKit
camera looks down -Z, u = cx + fx*x/(-z), v = cy - fy*y/(-z). World→camera
uses the Pose contract (world_from_camera) inverted.

Deterministic for identical inputs: frames sort by frame_index, all
reductions are order-stable, tile ranking breaks ties by tile index.

Pure numpy; no GCS, no PIL, no torch, no model imports.

Consumers: shell_receiver.py (feeds shell_material),
tests/test_shell_observation.py.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

import numpy as np
from room_planes import ShellPlaneGeom
from roomstudio_schemas.pose_math import pose_position, pose_quat, quat_to_rotmat

# ---------------------------------------------------------------------------
# Tunables (env-overridable)
# ---------------------------------------------------------------------------

SHELL_METERS_PER_TEXEL = float(os.environ.get("SHELL_METERS_PER_TEXEL", "0.02"))
SHELL_OBS_MAX_PX = int(os.environ.get("SHELL_OBS_MAX_PX", "2048"))

# Evidence crops: tile edge in meters, output resolution, count cap, and
# the minimum observed fraction for a tile to qualify as evidence.
SHELL_EVIDENCE_CROP_M = float(os.environ.get("SHELL_EVIDENCE_CROP_M", "0.64"))
SHELL_EVIDENCE_CROP_PX = int(os.environ.get("SHELL_EVIDENCE_CROP_PX", "256"))
SHELL_EVIDENCE_MAX_CROPS = int(os.environ.get("SHELL_EVIDENCE_MAX_CROPS", "4"))
SHELL_EVIDENCE_MIN_OBS = float(os.environ.get("SHELL_EVIDENCE_MIN_OBS", "0.8"))

# Sampling gates: reject grazing incidence (unstable projection) and
# implausibly close cameras; weight = cos_incidence / distance².
_MIN_COS_INCIDENCE = 0.2
_MIN_CAMERA_DISTANCE_M = 0.15
# Smallest world-space crop side worth shipping as evidence — slivers
# from plane-edge remainder tiles carry no material signal.
_MIN_CROP_SIDE_M = 0.15
# Texel rows processed per band — bounds peak memory at
# frames × band × width samples regardless of plane size.
_BAND_ROWS = 256


# ---------------------------------------------------------------------------
# Inputs / outputs
# ---------------------------------------------------------------------------

@dataclass
class FrameSample:
    """One complete frame's observation inputs.

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
class EvidenceCrop:
    """One rectified evidence crop: a single frame's RGB re-sampled on a
    fine grid over one plane tile, in the plane's measured UV frame."""

    rgb: np.ndarray  # (P, P, 3) uint8
    frame_index: int
    u0: float  # meters in the plane frame (origin = measured corner 0)
    v0: float
    u1: float
    v1: float
    observed_fraction: float  # crop pixels sampled from the frame
    fill_fraction: float  # residual pixels filled with the median color


@dataclass
class ObservationResult:
    """What the capture observed of one plane."""

    observed_fraction: float  # observed / in-region texels
    texel_count: int  # observed texels
    in_region_count: int  # texels in the plane's measured region
    frames_used: int  # frames contributing >= 1 valid sample
    grid_px: tuple[int, int]  # (width, height) of the texel grid
    colors: np.ndarray = field(repr=False, default=None)  # (N_obs, 3) f32
    weights: np.ndarray = field(repr=False, default=None)  # (N_obs,) f32
    crops: list[EvidenceCrop] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def _texel_grid(geom: ShellPlaneGeom) -> tuple[int, int, float, float]:
    """(width_px, height_px, step_u_m, step_v_m) for the plane's grid,
    at SHELL_METERS_PER_TEXEL capped so the long edge <= max px."""
    mpt = SHELL_METERS_PER_TEXEL
    long_edge_m = max(geom.width_m, geom.height_m)
    if long_edge_m / mpt > SHELL_OBS_MAX_PX:
        mpt = long_edge_m / SHELL_OBS_MAX_PX
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


def _region_mask(
    points_world: np.ndarray,
    member_polygons: list[np.ndarray] | None,
) -> np.ndarray:
    """In-region mask: inside the union of floor member polygons when
    given (the floor's MEASURED shape), else everywhere (wall quads are
    their own measured region)."""
    if not member_polygons:
        return np.ones(len(points_world), dtype=bool)
    px, pz = points_world[:, 0], points_world[:, 2]
    inside = np.zeros(len(points_world), dtype=bool)
    for poly in member_polygons:
        inside |= _points_in_polygon_xz(px, pz, poly)
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
# Evidence crops
# ---------------------------------------------------------------------------

def _rectify_crop(
    geom: ShellPlaneGeom,
    frame: FrameSample,
    u0: float,
    v0: float,
    u1: float,
    v1: float,
    member_polygons: list[np.ndarray] | None,
) -> EvidenceCrop | None:
    """Re-sample one frame over a fine grid on the plane tile
    [u0,u1]x[v0,v1] (meters in the plane frame). Returns None when the
    frame observes none of it (cannot happen for tiles chosen from that
    frame's weights, guarded anyway)."""
    p = SHELL_EVIDENCE_CROP_PX
    us = (np.arange(p) + 0.5) * (u1 - u0) / p + u0
    vs = (np.arange(p) + 0.5) * (v1 - v0) / p + v0
    vv, uu = np.meshgrid(vs, us, indexing="ij")
    pts = (
        geom.origin[None, :]
        + uu.ravel()[:, None] * geom.axis_u[None, :]
        + vv.ravel()[:, None] * geom.axis_v[None, :]
    )
    colors, weights, _ = _sample_frame(pts, geom.normal, frame)
    observed = weights > 0
    if member_polygons:
        observed &= _region_mask(pts, member_polygons)
    if not np.any(observed):
        return None

    img = colors.reshape(p, p, 3)
    obs = observed.reshape(p, p)
    median_color = np.median(colors[observed], axis=0)
    img[~obs] = median_color
    # Grid row 0 is v0 (near the plane origin); flip so row 0 is the far
    # end of +V — the same top-of-image convention the bake used.
    img_u8 = np.clip(np.round(np.flipud(img)), 0, 255).astype(np.uint8)

    obs_frac = float(observed.sum()) / observed.size
    return EvidenceCrop(
        rgb=img_u8,
        frame_index=frame.frame_index,
        u0=u0,
        v0=v0,
        u1=u1,
        v1=v1,
        observed_fraction=round(obs_frac, 4),
        fill_fraction=round(1.0 - obs_frac, 4),
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def observe_plane(
    geom: ShellPlaneGeom,
    frames: list[FrameSample],
    *,
    floor_member_polygons: list[np.ndarray] | None = None,
) -> ObservationResult:
    """Observe one plane from the complete frames.

    floor_member_polygons bounds the floor's measured region (ignored for
    walls). Deterministic for identical inputs.
    """
    w_px, h_px, step_u, step_v = _texel_grid(geom)
    frames = sorted(frames, key=lambda f: f.frame_index)
    n_frames = len(frames)

    sel_colors = np.zeros((h_px, w_px, 3), dtype=np.float32)
    total_weight = np.zeros((h_px, w_px), dtype=np.float32)
    observed = np.zeros((h_px, w_px), dtype=bool)
    in_region = np.ones((h_px, w_px), dtype=bool)
    frame_any = np.zeros(n_frames, dtype=bool)

    # Evidence tiling: disjoint tiles of ~SHELL_EVIDENCE_CROP_M, aligned to
    # the texel grid; per-frame per-tile weight sums drive crop selection.
    tile_w_px = max(1, min(w_px, int(round(SHELL_EVIDENCE_CROP_M / step_u))))
    tile_h_px = max(1, min(h_px, int(round(SHELL_EVIDENCE_CROP_M / step_v))))
    n_tc = (w_px + tile_w_px - 1) // tile_w_px
    n_tr = (h_px + tile_h_px - 1) // tile_h_px
    tile_frame_weight = np.zeros((n_frames, n_tr, n_tc), dtype=np.float64)
    tile_obs = np.zeros((n_tr, n_tc), dtype=np.int64)
    tile_count = np.zeros((n_tr, n_tc), dtype=np.int64)

    col_tile = np.arange(w_px) // tile_w_px

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
            band_region = _region_mask(pts, floor_member_polygons)
            in_region[rows[0]: rows[-1] + 1, :] = band_region.reshape(
                len(rows), w_px
            )

        band_tiles = (
            (jj.ravel() // tile_h_px) * n_tc + col_tile[ii.ravel()]
        )
        np.add.at(
            tile_count.ravel(),
            band_tiles[in_region[rows[0]: rows[-1] + 1, :].ravel()],
            1,
        )

        if not frames:
            continue  # zero frames: everything stays unobserved

        band_colors = np.zeros((n_frames, len(pts), 3), dtype=np.float32)
        band_weights = np.zeros((n_frames, len(pts)), dtype=np.float32)
        band_lums = np.zeros((n_frames, len(pts)), dtype=np.float32)
        for fi, frame in enumerate(frames):
            band_colors[fi], band_weights[fi], band_lums[fi] = _sample_frame(
                pts, geom.normal, frame
            )
            frame_any[fi] |= bool(np.any(band_weights[fi] > 0))
            tile_frame_weight[fi].ravel()[:] += np.bincount(
                band_tiles,
                weights=band_weights[fi].astype(np.float64),
                minlength=n_tr * n_tc,
            )

        sel, obs = _weighted_median_select(band_colors, band_weights, band_lums)
        band_slice = slice(rows[0], rows[-1] + 1)
        sel_colors[band_slice, :] = sel.reshape(len(rows), w_px, 3)
        observed[band_slice, :] = obs.reshape(len(rows), w_px)
        total_weight[band_slice, :] = (
            band_weights.sum(axis=0).reshape(len(rows), w_px)
        )
        band_obs_region = (
            obs.reshape(len(rows), w_px) & in_region[band_slice, :]
        ).ravel()
        np.add.at(tile_obs.ravel(), band_tiles[band_obs_region], 1)

    in_count = int(in_region.sum())
    observed_in = observed & in_region
    obs_count = int(observed_in.sum())
    observed_fraction = (obs_count / in_count) if in_count else 0.0

    # Evidence crops: rank qualifying tiles by total observed weight.
    crops: list[EvidenceCrop] = []
    if frames and obs_count:
        tile_total = tile_frame_weight.sum(axis=0)
        with np.errstate(invalid="ignore", divide="ignore"):
            tile_frac = np.where(
                tile_count > 0, tile_obs / np.maximum(tile_count, 1), 0.0
            )
        order = np.argsort(-tile_total.ravel(), kind="stable")
        for flat in order:
            if len(crops) >= SHELL_EVIDENCE_MAX_CROPS:
                break
            tr, tc = divmod(int(flat), n_tc)
            if tile_frac[tr, tc] < SHELL_EVIDENCE_MIN_OBS or tile_total[tr, tc] <= 0:
                continue
            best_frame = int(np.argmax(tile_frame_weight[:, tr, tc]))
            u0 = tc * tile_w_px * step_u
            v0 = tr * tile_h_px * step_v
            u1 = min(w_px, (tc + 1) * tile_w_px) * step_u
            v1 = min(h_px, (tr + 1) * tile_h_px) * step_v
            # Square in WORLD space (isotropic mm/px — plank-direction
            # gradients read wrong on stretched crops); skip slivers.
            side = min(u1 - u0, v1 - v0)
            if side < _MIN_CROP_SIDE_M:
                continue
            crop = _rectify_crop(
                geom, frames[best_frame], u0, v0, u0 + side, v0 + side,
                floor_member_polygons if geom.kind == "floor" else None,
            )
            if crop is not None:
                crops.append(crop)

    return ObservationResult(
        observed_fraction=round(observed_fraction, 4),
        texel_count=obs_count,
        in_region_count=in_count,
        frames_used=int(frame_any.sum()),
        grid_px=(w_px, h_px),
        colors=sel_colors[observed_in].reshape(-1, 3),
        weights=total_weight[observed_in].ravel(),
        crops=crops,
    )
