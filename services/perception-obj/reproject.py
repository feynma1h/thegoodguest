"""Two-tier reprojection-scoring instrument (decision 0067).

Given a candidate placement (a splat + a world transform: rotation,
translation, scale) and an observing frame (camera pose/intrinsics, the
frame's SAM mask, optionally its RGB), scores how well the placement
explains that frame's evidence:

  tier 1 — crop-aware soft-IoU between the splat's projected footprint and
           the observed SAM mask. Always available (masks are cached for
           every complete frame).
  tier 2 — a crude, deterministic numpy point-splat render of the object
           (colors + opacity read straight from the PLY; nearest-point-wins
           per pixel as a cheap z-buffer, no GPU) scored by masked
           normalized cross-correlation against the frame's RGB crop. Only
           when the frame's RGB is still fetchable (the captures bucket's
           1-day lifecycle can outlive the object; absent RGB degrades to
           tier 1 alone).

No GPU, no model dependency, no new third-party packages: plain numpy over
geometry placement.py and roomstudio_schemas.placement_math already
compute (splat vertices, camera poses, projected pixels).

Also home to the two other instrument uses from decision 0067: in-plane
candidate generation/classification for planar objects (chunk C) and the
sign-flip diagnostic (mirrored_twin) that institutionalizes the 0065
identity-twin episode as a runtime check. Policy (which candidate wins,
what margin is required, what a winning flag means for the manifest)
stays in fusion.py — this module only scores and proposes candidates.

Consumers: fusion.py (best-member selection, footprint correspondence,
silhouette fit objective, in-plane resolution, sign-flagging).
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass
from typing import Optional

import numpy as np
import placement
from roomstudio_schemas.placement_math import (
    DegenerateGeometryError,
    MaskEvidence,
    prepare_mask,
    project_points,
    rasterize_mask_density,
    rasterize_point_density,
    robust_cloud_stats,
    rotation_about_axis,
    soft_containment,
    soft_iou,
    union_bbox,
)
from roomstudio_schemas.pose_math import quat_to_rotmat, rotmat_to_quat

# Standard 3DGS SH0 -> RGB DC-term constant (1 / (2*sqrt(pi))): color =
# clip(0.5 + C0 * f_dc, 0, 1). Same convention every 3DGS viewer uses.
_SH_C0 = 0.28209479177387814

_TIER1_GRID = int(os.environ.get("PLACEMENT_TIER1_GRID", "32"))
# Soft IoU/containment need only enough points to estimate a density grid,
# not the full splat — a 200k+-point real object scored dozens of times
# per refinement pass (best-member selection, footprint join/merge,
# in-plane candidates, sign-flag) turns into minutes of wasted projection
# work otherwise. Tier 2's render_splat already subsamples; tier 1 didn't,
# which is a real production-viability bug, not just slow tests.
_TIER1_MAX_POINTS = int(os.environ.get("PLACEMENT_TIER1_MAX_POINTS", "8000"))
# ~128 px per decision 0067's instrument spec.
_TIER2_GRID = int(os.environ.get("PLACEMENT_TIER2_GRID", "128"))
_TIER2_MAX_POINTS = int(os.environ.get("PLACEMENT_TIER2_MAX_POINTS", "40000"))
_TIER2_MIN_WEIGHTED_PIXELS = int(os.environ.get("PLACEMENT_TIER2_MIN_PIXELS", "12"))

# A splat is "planar" (chunk C's in-plane candidates apply) when its
# smallest-variance extent is this much smaller than its middle extent.
_PLANAR_THIN_RATIO = float(os.environ.get("PLACEMENT_PLANAR_THIN_RATIO", "0.3"))


# -----------------------------------------------------------------------------
# Splat appearance (tier 2 only)
# -----------------------------------------------------------------------------

@dataclass(frozen=True)
class SplatAppearance:
    """Per-vertex color + opacity, decoded from a 3DGS PLY's SH DC term and
    opacity logit — the same convention every 3DGS viewer uses."""
    colors: np.ndarray  # (N, 3) float64 in [0, 1]
    opacity: np.ndarray  # (N,) float64 in [0, 1]


def load_splat_appearance(ply_bytes: bytes) -> SplatAppearance:
    """Read colors + opacity out of a 3DGS PLY (raises ValueError on an
    unsupported/malformed PLY — same contract as parse_ply_vertices)."""
    cols = placement.parse_ply_properties(
        ply_bytes, ("f_dc_0", "f_dc_1", "f_dc_2", "opacity")
    )
    colors = np.clip(
        0.5 + _SH_C0 * np.column_stack([cols["f_dc_0"], cols["f_dc_1"], cols["f_dc_2"]]),
        0.0, 1.0,
    )
    opacity = 1.0 / (1.0 + np.exp(-cols["opacity"]))
    return SplatAppearance(colors=colors, opacity=opacity)


def transform_points(
    local_points: np.ndarray, rotation_xyzw, translation, scale: float
) -> np.ndarray:
    """Local splat frame -> world frame: p_world = scale * R @ p_local + t."""
    R = quat_to_rotmat(tuple(rotation_xyzw))
    pts = np.asarray(local_points, dtype=np.float64)
    return (float(scale) * pts) @ R.T + np.asarray(translation, dtype=np.float64)


# -----------------------------------------------------------------------------
# Tier 1: silhouette agreement
# -----------------------------------------------------------------------------

def _subsample_for_scoring(world_points: np.ndarray, max_points: Optional[int]) -> np.ndarray:
    cap = max_points or _TIER1_MAX_POINTS
    idx = _subsample_indices(world_points.shape[0], cap)
    return world_points[idx]


def _as_evidence(mask) -> MaskEvidence:
    return mask if isinstance(mask, MaskEvidence) else prepare_mask(mask)


def _tier1_densities(
    world_points: np.ndarray, evidence: MaskEvidence, intrinsics, pose,
    grid_size: int, max_points: Optional[int],
):
    pts = _subsample_for_scoring(world_points, max_points)
    uv, _depth, valid = project_points(pts, intrinsics, pose)
    bbox = union_bbox(evidence.shape, evidence.bounds, uv, valid)
    density_pts = rasterize_point_density(uv, valid, bbox, grid_size)
    density_mask = rasterize_mask_density(evidence, bbox, grid_size)
    return density_pts, density_mask


def score_tier1(
    world_points: np.ndarray, mask, intrinsics, pose,
    grid_size: Optional[int] = None, max_points: Optional[int] = None,
) -> float:
    """Crop-aware soft-IoU between the projected splat footprint and mask.

    mask may be a raw (H, W) bool array or a prepared MaskEvidence —
    callers scoring the same mask repeatedly (fitting, candidate ranking)
    should prepare once; the raw form pays an O(H·W) table build per call.
    """
    ev = _as_evidence(mask)
    density_pts, density_mask = _tier1_densities(
        world_points, ev, intrinsics, pose, grid_size or _TIER1_GRID, max_points
    )
    return soft_iou(density_pts, density_mask)


def score_tier1_containment(
    world_points: np.ndarray, mask, intrinsics, pose,
    grid_size: Optional[int] = None, max_points: Optional[int] = None,
) -> float:
    """Crop-aware soft-containment (tolerant of partial framing) — the
    footprint join/merge signal, distinct from tier-1 selection scoring.
    Accepts a raw mask or a prepared MaskEvidence, like score_tier1."""
    ev = _as_evidence(mask)
    density_pts, density_mask = _tier1_densities(
        world_points, ev, intrinsics, pose, grid_size or _TIER1_GRID, max_points
    )
    return soft_containment(density_pts, density_mask)


# -----------------------------------------------------------------------------
# Tier 2: crude appearance render + masked NCC
# -----------------------------------------------------------------------------

def _subsample_indices(n: int, max_points: int) -> np.ndarray:
    if n <= max_points:
        return np.arange(n)
    idx = np.linspace(0, n - 1, max_points).astype(int)
    return np.unique(idx)


def render_splat(
    world_points: np.ndarray,
    colors: np.ndarray,
    opacity: np.ndarray,
    mask: np.ndarray,
    intrinsics,
    pose,
    grid_size: Optional[int] = None,
    max_points: Optional[int] = None,
    opacity_min: float = 0.1,
):
    """Deterministic, GPU-free point-splat render into a grid_size x
    grid_size raster over the mask's crop-aware bbox.

    Nearest-point-wins per cell (a proper, if crude, z-buffer): points
    below opacity_min are dropped first (near-transparent gaussians carry
    no visible surface color), then for each cell the LAST-written point
    wins by construction — points are processed in far-to-near depth
    order, so the nearest survives. Plain opacity-weighted averaging
    (tried first) blends a folded/pleated object's near and far surfaces
    together and washes out exactly the texture tier 2 needs; a z-buffer
    keeps only what the camera would actually see. Fully vectorized (no
    per-pixel Python loop): numpy's fancy-index assignment resolves
    repeated indices by keeping the last occurrence in array order.

    Returns (render, coverage, bbox) or None if nothing projects into the
    bbox. render is (G, G, 3) in [0, 1]; coverage is (G, G) in {0, 1}
    (1 where an opaque-enough point landed).
    """
    grid_size = grid_size or _TIER2_GRID
    max_points = max_points or _TIER2_MAX_POINTS
    idx = _subsample_indices(world_points.shape[0], max_points)
    pts = world_points[idx]
    col = colors[idx]
    w = opacity[idx]
    opaque = w >= opacity_min
    pts, col, w = pts[opaque], col[opaque], w[opaque]
    if pts.shape[0] == 0:
        return None

    ev = _as_evidence(mask)
    uv, depth, valid = project_points(pts, intrinsics, pose)
    bbox = union_bbox(ev.shape, ev.bounds, uv, valid)
    u0, v0, u1, v1 = bbox
    if u1 <= u0 or v1 <= v0:
        return None
    in_box = valid & (uv[:, 0] >= u0) & (uv[:, 0] < u1) & (uv[:, 1] >= v0) & (uv[:, 1] < v1)
    if not np.any(in_box):
        return None

    col_idx = np.clip(((uv[in_box, 0] - u0) / (u1 - u0) * grid_size).astype(int), 0, grid_size - 1)
    row_idx = np.clip(((uv[in_box, 1] - v0) / (v1 - v0) * grid_size).astype(int), 0, grid_size - 1)
    flat = row_idx * grid_size + col_idx
    order = np.argsort(-depth[in_box])  # far-to-near: nearest assigned last, wins ties

    render = np.zeros((grid_size * grid_size, 3), dtype=np.float64)
    coverage = np.zeros(grid_size * grid_size, dtype=np.float64)
    render[flat[order]] = col[in_box][order]
    coverage[flat[order]] = 1.0
    return (
        render.reshape(grid_size, grid_size, 3),
        coverage.reshape(grid_size, grid_size),
        bbox,
    )


# Target sample count per grid cell for _rasterize_average's strided
# estimate — 3x3 per cell balances estimate quality against the bounded
# work guarantee (the whole point: cost scales with grid_size², never
# with crop pixel count).
_AVERAGE_SAMPLES_PER_CELL_SIDE = 3


def _rasterize_average(values: np.ndarray, bbox, grid_size: int) -> np.ndarray:
    """Strided-sample average of a (H, W) or (H, W, C) array into a
    grid_size x grid_size (x C) grid over bbox — used for the RGB crop.

    Deterministic estimate, not an exact box average: pixels are sampled
    on a fixed stride chosen so each cell sees roughly
    _AVERAGE_SAMPLES_PER_CELL_SIDE² samples, bounding the work by the
    GRID size instead of the crop size. Profiling showed the exact
    version (histogramming every crop pixel) at ~310 ms per call was
    ~90% of the whole refinement pass; an appearance-NCC input doesn't
    need exactness, it needs a stable per-cell color estimate.
    """
    h, w = values.shape[:2]
    u0, v0, u1, v1 = bbox
    iu0, iv0 = max(int(np.floor(u0)), 0), max(int(np.floor(v0)), 0)
    iu1, iv1 = min(int(np.ceil(u1)), w), min(int(np.ceil(v1)), h)
    out_shape = (grid_size, grid_size) if values.ndim == 2 else (grid_size, grid_size, values.shape[2])
    if iu1 <= iu0 or iv1 <= iv0 or u1 <= u0 or v1 <= v0:
        return np.zeros(out_shape, dtype=np.float64)
    target = grid_size * _AVERAGE_SAMPLES_PER_CELL_SIDE
    step_v = max(1, (iv1 - iv0) // target)
    step_u = max(1, (iu1 - iu0) // target)
    crop = values[iv0:iv1:step_v, iu0:iu1:step_u]
    vs = np.arange(iv0, iv1, step_v, dtype=np.float64) + 0.5
    us = np.arange(iu0, iu1, step_u, dtype=np.float64) + 0.5
    vv, uu = np.meshgrid(vs, us, indexing="ij")
    count_all, _, _ = np.histogram2d(
        vv.ravel(), uu.ravel(), bins=grid_size, range=[[v0, v1], [u0, u1]]
    )
    if values.ndim == 2:
        count_val, _, _ = np.histogram2d(
            vv.ravel(), uu.ravel(), bins=grid_size, range=[[v0, v1], [u0, u1]],
            weights=crop.ravel().astype(np.float64),
        )
        return np.divide(count_val, count_all, out=np.zeros_like(count_val), where=count_all > 0)
    chans = []
    for c in range(values.shape[2]):
        count_val, _, _ = np.histogram2d(
            vv.ravel(), uu.ravel(), bins=grid_size, range=[[v0, v1], [u0, u1]],
            weights=crop[:, :, c].ravel().astype(np.float64),
        )
        chans.append(np.divide(count_val, count_all, out=np.zeros_like(count_val), where=count_all > 0))
    return np.stack(chans, axis=-1)


def _masked_ncc(render: np.ndarray, rgb_crop: np.ndarray, weight: np.ndarray) -> Optional[float]:
    """Weighted normalized cross-correlation of two (G, G, 3) images'
    luminance over pixels with weight > 0. None if too few weighted pixels
    survive (an inconclusive tier 2, not a bad score)."""
    w = weight.ravel()
    keep = w > 1e-3
    if int(keep.sum()) < _TIER2_MIN_WEIGHTED_PIXELS:
        return None
    r_l = render.reshape(-1, 3)[keep].mean(axis=1)
    c_l = rgb_crop.reshape(-1, 3)[keep].mean(axis=1)
    wv = w[keep]
    wsum = wv.sum()
    r_mean = (r_l * wv).sum() / wsum
    c_mean = (c_l * wv).sum() / wsum
    r_c = r_l - r_mean
    c_c = c_l - c_mean
    den = math.sqrt(float((wv * r_c ** 2).sum()) * float((wv * c_c ** 2).sum()))
    if den < 1e-9:
        return None
    num = float((wv * r_c * c_c).sum())
    return num / den


def score_tier2(
    render: np.ndarray, coverage: np.ndarray, mask, rgb: np.ndarray, bbox, grid_size: int
) -> Optional[float]:
    """Masked-NCC appearance score, mapped from [-1, 1] to [0, 1].

    mask may be raw or a prepared MaskEvidence. rgb is (H, W, 3) at the
    mask's resolution, in ANY linear scale (float [0, 1] or uint8 [0, 255]
    both work — NCC is invariant to affine intensity scaling, which lets
    production cache the much smaller uint8 form).
    """
    mask_density = rasterize_mask_density(_as_evidence(mask), bbox, grid_size)
    weight = coverage * mask_density
    rgb_grid = _rasterize_average(rgb, bbox, grid_size)
    ncc = _masked_ncc(render, rgb_grid, weight)
    if ncc is None:
        return None
    return float(np.clip((ncc + 1.0) / 2.0, 0.0, 1.0))


# -----------------------------------------------------------------------------
# The combined instrument
# -----------------------------------------------------------------------------

def score_placement(
    *,
    local_points: np.ndarray,
    rotation_xyzw,
    translation,
    scale: float,
    mask,
    intrinsics,
    pose,
    appearance: Optional[SplatAppearance] = None,
    rgb: Optional[np.ndarray] = None,
    tier1_grid_size: Optional[int] = None,
    tier2_grid_size: Optional[int] = None,
    max_points: Optional[int] = None,
) -> dict:
    """Score one candidate placement against one observing frame.

    mask may be raw or a prepared MaskEvidence (prepare once when scoring
    several candidates against the same frame). Returns {tier1: float,
    tier2: float | None, tiers_used: [...]}. tier2 requires both
    `appearance` (from load_splat_appearance) and `rgb` (the frame's RGB
    at the mask's resolution; float [0, 1] or uint8 — see score_tier2) —
    either missing degrades to tier1-only, recorded.
    """
    ev = _as_evidence(mask)
    world_points = transform_points(local_points, rotation_xyzw, translation, scale)
    tier1 = score_tier1(world_points, ev, intrinsics, pose, tier1_grid_size)
    tier2 = None
    tiers_used = ["tier1"]
    if appearance is not None and rgb is not None:
        rendered = render_splat(
            world_points, appearance.colors, appearance.opacity, ev, intrinsics, pose,
            tier2_grid_size, max_points,
        )
        if rendered is not None:
            render, coverage, bbox = rendered
            g = tier2_grid_size or _TIER2_GRID
            tier2 = score_tier2(render, coverage, ev, rgb, bbox, g)
            if tier2 is not None:
                tiers_used.append("tier2")
    return {"tier1": tier1, "tier2": tier2, "tiers_used": tiers_used}


def combined_score(result: dict) -> float:
    """tier2-weighted combination when tier2 is present, else tier1 alone —
    the ranking key for best-member selection and candidate comparisons."""
    if result.get("tier2") is not None:
        return 0.7 * result["tier2"] + 0.3 * result["tier1"]
    return result["tier1"]


# -----------------------------------------------------------------------------
# Multi-view silhouette fit (chunk B's position/scale authority)
# -----------------------------------------------------------------------------

_FIT_MAX_ITERS = int(os.environ.get("PLACEMENT_FIT_MAX_ITERS", "60"))
_FIT_MAX_POINTS = int(os.environ.get("PLACEMENT_FIT_MAX_POINTS", "4000"))
# The optimization loop evaluates the objective dozens of times per
# cluster; a coarser grid than final-selection scoring (_TIER1_GRID) keeps
# each objective-function call cheap without changing what's being
# optimized (soft IoU at any reasonable resolution).
_FIT_GRID_SIZE = int(os.environ.get("PLACEMENT_FIT_GRID_SIZE", "24"))
# Scale search stays within [init_scale / factor, init_scale * factor]. A
# soft-IoU objective alone can be gamed by inflating scale until the
# footprint swamps a large mask; SAM 3D's layout scale prior is trusted to
# within this bound, matching fit_single_view's role elsewhere as the
# metric authority rather than an unconstrained appearance search.
_FIT_SCALE_BOUND_FACTOR = float(os.environ.get("PLACEMENT_FIT_SCALE_BOUND", "1.5"))


def fit_silhouette(
    local_points: np.ndarray,
    rotation_xyzw,
    init_scale: float,
    init_translation,
    observations: list,
    *,
    grid_size: Optional[int] = None,
    max_points: Optional[int] = None,
    max_iters: Optional[int] = None,
    init_step_scale: float = 0.15,
    init_step_t: float = 0.15,
    scale_bound_factor: Optional[float] = None,
) -> dict:
    """Deterministic coarse-to-fine pattern search (Hooke-Jeeves style) for
    (scale, translation) maximizing mean tier-1 silhouette agreement across
    member frames. Rotation is held fixed (0065: canonical frames are
    per-reconstruction arbitrary; only the best member's own frame is
    meaningful).

    observations: [(mask, intrinsics, pose), ...] — one per member frame,
    each already the frame's own SAM mask for its own detection (raw or
    MaskEvidence; prepared once here regardless, since the objective is
    evaluated up to max_iters times against every observation).

    Bounded, no RNG: a fixed candidate set (+-scale, +-x, +-y, +-z) per
    round, halving the step whenever no candidate improves, stopping at
    max_iters objective evaluations or once both steps are negligible.
    Scale candidates outside [init_scale/scale_bound_factor,
    init_scale*scale_bound_factor] are skipped — soft IoU alone rewards
    inflating the footprint against a large mask; the layout prior's scale
    is trusted to within this factor.

    Returns {scale, translation, tier1_mean, init_tier1_mean, iterations,
    improved}. improved is False (and scale/translation echo the input)
    when the search never beats the starting point — callers must keep the
    initial values in that case (fit must beat init to ship).
    """
    grid_size = grid_size or _FIT_GRID_SIZE
    max_points = max_points or _FIT_MAX_POINTS
    max_iters = max_iters or _FIT_MAX_ITERS
    factor = scale_bound_factor or _FIT_SCALE_BOUND_FACTOR
    scale_lo, scale_hi = float(init_scale) / factor, float(init_scale) * factor
    idx = _subsample_indices(local_points.shape[0], max_points)
    pts_local = local_points[idx]
    prepared = [(_as_evidence(mask), intr, pose) for mask, intr, pose in observations]

    def objective(scale: float, t: np.ndarray) -> float:
        world_pts = transform_points(pts_local, rotation_xyzw, t, scale)
        scores = [
            score_tier1(world_pts, ev, intr, pose, grid_size, max_points)
            for ev, intr, pose in prepared
        ]
        return float(np.mean(scores)) if scores else 0.0

    scale = float(init_scale)
    t = np.asarray(init_translation, dtype=np.float64).copy()
    init_score = objective(scale, t)
    best = init_score
    step_scale, step_t = init_step_scale, init_step_t
    iters = 0
    axes = [np.array(a, dtype=np.float64) for a in ([1, 0, 0], [0, 1, 0], [0, 0, 1])]
    while iters < max_iters and (step_scale > 1e-3 or step_t > 1e-3):
        improved = False
        candidates = [(scale * (1.0 + step_scale), t), (scale * (1.0 - step_scale), t)]
        for ax in axes:
            candidates.append((scale, t + step_t * ax))
            candidates.append((scale, t - step_t * ax))
        for cs, ct in candidates:
            if cs < scale_lo or cs > scale_hi or iters >= max_iters:
                continue
            sc = objective(cs, ct)
            iters += 1
            if sc > best + 1e-6:
                best, scale, t = sc, cs, ct
                improved = True
        if not improved:
            step_scale *= 0.5
            step_t *= 0.5
    return {
        "scale": scale,
        "translation": t.tolist(),
        "tier1_mean": best,
        "init_tier1_mean": init_score,
        "iterations": iters,
        "improved": bool(best > init_score + 1e-6),
    }


# -----------------------------------------------------------------------------
# In-plane candidates (chunk C) and the sign-flip diagnostic
# -----------------------------------------------------------------------------

def is_planar(local_points: np.ndarray, thin_ratio: float = _PLANAR_THIN_RATIO) -> bool:
    """True if the splat's smallest-variance extent is thin relative to its
    middle extent — a near-flat object (curtain, artwork, door) where the
    layout rotation's spin about its own normal is the ambiguous DOF."""
    try:
        stats = robust_cloud_stats(local_points)
    except DegenerateGeometryError:
        return False
    if stats.extents[1] <= 1e-9:
        return False
    return bool((stats.extents[2] / stats.extents[1]) < thin_ratio)


def in_plane_candidates(rotation_xyzw, local_points: np.ndarray) -> list:
    """Four rotation candidates spun in 90-degree steps about the splat's
    own (world-lifted) normal axis — the ambiguity class SAM 3D exhibits
    on near-square planar objects. First candidate is the input rotation
    itself (k=0)."""
    R_world = quat_to_rotmat(tuple(rotation_xyzw))
    stats = robust_cloud_stats(local_points)
    normal_local = stats.axes[:, 2]
    normal_world = R_world @ normal_local
    out = []
    for k in range(4):
        Rk = rotation_about_axis(normal_world, k * math.pi / 2.0) @ R_world
        out.append(tuple(rotmat_to_quat(Rk)))
    return out


def mirrored_twin(rotation_xyzw, view_dir_world: np.ndarray):
    """The 180-degree-about-the-viewing-axis twin of a world rotation —
    the general form of the 0065 identity-twin bug (a camera-basis sign
    error is exactly a flip about the observing camera's own forward
    direction). A materially better-scoring twin flags a possible
    convention regression; it does not by itself correct anything
    (rotation correction stays 0065's domain)."""
    R_world = quat_to_rotmat(tuple(rotation_xyzw))
    R_flip = rotation_about_axis(view_dir_world, math.pi)
    R_twin = R_flip @ R_world
    return tuple(rotmat_to_quat(R_twin))
