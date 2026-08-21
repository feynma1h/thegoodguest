"""Box-anchored placement — RoomPlan boxes as the object skeleton
(decision 0077).

For covered furniture categories the RoomPlan box IS the measurement:
position, extent, upright, and yaw were operator-verified 9/9 (0076), while
the shipped SAM-3D-layout rotation measured ~90° yaw-wrong on the real bed
and depth_fit halved its width (visible-region truncation — measured as
collateral by 0077's scoring probe). So a box-anchored object takes
position/extent/upright/yaw from the box; SAM 3D contributes APPEARANCE
only (the splat from the best associated view), and the one genuinely
unknown DOF — how the splat's per-reconstruction-ARBITRARY canonical frame
sits inside the box — splits into two bits with two different instruments:

  * the ASSIGNMENT (which splat axis lies along which box axis) is scored
    by cloud alignment against the observation's own LiDAR cloud, in world
    space where truncation is harmless (decision 0081; every crop-space
    appearance variant measured unable to separate any box). Candidates are
    filtered first by the layout's up AXIS LINE, sign-agnostic
    (PLACEMENT_AXIS_UP_MAX_DEG), and the winner ships only with a clear
    margin (PLACEMENT_AXIS_MARGIN, default 0.10); below it the extent-best
    mapping ships with `splat_axis_resolved: false`;
  * the 180° SIGN, on which the cloud is near-degenerate, is READ from the
    layout ROTATION — the only channel that saw which side the camera
    photographed — gated on how far the chosen mapping sits from it
    (PLACEMENT_FACING_SIGN_MAX_RESIDUAL_DEG; see `resolve_facing_sign` and
    decision 0171). Past the gate the two systems disagree about the
    assignment rather than the sign, the layout has no standing, and the
    fixed (+,+) convention stands with `facing_sign_resolved: false`.
    Reading it is not acting on it: the preference is recorded on every
    capture and applied only under PLACEMENT_FACING_SIGN_APPLY, because it
    is measured right on the two objects the operator reported and wrong on
    a third, with nothing it reports separating them.

The appearance instrument keeps one job: when it prefers the shipped
mapping's 180° partner (= the anti-RoomPlan facing — a cuboid's 180° yaw is
a self-symmetry, so the mapping partner and the box-yaw flip are the same
rotation), `facing_flag: true` records the disagreement and nothing moves.
It stays FLAG-ONLY (the 0067 lock-6 precedent) for a measured reason:
0104 found it preferring the WRONG answer on both signs the operator's walk
proved wrong. Two regime facts that probe pinned still hold for it —
position precedes rotation (at a 0.79 m-off centre the scorer prefers
UPSIDE-DOWN, so candidates are only ever scored at box-quality centres),
and degenerate views are SKIPPED rather than averaged (a 1.4 m view of the
2 m bed zeroes tier 1 for every box-frame candidate).

Scale stays UNIFORM (the uniform-vs-per-axis-scale A/B on the first real
RoomPlan rooms, decision 0080: per-axis stretch amplified truncation),
so a mis-proportioned splat necessarily overshoots its box on some axis.
That overshoot is declared as a `splat_clip` volume rather than hidden by
moving or rescaling the object — see `splat_clip_block` and decision 0104.

Association projects each box's footprint into each sampled frame (poses +
intrinsics) and matches SAM masks by footprint overlap + a RoomPlan↔SAM
label-family map; greedy best-match, deterministic. Every associated
observation is CONSUMED by its box — one object per box by construction
(the operator's one-object-one-reconstruction corollary).

WHICH of a box's associations supplies the appearance is a separate
question from which observations it consumes, and the overlap sort does not
answer it: overlap describes the box's projected footprint, not how well
the object was photographed, so it belongs to the family of input measures
0197 retired. `select_arm` answers it on the OUTPUT side instead, against
the one measurement in this system that is not itself a fabrication — the
box — and ships behind PERCEPTION_ARM_SELECT, default off (decision 0204). Boxes with no
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
# substantially in-frame (the degenerate-view lesson: the f164 close view
# zeroes tier 1 — measured in-frame fraction 0.0 vs f129's 0.63).
_BOX_SCORE_MIN_INFRAME = float(os.environ.get("PLACEMENT_BOX_SCORE_MIN_INFRAME", "0.5"))

# How far a box's own up axis may tilt off the world vertical before its
# extents lose their axis semantics (decision 0096's trigger). RoomPlan
# boxes are pure-yaw by construction — measured on the spike room's 9
# boxes, worst |up_y - 1| = 1e-7, i.e. ~0.03°, so this is not a threshold
# real data sits near; it is the gate that keeps a tilted box from
# claiming a height it does not have.
_BOX_UP_MAX_TILT_DEG = float(os.environ.get("PLACEMENT_BOX_UP_MAX_TILT_DEG", "5"))

# Extent-consistency bound for an axis assignment: max/min of the per-axis
# box-dim / splat-extent ratios. Near-equal extents keep several assignments
# alive — exactly the "enumerate all" clause.
_AXIS_RATIO_TOL = float(os.environ.get("PLACEMENT_AXIS_RATIO_TOL", "1.6"))

# The winning ASSIGNMENT's best cloud score must beat every other
# assignment's best by this to ship (decision 0081: the margin gate keeps
# its value and its meaning — refuse coin flips — but gates the assignment
# DOF, the one the cloud instrument actually measures; the appearance
# margin the design probe achieved never materialized live — 0.0018-0.089
# on the first real RoomPlan rooms against the same 0.10 gate).
_AXIS_MARGIN = float(os.environ.get("PLACEMENT_AXIS_MARGIN", "0.10"))

# Axis-level up filter (decision 0081): a candidate must map the layout
# prior's splat-up direction to within this many degrees of the world
# vertical AXIS LINE (sign-agnostic — the layout's up AXIS measured
# trustworthy on 6/6 spike-room boxes, its SIGN measured wrong on one, so
# the sign is never trusted). Only applies when the observation carries a
# layout rotation; without one the extent-tolerance enumeration stands.
_AXIS_UP_MAX_DEG = float(os.environ.get("PLACEMENT_AXIS_UP_MAX_DEG", "45"))

# Cloud-NN score mapping: score = exp(-rms / sigma). Sigma chosen so the
# probe's measured assignment margins (0.15-0.47 correct, 0.002-0.014
# ambiguous) straddle the 0.10 gate exactly as adjudicated.
_AXIS_CLOUD_SIGMA = float(os.environ.get("PLACEMENT_AXIS_CLOUD_SIGMA", "0.05"))

# Translation-only NN passes per candidate when fitting the splat to the
# observation cloud (2 measured sufficient to settle correspondence).
_AXIS_CLOUD_ITERS = 2

# Below the ship margin, a partner (180°-about-vertical) preference this
# large over the shipped default raises facing_flag (flag-only v1).
_FACING_FLAG_MARGIN = float(os.environ.get("PLACEMENT_FACING_FLAG_MARGIN", "0.03"))

# How far the chosen mapping may sit from the observation's layout rotation
# before the layout loses standing to arbitrate the 180° sign (decision
# 0171). Shares its value with the up-axis filter above, and for the same
# reason: past 45° the two systems are describing different placements, not
# two signs of one. Measured on the four walk rooms, the two populations
# separate at 29°-70° with nothing between, so this sits in a gap.
_FACING_SIGN_MAX_RESIDUAL_DEG = float(
    os.environ.get("PLACEMENT_FACING_SIGN_MAX_RESIDUAL_DEG", "45")
)

# Whether a resolved sign is APPLIED or only recorded. Default off — the
# 0080 lock-6 / 0081 flag-only precedent, and here it is not caution but a
# measurement: of the three objects this leaf would turn on the walk rooms,
# two are exactly the ones the operator reported facing backwards and the
# third was already right, and no number the leaf reports separates them
# (their residuals are 2.9°, 28.9° and 15.4° — the wrong one sits between
# the two right ones). So it records its preference on every capture, which
# grows the adjudicated table for free, and turns nothing until a person
# has looked. Decision 0171.
_FACING_SIGN_APPLY = os.environ.get("PLACEMENT_FACING_SIGN_APPLY", "0") not in (
    "0", "false", "False", ""
)

# Suppression: a non-box object's center inside a matched box's volume
# (padded by this) with a compatible label is a box duplicate.
_BOX_SUPPRESS_MARGIN_M = float(os.environ.get("PLACEMENT_BOX_SUPPRESS_MARGIN_M", "0.1"))

# Cap on mask pixels sampled for the footprint-overlap test (deterministic
# stride — association needs a stable fraction, not an exact count).
_OVERLAP_MAX_PIXELS = int(os.environ.get("PLACEMENT_BOX_OVERLAP_MAX_PIXELS", "20000"))

# Splat-clip margin (decision 0104). A box-anchored splat is scaled by ONE
# uniform factor — the median of the three box-dim/splat-extent ratios —
# because per-axis stretch amplifies truncation (the same A/B as above).
# When the splat's PROPORTIONS are wrong (visible-region truncation, the
# residue 0080 recorded as model capability), a uniform factor that fits
# one axis necessarily overshoots another, and the overshoot leaves the
# measured box entirely: the acceptance review (decision 0085) found a bed
# reaching 0.44 m past its own footprint into the table and the chair, in
# two independent rooms.
#
# The overshoot is KNOWN-FALSE mass: the box is RoomPlan measurement the
# operator verified 9/9 (0076), so splat points outside it are model
# error, not evidence. Declining to render them is not falsifying the
# measurement — moving or rescaling the object to hide them would be
# (0082's reasoning, which this respects: position, extent and scale are
# untouched).
#
# The margin is measured, not guessed: at 0.10 m the clip removes nothing
# from 8 of the 14 reviewed box objects and trims exactly the four gross
# overhangs the operator named (bed 0.46 m, storage 0.25 m, chair 0.21 m,
# table 0.18 m). Tighter margins start gutting well-proportioned shells —
# at 0.0 m a table with a 3 cm overhang loses 60% of its points.
_SPLAT_CLIP_MARGIN_M = float(os.environ.get("PLACEMENT_SPLAT_CLIP_MARGIN_M", "0.10"))

# Below this removed fraction the clip is not worth declaring — the object
# is already inside its box and the field would be noise in every manifest.
_SPLAT_CLIP_MIN_FRACTION = float(
    os.environ.get("PLACEMENT_SPLAT_CLIP_MIN_FRACTION", "0.005")
)

# Percentile clip for splat extents along its LOCAL COORDINATE axes (the
# scoring probe's convention — candidates map coordinate axes onto box
# axes, so the extents must be measured along the same axes, not PCA axes).
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
#
# `nightstand` appears under BOTH table and storage: RoomPlan files a
# bedside cabinet as `storage`/StorageType cabinet while SAM calls it
# `nightstand`, so the 0077 map could never associate the two. Measured on
# rp7 (decision 0104): box_05 — a 0.58 x 0.64 x 0.48 storage box that IS
# the nightstand — shipped as no_appearance inventory while the same
# object also shipped as a free depth_fit splat, and the lamp and TV that
# rest on it inherited the disagreement. Association is greedy on overlap
# and each observation joins at most one box, so listing a label in two
# families costs nothing but lets the right box win.
_DEFAULT_FAMILIES = (
    "bed:bed"
    "|table:table,desk,nightstand"
    "|chair:chair,stool,bench"
    "|storage:cabinet,dresser,wardrobe,bookshelf,shelf,nightstand"
    "|sofa:sofa,couch"
    "|television:tv,television,monitor"
)
BOX_LABEL_FAMILIES: dict[str, frozenset[str]] = _parse_family_map(
    os.environ.get("PLACEMENT_BOX_LABEL_FAMILIES", _DEFAULT_FAMILIES)
)


# RoomPlan categories whose TOP is a surface other things rest on. Read
# twice: here, to decide which end of an under-filling splat to anchor, and
# by fusion's support pass, to decide which boxes are surfaces at all.
# Deliberately short — `chair`, `bed` and `sofa` are the categories whose
# absence is doing the work, and one joins on evidence from a real capture.
SURFACE_TOP_CATEGORIES = frozenset(
    s.strip().lower()
    for s in os.environ.get(
        "PLACEMENT_SURFACE_TOP_CATEGORIES", "table,storage"
    ).split(",")
    if s.strip()
)

# A splat filling less than this much of its box's measured height is
# missing mass at one end, and centring it puts half the deficit at each.
_SEAT_MIN_FILL = float(os.environ.get("PLACEMENT_BOX_SEAT_MIN_FILL", "0.85"))
_SEAT_PCTL = 1.0

# --- Arm selection (decision 0204) -----------------------------------------
# Whether an object's shipped reconstruction is CHOSEN among the arms it
# already has, or taken as the first association carrying a splat. Default
# off: the instrument below is measured on eight boxes and walked on two,
# and 0197 named an operator sitting as the gate before it turns anything.
_ARM_SELECT = os.environ.get("PERCEPTION_ARM_SELECT", "0") not in (
    "0", "false", "False", ""
)

# How much closer to spanning its measured box a challenger must render
# before it displaces the shipped arm. 0197 swept every multi-arm box in
# the four preserved rooms and the gains are bimodal: 0.000 six times, then
# 0.017, then 0.590. This sits at the GEOMETRIC CENTRE of that gap
# (sqrt(0.017 * 0.590) = 0.100), so it is fitted to neither end — 5.7x
# above the noise it must refuse and 5.9x below the case it must accept.
_ARM_FILL_MARGIN = float(
    os.environ.get("PERCEPTION_ARM_SELECT_FILL_MARGIN", "0.10")
)

# Arms scored per box, best-associated first. Each costs one splat parse
# and nothing else — no cloud, no appearance, no GPU — but a room whose
# sampler was told to spend its residue on boxes (0202) can hand a single
# box many, and the budget this pass spends is not its own.
_ARM_SELECT_MAX = int(os.environ.get("PERCEPTION_ARM_SELECT_MAX", "4"))


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


def splat_layout_rotation(obs: dict) -> np.ndarray | None:
    """The observation's LAYOUT rotation as a world matrix, or None when it
    carries none. This is SAM 3D's own statement of how the splat it
    reconstructed sits in the room: `placement.place_object` fits the cloud
    with `refine_similarity_nn(..., mode="translation")`, which moves the
    object and never turns it, so the world_transform of a `sam3d_layout`
    observation IS `rotation_world_from_layout` — the layout rotation under
    decision 0065's conventions, unmodified.
    Reads the same fields fusion's ray path trusts (world_transform
    on a placed depth_fit, world_rotation_xyzw on a demoted/ray
    observation)."""
    pl = obs.get("placement") or {}
    q = None
    if pl.get("rotation_source") == "sam3d_layout":
        wt = pl.get("world_transform") or {}
        q = wt.get("rotation_xyzw") or pl.get("world_rotation_xyzw")
    if q is None and pl.get("world_rotation_xyzw"):
        q = pl["world_rotation_xyzw"]
    if q is None:
        return None
    from roomstudio_schemas.pose_math import quat_to_rotmat

    return quat_to_rotmat(tuple(q))


def splat_up_local(obs: dict) -> np.ndarray | None:
    """The splat-local direction the observation's layout rotation calls
    world-up, or None when the observation carries no layout rotation."""
    R = splat_layout_rotation(obs)
    return None if R is None else R.T @ np.array([0.0, 1.0, 0.0])


def axis_up_angle_deg(cand: AxisCandidate, up_local: np.ndarray) -> float:
    """Angle of the candidate's mapped layout-up to the vertical AXIS LINE
    (sign-agnostic: min of the angles to +Y and −Y)."""
    from roomstudio_schemas.pose_math import quat_to_rotmat

    R = quat_to_rotmat(tuple(cand.rotation_xyzw))
    up_world = R @ np.asarray(up_local, dtype=np.float64)
    return float(np.degrees(np.arccos(np.clip(abs(up_world[1]), 0.0, 1.0))))


def axis_mapping_candidates(
    box, splat_extents: np.ndarray, up_local: np.ndarray | None = None
) -> list[AxisCandidate]:
    """Enumerate extent-consistent right-handed mappings of the splat's
    coordinate axes onto the box axes. Per assignment, four sign candidates
    (s_up, s_h1) ∈ {±1}² with the third axis forced by right-handedness —
    exactly the candidate set 0077's scoring probe used. Ordered:
    assignments by consistency (extent-best first), signs in the fixed order
    (+,+), (+,−), (−,+), (−,−) — so candidates[0] is the extent-best
    default ("RoomPlan's" conventional mapping).

    With `up_local` (the layout prior's splat-up direction, decision 0081):
    ALL SIX assignments are enumerated and filtered to those whose mapped
    up stays within PLACEMENT_AXIS_UP_MAX_DEG of the vertical axis line —
    extent consistency measured actively MISLEADING under visible-region
    truncation (the spike room's bed: the correct assignment sat at
    consistency 2.07, excluded by the 1.6 tolerance, while 1.53 shipped
    90° wrong), so when a trustworthy up axis exists it replaces the
    extent tolerance as the gate. Candidate ORDER is unchanged
    (consistency-ascending, so candidates[0] stays the extent-best
    surviving default). Without `up_local` the behaviour is byte-identical
    to the pre-0081 enumeration (the degrade lock)."""
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
    if up_local is None:
        kept = [a for a in assignments if a[1] <= max(_AXIS_RATIO_TOL, best_consistency)]
    else:
        kept = assignments  # all six; the axis-up filter prunes below

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
            cand = AxisCandidate(
                rotation_xyzw=tuple(float(c) for c in rotmat_to_quat(R_world)),
                scale=scale,
                assignment=(i_x, i_up, i_z),
                signs=(s_up, s_x),
                consistency=consistency,
                residual_m=residual,
            )
            if up_local is not None and axis_up_angle_deg(cand, up_local) > _AXIS_UP_MAX_DEG:
                continue
            out.append(cand)
    if up_local is not None and not out:
        # A near-diagonal layout up can fail the axis filter for every
        # mapping (the closest coordinate axis is at most 54.7° away).
        # Degrade to the extent-tolerance enumeration rather than crash.
        return axis_mapping_candidates(box, splat_extents, None)
    return out


def observation_cloud_from_ctx(ctx, frame_index: int, mask_index) -> np.ndarray | None:
    """The observation's world-frame LiDAR cloud via the RefinementContext,
    or None (no depth accessor / swept capture / no mask / sparse cloud —
    every miss degrades scoring to the up-filtered extent default)."""
    get_depth = getattr(ctx, "get_depth", None)
    if get_depth is None:
        return None
    payload = get_depth(frame_index)
    if payload is None:
        return None
    depth_raster, depth_confidence, depth_intrinsics = payload
    mask = ctx.mask_for(frame_index, mask_index)
    cam = ctx.get_camera(frame_index)
    if mask is None or cam is None:
        return None
    pose, _intr = cam
    import placement

    return placement.observation_world_cloud(
        depth_raster, depth_confidence, depth_intrinsics, mask, pose
    )


def score_candidates_cloud(
    candidates: list[AxisCandidate],
    local_points: np.ndarray,
    cloud: np.ndarray,
    scale: float,
) -> list[float | None]:
    """Cloud-alignment score per candidate (decision 0081): the splat under
    the candidate rotation, at the OBSERVATION's own fitted scale, is
    translation-fitted to the observation's LiDAR cloud (robust-center init
    + _AXIS_CLOUD_ITERS trimmed-NN translation passes — the same
    refine_similarity_nn the depth_fit path trusts) and scored
    exp(-rms / sigma). World-space by construction: immune to the crop-
    misalignment that defeats appearance scoring on truncated splats
    (measured — no appearance-scorer variant separated any box's axis
    mapping, across every view set tried (decision 0081); this does)."""
    from roomstudio_schemas.placement_math import (
        DegenerateGeometryError,
        refine_similarity_nn,
        robust_cloud_stats,
    )
    from roomstudio_schemas.pose_math import quat_to_rotmat

    try:
        c_local = robust_cloud_stats(local_points).center
    except DegenerateGeometryError:
        return [None] * len(candidates)
    cloud_c = cloud.mean(axis=0)
    out: list[float | None] = []
    for cand in candidates:
        R = quat_to_rotmat(tuple(cand.rotation_xyzw))
        t = cloud_c - scale * (R @ c_local)
        rms = None
        try:
            for _ in range(_AXIS_CLOUD_ITERS):
                _s, _R, t, rms = refine_similarity_nn(
                    local_points, cloud, scale, R, t, mode="translation"
                )
        except DegenerateGeometryError:
            rms = None
        out.append(None if rms is None else float(np.exp(-rms / _AXIS_CLOUD_SIGMA)))
    return out


def resolve_axis_mapping(
    candidates: list[AxisCandidate], cloud_scores: list[float | None]
) -> tuple[int, bool, float | None]:
    """(chosen_index, resolved, assignment_margin) — decision 0081's
    resolution policy. Scores group by ASSIGNMENT (the DOF the cloud
    instrument measures; 180° sign twins are cloud-near-degenerate —
    measured 0.003-0.006 apart on the spike room's bed — and stay with the
    fixed (+,+)-first convention 0077's probe called RoomPlan's
    conventional mapping, which measured 5/5 on the corrected truth table).
    The winning
    assignment ships only when its best score beats every other
    assignment's best by _AXIS_MARGIN; otherwise the extent-best surviving
    assignment (candidates[0]) stands. chosen_index is always the FIRST
    candidate of the chosen assignment in candidate order (+,+ first)."""
    by_assign: dict[tuple, list[int]] = {}
    for i, c in enumerate(candidates):
        by_assign.setdefault(c.assignment, []).append(i)
    default_assign = candidates[0].assignment if candidates else None
    group_best: dict[tuple, float] = {}
    for a, idxs in by_assign.items():
        vals = [cloud_scores[i] for i in idxs if cloud_scores[i] is not None]
        if vals:
            group_best[a] = max(vals)
    ranked = sorted(
        group_best.items(), key=lambda kv: (-kv[1], min(by_assign[kv[0]]))
    )
    if len(ranked) < 2:
        return (by_assign[default_assign][0], False, None)
    margin = ranked[0][1] - ranked[1][1]
    if margin >= _AXIS_MARGIN:
        return (by_assign[ranked[0][0]][0], True, float(margin))
    return (by_assign[default_assign][0], False, float(margin))


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


def resolve_facing_sign(
    candidates: list[AxisCandidate], chosen: int, layout_rotation: np.ndarray | None
) -> tuple[int, bool, float | None, float | None]:
    """(preferred_index, resolved, residual_deg, separation_deg) — 0171.

    Reports which sign the layout prefers. Whether that preference is acted
    on is the caller's decision and `_FACING_SIGN_APPLY`'s default is off;
    this function is the instrument, not the policy.

    The assignment is settled by the cloud (0081); this settles the one bit
    the cloud is near-degenerate on, the 180° sign, and it settles it from
    the only channel that ever saw which side the camera photographed.

    A reconstruction is made FROM one frame, so SAM 3D's layout rotation is
    a statement about which way the object was facing when it was
    photographed. Box placement re-derives orientation from the measured
    box and discards it — and because `resolve_axis_mapping` always returns
    the first candidate of the winning assignment, the sign that ships is
    the fixed (+,+) convention, which lands on the layout's answer about
    half the time. Measured on the four preserved walk rooms: the shipped
    rotation is the layout's exact 180° partner on 8 of the 16 box
    placements that carry a layout.

    So: measure the rotation distance from the layout to each of the two
    sign candidates and take the nearer. The RESIDUAL — the distance to
    that nearer one — is the gate, and it is the honest one, because the
    layout can only arbitrate a sign along an axis both systems agree on.
    A residual near zero means the two describe the same placement and
    differ in the one bit; a large residual means they disagree about the
    ASSIGNMENT, where the cloud is the better instrument and the layout has
    no standing. On real data the two cases separate with nothing in
    between — residuals run 2.9°-28.9° on eight objects and 70°-177° on the
    other eight — so the gate is reading a gap, not slicing a continuum.

    No separate margin knob: a residual inside the gate forces a large
    separation, since the two candidates are 180° apart (measured
    separations are 142°-174° inside the gate and 2°-43° outside it).

    Abstention is the default everywhere: no layout, no partner candidate,
    or a residual past the gate all leave `chosen` exactly as it arrived.
    """
    from roomstudio_schemas.pose_math import quat_to_rotmat, rotation_angle_deg

    if layout_rotation is None or not candidates:
        return (chosen, False, None, None)
    partner = _partner_index(candidates, chosen)
    if partner is None:
        return (chosen, False, None, None)
    d_chosen = rotation_angle_deg(
        quat_to_rotmat(tuple(candidates[chosen].rotation_xyzw)), layout_rotation
    )
    d_partner = rotation_angle_deg(
        quat_to_rotmat(tuple(candidates[partner].rotation_xyzw)), layout_rotation
    )
    residual = min(d_chosen, d_partner)
    separation = abs(d_chosen - d_partner)
    if residual > _FACING_SIGN_MAX_RESIDUAL_DEG:
        return (chosen, False, residual, separation)
    return (
        (chosen if d_chosen <= d_partner else partner),
        True,
        residual,
        separation,
    )


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

def box_extent_axes(box) -> dict | None:
    """Which of the box's three extents is the UP one — or None when the
    box's own geometry does not warrant the claim (decision 0096's named
    trigger; see `_box_dict` for what ships).

    RoomPlan's box frame is y-up, so `dimensions[1]` is the extent along
    local +Y and `dimensions[0]/[2]` span the footprint. That is only a
    statement about the WORLD vertical while local +Y IS world +Y, which
    is exactly what a pure-yaw transform gives (0076; the parser pins
    measure worst |up_y - 1| = 1e-7 across the spike room's 9 boxes). So
    the warrant is measured per box off the transform rather than assumed
    from the format: tilt the box past `_BOX_UP_MAX_TILT_DEG` and there is no
    up extent to name, so nothing is emitted and the consumer is back to
    the sorted triple it has today.

    The two horizontal extents ship DESCENDING and deliberately unnamed.
    RoomPlan does not fix which of local X/Z is the long one (see
    `RoomPlanBox.dimensions`), and there is no facing convention that
    would make one "width" and the other "depth" — so they are reported
    as a footprint pair, not as two named dimensions. Calling them width
    and depth would be the 0065 error again: a label certifying more than
    was measured.

    Returns None rather than a flagged block: absent is already the state
    every existing consumer handles, and an emitted-but-untrustworthy
    number is the failure 0096 exists to prevent.
    """
    R = np.asarray(box.transform, dtype=np.float64)[:3, :3]
    up_local = R[:, 1]
    norm = float(np.linalg.norm(up_local))
    if norm <= 0.0:
        return None
    # Angle between the box's own up axis and the world vertical. Signed,
    # not axis-line: an upside-down box has no "up" extent to report.
    cos_tilt = float(up_local[1]) / norm
    tilt_deg = float(np.degrees(np.arccos(float(np.clip(cos_tilt, -1.0, 1.0)))))
    if tilt_deg > _BOX_UP_MAX_TILT_DEG:
        return None
    dims = [float(d) for d in np.asarray(box.dimensions, dtype=np.float64)]
    if len(dims) != 3 or not all(d > 0.0 for d in dims):
        return None
    horizontal = sorted((dims[0], dims[2]), reverse=True)
    return {
        "up_m": round(dims[1], 4),
        "horizontal_m": [round(h, 4) for h in horizontal],
        "up_tilt_deg": round(tilt_deg, 4),
    }


def _box_dict(box, box_index: int) -> dict:
    """The manifest's roomplan_box provenance block.

    `dims` is RoomPlan's own local (x, y, z) order and stays that way —
    it is provenance. `extent_axes_m` is the additive companion that says
    which of those three is the vertical one, present only when the box's
    transform warrants it (see `box_extent_axes`). Everything else here is
    unchanged, so a reader that does not know the new key sees exactly the
    block it saw before.
    """
    block = {
        "box_id": f"box_{box_index:02d}",
        "identifier": box.identifier,
        "category": box.category,
        "confidence": box.confidence,
        "attributes": box.attributes,
        "dims": [round(float(d), 4) for d in box.dimensions],
        "yaw_rad": round(float(box.yaw_rad), 4),
        "center_world": [round(float(c), 4) for c in box.center_world],
    }
    axes = box_extent_axes(box)
    if axes is not None:
        block["extent_axes_m"] = axes
    return block


# ---------------------------------------------------------------------------
# Arm selection — which of an object's reconstructions ships (decision 0204)
# ---------------------------------------------------------------------------

@dataclass
class ArmFit:
    """One already-reconstructed arm, measured against its box."""

    index: int  # position in the association sort; 0 is what ships today
    fill: float  # rendered vertical span / the box's MEASURED height
    residual_m: float  # sum |scale*extent - dim| over the three box axes

    @property
    def fill_dist(self) -> float:
        """Distance from spanning the box exactly. Overshoot is penalised
        the same as truncation: mass outside the measurement is not legs."""
        return abs(self.fill - 1.0)


def arm_fit(box, box_index: int, object_id: str, assoc, ctx) -> ArmFit | None:
    """0197's two output-side checks for one arm, or None when it cannot be
    placed at all.

    Placed by production's own `build_box_object` with scoring OFF, which is
    the call 0197 measured the instrument under — a single-arm list has no
    partner views to score and the extent-best mapping is what an unscored
    box ships anyway. So this is the measured instrument rather than a
    relative of it, and it costs one splat parse: no cloud, no appearance,
    no GPU. `allow_scoring=False` is also the recursion guard — the scored
    path is the only one that selects.
    """
    pts = ctx.get_splat(assoc.obs["splat_gcs_uri"])
    if pts is None:
        return None
    entry = build_box_object(
        box=box, box_index=box_index, object_id=object_id,
        associations=[assoc], ctx=ctx, allow_scoring=False,
    )
    wt = entry.get("world_transform")
    height = float(box.dimensions[1])
    if not wt or height <= 0.0:
        return None
    span = _rendered_span(pts, wt["rotation_xyzw"], float(wt["scale"]), box)
    if span is None:
        return None
    return ArmFit(
        index=-1,
        fill=float((span[1] - span[0]) / height),
        residual_m=float(sum(entry.get("box_fit_residual") or [0.0])),
    )


def select_arm(*, box, box_index: int, object_id: str, associations: list, ctx):
    """Move the best-rendering arm to the front of `associations`, or leave
    the order alone. Returns `(associations, record | None)`.

    Today the first association carrying a splat ships, and the sort is by
    mask-hull overlap — an INPUT measure, computed before any reconstruction
    exists, and a close relative of the family 0197 retired. The second arm
    is reconstructed, uploaded, and never looked at. This looks at it.

    The claim is narrow and is the reason it can be made at all: the arm
    EXISTS, so it can be scored against something that is not itself a
    fabrication. The RoomPlan box is that thing — measured, not derived from
    any splat, and already trusted this way (0104 clips to it, 0148 seats
    against its faces). A reconstruction spanning 0.41 of its measured
    height is missing mass that one spanning 1.00 of it is not, whichever
    photograph produced it.

    Two output-side checks, both smaller-is-better, and BOTH must prefer the
    challenger:

      * `fill_dist` — how far the rendered span sits from the box's height —
        must improve by `_ARM_FILL_MARGIN`;
      * `residual_m` — the axis fit the entry already ships — must improve
        at all.

    Requiring agreement rather than combining them is what the measurement
    asks for. Over the eight multi-arm boxes in the four preserved rooms the
    two agree on seven; the eighth is the spike bed, where fill prefers the
    shipped arm and the residual prefers the other, and nobody has looked at
    either. A disagreement there is not a tie to be broken by weights, it is
    the instrument saying it cannot tell — the 0081 margin-gate posture, one
    stage later.

    Move-to-front rather than replacement, so only the chosen arm changes:
    `frames_observed` still counts every association and the facing check
    still scores every view it would have.
    """
    fits: list[ArmFit] = []
    for i, a in enumerate(associations):
        if len(fits) >= _ARM_SELECT_MAX:
            break
        f = arm_fit(box, box_index, object_id, a, ctx)
        if f is not None:
            fits.append(ArmFit(index=i, fill=f.fill, residual_m=f.residual_m))
    if len(fits) < 2:
        return associations, None

    best, record = choose_arm(fits)
    if best.index == fits[0].index:
        return associations, record
    reordered = (
        [associations[best.index]]
        + [a for i, a in enumerate(associations) if i != best.index]
    )
    return reordered, record


def choose_arm(fits: list[ArmFit]) -> tuple[ArmFit, dict]:
    """The decision, with the measurement already made. `fits[0]` is the
    arm that ships today.

    Separated from `select_arm` because the measurement needs splats and
    the decision needs eight numbers: the sweep those eight came from is
    committed as a fixture, so the rule is pinned against the real rooms
    without a gigabyte of PLY (tests/fixtures/arm_select/sweep.json).
    """
    shipped = fits[0]
    best = shipped
    for f in fits[1:]:
        gain = shipped.fill_dist - f.fill_dist
        if gain < _ARM_FILL_MARGIN:
            continue  # inside the noise the sweep measured
        if f.residual_m >= shipped.residual_m:
            continue  # the second check disagrees: refuse, do not weigh
        if gain > shipped.fill_dist - best.fill_dist:
            best = f  # strict, so ties keep the lower index
    return best, {
        "arms": len(fits),
        "shipped_fill": round(shipped.fill, 4),
        "shipped_residual_m": round(shipped.residual_m, 4),
        "chosen_rank": best.index,
        "chosen_fill": round(best.fill, 4),
        "chosen_residual_m": round(best.residual_m, 4),
        "fill_gain": round(shipped.fill_dist - best.fill_dist, 4),
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
    # Which arm ships, when the object has more than one (decision 0204).
    # Gated on the flag AND on `allow_scoring`, which is both the recursion
    # guard and the budget one: a starved scene loses this the way it loses
    # every other post-pass, and no preserved room pays for that — rp6g2,
    # the one room that budget-stops, has no multi-arm box at all.
    arm_record = None
    if _ARM_SELECT and allow_scoring:
        associations, arm_record = select_arm(
            box=box, box_index=box_index, object_id=object_id,
            associations=associations, ctx=ctx,
        )
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
    layout_rotation = splat_layout_rotation(best_view.obs)
    u_local = splat_up_local(best_view.obs)
    candidates = axis_mapping_candidates(box, extents, u_local)
    center = np.asarray(box.center_world, dtype=np.float64)

    quality: dict = {
        "frames_observed": len(associations),
        "score": best_view.obs["score"],
        "association_overlap": round(best_view.overlap, 4),
    }
    quality["axis_candidates"] = len(candidates)
    quality["axis_up_filtered"] = u_local is not None
    if arm_record is not None:
        quality["arm_select"] = arm_record

    # --- Assignment resolution: cloud-alignment instrument (0081). ------
    # The appearance instrument measured unable to separate ANY box on the
    # first real RoomPlan rooms (margins 0.0018-0.089 across every scorer
    # variant and view set); the observation's own LiDAR cloud separates
    # the assignment DOF at measured margins 0.15-0.47 where the geometry
    # is decisive, and refuses honestly (0.002-0.014) on near-cubic objects.
    chosen = 0  # extent-best surviving default, signs (+, +)
    splat_axis_resolved = False
    facing_flag = False
    if allow_scoring and candidates:
        cloud = observation_cloud_from_ctx(
            ctx, best_view.frame_index, best_view.mask_index
        )
        if cloud is not None:
            wt_obs = (best_view.obs.get("placement") or {}).get("world_transform") or {}
            s_obs = float(
                wt_obs.get("scale")
                or float(np.median([c.scale for c in candidates]))
            )
            cloud_scores = score_candidates_cloud(candidates, splat, cloud, s_obs)
            chosen, splat_axis_resolved, margin = resolve_axis_mapping(
                candidates, cloud_scores
            )
            quality["axis_cloud_points"] = int(cloud.shape[0])
            if margin is not None:
                quality["axis_margin"] = round(margin, 4)
            if cloud_scores[chosen] is not None:
                quality["axis_score"] = round(float(cloud_scores[chosen]), 4)

    # --- Sign resolution: the layout rotation (0171). Runs whether or not
    # scoring was affordable — it reads a channel already loaded for the up
    # filter and costs no IO — and abstains on its own residual, so a
    # budget-starved scene whose assignment was never vetted is protected
    # by the gate rather than by the budget.
    chosen_before_sign = chosen
    preferred, facing_sign_resolved, sign_residual, sign_separation = (
        resolve_facing_sign(candidates, chosen, layout_rotation)
    )
    if sign_residual is not None:
        quality["facing_sign_residual_deg"] = round(sign_residual, 2)
        quality["facing_sign_separation_deg"] = round(sign_separation, 2)
    if facing_sign_resolved and _FACING_SIGN_APPLY:
        chosen = preferred

    # --- Facing check (flag-only v1, semantics unchanged): the appearance
    # instrument still owns the 180°-partner leaf — the cloud is near-
    # degenerate there (measured 0.003-0.006 on the spike bed's sign twins).
    scoreable_views: list[tuple] = []
    if allow_scoring and candidates:
        partner = _partner_index(candidates, chosen)
        if partner is not None:
            appearance = (
                ctx.get_appearance(best_view.obs["splat_gcs_uri"])
                if ctx.get_appearance is not None else None
            )
            for assoc in associations:
                if assoc.in_frame_fraction < _BOX_SCORE_MIN_INFRAME:
                    continue  # degenerate view: skip, never average
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
                pair = [candidates[chosen], candidates[partner]]
                pair_scores = score_candidates_at_center(
                    pair, center, splat, appearance, scoreable_views
                )
                if (
                    pair_scores[0] is not None
                    and pair_scores[1] is not None
                    and pair_scores[1] >= pair_scores[0] + _FACING_FLAG_MARGIN
                ):
                    # The appearance scorer prefers the anti-RoomPlan
                    # facing, but that leaf never ships on appearance
                    # evidence alone: flag it, ship the conventional sign.
                    facing_flag = True
    quality["axis_scored_views"] = len(scoreable_views)

    cand = candidates[chosen]
    seat = vertical_seat_offset(box, splat, cand.rotation_xyzw, cand.scale)
    if seat is not None:
        dy, anchor, fill = seat
        center = center + np.array([0.0, dy, 0.0])
        quality["vertical_seat_m"] = round(dy, 4)
        quality["vertical_seat_anchor"] = anchor
        quality["box_height_fill"] = round(fill, 3)
    clip = splat_clip_block(box, splat, cand.rotation_xyzw, cand.scale, center)
    if clip is not None:
        quality["splat_clip_removed"] = clip["removed_fraction"]
    return {
        **entry_base,
        "sam_label": best_view.obs.get("label"),
        **({"splat_clip": clip} if clip is not None else {}),
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
        "facing_sign_resolved": facing_sign_resolved,
        **(
            {
                "facing_sign_source": "sam3d_layout",
                "facing_sign_preference": (
                    "flip" if preferred != chosen_before_sign else "keep"
                ),
                "facing_sign_applied": bool(_FACING_SIGN_APPLY),
            }
            if facing_sign_resolved
            else {}
        ),
        "facing_flag": facing_flag,
        "box_fit_residual": cand.residual_m,
        "constraints_applied": ["roomplan_box"],
        "quality": quality,
    }


# ---------------------------------------------------------------------------
# Box-duplicate suppression
# ---------------------------------------------------------------------------

def splat_clip_block(
    box, local_points: np.ndarray, rotation_xyzw, scale: float, position=None
) -> dict | None:
    """The `splat_clip` manifest block for a box-anchored object, or None
    when the splat already sits inside its measured box (decision 0104).

    The clip volume IS the RoomPlan box, grown by _SPLAT_CLIP_MARGIN_M. It
    is declared, never applied here: the splat asset ships untouched and a
    renderer that ignores the block reproduces today's picture exactly (the
    degrade lock). `removed_fraction` is measured on the real point set so
    the cost of the clip is recorded beside it rather than inferred.

    RoomPlan boxes are pure-yaw by construction (0076), so centre + dims +
    yaw fully determine the volume for any consumer; the block repeats them
    rather than making the renderer re-derive them from `roomplan_box`.
    """
    from roomstudio_schemas.pose_math import quat_to_rotmat

    if local_points is None or local_points.shape[0] == 0:
        return None
    R = quat_to_rotmat(tuple(rotation_xyzw))
    # The object's own position, which is the box centre unless the splat
    # was seated against one of the box's faces (see vertical_seat_offset).
    origin = np.asarray(
        box.center_world if position is None else position, dtype=np.float64
    )
    world = (float(scale) * (local_points @ R.T)) + origin
    Rb = np.asarray(box.transform[:3, :3], dtype=np.float64)
    local = (world - np.asarray(box.transform[:3, 3], dtype=np.float64)) @ Rb
    half = np.asarray(box.dimensions, dtype=np.float64) / 2.0 + _SPLAT_CLIP_MARGIN_M
    outside = ~np.all(np.abs(local) <= half, axis=1)
    fraction = float(outside.mean())
    if fraction < _SPLAT_CLIP_MIN_FRACTION:
        return None
    return {
        "kind": "roomplan_box",
        "margin_m": round(_SPLAT_CLIP_MARGIN_M, 4),
        "center_world": [round(float(c), 4) for c in box.center_world],
        "half_extents_m": [round(float(h), 4) for h in half],
        "yaw_rad": round(float(box.yaw_rad), 4),
        "removed_fraction": round(fraction, 4),
    }


def vertical_seat_offset(box, local_points: np.ndarray, rotation_xyzw, scale: float):
    """How far to slide a box-anchored splat vertically inside its measured
    box, or None when it fills the box's height (decision 0148).

    A reconstruction that under-fills its box is missing mass at ONE end —
    rp7's desk is a tabletop with the legs cut off at 0.42 of its measured
    height. Centring it splits that deficit evenly, which puts the object
    clear of the floor AND its top below the measurement: the desk floats
    0.225 m up, and the monitor resting on its measured top hovers 0.206 m
    over the surface anyone can see.

    Which end to keep follows from what the category's top IS. A table or a
    cabinet has a functional top surface — things rest on it, and fusion's
    support pass hands out contact heights from it — so its top must be the
    measured one and the missing mass hangs off the bottom. Everything
    else (a chair, a bed, a sofa) has only one contact worth being right,
    the floor, so it is seated on the box's floor.

    Not the observation's LiDAR cloud, which is the obvious candidate and
    measured unusable: the cloud is the VISIBLE surface, so it is
    top-biased on every object (a chair's cloud spans 0.47 m of a 1.08 m
    box) and matching to it would push well-fitting objects upward too.
    The box's own two faces are measurement, and one of them is a contact.
    """
    span = _rendered_span(local_points, rotation_xyzw, scale, box)
    if span is None:
        return None
    lo, hi = span
    box_lo = float(box.center_world[1]) - float(box.dimensions[1]) / 2.0
    box_hi = float(box.center_world[1]) + float(box.dimensions[1]) / 2.0
    height = box_hi - box_lo
    if height <= 0.0 or (hi - lo) >= _SEAT_MIN_FILL * height:
        return None
    topped = (box.category or "").strip().lower() in SURFACE_TOP_CATEGORIES
    dy = (box_hi - hi) if topped else (box_lo - lo)
    return float(dy), ("box_top" if topped else "box_floor"), float((hi - lo) / height)


def _rendered_span(local_points, rotation_xyzw, scale, box):
    """(lo, hi) world heights of a placed splat, percentile-clipped at both
    ends for the reason extents are everywhere else."""
    from roomstudio_schemas.pose_math import quat_to_rotmat

    if local_points is None or local_points.shape[0] < 8:
        return None
    R = quat_to_rotmat(tuple(rotation_xyzw))
    y = (float(scale) * (local_points @ R.T))[:, 1] + float(box.center_world[1])
    return (
        float(np.percentile(y, _SEAT_PCTL)),
        float(np.percentile(y, 100.0 - _SEAT_PCTL)),
    )


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
