"""Pose-diverse frame sampling for the perception receiver.

The first real capture (scene 25a14caf, 126 keyframes, 2026-07-21) proved
that reconstructing EVERY keyframe breaks the processing envelope: at
~70-130 s per frame the run needs hours, while the Cloud Run request budget
is 900 s including the ~3.5 min cold-start model load. Reconstruction cost
must be bounded BEFORE the frame loop starts.

This module selects a bounded subset of a bundle's frames (default
DEFAULT_MAX_FRAMES, env-overridable via PERCEPTION_MAX_FRAMES) by
farthest-point sampling over a pose-diversity metric:

    d(a, b) = ||position_a - position_b||
              + ROTATION_WEIGHT_M_PER_RAD * angle(view_dir_a, view_dir_b)

Position spread gives fusion the translation baselines ray triangulation
needs; view-direction spread covers yaw (and pitch) diversity so the same
object is observed from genuinely different directions. A plain stride
over frame indices would keep temporal coverage but can waste the whole
budget on one corner of the room when the user lingered there — FPS
spends it on the most mutually-distant viewpoints instead.

Selection is deterministic for a given input (ties broken by lower list
index). That matters beyond reproducibility: per-frame output caching in
GCS is keyed by frame_index, so a Cloud Tasks retry that re-samples the
same bundle must pick the same subset to hit its own cache.

The output preserves the input's relative order (sorted by position in
the input list), so downstream per-frame-uniqueness guards in fusion see
the same ordering invariants as an unsampled run.

Consumers: process_receiver.run_perception.
"""
from __future__ import annotations

import os
from collections.abc import Sequence

import numpy as np
from thegoodguest_schemas.pose_math import pose_position, pose_quat, quat_to_rotmat

# Default cap on frames reconstructed per scene. ~12 pose-diverse frames give
# fusion enough multi-view observations (triangulation needs >= 2 per object)
# while fitting the request budget at the observed ~70-130 s/frame worst case
# together with the budget tracker's early stop (see budget.py).
DEFAULT_MAX_FRAMES: int = int(os.environ.get("PERCEPTION_MAX_FRAMES", "12"))

# Meters of translation considered equivalent to one radian of view-direction
# change. 0.5 m/rad makes a 30-degree pan (~0.26 m equivalent) comparable to a
# typical between-keyframe step, so neither term dominates for handheld scans.
ROTATION_WEIGHT_M_PER_RAD: float = 0.5

# ARKit camera looks down -Z in its local frame.
_CAMERA_FORWARD = np.array([0.0, 0.0, -1.0])


def _frame_features(frames: Sequence) -> tuple[np.ndarray, np.ndarray]:
    """Per-frame (position, world view direction) feature arrays.

    A frame with a degenerate (near-zero-norm) quaternion contributes the
    un-rotated camera forward instead of NaNs — sampling must never crash
    on a malformed pose; validation of pose quality is not its job.
    """
    positions = np.zeros((len(frames), 3), dtype=np.float64)
    view_dirs = np.zeros((len(frames), 3), dtype=np.float64)
    for i, frame in enumerate(frames):
        pose = frame.camera_pose
        positions[i] = pose_position(pose)
        q = pose_quat(pose)
        norm = float(np.linalg.norm(q))
        if norm < 1e-6:
            view_dirs[i] = _CAMERA_FORWARD
            continue
        q = tuple(c / norm for c in q)
        view_dirs[i] = quat_to_rotmat(q) @ _CAMERA_FORWARD
    return positions, view_dirs


def _distance_matrix(positions: np.ndarray, view_dirs: np.ndarray) -> np.ndarray:
    """Full pairwise pose-diversity distance matrix (see module docstring)."""
    diffs = positions[:, None, :] - positions[None, :, :]
    pos_d = np.linalg.norm(diffs, axis=-1)
    cos = np.clip(view_dirs @ view_dirs.T, -1.0, 1.0)
    ang = np.arccos(cos)
    return pos_d + ROTATION_WEIGHT_M_PER_RAD * ang


def select_frames(frames: Sequence, max_frames: int | None = None) -> list:
    """Select a bounded, pose-diverse subset of frames.

    Returns the frames themselves (not indices), in their original input
    order. When len(frames) <= max_frames, returns all frames unchanged.
    max_frames None falls back to DEFAULT_MAX_FRAMES; values < 1 are
    clamped to 1 (a scene with a budget processes at least one frame).
    """
    if max_frames is None:
        max_frames = DEFAULT_MAX_FRAMES
    max_frames = max(1, int(max_frames))

    frames = list(frames)
    n = len(frames)
    if n <= max_frames:
        return frames

    positions, view_dirs = _frame_features(frames)
    dist = _distance_matrix(positions, view_dirs)

    # Seed with the most extreme frame (max summed distance to all others);
    # np.argmax's first-hit rule makes ties deterministic by lower index.
    selected = [int(np.argmax(dist.sum(axis=1)))]
    min_dist = dist[selected[0]].copy()

    while len(selected) < max_frames:
        # Never re-pick a selected frame, even in fully-degenerate inputs
        # where every distance is 0 (all poses identical).
        min_dist[selected] = -1.0
        nxt = int(np.argmax(min_dist))
        selected.append(nxt)
        min_dist = np.minimum(min_dist, dist[nxt])

    return [frames[i] for i in sorted(selected)]
