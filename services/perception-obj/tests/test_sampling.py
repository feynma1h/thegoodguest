"""Invariant tests for sampling.select_frames (pose-diverse frame selection).

These pin the sampler's contract — bounds, determinism, order preservation,
and diversity (spatial + view-direction) — not the FPS implementation. They
must still pass if the selection algorithm is swapped for anything that
honors the same contract.

Run from repo root:
  pytest services/perception-obj/tests/test_sampling.py -v
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

_schemas_path = Path(__file__).resolve().parents[3] / "packages/schemas"
if str(_schemas_path) not in sys.path:
    sys.path.insert(0, str(_schemas_path))

from thegoodguest_schemas import CaptureBundle  # noqa: E402
from sampling import select_frames  # noqa: E402  (conftest adds the service dir)


def _make_frames(specs):
    """Build Frame protos from (pos_xyz, yaw_deg) specs.

    Yaw rotates about world +Y; yaw 0 looks down world -Z (ARKit camera
    forward). Frames get sequential frame_index values.
    """
    bundle = CaptureBundle()
    for i, (pos, yaw_deg) in enumerate(specs):
        f = bundle.frames.add()
        f.frame_index = i
        f.camera_pose.pos_x, f.camera_pose.pos_y, f.camera_pose.pos_z = pos
        half = math.radians(yaw_deg) / 2.0
        f.camera_pose.quat_y = math.sin(half)
        f.camera_pose.quat_w = math.cos(half)
    return list(bundle.frames)


def _indices(frames):
    return [f.frame_index for f in frames]


def _yaw_of(frame) -> float:
    """Recover the yaw (degrees) of a frame built by _make_frames."""
    return math.degrees(2.0 * math.atan2(frame.camera_pose.quat_y,
                                         frame.camera_pose.quat_w))


class TestBounds:
    def test_returns_all_when_under_cap(self):
        frames = _make_frames([((i * 0.1, 0, 0), 0) for i in range(5)])
        assert _indices(select_frames(frames, 12)) == [0, 1, 2, 3, 4]

    def test_returns_all_at_exact_cap(self):
        frames = _make_frames([((i * 0.1, 0, 0), 0) for i in range(12)])
        assert _indices(select_frames(frames, 12)) == list(range(12))

    def test_selects_exactly_max_when_over_cap(self):
        frames = _make_frames([((i * 0.1, 0, 0), i * 2.0) for i in range(50)])
        out = select_frames(frames, 12)
        assert len(out) == 12
        assert len(set(_indices(out))) == 12  # no duplicates

    def test_max_frames_clamped_to_at_least_one(self):
        frames = _make_frames([((i * 0.1, 0, 0), 0) for i in range(5)])
        assert len(select_frames(frames, 0)) == 1


class TestDeterminismAndOrder:
    def test_deterministic(self):
        frames = _make_frames(
            [((math.sin(i), 0.0, math.cos(i * 0.7)), i * 7.0) for i in range(60)]
        )
        assert _indices(select_frames(frames, 10)) == _indices(select_frames(frames, 10))

    def test_preserves_input_order(self):
        frames = _make_frames(
            [((math.sin(i), 0.0, math.cos(i * 0.7)), i * 7.0) for i in range(60)]
        )
        idx = _indices(select_frames(frames, 10))
        assert idx == sorted(idx)

    def test_output_is_subset_of_input(self):
        frames = _make_frames([((i * 0.3, 0, 0), 0) for i in range(30)])
        assert set(_indices(select_frames(frames, 8))) <= set(range(30))


class TestDiversity:
    def test_two_spatial_clusters_both_represented(self):
        """A capture that lingers in one corner then moves: a temporal-prefix
        or budget-truncated pick would take everything from cluster A; a
        pose-diverse pick must cover both."""
        cluster_a = [((0.02 * i, 0.0, 0.01 * i), 0.0) for i in range(40)]
        cluster_b = [((5.0 + 0.02 * i, 0.0, 3.0 + 0.01 * i), 0.0) for i in range(40)]
        frames = _make_frames(cluster_a + cluster_b)
        out = select_frames(frames, 6)
        idx = set(_indices(out))
        assert any(i < 40 for i in idx), "cluster A unrepresented"
        assert any(i >= 40 for i in idx), "cluster B unrepresented"

    def test_yaw_diversity_when_stationary(self):
        """Pure pan in place (zero baseline): selection must spread by view
        direction, not collapse to adjacent frames."""
        frames = _make_frames([((0.0, 1.5, 0.0), float(y)) for y in range(0, 180)])
        out = select_frames(frames, 5)
        yaws = sorted(_yaw_of(f) for f in out)
        assert yaws[-1] - yaws[0] >= 120.0, f"span too narrow: {yaws}"
        gaps = [b - a for a, b in zip(yaws, yaws[1:], strict=False)]
        assert min(gaps) >= 15.0, f"selected views too bunched: {yaws}"

    def test_translation_diversity_on_a_line(self):
        """Camera walking a straight line: selection spans the walk, and no
        two picks are closer than a fair share of it."""
        frames = _make_frames([((0.05 * i, 0.0, 0.0), 0.0) for i in range(100)])
        out = select_frames(frames, 5)
        xs = sorted(f.camera_pose.pos_x for f in out)
        assert xs[-1] - xs[0] >= 0.8 * (0.05 * 99)
        gaps = [b - a for a, b in zip(xs, xs[1:], strict=False)]
        assert min(gaps) >= (0.05 * 99) / (2 * 4)


class TestDegenerateInputs:
    def test_identical_poses_no_crash(self):
        frames = _make_frames([((1.0, 1.0, 1.0), 45.0) for _ in range(30)])
        out = select_frames(frames, 4)
        assert len(out) == 4
        assert len(set(_indices(out))) == 4

    def test_zero_norm_quaternions_no_crash(self):
        bundle = CaptureBundle()
        for i in range(20):
            f = bundle.frames.add()
            f.frame_index = i
            f.camera_pose.pos_x = float(i)
            # all quat components left at 0.0 — malformed pose
        out = select_frames(list(bundle.frames), 6)
        assert len(out) == 6
