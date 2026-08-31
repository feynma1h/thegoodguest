"""Per-object best-frame selection over SAM 3.1's tracked segments.

    from track_selection import Detection, select_best_frames
    choices = select_best_frames(dets, get_rgb=..., timestamps=...)
    choices["nightstand#2"].frame_index   # the frame to hand SAM 3D

WHAT THIS IS AND WHAT IT IS NOT. `census_sampling.select_frames_census` picks a
frame BUDGET for a whole room, and every pass in it takes a RoomPlan box as its
argument -- which is why 0271 measured that nine of fourteen object kinds are
invisible to it. This module answers the other question, per object rather than
per room: given the frames a tracked object actually appears in, which single
frame is the best photograph of it. It needs no box, so it reaches the unboxed
nine, and it needs no GPU, so it is testable offline.

THE UNIT OF SELECTION IS THE CALLER'S CHOICE, DELIBERATELY. Every detection
carries an opaque `object_key` and this module never derives one. 0279 measured
that SAM 3.1's instance ids are unstable across a revisit -- mean box purity
0.6404, with four of six measured boxes arriving as three ids in disjoint frame
windows -- so `f"{concept}#{obj_id}"` names a FRAGMENT, not an object, and a
selector that hardcoded it would silently return three best frames for one
nightstand. Keying is therefore a decision made above this module and visible in
its input. `instance_key` spells the raw tracked instance and
`merge_nested_instances` collapses the half of the problem that is exactly
answerable; neither is applied for you.

TWO KINDS OF DUPLICATE, AND ONLY ONE IS SOLVABLE HERE. Fragments in DISJOINT
frame windows (0279) share no frame, so no mask comparison can reach them and
0280 measured the geometric route as insufficient. Instances that SHARE frames
are a different case: their masks either coincide or they do not, which is an
observation rather than an inference. Measured on the preserved capture, 14 of
48 overlapping instance pairs sit at containment 0.996-1.000 and the next
highest is 0.511 -- one object found by two different text prompts, since the
tracker runs one concept per pass. That gap is what `NESTED_CONTAINMENT` stands
in, and it is why the occlusion filter below cannot use a bare union.

Consumers: tools/track_select.py, tests/test_track_selection.py.
"""
from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

import numpy as np

__all__ = [
    "Detection",
    "SelectionConfig",
    "FrameScore",
    "ObjectChoice",
    "DEFAULT_CONFIG",
    "instance_key",
    "merge_nested_instances",
    "select_best_frames",
    "apply_key_map",
]


# ── configuration ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SelectionConfig:
    """Every threshold and weight, in one place and overridable per call.

    Fractions rather than pixels throughout, so the same configuration is
    correct whether the masks arrive at full resolution or at the stride-4
    raster /track actually writes.
    """

    # -- stage 1, hard filters. Any rule firing rejects the frame FOR THAT
    # OBJECT only; the same frame may serve another object in the same pass.
    border_margin_frac: float = 0.025
    min_area_frac: float = 0.005
    max_occluded_frac: float = 0.10
    # When is another mask in this frame NOT an occluder? The bar sits in a
    # measured gap rather than on a tuning curve: over the preserved capture 14
    # overlapping instance pairs score 0.996-1.000 and the next highest scores
    # 0.511, with nothing in between.
    #
    # The two consumers ask it in different DIRECTIONS, deliberately.
    # `_occluder_union` asks only whether the other mask CONTAINS mine, because
    # that direction is sound and the other is not: if another reading spans my
    # whole extent then every pixel of me was still segmented as me, so I am
    # fully visible. The converse -- a small mask inside my large one -- is
    # genuinely ambiguous between a duplicate sub-reading and a small object
    # sitting in front of me, and mask geometry cannot separate those, so it is
    # left counted as occlusion. `merge_nested_instances` asks symmetrically,
    # since for identity a sub-part and a super-part are the same finding.
    nested_containment: float = 0.90

    # -- stage 2, soft scoring. Weights need not sum to 1; the score is
    # normalised by the weight actually spent, so a term that cannot be
    # measured for a frame drops out instead of scoring zero.
    w_sharpness: float = 0.30
    w_size: float = 0.25
    w_solidity: float = 0.20
    w_centeredness: float = 0.15
    w_temporal: float = 0.10

    size_cap_frac: float = 0.35
    # A run breaks when consecutive SURVIVING frames are further apart than
    # this. Seconds when the caller supplies timestamps, frames otherwise.
    run_break_seconds: float = 1.0
    run_break_frames: int = 8

    def weights(self) -> dict[str, float]:
        return {
            "sharpness": self.w_sharpness,
            "size": self.w_size,
            "solidity": self.w_solidity,
            "centeredness": self.w_centeredness,
            "temporal": self.w_temporal,
        }


DEFAULT_CONFIG = SelectionConfig()

TERMS = ("sharpness", "size", "solidity", "centeredness", "temporal")


# ── input and output records ─────────────────────────────────────────────────


@dataclass(frozen=True)
class Detection:
    """One object seen in one frame.

    `mask` is a 2-D boolean raster in whatever resolution it was stored at.
    Nothing here needs to be told which resolution: the filters and the
    geometric terms are fractions of the raster, and the sharpness crop scales
    itself against the RGB frame it is handed, so a change to `MASK_STRIDE`
    upstream cannot silently move a threshold here.
    """

    object_key: str
    frame_index: int
    mask: np.ndarray


@dataclass
class FrameScore:
    """One (object, frame) pair, and everything that decided it."""

    frame_index: int
    kept: bool
    reasons: list[str] = field(default_factory=list)
    raw: dict[str, float] = field(default_factory=dict)
    normalized: dict[str, float] = field(default_factory=dict)
    score: float = 0.0


@dataclass
class ObjectChoice:
    """The winning frame for one object, and the trail to it."""

    object_key: str
    frame_index: int | None
    score: float
    is_fallback: bool
    n_frames: int
    n_kept: int
    frames: list[FrameScore] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "object_key": self.object_key,
            "frame_index": self.frame_index,
            "score": round(self.score, 6),
            "is_fallback": self.is_fallback,
            "n_frames": self.n_frames,
            "n_kept": self.n_kept,
            "terms": {
                k: round(v, 6)
                for k, v in next(
                    (f.normalized for f in self.frames if f.frame_index == self.frame_index),
                    {},
                ).items()
            },
        }


# ── keying ───────────────────────────────────────────────────────────────────


def instance_key(concept: str, obj_id: int) -> str:
    """The raw tracked instance. A FRAGMENT: see 0279 before treating one as an
    object. Never called by this module -- it is offered to the caller."""
    return f"{concept}#{obj_id}"


def merge_nested_instances(
    detections: Iterable[Detection], config: SelectionConfig = DEFAULT_CONFIG
) -> dict[str, str]:
    """Group instances whose masks coincide in the frames they share.

    Returns {object_key: merged_key}, where the merged key is the
    lexicographically smallest member -- deterministic, since 0062's law makes
    a retry's selection have to match its own cache. Containment is asked
    SYMMETRICALLY here, unlike in the occlusion filter: for identity it does not
    matter which of two masks is the sub-part.

    SOLVES ONE HALF OF THE IDENTITY PROBLEM AND SAYS SO. Two instances that
    share a frame either segment the same pixels or they do not, and that is
    measured, not inferred. Two instances in disjoint windows -- 0279's
    `nightstand#1/#2/#3` -- share no frame, so this cannot see them and
    returns them unmerged. 0280 measured the obvious geometric route to that
    other half and found it insufficient; nothing here improves on it.
    """
    by_frame: dict[int, list[Detection]] = {}
    for d in detections:
        by_frame.setdefault(d.frame_index, []).append(d)

    inter: dict[tuple[str, str], int] = {}
    smaller: dict[tuple[str, str], int] = {}
    for dets in by_frame.values():
        for i, a in enumerate(dets):
            for b in dets[i + 1:]:
                if a.object_key == b.object_key or a.mask.shape != b.mask.shape:
                    continue
                overlap = int(np.logical_and(a.mask, b.mask).sum())
                if overlap == 0:
                    continue
                pair = tuple(sorted((a.object_key, b.object_key)))
                inter[pair] = inter.get(pair, 0) + overlap
                smaller[pair] = smaller.get(pair, 0) + min(
                    int(a.mask.sum()), int(b.mask.sum())
                )

    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: str, y: str) -> None:
        rx, ry = find(x), find(y)
        if rx != ry:
            # Smaller name wins, so the merged key does not depend on order.
            lo, hi = sorted((rx, ry))
            parent[hi] = lo

    for d in detections:
        find(d.object_key)
    for pair, overlap in sorted(inter.items()):
        if smaller[pair] and overlap / smaller[pair] >= config.nested_containment:
            union(*pair)
    return {k: find(k) for k in sorted(parent)}


# ── geometry, all in the mask raster's own resolution ────────────────────────


def mask_bbox(mask: np.ndarray) -> tuple[int, int, int, int] | None:
    """(x0, y0, x1, y1) inclusive, or None for an empty mask.

    The mask's OWN bounding box, deliberately, and not the `bbox_px` that
    travels in tracks.json: that field is upstream's detector box
    (`out_boxes_xywh`) rather than a bound on the mask, and the two disagree --
    one preserved frame carries a mask of 28,277 px inside a declared box of
    1,653x688. A border test is a statement about the segmentation, so it has
    to read the segmentation.
    """
    rows = np.flatnonzero(mask.any(axis=1))
    cols = np.flatnonzero(mask.any(axis=0))
    if rows.size == 0 or cols.size == 0:
        return None
    return int(cols[0]), int(rows[0]), int(cols[-1]), int(rows[-1])


def _hull_area(mask: np.ndarray) -> float:
    """Area of the convex hull of the mask's true pixels.

    Per-row extremes are enough and are exact: a true pixel strictly between
    its row's leftmost and rightmost is a convex combination of them, so it
    can never be a hull vertex. That is at most 2 points per row instead of
    every pixel, and it costs no accuracy.
    """
    pts: list[tuple[float, float]] = []
    for y in np.flatnonzero(mask.any(axis=1)):
        xs = np.flatnonzero(mask[y])
        pts.append((float(xs[0]), float(y)))
        if xs[-1] != xs[0]:
            pts.append((float(xs[-1]), float(y)))
    if len(pts) < 3:
        return 0.0
    pts = sorted(set(pts))

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[tuple[float, float]] = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper: list[tuple[float, float]] = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    hull = lower[:-1] + upper[:-1]
    if len(hull) < 3:
        return 0.0
    area = 0.0
    for i, (x0, y0) in enumerate(hull):
        x1, y1 = hull[(i + 1) % len(hull)]
        area += x0 * y1 - x1 * y0
    return abs(area) / 2.0


def _laplacian_variance(gray: np.ndarray) -> float:
    """Variance of the Laplacian by direct convolution -- scipy is not in the
    perception image, which `census_sampling.frame_is_usable` already notes."""
    if gray.shape[0] < 3 or gray.shape[1] < 3:
        return float("nan")
    lap = (
        -4.0 * gray[1:-1, 1:-1]
        + gray[:-2, 1:-1] + gray[2:, 1:-1] + gray[1:-1, :-2] + gray[1:-1, 2:]
    )
    return float(lap.var()) if lap.size else float("nan")


# ── stage 1: the hard filters ────────────────────────────────────────────────


def _occluder_union(
    target: Detection, others: Sequence[Detection], config: SelectionConfig
) -> np.ndarray | None:
    """The union of the other masks in this frame that may be hiding this one.

    A mask that CONTAINS the target is left out, and that exclusion is provable
    rather than heuristic: if another reading covers my whole extent, then every
    pixel the tracker attributed to me was still attributed to me, so none of me
    is hidden. It is what makes the rule survive the fact that the tracker runs
    one concept per pass -- `artwork#0` and `painting#1` are one wall picture
    found by two prompts, and a bare union would report each as ~99% occluded by
    the other and reject all 54 of their shared frames.

    The converse is NOT excluded. A small mask sitting inside a large one is
    ambiguous between a sub-part read separately and a small object in front,
    mask geometry cannot separate them, and rejecting is the conservative
    direction for "is this a good photograph of the large object".
    """
    acc: np.ndarray | None = None
    t_area = int(target.mask.sum())
    if t_area == 0:
        return None
    for o in others:
        if o.object_key == target.object_key or o.mask.shape != target.mask.shape:
            continue
        overlap = int(np.logical_and(target.mask, o.mask).sum())
        if overlap == 0:
            continue
        if overlap / t_area >= config.nested_containment:
            continue  # it spans all of me, so it cannot be hiding any of me
        acc = o.mask.copy() if acc is None else np.logical_or(acc, o.mask)
    return acc


def _hard_filter_reasons(
    det: Detection,
    frame_dets: Sequence[Detection],
    config: SelectionConfig,
) -> list[str]:
    """Every rule that fires, not just the first.

    Deliberately not short-circuiting: a frame rejected for three reasons and
    one rejected for a single marginal one are different diagnoses, and a
    selector that reports only the first hides which threshold to argue with.
    """
    reasons: list[str] = []
    h, w = det.mask.shape
    area = int(det.mask.sum())
    if area == 0:
        return ["empty_mask"]

    bbox = mask_bbox(det.mask)
    if bbox is None:
        return ["empty_mask"]
    x0, y0, x1, y1 = bbox
    mx, my = config.border_margin_frac * w, config.border_margin_frac * h
    # The mask reaches the edge band -- the sensor stopped before the object
    # did (0259's disqualification 1, now read from the mask rather than from
    # a projected box hull, because a tracked object need not have a box).
    # Inclusive on both sides, so `border_margin_frac = 0` means "the mask
    # touches the edge" rather than never firing: a bounding box is clipped to
    # the raster by construction, so a strict comparison at zero is
    # unreachable and the knob would silently have no off-by-touching setting.
    if x0 <= mx or y0 <= my or x1 >= (w - 1) - mx or y1 >= (h - 1) - my:
        reasons.append("border")

    if area < config.min_area_frac * (h * w):
        reasons.append("too_small")

    union = _occluder_union(det, frame_dets, config)
    if union is not None:
        covered = int(np.logical_and(det.mask, union).sum())
        if covered / area > config.max_occluded_frac:
            reasons.append("occluded")

    # TODO(completeness): compare this frame's mask area against the object's
    # peak area across its whole track -- a mask far below its own maximum is a
    # partial view of the object even when nothing here rejects it. Left out
    # deliberately and not merely unimplemented: the peak is the object's
    # LARGEST observed extent, not its true one, so the rule would rank
    # candidates against a fabricated bound, and 0197 measured that class of
    # ranking as large and bidirectional. It needs its own registered
    # prediction before it goes in.
    return reasons


# ── stage 2: the soft terms ──────────────────────────────────────────────────


def _static_terms(
    det: Detection,
    get_rgb: Callable[[int], np.ndarray | None] | None,
    config: SelectionConfig,
) -> dict[str, float]:
    """The four terms that depend on one frame alone. Temporal stability is not
    here: it depends on which frames survived, so it is computed per set."""
    h, w = det.mask.shape
    area = int(det.mask.sum())
    out: dict[str, float] = {}

    frac = area / float(h * w)
    out["size"] = min(math.sqrt(frac), config.size_cap_frac) / config.size_cap_frac

    hull = _hull_area(det.mask)
    out["solidity"] = float(np.clip(area / hull, 0.0, 1.0)) if hull > 0 else 0.0

    ys, xs = np.nonzero(det.mask)
    cy, cx = float(ys.mean()), float(xs.mean())
    half_diag = math.hypot(w, h) / 2.0
    dist = math.hypot(cx - (w - 1) / 2.0, cy - (h - 1) / 2.0)
    out["centeredness"] = float(np.clip(1.0 - dist / half_diag, 0.0, 1.0))

    out["sharpness"] = float("nan")
    bbox = mask_bbox(det.mask)
    if get_rgb is not None and bbox is not None:
        rgb = get_rgb(det.frame_index)
        if rgb is not None:
            a = np.asarray(rgb)
            if a.size:
                # The scale between raster and image is derived, never assumed
                # to be MASK_STRIDE: upstream owns that constant and this
                # module must not carry a second copy of it.
                ih, iw = a.shape[:2]
                sx, sy = iw / float(w), ih / float(h)
                x0, y0, x1, y1 = bbox
                cx0, cx1 = int(x0 * sx), int(math.ceil((x1 + 1) * sx))
                cy0, cy1 = int(y0 * sy), int(math.ceil((y1 + 1) * sy))
                crop = a[max(cy0, 0):min(cy1, ih), max(cx0, 0):min(cx1, iw)]
                if crop.size:
                    g = crop.mean(axis=2) if crop.ndim == 3 else crop.astype(float)
                    v = _laplacian_variance(g)
                    if v == v:
                        out["sharpness"] = math.log1p(max(v, 0.0))
    return out


def _temporal_terms(
    frame_indices: Sequence[int],
    timestamps: dict[int, float] | None,
    config: SelectionConfig,
) -> dict[int, float]:
    """1.0 at the centre of a contiguous run, falling linearly to 0 at its ends.

    A run of one or two frames scores 0 throughout, and that is the consistent
    reading rather than a special case: with `c = (n - 1) / 2` every frame of a
    two-frame run IS an end, and a one-frame run is the limit of that. Scoring
    an isolated glimpse 1.0 would have the term reward maximally the least
    stable thing it can see.
    """
    ordered = sorted(frame_indices)
    runs: list[list[int]] = []
    for fi in ordered:
        if not runs:
            runs.append([fi])
            continue
        prev = runs[-1][-1]
        if timestamps is not None and fi in timestamps and prev in timestamps:
            broke = (timestamps[fi] - timestamps[prev]) > config.run_break_seconds
        else:
            broke = (fi - prev) > config.run_break_frames
        (runs.append([fi]) if broke else runs[-1].append(fi))

    out: dict[int, float] = {}
    for run in runs:
        n = len(run)
        c = (n - 1) / 2.0
        for i, fi in enumerate(run):
            out[fi] = 0.0 if c <= 0 else float(np.clip(1.0 - abs(i - c) / c, 0.0, 1.0))
    return out


def _normalize_and_score(
    scores: list[FrameScore], config: SelectionConfig
) -> None:
    """Min-max each term across this set, then a weighted sum. Mutates in place.

    Zero variance maps to 1.0, per the specification. A term that could not be
    measured for a frame -- sharpness with no readable RGB -- is DROPPED from
    that frame's sum and its weight removed from the divisor, rather than
    scored zero: the repo's standing rule is that an instrument which cannot
    ask its question does not get to answer it.
    """
    weights = config.weights()
    for term in TERMS:
        vals = [s.raw.get(term, float("nan")) for s in scores]
        finite = [v for v in vals if v == v]
        lo, hi = (min(finite), max(finite)) if finite else (0.0, 0.0)
        span = hi - lo
        for s, v in zip(scores, vals, strict=True):
            if v != v:
                continue
            s.normalized[term] = 1.0 if span <= 0 else (v - lo) / span
    for s in scores:
        spent = sum(weights[t] for t in TERMS if t in s.normalized)
        total = sum(weights[t] * s.normalized[t] for t in TERMS if t in s.normalized)
        s.score = (total / spent) if spent > 0 else 0.0


# ── the selector ─────────────────────────────────────────────────────────────


def select_best_frames(
    detections: Iterable[Detection],
    *,
    get_rgb: Callable[[int], np.ndarray | None] | None = None,
    timestamps: dict[int, float] | None = None,
    config: SelectionConfig = DEFAULT_CONFIG,
) -> dict[str, ObjectChoice]:
    """One frame per object_key, with the reasoning kept beside each answer.

    There is deliberately no `image_size` parameter. Every filter and every
    geometric term is a FRACTION of the mask raster, so none of them needs one,
    and the sharpness crop takes its scale from the RGB frame it was actually
    handed -- which is correct even if the raster's stride changes upstream.
    `timestamps` maps frame_index -> seconds and, when absent, run breaks fall
    back to a frame-count gap.

    Deterministic: frames are considered in index order and ties resolve to the
    lower frame index, because 0062's law is that a retry has to reproduce its
    own cached selection.
    """
    dets = [d for d in detections]
    by_frame: dict[int, list[Detection]] = {}
    for d in dets:
        by_frame.setdefault(d.frame_index, []).append(d)
    by_object: dict[str, list[Detection]] = {}
    for d in dets:
        by_object.setdefault(d.object_key, []).append(d)

    results: dict[str, ObjectChoice] = {}
    for key in sorted(by_object):
        obj_dets = sorted(by_object[key], key=lambda d: d.frame_index)
        static: dict[int, dict[str, float]] = {}
        rows: list[FrameScore] = []
        for d in obj_dets:
            reasons = _hard_filter_reasons(d, by_frame.get(d.frame_index, []), config)
            static[d.frame_index] = _static_terms(d, get_rgb, config)
            rows.append(
                FrameScore(frame_index=d.frame_index, kept=not reasons, reasons=reasons)
            )

        kept = [r for r in rows if r.kept]
        # The fallback scores the object's WHOLE track rather than nothing.
        # Which set is scored also fixes what the min-max normalises over, so
        # the two paths cannot be collapsed into one scoring call.
        scoring = kept if kept else rows
        is_fallback = not kept

        temporal = _temporal_terms(
            [r.frame_index for r in scoring], timestamps, config
        )
        for r in scoring:
            r.raw = dict(static[r.frame_index])
            r.raw["temporal"] = temporal.get(r.frame_index, 0.0)
        _normalize_and_score(scoring, config)

        best = max(scoring, key=lambda r: (r.score, -r.frame_index), default=None)
        results[key] = ObjectChoice(
            object_key=key,
            frame_index=best.frame_index if best else None,
            score=best.score if best else 0.0,
            is_fallback=is_fallback,
            n_frames=len(rows),
            n_kept=len(kept),
            frames=rows,
        )
    return results


def apply_key_map(
    detections: Iterable[Detection], key_map: dict[str, str]
) -> list[Detection]:
    """Re-key detections through a mapping such as `merge_nested_instances`."""
    return [
        replace(d, object_key=key_map.get(d.object_key, d.object_key))
        for d in detections
    ]
