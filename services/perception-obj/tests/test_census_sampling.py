"""Census-driven frame selection invariants (decision 0077 lock 6;
census_sampling.py): the spike-fixture coverage gate (all 9 boxes covered
well inside PERCEPTION_MAX_FRAMES, pinned at the achieved greedy picks),
determinism, the pose-diverse residue, and the no-census equivalence with
the 0062 sampler.

Run from repo root:
    python -m pytest services/perception-obj/tests/test_census_sampling.py -v
"""
from __future__ import annotations

import math
from pathlib import Path

import census_sampling
import numpy as np
import pytest
import sampling
from roomplan_room import RoomPlanBox, parse_captured_room
from roomstudio_schemas import CaptureBundle

SPIKE_ROOM_JSON = (
    Path(__file__).resolve().parent / "fixtures" / "roomplan_spike"
    / "captured_room_built.json"
)
SPIKE_BUNDLE = Path(
    "/Users/aubrey/projects/roomstudio/outputs/roomplan-spike-bundle/bundle.pb"
)

_needs_spike_bundle = pytest.mark.skipif(
    not SPIKE_BUNDLE.exists(),
    reason="converted spike bundle only in the main checkout's outputs/",
)


class _Frame:
    """Minimal frame stand-in (camera_pose + intrinsics + frame_index)."""

    class _Pose:
        def __init__(self, pos, quat):
            self.pos_x, self.pos_y, self.pos_z = pos
            self.quat_x, self.quat_y, self.quat_z, self.quat_w = quat

    class _Intr:
        def __init__(self):
            self.fx = self.fy = 60.0
            self.cx = self.cy = 32.0
            self.width = self.height = 64

    def __init__(self, index, pos, yaw_deg=0.0):
        half = math.radians(yaw_deg) / 2.0
        self.frame_index = index
        self.camera_pose = self._Pose(pos, (0.0, math.sin(half), 0.0, math.cos(half)))
        self.intrinsics = self._Intr()


def _box(center, dims=(2.0, 0.5, 1.0), identifier="B"):
    T = np.eye(4)
    T[:3, 3] = center
    return RoomPlanBox(
        identifier=identifier, category="bed", confidence="high", attributes={},
        dimensions=np.asarray(dims, dtype=float), transform=T,
        center_world=np.asarray(center, dtype=float), up_y=1.0, yaw_rad=0.0,
    )


class TestSynthetic:
    def test_cover_picks_the_frame_that_sees_the_box(self):
        # 20 frames marching +x; the box sits in front of frame 0 only.
        frames = [_Frame(i, (0.5 * i, 0.0, 0.0)) for i in range(20)]
        box = _box((0.0, 0.0, -3.0))
        selected, info = census_sampling.select_frames_census(frames, [box], 4)
        assert len(selected) == 4
        assert 0 in [f.frame_index for f in selected]
        assert info["box_coverage"]["box_00"]
        assert info["uncovered_box_ids"] == []

    def test_unseen_box_recorded_uncovered(self):
        frames = [_Frame(i, (0.5 * i, 0.0, 0.0)) for i in range(20)]
        behind = _box((0.0, 0.0, 5.0))  # behind every camera
        selected, info = census_sampling.select_frames_census(frames, [behind], 4)
        assert len(selected) == 4  # residue still fills the budget
        assert info["uncovered_box_ids"] == ["box_00"]
        assert info["box_coverage"]["box_00"] == []

    def test_no_boxes_equals_0062_sampler(self):
        """With an empty census the residue IS the 0062 metric from the
        same seeding — selection identical to sampling.select_frames."""
        frames = [_Frame(i, (0.3 * i, 0.0, 0.1 * (i % 3)), yaw_deg=5.0 * i)
                  for i in range(30)]
        ours = census_sampling.select_frames_census(frames, [], 8)[0]
        legacy = sampling.select_frames(frames, 8)
        assert [f.frame_index for f in ours] == [f.frame_index for f in legacy]

    def test_small_bundle_taken_whole(self):
        frames = [_Frame(i, (0.5 * i, 0.0, 0.0)) for i in range(3)]
        selected, info = census_sampling.select_frames_census(
            frames, [_box((0.0, 0.0, -3.0))], 12
        )
        assert [f.frame_index for f in selected] == [0, 1, 2]
        assert "box_coverage" in info

    def test_output_preserves_input_order(self):
        frames = [_Frame(i, (0.4 * i, 0.0, 0.0), yaw_deg=7.0 * i) for i in range(25)]
        selected, _ = census_sampling.select_frames_census(
            frames, [_box((2.0, 0.0, -3.0))], 6
        )
        indices = [f.frame_index for f in selected]
        assert indices == sorted(indices)

    def test_deterministic(self):
        frames = [_Frame(i, (0.4 * i, 0.0, 0.05 * i), yaw_deg=4.0 * i)
                  for i in range(40)]
        boxes = [_box((1.0, 0.0, -3.0)), _box((6.0, 0.0, -2.0), identifier="C")]
        a, ia = census_sampling.select_frames_census(frames, boxes, 6)
        b, ib = census_sampling.select_frames_census(frames, boxes, 6)
        assert [f.frame_index for f in a] == [f.frame_index for f in b]
        assert ia == ib


@_needs_spike_bundle
class TestSpikeFixtureGate:
    """The census set-cover gate: on the spike fixture all 9 boxes are
    covered in <= PERCEPTION_MAX_FRAMES with >= 1 good view each; deterministic;
    achieved greedy picks pinned (7 cover frames, measured)."""

    @pytest.fixture(scope="class")
    def spike(self):
        b = CaptureBundle()
        b.ParseFromString(SPIKE_BUNDLE.read_bytes())
        room = parse_captured_room(SPIKE_ROOM_JSON.read_bytes())
        return b, room

    def test_nine_of_nine_covered_within_budget(self, spike):
        b, room = spike
        selected, info = census_sampling.select_frames_census(
            b.frames, room.objects, 12
        )
        assert len(selected) <= 12
        assert info["uncovered_box_ids"] == []
        assert len(info["box_coverage"]) == 9
        assert all(v for v in info["box_coverage"].values())

    def test_achieved_cover_picks_pinned(self, spike):
        b, room = spike
        _selected, info = census_sampling.select_frames_census(
            b.frames, room.objects, 12
        )
        # Measured on the probe run: greedy covers 9/9 in 7 picks.
        assert info["cover_frame_indices"] == [10, 61, 142, 171, 398, 568, 613]
        assert len(info["residue_frame_indices"]) == 5

    def test_deterministic_on_real_data(self, spike):
        b, room = spike
        a, ia = census_sampling.select_frames_census(b.frames, room.objects, 12)
        c, ic = census_sampling.select_frames_census(b.frames, room.objects, 12)
        assert [f.frame_index for f in a] == [f.frame_index for f in c]
        assert ia == ic
