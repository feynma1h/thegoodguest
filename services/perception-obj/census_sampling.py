"""Census-driven frame selection: box-visibility set-cover + pose-diverse
residue (decision 0077 lock 6 — 0062's successor on the LIDAR_ROOMPLAN
tier; the 0062 sampler stays verbatim as the no-census degrade path and on
the legacy tiers).

The 0075 starvation finding: pose-diverse FPS is object-blind — 12/293
frames sampled on capture #1 left most furniture with zero good views.
With a CapturedRoom census the server knows where every box IS before any
GPU work, so selection maximizes per-box visibility instead of pose
spread:

  1. Set-cover pass: greedy over frames, gain = Σ over UNCOVERED boxes of
     v(frame, box) where v = on-frame projected box area × in-frame
     fraction (box_placement.project_box_footprint). A box counts covered
     once a selected frame sees it WELL (in-frame fraction ≥
     PERCEPTION_BOX_COVER_MIN_INFRAME and on-frame area ≥
     PERCEPTION_BOX_COVER_MIN_AREA_FRAC of the frame) — the same
     visibility class box_placement's axis scorer accepts
     (PLACEMENT_BOX_SCORE_MIN_INFRAME), so a covering view is a scoreable
     view. Measured on the spike fixture (722 frames, 9
     boxes): every box has 52–156 qualifying frames and greedy covers
     9/9 in 7 picks.
  2. Residue pass: remaining slots (within PERCEPTION_MAX_FRAMES) go to
     pose-diverse farthest-point frames seeded WITH the cover set — the
     long tail (small objects RoomPlan doesn't box) keeps the 0062-style
     spread.

Deterministic (0062's law — retries must hit their own GCS cache): fixed
iteration order, ties by lower frame index, no RNG.

Consumers: process_receiver.run_perception (LIDAR_ROOMPLAN scenes),
tests/test_census_sampling.py.
"""
from __future__ import annotations

import os
from collections.abc import Sequence

import box_placement
import numpy as np
from sampling import ROTATION_WEIGHT_M_PER_RAD, _distance_matrix, _frame_features

# A frame covers a box when the projected footprint is at least this
# in-frame (deliberately mirrors box_placement's
# PLACEMENT_BOX_SCORE_MIN_INFRAME — cover views must be scoreable) and at
# least this fraction of the frame's pixel area (a
# distant speck view is not a good view). One-fixture-calibrated like
# every PERCEPTION_* knob.
PERCEPTION_BOX_COVER_MIN_INFRAME = float(
    os.environ.get("PERCEPTION_BOX_COVER_MIN_INFRAME", "0.5")
)
PERCEPTION_BOX_COVER_MIN_AREA_FRAC = float(
    os.environ.get("PERCEPTION_BOX_COVER_MIN_AREA_FRAC", "0.01")
)

# Spend the residue slots on SECOND views of boxes we already cover,
# instead of on pose spread that knows nothing about where anything is
# (decision 0202). Off by default; with it off the residue is 0062's
# farthest-point sampler, byte for byte, which is what every preserved
# capture shipped.
#
# What this is NOT: a ranking of which view of an object is better. Eleven
# such measures have failed (0146, 0152, 0162) and 0197 measured the twelfth
# as large and BIDIRECTIONAL — the same swap gained one table a set of legs
# and cost another the ones it had. So the rule here is diversity only: give
# each box the qualifying frame FARTHEST in camera pose from the frames that
# already see it, round-robin so every box gets a second view before any
# gets a third. Which of an object's views is the good one is then settled
# downstream, on the output, against its measured box.
OBJECT_AWARE_RESIDUE = os.environ.get("PERCEPTION_OBJECT_AWARE_RESIDUE", "0") == "1"

# --- The two vetoes (decision 0234) ----------------------------------------
# Selection today asks only where a box PROJECTS. Two frames can project a
# box identically while one of them is unusable and the other shows the
# object's lower half. Off by default; with it off this module is byte for
# byte what every preserved capture shipped.
#
# REJECT ONLY, NEVER RANK. That restriction is the whole design and it is not
# caution — it is measured. Eleven view measures have been refuted (0146,
# 0152, 0162) and 0197 measured the twelfth as large and BIDIRECTIONAL, the
# same swap gaining one table a full set of legs and costing another the ones
# it had. Part-wise visibility in particular separated an object with no leg
# failure mode by 5.7x, which was the pre-registered tripwire for a generic
# quality proxy, and its top-ranked frames have never been reconstructed. So
# these vetoes answer only "can this frame serve this object AT ALL", at
# zero, and every surviving frame is ordered by exactly what ordered it
# before.
VISIBILITY_VETO = os.environ.get("PERCEPTION_VISIBILITY_VETO", "0") == "1"

# Veto 1, whole-frame usability. Deliberately extreme: these reject a frame
# that carries no information, not a frame that is merely worse than another.
VETO_MIN_MEAN_LUMA = float(os.environ.get("PERCEPTION_VETO_MIN_LUMA", "12"))
VETO_MAX_BLOWN_FRACTION = float(os.environ.get("PERCEPTION_VETO_MAX_BLOWN", "0.85"))
VETO_MIN_LAPLACIAN_VAR = float(os.environ.get("PERCEPTION_VETO_MIN_LAPVAR", "3.0"))

# Veto 2's band, carried from the detector rather than restated so one cut
# moves both.
VETO_BAND = "lower"

# How far the cover bar may relax for a box the vetoes would otherwise
# orphan. Veto 2 REMOVES candidate frames, so it can starve a box that had
# few — rp6g2 has one with exactly one qualifying frame across 124 — and this
# is that veto's counterweight rather than an independent feature.
VETO_RELAX_STEPS = (1.0, 0.8, 0.6, 0.4)

# How many qualifying views of one box the object-aware residue will buy.
# Deliberately the SAME env var the reconstruction plan caps itself with
# (process_receiver._PLAN_VIEWS_PER_BOX), because a view beyond the plan's
# cap is policy-skipped: sampling a box's sixth good view spends a frame
# slot on something that is recorded and never reconstructed. Measured on
# the four preserved captures: without this bound rp6g1 buys 15 views the
# plan discards; with it, 3.
VIEWS_PER_BOX_TARGET = max(1, int(os.environ.get("PERCEPTION_PLAN_VIEWS_PER_BOX", "2")))


def _frame_dims(intrinsics) -> tuple[float, float]:
    w = float(getattr(intrinsics, "width", 0) or 2.0 * intrinsics.cx)
    h = float(getattr(intrinsics, "height", 0) or 2.0 * intrinsics.cy)
    return w, h


def box_visibility(frames: Sequence, boxes: list) -> tuple[np.ndarray, np.ndarray]:
    """(V, Q): V[f, b] = on-frame projected box area × in-frame fraction;
    Q[f, b] = the boolean cover-quality bar."""
    n_f, n_b = len(frames), len(boxes)
    V = np.zeros((n_f, n_b))
    Q = np.zeros((n_f, n_b), dtype=bool)
    for fi, frame in enumerate(frames):
        w, h = _frame_dims(frame.intrinsics)
        frame_area = w * h
        for bi, box in enumerate(boxes):
            hull, frac = box_placement.project_box_footprint(
                box, frame.intrinsics, frame.camera_pose
            )
            if hull is None:
                continue
            on_frame_area = box_placement._polygon_area(
                box_placement._clip_to_rect(hull, w, h)
            )
            V[fi, bi] = on_frame_area * frac
            Q[fi, bi] = (
                frac >= PERCEPTION_BOX_COVER_MIN_INFRAME
                and on_frame_area >= PERCEPTION_BOX_COVER_MIN_AREA_FRAC * frame_area
            )
    return V, Q


def frame_is_usable(rgb) -> bool:
    """Veto 1. False only for a frame carrying no information: black, blown
    out, or catastrophically blurred. Never a comparison between frames."""
    if rgb is None:
        return True  # cannot tell -> do not reject
    a = np.asarray(rgb)
    if a.size == 0:
        return True
    g = a.mean(axis=2) if a.ndim == 3 else a.astype(float)
    if float(g.mean()) < VETO_MIN_MEAN_LUMA:
        return False
    if float((g >= 250).mean()) > VETO_MAX_BLOWN_FRACTION:
        return False
    # Variance of the Laplacian, the standard blur proxy, by direct
    # convolution — scipy is not in this image.
    lap = (
        -4.0 * g[1:-1, 1:-1]
        + g[:-2, 1:-1] + g[2:, 1:-1] + g[1:-1, :-2] + g[1:-1, 2:]
    )
    if lap.size and float(lap.var()) < VETO_MIN_LAPLACIAN_VAR:
        return False
    return True


def box_band_is_visible(box, room, frame, get_depth) -> bool:
    """Veto 2. Does this frame see ANY of the box's lower band?

    True whenever the question cannot be asked — no depth, no payload — so a
    missing raster never removes a candidate. The measurement is the
    detector's own geometry with the mask half absent, which is what makes it
    available before any GPU work.
    """
    if get_depth is None or box is None:
        return True
    try:
        import mask_refine  # deferred: peer module, imported for its geometry

        cloud = mask_refine.box_measured_cloud(
            box=box, room=room, frame_indices=[frame.frame_index],
            get_depth=get_depth,
            get_camera=lambda _fi: (frame.camera_pose, frame.intrinsics),
        )
        if len(cloud) == 0:
            return True  # nothing measured at all -> not a band verdict
        local = mask_refine._box_local(cloud, box)
        height = float(box.dimensions[1])
        if height <= 0.0:
            return True
        hf = (local[:, 1] + height / 2.0) / height
        return bool(mask_refine.height_bands(hf)[VETO_BAND].any())
    except Exception:
        return True  # never reject on an error


class _Vetoes:
    """Lazily evaluated and memoized, so a depth raster is fetched only for a
    (frame, box) pair the cover pass actually wants. Precomputing the matrix
    would cost one depth fetch per keyframe — 722 on the spike capture —
    before any GPU work, to answer a question about the handful of frames
    that get picked."""

    def __init__(self, frames, boxes, room, get_depth, get_rgb):
        self._frames, self._boxes, self._room = frames, boxes, room
        self._get_depth, self._get_rgb = get_depth, get_rgb
        self._usable: dict[int, bool] = {}
        self._band: dict[tuple[int, int], bool] = {}
        self.rejected_frames: list[int] = []
        self.rejected_pairs: list[tuple[int, int]] = []

    def frame_ok(self, fi: int) -> bool:
        if fi not in self._usable:
            rgb = None
            if self._get_rgb is not None:
                try:
                    rgb = self._get_rgb(self._frames[fi].frame_index)
                except Exception:
                    rgb = None
            ok = frame_is_usable(rgb)
            self._usable[fi] = ok
            if not ok:
                self.rejected_frames.append(self._frames[fi].frame_index)
        return self._usable[fi]

    def pair_ok(self, fi: int, bi: int) -> bool:
        key = (fi, bi)
        if key not in self._band:
            ok = box_band_is_visible(
                self._boxes[bi], self._room, self._frames[fi], self._get_depth
            )
            self._band[key] = ok
            if not ok:
                self.rejected_pairs.append((self._frames[fi].frame_index, bi))
        return self._band[key]


def _reselect_info(frames, boxes, max_frames) -> dict:
    """The info block an unvetoed selection would have produced. Used only
    by the overrule path, so the manifest still describes what shipped."""
    before = globals()["VISIBILITY_VETO"]
    globals()["VISIBILITY_VETO"] = False
    try:
        return select_frames_census(frames, boxes, max_frames)[1]
    finally:
        globals()["VISIBILITY_VETO"] = before


def _q_relaxed(frame, box, scale: float) -> bool:
    """The cover bar with both thresholds scaled down together. Used only by
    the per-object relaxation, and only for a box the vetoes would otherwise
    orphan."""
    w, h = _frame_dims(frame.intrinsics)
    hull, frac = box_placement.project_box_footprint(
        box, frame.intrinsics, frame.camera_pose
    )
    if hull is None:
        return False
    area = box_placement._polygon_area(box_placement._clip_to_rect(hull, w, h))
    return (
        frac >= PERCEPTION_BOX_COVER_MIN_INFRAME * scale
        and area >= PERCEPTION_BOX_COVER_MIN_AREA_FRAC * scale * w * h
    )


def select_frames_census(
    frames: Sequence, boxes: list, max_frames: int,
    *, room=None, get_depth=None, get_rgb=None,
) -> tuple[list, dict]:
    """Select up to max_frames frames: set-cover over the census first,
    pose-diverse residue after. Returns (frames in input order, info) —
    info feeds the manifest's sampling.census block."""
    frames = list(frames)
    max_frames = max(1, int(max_frames))
    if len(frames) <= max_frames:
        info = {
            "cover_frame_indices": [f.frame_index for f in frames],
            "residue_frame_indices": [],
            "box_coverage": {},
            "uncovered_box_ids": [],
        }
        # Small bundles are taken whole; coverage is still reported below.
        V, Q = box_visibility(frames, boxes)
        info["box_coverage"] = _coverage_map(frames, list(range(len(frames))), V, Q, boxes)
        info["uncovered_box_ids"] = [
            f"box_{bi:02d}" for bi in range(len(boxes))
            if not any(Q[fi, bi] for fi in range(len(frames)))
        ]
        return frames, info

    V, Q = box_visibility(frames, boxes)

    vetoes = (
        _Vetoes(frames, boxes, room, get_depth, get_rgb)
        if VISIBILITY_VETO else None
    )

    # Both vetoes are asked ONLY about the frame the pass is about to take,
    # never about every candidate. That is a cost decision with a number
    # behind it: veto 1 needs the frame's pixels and veto 2 needs its depth
    # raster, so scoring all candidates would fetch two blobs per keyframe —
    # 1,444 on the spike capture — before any GPU work, to answer a question
    # about the handful of frames that actually get picked. Scoring stays on
    # the projection alone; the veto only ever removes a winner.
    blocked_frames: set[int] = set()
    blocked_pairs: set[tuple[int, int]] = set()

    def _covers(fi: int, bi: int, scale: float = 1.0) -> bool:
        if (fi, bi) in blocked_pairs or fi in blocked_frames:
            return False
        if scale >= 1.0:
            return bool(Q[fi, bi])
        return _q_relaxed(frames[fi], boxes[bi], scale)

    def _admit(fi: int, targets: set[int]) -> set[int] | None:
        """The boxes `fi` may cover once the vetoes have had their say, or
        None if the frame itself is rejected."""
        if vetoes is None:
            return targets
        if not vetoes.frame_ok(fi):
            blocked_frames.add(fi)
            return None
        kept = set()
        for bi in sorted(targets):
            if vetoes.pair_ok(fi, bi):
                kept.add(bi)
            else:
                blocked_pairs.add((fi, bi))
        return kept

    uncovered = set(range(len(boxes)))
    cover_positions: list[int] = []
    while uncovered and len(cover_positions) < max_frames:
        best_pos, best_gain = None, 0.0
        for fi in range(len(frames)):
            if fi in cover_positions or fi in blocked_frames:
                continue
            gain = float(sum(V[fi, bi] for bi in uncovered if _covers(fi, bi)))
            # Strictly-greater keeps ties at the lower frame index.
            if gain > best_gain:
                best_pos, best_gain = fi, gain
        if best_pos is None:
            break  # nothing sees any remaining box well
        would_cover = {bi for bi in uncovered if _covers(best_pos, bi)}
        admitted = _admit(best_pos, would_cover)
        if not admitted:
            # Rejected outright, or every box it would have covered vetoed.
            # Both are now recorded in blocked_*, so the next pass re-ranks
            # without it and this terminates.
            continue
        cover_positions.append(best_pos)
        uncovered -= admitted

    # Per-object relaxation, the vetoes' counterweight. Veto 2 REMOVES
    # candidate frames, so a box that had few can be starved by it — rp6g2
    # carries one with exactly one qualifying frame across 124. Rather than
    # let the veto orphan such a box, its own bar relaxes until something
    # qualifies. Per box, never global: relaxing the bar for everyone would
    # change which frames cover the boxes that were already fine.
    relaxed_boxes: dict[str, float] = {}
    if vetoes is not None and uncovered:
        for bi in sorted(uncovered):
            placed = False
            for scale in VETO_RELAX_STEPS[1:]:
                if placed or len(cover_positions) >= max_frames:
                    break
                cands = sorted(
                    (fi for fi in range(len(frames))
                     if fi not in cover_positions and _covers(fi, bi, scale)),
                    key=lambda fi: (-V[fi, bi], fi),
                )
                for fi in cands:
                    if _admit(fi, {bi}):
                        cover_positions.append(fi)
                        relaxed_boxes[f"box_{bi:02d}"] = scale
                        uncovered.discard(bi)
                        placed = True
                        break
        cover_positions.sort()

    # Per-object relaxation, the vetoes' counterweight. Veto 2 REMOVES
    # candidate frames, so a box that had few can be starved by it — rp6g2
    # carries one with exactly one qualifying frame across 124. Rather than
    # let the veto orphan such a box, its own bar relaxes until something
    # qualifies. Per box, never global: relaxing the bar for everyone would
    # change which frames cover the boxes that were already fine.

    # Residue: farthest-point over the pose-diversity metric, seeded with
    # the cover picks (the 0062 metric, continued from a non-empty seed).
    residue_positions: list[int] = []
    n_residue = max_frames - len(cover_positions)
    if n_residue > 0:
        positions, view_dirs = _frame_features(frames)
        dist = _distance_matrix(positions, view_dirs)
        if OBJECT_AWARE_RESIDUE:
            residue_positions = _object_aware_residue(
                dist, Q, cover_positions, n_residue
            )
            n_residue -= len(residue_positions)
        if cover_positions or residue_positions:
            seeded = cover_positions + residue_positions
            min_dist = dist[seeded].min(axis=0) if seeded else None
        else:
            min_dist = None
        # The residue draws from the SURVIVORS too. Veto 1 is a statement
        # about the frame, not about the frame's relationship to a box, so a
        # frame that carries no information is no more useful as pose spread
        # than as coverage — and rp6g2's last 28 keyframes are black, two of
        # which the shipped sampler takes.
        taken = 0
        guard = 0
        while taken < n_residue and guard < len(frames) * 2:
            guard += 1
            if min_dist is None:
                nxt = int(np.argmax(dist.sum(axis=1)))
                min_dist = dist[nxt].copy()
            else:
                min_dist[cover_positions + residue_positions] = -1.0
                if blocked_frames:
                    min_dist[sorted(blocked_frames)] = -1.0
                nxt = int(np.argmax(min_dist))
                if min_dist[nxt] < 0:
                    break  # nothing left that is not taken or blocked
                min_dist = np.minimum(min_dist, dist[nxt])
            if vetoes is not None and not vetoes.frame_ok(nxt):
                blocked_frames.add(nxt)
                continue
            residue_positions.append(nxt)
            taken += 1

    selected_positions = sorted(cover_positions + residue_positions)

    # A veto that empties the selection is overruled. Every frame failing
    # veto 1 is a capture problem — a dark room, a covered lens — and the
    # right response to it is a bad scene, not NO scene: shipping zero
    # frames means the room produces nothing at all, where shipping the
    # frames the sampler would have taken at least reaches the ingest gate
    # with something a person can be told about. Recorded, never silent.
    if vetoes is not None and not selected_positions:
        return select_frames_census(frames, boxes, max_frames)[0], {
            **_reselect_info(frames, boxes, max_frames),
            "veto": {
                "policy": "visibility_veto_v1",
                "overruled": True,
                "unusable_frames": [],
                "band_vetoed_pairs": [],
                "relaxed_boxes": {},
            },
        }

    selected = [frames[i] for i in selected_positions]
    info = {
        "cover_frame_indices": sorted(
            frames[i].frame_index for i in cover_positions
        ),
        "residue_frame_indices": sorted(
            frames[i].frame_index for i in residue_positions
        ),
        "box_coverage": _coverage_map(frames, selected_positions, V, Q, boxes),
        "uncovered_box_ids": [f"box_{bi:02d}" for bi in sorted(uncovered)],
    }
    if OBJECT_AWARE_RESIDUE:
        # Emitted only when the residue is object-aware, so every manifest
        # written under the default is byte-identical to what shipped.
        info["residue_policy"] = "object_aware_v1"
        info["views_per_box_target"] = VIEWS_PER_BOX_TARGET
    if vetoes is not None:
        # Same rule: only present when the vetoes ran, so a default manifest
        # is unchanged. What was REMOVED is recorded, because a selector that
        # silently drops candidates is indistinguishable from one that never
        # saw them.
        info["veto"] = {
            "policy": "visibility_veto_v1",
            "unusable_frames": sorted(vetoes.rejected_frames),
            "band_vetoed_pairs": sorted(
                f"f{f}:box_{b:02d}" for f, b in vetoes.rejected_pairs
            ),
            "relaxed_boxes": relaxed_boxes,
        }
    return selected, info


def _object_aware_residue(
    dist: np.ndarray, Q: np.ndarray, cover_positions: list[int], n_slots: int
) -> list[int]:
    """Residue slots spent on second views of boxes we already cover.

    Round-robin over the boxes, fewest-views-first: each round every box
    that still has a qualifying frame nobody has picked gets the one
    FARTHEST — in the same pose metric 0062 uses — from every frame already
    seeing that box. Ties break at the lower frame index, and the whole
    thing is deterministic, because a Cloud Tasks retry must re-sample the
    same subset to hit its own per-frame GCS cache (0062's law).

    A box stops asking once it has VIEWS_PER_BOX_TARGET qualifying views,
    because the reconstruction plan reconstructs no more than that and
    records the rest as policy skips — buying a box's sixth good view
    spends a frame slot on something nothing will ever look at.

    Returns fewer than n_slots when the boxes are satisfied or run out of
    distinct qualifying views; the caller fills the remainder with the
    pose-diverse residue, so the long tail of small objects RoomPlan never
    boxed keeps the spread it has today.

    No frame is ever compared to another for quality. The only question
    asked of a candidate is how far it stands from the views this box
    already has, which is the one property 0197 did not measure as
    bidirectional — it measured that you cannot tell in advance which of
    two views reconstructs better, not that more of them is worse.
    """
    n_boxes = Q.shape[1]
    seen: dict[int, list[int]] = {
        bi: [p for p in cover_positions if Q[p, bi]] for bi in range(n_boxes)
    }
    chosen: list[int] = []
    taken = set(cover_positions)
    exhausted: set[int] = {
        bi for bi in range(n_boxes) if len(seen[bi]) >= VIEWS_PER_BOX_TARGET
    }

    while len(chosen) < n_slots and len(exhausted) < n_boxes:
        order = sorted(
            (bi for bi in range(n_boxes) if bi not in exhausted),
            key=lambda bi: (len(seen[bi]), bi),
        )
        progressed = False
        for bi in order:
            if len(chosen) >= n_slots:
                break
            candidates = [
                p for p in np.nonzero(Q[:, bi])[0].tolist() if p not in taken
            ]
            if not candidates:
                exhausted.add(bi)
                continue
            if seen[bi]:
                spread = dist[np.ix_(candidates, seen[bi])].min(axis=1)
            else:
                spread = np.zeros(len(candidates))
            # Strictly-greater keeps ties at the lower frame index, since
            # candidates is ascending in position and position is ascending
            # in frame index.
            best, best_d = None, -1.0
            for cand, d in zip(candidates, spread.tolist(), strict=True):
                if d > best_d:
                    best, best_d = cand, d
            chosen.append(best)
            taken.add(best)
            for other in range(n_boxes):
                if Q[best, other]:
                    seen[other].append(best)
                    if len(seen[other]) >= VIEWS_PER_BOX_TARGET:
                        exhausted.add(other)
            progressed = True
        if not progressed:
            break
    return chosen


def _coverage_map(frames, selected_positions, V, Q, boxes) -> dict:
    """box_id → selected frame indices that cover it, best (highest v)
    first — the per-box frame assignments the manifest records."""
    out: dict[str, list[int]] = {}
    for bi in range(len(boxes)):
        covering = [
            (float(V[fi, bi]), frames[fi].frame_index)
            for fi in selected_positions
            if Q[fi, bi]
        ]
        covering.sort(key=lambda p: (-p[0], p[1]))
        out[f"box_{bi:02d}"] = [idx for _v, idx in covering]
    return out


# Re-export for callers that want to log the metric weight beside 0062's.
__all__ = [
    "OBJECT_AWARE_RESIDUE",
    "VIEWS_PER_BOX_TARGET",
    "PERCEPTION_BOX_COVER_MIN_AREA_FRAC",
    "PERCEPTION_BOX_COVER_MIN_INFRAME",
    "ROTATION_WEIGHT_M_PER_RAD",
    "box_visibility",
    "select_frames_census",
]
