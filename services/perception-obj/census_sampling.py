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
        if cover_positions:
            min_dist = dist[cover_positions].min(axis=0)
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
    return selected, info


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
    "PERCEPTION_BOX_COVER_MIN_AREA_FRAC",
    "PERCEPTION_BOX_COVER_MIN_INFRAME",
    "ROTATION_WEIGHT_M_PER_RAD",
    "box_visibility",
    "select_frames_census",
]
