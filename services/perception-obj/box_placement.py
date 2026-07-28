"""Box-anchored placement — RoomPlan boxes as the object skeleton
(decision 0077 lock 5; P1 probe regime).

For covered furniture categories the RoomPlan box IS the measurement:
position, extent, upright, and yaw were operator-verified 9/9 (0076), while
the shipped SAM-3D-layout rotation measured ~90° yaw-wrong on the real bed
and depth_fit halved its width (visible-region truncation — P1/P2
collateral). So a box-anchored object takes position/extent/upright/yaw
from the box; SAM 3D contributes APPEARANCE only (the splat from the best
associated view), and the one genuinely unknown DOF — how the splat's
per-reconstruction-ARBITRARY canonical frame sits inside the box — is
resolved by the two-tier appearance instrument at the BOX center, P1's
verified regime:

  * position precedes rotation: at the shipped (0.79 m off) center the
    scorer prefers UPSIDE-DOWN — candidates are only ever scored at
    box-quality centers (the pinned negative);
  * degenerate views are SKIPPED, not averaged (P1's f164: a 1.4 m view of
    the 2 m bed zeroes tier 1 for every box-frame candidate);
  * the winner ships only with a clear margin (PLACEMENT_AXIS_MARGIN,
    default = P1's achieved 0.10 combined); below it the extent-best
    mapping ships with `splat_axis_resolved: false`;
  * the facing guard is FLAG-ONLY (v1, the 0067 lock-6 precedent): when the
    scorer prefers the 180°-about-vertical partner of the shipped mapping
    (= the anti-RoomPlan facing — a cuboid's 180° yaw is a self-symmetry,
    so the mapping partner and the box-yaw flip are the same rotation) but
    not decisively enough to ship, `facing_flag: true` records the
    disagreement and RoomPlan's conventional mapping ships.

Association projects each box's footprint into each sampled frame (poses +
intrinsics) and matches SAM masks by footprint overlap + a RoomPlan↔SAM
label-family map; greedy best-match, deterministic. Every associated
observation is CONSUMED by its box — one object per box by construction
(the operator's one-object-one-reconstruction corollary). Boxes with no
associated splat ship as honest inventory (`placed: false, reason
"no_appearance"`, box geometry carried); unmatched observations flow to
the existing pipeline untouched.

Pure numpy + reproject over the fusion RefinementContext's accessors; no
GCS, no models. Deterministic: fixed candidate order, ties by lower index.

Consumers: fusion.py (census-aware fusion pass),
tests/test_box_placement.py, tests/test_box_placement_real_data.py.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

import numpy as np
import reproject
from roomstudio_schemas.placement_math import project_points
from roomstudio_schemas.pose_math import rotmat_to_quat

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tunables (env-overridable; one-room-calibrated placeholders like every
# PLACEMENT_* knob)
# ---------------------------------------------------------------------------

# Minimum fraction of a SAM mask's pixels inside the projected box footprint
# for the pair to be an association candidate.
_BOX_MATCH_MIN = float(os.environ.get("PLACEMENT_BOX_MATCH_MIN", "0.5"))

# A view scores axis candidates only when the projected box footprint is
# substantially in-frame (P1's degenerate-view lesson: the f164 close view
# zeroes tier 1 — measured in-frame fraction 0.0 vs f129's 0.63).
_BOX_SCORE_MIN_INFRAME = float(os.environ.get("PLACEMENT_BOX_SCORE_MIN_INFRAME", "0.5"))

# Extent-consistency bound for an axis assignment: max/min of the per-axis
# box-dim / splat-extent ratios. Near-equal extents keep several assignments
# alive — exactly the "enumerate all" clause.
_AXIS_RATIO_TOL = float(os.environ.get("PLACEMENT_AXIS_RATIO_TOL", "1.6"))

# The winner must beat every other candidate's mean combined score by this
# to ship (P1's achieved combined winner margin: 0.0999 on the real bed).
_AXIS_MARGIN = float(os.environ.get("PLACEMENT_AXIS_MARGIN", "0.10"))

# Below the ship margin, a partner (180°-about-vertical) preference this
# large over the shipped default raises facing_flag (flag-only v1).
_FACING_FLAG_MARGIN = float(os.environ.get("PLACEMENT_FACING_FLAG_MARGIN", "0.03"))

# Suppression: a non-box object's center inside a matched box's volume
# (padded by this) with a compatible label is a box duplicate.
_BOX_SUPPRESS_MARGIN_M = float(os.environ.get("PLACEMENT_BOX_SUPPRESS_MARGIN_M", "0.1"))

# Cap on mask pixels sampled for the footprint-overlap test (deterministic
# stride — association needs a stable fraction, not an exact count).
_OVERLAP_MAX_PIXELS = int(os.environ.get("PLACEMENT_BOX_OVERLAP_MAX_PIXELS", "20000"))

# Percentile clip for splat extents along its LOCAL COORDINATE axes (the P1
# probe's convention — candidates map coordinate axes onto box axes, so the
# extents must be measured along the same axes, not PCA axes).
_EXTENT_PCTL = 2.0


def _parse_family_map(raw: str) -> dict[str, frozenset[str]]:
    """"bed:bed|table:table,desk" → {category: {labels}}. Lowercased."""
    out: dict[str, frozenset[str]] = {}
    for part in raw.split("|"):
        part = part.strip()
        if not part or ":" not in part:
            continue
        cat, labels = part.split(":", 1)
        out[cat.strip().lower()] = frozenset(
            s.strip().lower() for s in labels.split(",") if s.strip()
        )
    return out


# RoomPlan category → compatible SAM labels (decision 0077's starting
# families, verbatim; env-overridable so vocabulary growth needs no code
# edit). An unmapped category never associates — the box ships as honest
# inventory instead of grabbing a wrong mask.
_DEFAULT_FAMILIES = (
    "bed:bed"
    "|table:table,desk,nightstand"
    "|chair:chair,stool,bench"
    "|storage:cabinet,dresser,wardrobe,bookshelf,shelf"
    "|sofa:sofa,couch"
    "|television:tv,television,monitor"
)
BOX_LABEL_FAMILIES: dict[str, frozenset[str]] = _parse_family_map(
    os.environ.get("PLACEMENT_BOX_LABEL_FAMILIES", _DEFAULT_FAMILIES)
)


def family_compatible(category: str | None, label: str | None) -> bool:
    if not category or not label:
        return False
    family = BOX_LABEL_FAMILIES.get(category.strip().lower())
    return family is not None and label.strip().lower() in family


# ---------------------------------------------------------------------------
# Footprint geometry (pure 2D; no scipy)
# ---------------------------------------------------------------------------

def box_corners_world(box) -> np.ndarray:
    """(8, 3) world corners of a RoomPlanBox."""
    hx, hy, hz = (float(d) / 2.0 for d in box.dimensions)
    signs = np.array([
        [sx, sy, sz]
        for sx in (-1.0, 1.0) for sy in (-1.0, 1.0) for sz in (-1.0, 1.0)
    ])
    local = signs * np.array([hx, hy, hz])
    R = box.transform[:3, :3]
    t = box.transform[:3, 3]
    return local @ R.T + t


def _convex_hull_2d(pts: np.ndarray) -> np.ndarray:
    """Andrew monotone chain; (M, 2) CCW hull. Deterministic."""
    pts = np.unique(np.round(pts, 6), axis=0)
    if pts.shape[0] < 3:
        return pts
    order = np.lexsort((pts[:, 1], pts[:, 0]))
    pts = pts[order]

    def _cross2(o: np.ndarray, a: np.ndarray, b: np.ndarray) -> float:
        return float((a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]))

    def _half(seq):
        out: list[np.ndarray] = []
        for p in seq:
            while len(out) >= 2 and _cross2(out[-2], out[-1], p) <= 0:
                out.pop()
            out.append(p)
        return out

    lower = _half(list(pts))
    upper = _half(list(pts[::-1]))
    return np.array(lower[:-1] + upper[:-1])


def _polygon_area(poly: np.ndarray) -> float:
    if poly.shape[0] < 3:
        return 0.0
    x, y = poly[:, 0], poly[:, 1]
    return 0.5 * abs(float(np.dot(x, np.roll(y, -1)) - np.dot(np.roll(x, -1), y)))


def _clip_to_rect(poly: np.ndarray, w: float, h: float) -> np.ndarray:
    """Sutherland–Hodgman clip of a convex polygon to [0, w] x [0, h]."""
    edges = [
        (np.array([1.0, 0.0]), 0.0),
        (np.array([-1.0, 0.0]), -w),
        (np.array([0.0, 1.0]), 0.0),
        (np.array([0.0, -1.0]), -h),
    ]
    out = poly
    for n, c in edges:
        if out.shape[0] == 0:
            return out
        keep: list[np.ndarray] = []
        m = out.shape[0]
        d = out @ n - c
        for i in range(m):
            j = (i + 1) % m
            if d[i] >= 0:
                keep.append(out[i])
            if (d[i] >= 0) != (d[j] >= 0):
                t = d[i] / (d[i] - d[j])
                keep.append(out[i] + t * (out[j] - out[i]))
        out = np.array(keep) if keep else np.zeros((0, 2))
    return out


def _points_in_hull(pts: np.ndarray, hull: np.ndarray) -> np.ndarray:
    """(N,) bool: inside a CCW convex hull (boundary counts as inside)."""
    if hull.shape[0] < 3:
        return np.zeros(pts.shape[0], dtype=bool)
    inside = np.ones(pts.shape[0], dtype=bool)
    m = hull.shape[0]
    for i in range(m):
        a, b = hull[i], hull[(i + 1) % m]
        edge = b - a
        rel = pts - a
        cross = edge[0] * rel[:, 1] - edge[1] * rel[:, 0]
        inside &= cross >= -1e-9
    return inside


def project_box_footprint(box, intrinsics, pose):
    """(hull_uv, in_frame_fraction) of a box's projected footprint, or
    (None, 0.0) when fewer than 3 corners project in front of the camera.
    in_frame_fraction = area(hull ∩ frame) / area(hull)."""
    uv, _depth, valid = project_points(box_corners_world(box), intrinsics, pose)
    if int(valid.sum()) < 3:
        return None, 0.0
    hull = _convex_hull_2d(uv[valid])
    area = _polygon_area(hull)
    if area <= 0.0:
        return None, 0.0
    w = float(getattr(intrinsics, "width", 0) or 2.0 * intrinsics.cx)
    h = float(getattr(intrinsics, "height", 0) or 2.0 * intrinsics.cy)
    clipped = _clip_to_rect(hull, w, h)
    return hull, _polygon_area(clipped) / area


def mask_overlap_with_hull(mask: np.ndarray, hull: np.ndarray) -> float:
    """Fraction of a mask's true pixels inside the hull (deterministic
    stride cap — a stable fraction, not an exact count)."""
    ys, xs = np.nonzero(mask)
    n = xs.shape[0]
    if n == 0 or hull is None:
        return 0.0
    if n > _OVERLAP_MAX_PIXELS:
        idx = np.linspace(0, n - 1, _OVERLAP_MAX_PIXELS).astype(int)
        xs, ys = xs[idx], ys[idx]
    pts = np.column_stack([xs + 0.5, ys + 0.5]).astype(np.float64)
    return float(_points_in_hull(pts, hull).mean())


# ---------------------------------------------------------------------------
# Association
# ---------------------------------------------------------------------------

@dataclass
class BoxAssociation:
    """One observation matched to one box in one frame."""

    box_index: int
    frame_index: int
    mask_index: int | None
    overlap: float
    in_frame_fraction: float
    obs: dict


def associate_observations(
    boxes: list, observations: list[dict], ctx
) -> dict[int, list[BoxAssociation]]:
    """Greedy best-match association: candidate pairs need label-family
    compatibility AND footprint overlap >= PLACEMENT_BOX_MATCH_MIN; each
    observation joins at most one box (highest overlap wins; ties by frame
    then mask then box index). Deterministic. Returns box_index →
    associations sorted by (-overlap, frame_index)."""
    footprints: dict[tuple[int, int], tuple] = {}  # (frame, box) → (hull, frac)

    def _footprint(frame_index: int, box_index: int):
        key = (frame_index, box_index)
        if key not in footprints:
            cam = ctx.get_camera(frame_index)
            if cam is None:
                footprints[key] = (None, 0.0)
            else:
                pose, intrinsics = cam
                footprints[key] = project_box_footprint(
                    boxes[box_index], intrinsics, pose
                )
        return footprints[key]

    candidates: list[tuple[float, int, int, int, dict, float]] = []
    for o in observations:
        label = o.get("label")
        mask = ctx.mask_for(o["frame_index"], o.get("mask_index"))
        if mask is None:
            continue
        for bi, box in enumerate(boxes):
            if not family_compatible(box.category, label):
                continue
            hull, in_frame = _footprint(o["frame_index"], bi)
            if hull is None:
                continue
            overlap = mask_overlap_with_hull(mask, hull)
            if overlap >= _BOX_MATCH_MIN:
                candidates.append(
                    (overlap, o["frame_index"], o.get("mask_index") or 0, bi, o, in_frame)
                )

    candidates.sort(key=lambda c: (-c[0], c[1], c[2], c[3]))
    assigned: set[tuple[int, int | None]] = set()
    out: dict[int, list[BoxAssociation]] = {}
    for overlap, _frame_index, _mi, bi, o, in_frame in candidates:
        obs_key = (o["frame_index"], o.get("mask_index"))
        if obs_key in assigned:
            continue
        assigned.add(obs_key)
        out.setdefault(bi, []).append(BoxAssociation(
            box_index=bi,
            frame_index=o["frame_index"],
            mask_index=o.get("mask_index"),
            overlap=float(overlap),
            in_frame_fraction=float(in_frame),
            obs=o,
        ))
    for assocs in out.values():
        assocs.sort(key=lambda a: (-a.overlap, a.frame_index, a.mask_index or 0))
    return out


# ---------------------------------------------------------------------------
# Axis mapping (the splat-canonical-frame → box correspondence)
# ---------------------------------------------------------------------------

def splat_axis_extents(local_points: np.ndarray) -> np.ndarray:
    """(3,) percentile-clipped extents along the splat's LOCAL COORDINATE
    axes (not PCA axes — candidates map coordinate axes onto box axes)."""
    lo = np.percentile(local_points, _EXTENT_PCTL, axis=0)
    hi = np.percentile(local_points, 100.0 - _EXTENT_PCTL, axis=0)
    return np.asarray(hi - lo, dtype=np.float64)


@dataclass
class AxisCandidate:
    """One extent-consistent, right-handed splat→box mapping."""

    rotation_xyzw: tuple
    scale: float
    assignment: tuple[int, int, int]  # splat axis index for (box X, Y, Z)
    signs: tuple[int, int]  # (s_up, s_h1)
    consistency: float  # max/min of per-axis ratios (1.0 = perfect)
    residual_m: list  # (dim, |scale*ext - dim|) pairs sorted by dim desc


def axis_mapping_candidates(
    box, splat_extents: np.ndarray
) -> list[AxisCandidate]:
    """Enumerate extent-consistent right-handed mappings of the splat's
    coordinate axes onto the box axes. Per assignment, four sign candidates
    (s_up, s_h1) ∈ {±1}² with the third axis forced by right-handedness —
    exactly the P1 probe's candidate set. Ordered: assignments by
    consistency (extent-best first), signs in the fixed order
    (+,+), (+,−), (−,+), (−,−) — so candidates[0] is the extent-best
    default ("RoomPlan's" conventional mapping)."""
    R = box.transform[:3, :3]
    bx, by = R[:, 0].copy(), R[:, 1].copy()
    dims = np.asarray(box.dimensions, dtype=np.float64)
    ext = np.maximum(np.asarray(splat_extents, dtype=np.float64), 1e-9)

    assignments = []
    for i_up in range(3):
        for i_x in range(3):
            if i_x == i_up:
                continue
            i_z = 3 - i_up - i_x
            ratios = np.array([
                dims[0] / ext[i_x], dims[1] / ext[i_up], dims[2] / ext[i_z]
            ])
            consistency = float(ratios.max() / ratios.min())
            assignments.append(((i_x, i_up, i_z), consistency, float(np.median(ratios)), ratios))
    assignments.sort(key=lambda a: (a[1], a[0]))
    best_consistency = assignments[0][1]
    kept = [a for a in assignments if a[1] <= max(_AXIS_RATIO_TOL, best_consistency)]

    out: list[AxisCandidate] = []
    eye = np.eye(3)
    for (i_x, i_up, i_z), consistency, scale, _ratios in kept:
        e_up, e_x, e_z = eye[i_up], eye[i_x], eye[i_z]
        if float(np.dot(np.cross(e_up, e_x), e_z)) < 0:
            e_z = -e_z
        E = np.column_stack([e_up, e_x, e_z])
        resid = sorted(
            (
                (float(dims[1]), abs(scale * ext[i_up] - float(dims[1]))),
                (float(dims[0]), abs(scale * ext[i_x] - float(dims[0]))),
                (float(dims[2]), abs(scale * ext[i_z] - float(dims[2]))),
            ),
            key=lambda p: -p[0],
        )
        residual = [round(r, 4) for _d, r in resid]
        for s_up, s_x in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
            U = s_up * by
            H1 = s_x * bx
            H2 = np.cross(U, H1)
            M = np.column_stack([U, H1, H2])
            R_world = M @ E.T
            out.append(AxisCandidate(
                rotation_xyzw=tuple(float(c) for c in rotmat_to_quat(R_world)),
                scale=scale,
                assignment=(i_x, i_up, i_z),
                signs=(s_up, s_x),
                consistency=consistency,
                residual_m=residual,
            ))
    return out


def _partner_index(candidates: list[AxisCandidate], idx: int) -> int | None:
    """The 180°-about-box-vertical partner of candidates[idx]: same
    assignment, same s_up, opposite s_h1."""
    c = candidates[idx]
    for j, other in enumerate(candidates):
        if (
            j != idx
            and other.assignment == c.assignment
            and other.signs[0] == c.signs[0]
            and other.signs[1] == -c.signs[1]
        ):
            return j
    return None


def score_candidates_at_center(
    candidates: list[AxisCandidate],
    center: np.ndarray,
    local_points: np.ndarray,
    appearance,
    views: list[tuple],  # (evidence, intrinsics, pose, rgb)
) -> list[float | None]:
    """Mean combined score per candidate across the (non-degenerate) views.
    None when no view produced a score."""
    out: list[float | None] = []
    for cand in candidates:
        scores = []
        for evidence, intrinsics, pose, rgb in views:
            result = reproject.score_placement(
                local_points=local_points,
                rotation_xyzw=cand.rotation_xyzw,
                translation=center,
                scale=cand.scale,
                mask=evidence,
                intrinsics=intrinsics,
                pose=pose,
                appearance=appearance,
                rgb=rgb,
            )
            scores.append(reproject.combined_score(result))
        out.append(float(np.mean(scores)) if scores else None)
    return out


# ---------------------------------------------------------------------------
# The box-anchored object
# ---------------------------------------------------------------------------

def _box_dict(box, box_index: int) -> dict:
    """The manifest's roomplan_box provenance block."""
    return {
        "box_id": f"box_{box_index:02d}",
        "identifier": box.identifier,
        "category": box.category,
        "confidence": box.confidence,
        "attributes": box.attributes,
        "dims": [round(float(d), 4) for d in box.dimensions],
        "yaw_rad": round(float(box.yaw_rad), 4),
        "center_world": [round(float(c), 4) for c in box.center_world],
    }


def build_box_object(
    *,
    box,
    box_index: int,
    object_id: str,
    associations: list[BoxAssociation],
    ctx,
    allow_scoring: bool = True,
) -> dict:
    """One manifest object from one RoomPlan box. Never raises: any missing
    evidence degrades (extent-best mapping, or the honest no_appearance
    inventory entry)."""
    entry_base = {
        "object_id": object_id,
        "label": box.category,
        "roomplan_box": _box_dict(box, box_index),
        "extent_m_sorted": sorted(
            (round(float(d), 4) for d in box.dimensions), reverse=True
        ),
        "deduped_observations": 0,
    }

    best_view = None
    splat = None
    for assoc in associations:  # already sorted best-first
        candidate_splat = ctx.get_splat(assoc.obs["splat_gcs_uri"])
        if candidate_splat is not None:
            best_view, splat = assoc, candidate_splat
            break

    if best_view is None:
        return {
            **entry_base,
            "placed": False,
            "method": None,
            "reason": "no_appearance",
            "splat_gcs_uri": None,
            "source": None,
            "world_transform": None,
            "quality": {
                "frames_observed": len(associations),
                "score": max((a.obs["score"] for a in associations), default=None),
            },
        }

    extents = splat_axis_extents(splat)
    candidates = axis_mapping_candidates(box, extents)
    center = np.asarray(box.center_world, dtype=np.float64)

    quality: dict = {
        "frames_observed": len(associations),
        "score": best_view.obs["score"],
        "association_overlap": round(best_view.overlap, 4),
    }

    scores: list[float | None] = [None] * len(candidates)
    scoreable_views: list[tuple] = []
    if allow_scoring:
        appearance = (
            ctx.get_appearance(best_view.obs["splat_gcs_uri"])
            if ctx.get_appearance is not None else None
        )
        for assoc in associations:
            if assoc.in_frame_fraction < _BOX_SCORE_MIN_INFRAME:
                continue  # degenerate view: skip, never average (P1)
            cam = ctx.get_camera(assoc.frame_index)
            evidence = ctx.evidence_for(assoc.frame_index, assoc.mask_index)
            if cam is None or evidence is None:
                continue
            pose, intrinsics = cam
            rgb = (
                ctx.get_rgb(assoc.frame_index)
                if (appearance is not None and ctx.get_rgb is not None) else None
            )
            scoreable_views.append((evidence, intrinsics, pose, rgb))
        if scoreable_views:
            scores = score_candidates_at_center(
                candidates, center, splat, appearance, scoreable_views
            )
    quality["axis_scored_views"] = len(scoreable_views)
    quality["axis_candidates"] = len(candidates)

    chosen = 0  # extent-best default: first assignment, signs (+, +)
    splat_axis_resolved = False
    facing_flag = False
    numeric = [(i, s) for i, s in enumerate(scores) if s is not None]
    if len(numeric) >= 2:
        ranked = sorted(numeric, key=lambda p: (-p[1], p[0]))
        margin = ranked[0][1] - ranked[1][1]
        quality["axis_margin"] = round(margin, 4)
        if margin >= _AXIS_MARGIN:
            chosen = ranked[0][0]
            splat_axis_resolved = True
        else:
            partner = _partner_index(candidates, chosen)
            if (
                partner is not None
                and scores[chosen] is not None
                and scores[partner] is not None
                and scores[partner] >= scores[chosen] + _FACING_FLAG_MARGIN
            ):
                # The scorer prefers the anti-RoomPlan facing, but not
                # decisively enough to ship: flag it, ship RoomPlan's
                # conventional mapping (flag-only v1).
                facing_flag = True
    if scores[chosen] is not None:
        quality["axis_score"] = round(float(scores[chosen]), 4)

    cand = candidates[chosen]
    return {
        **entry_base,
        "sam_label": best_view.obs.get("label"),
        "placed": True,
        "method": "roomplan_box",
        "position_source": "roomplan_box",
        "rotation_source": "roomplan_box",
        "splat_gcs_uri": best_view.obs["splat_gcs_uri"],
        "source": {
            "frame_index": best_view.frame_index,
            "mask_index": best_view.mask_index,
        },
        "world_transform": {
            "position": [float(c) for c in center],
            "rotation_xyzw": list(cand.rotation_xyzw),
            "scale": float(cand.scale),
        },
        "splat_axis_resolved": splat_axis_resolved,
        "facing_flag": facing_flag,
        "box_fit_residual": cand.residual_m,
        "constraints_applied": ["roomplan_box"],
        "quality": quality,
    }


# ---------------------------------------------------------------------------
# Box-duplicate suppression
# ---------------------------------------------------------------------------

def center_inside_box(position, box, margin_m: float | None = None) -> bool:
    m = _BOX_SUPPRESS_MARGIN_M if margin_m is None else margin_m
    R = box.transform[:3, :3]
    t = box.transform[:3, 3]
    local = R.T @ (np.asarray(position, dtype=np.float64) - t)
    half = np.asarray(box.dimensions, dtype=np.float64) / 2.0 + m
    return bool(np.all(np.abs(local) <= half))


def find_suppressing_box(
    obj: dict, boxes: list, matched_box_indices: set[int]
) -> int | None:
    """The lowest-index MATCHED box whose volume contains a placed non-box
    object's center with a family-compatible label, or None."""
    wt = obj.get("world_transform") or {}
    pos = wt.get("position")
    if not obj.get("placed") or pos is None:
        return None
    for bi in sorted(matched_box_indices):
        box = boxes[bi]
        if not family_compatible(box.category, obj.get("label")):
            continue
        if center_inside_box(pos, box):
            return bi
    return None
