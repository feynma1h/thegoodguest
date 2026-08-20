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


def select_frames_census(
    frames: Sequence, boxes: list, max_frames: int
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

    uncovered = set(range(len(boxes)))
    cover_positions: list[int] = []
    while uncovered and len(cover_positions) < max_frames:
        best_pos, best_gain = None, 0.0
        for fi in range(len(frames)):
            if fi in cover_positions:
                continue
            gain = float(sum(V[fi, bi] for bi in uncovered if Q[fi, bi]))
            # Strictly-greater keeps ties at the lower frame index.
            if gain > best_gain:
                best_pos, best_gain = fi, gain
        if best_pos is None:
            break  # nothing sees any remaining box well
        cover_positions.append(best_pos)
        uncovered -= {bi for bi in uncovered if Q[best_pos, bi]}

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
        for _ in range(n_residue):
            if min_dist is None:
                seed = int(np.argmax(dist.sum(axis=1)))
                residue_positions.append(seed)
                min_dist = dist[seed].copy()
                continue
            min_dist[cover_positions + residue_positions] = -1.0
            nxt = int(np.argmax(min_dist))
            residue_positions.append(nxt)
            min_dist = np.minimum(min_dist, dist[nxt])

    selected_positions = sorted(cover_positions + residue_positions)
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
