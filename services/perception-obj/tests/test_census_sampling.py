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
from thegoodguest_schemas import CaptureBundle

SPIKE_ROOM_JSON = (
    Path(__file__).resolve().parent / "fixtures" / "roomplan_spike"
    / "captured_room_built.json"
)
SPIKE_BUNDLE = Path(
    "/Users/aubrey/projects/thegoodguest/outputs/roomplan-spike-bundle/bundle.pb"
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


def _lit(n: int = 32) -> np.ndarray:
    """A frame with light and texture — passes veto 1 on every check."""
    g = np.full((n, n), 128.0)
    g[::2, ::2] = 168.0
    return g


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


# ---------------------------------------------------------------------------
# The two vetoes (decision 0234)
# ---------------------------------------------------------------------------

class TestVetoOne:
    """Whole-frame usability. REJECT ONLY — it never ranks, and it never
    rejects a frame it cannot assess."""

    def _grey(self, v=128.0, n=32):
        g = np.full((n, n), v, dtype=float)
        g[::2, ::2] = v + 40  # texture, so the blur check passes
        return g

    def test_a_normal_frame_is_usable(self):
        assert census_sampling.frame_is_usable(self._grey()) is True

    def test_a_black_frame_is_not(self):
        assert census_sampling.frame_is_usable(np.zeros((32, 32))) is False

    def test_a_blown_out_frame_is_not(self):
        assert census_sampling.frame_is_usable(np.full((32, 32), 255.0)) is False

    def test_a_featureless_frame_is_not(self):
        """Uniform mid-grey: bright enough, not blown, and carrying no
        gradient at all."""
        assert census_sampling.frame_is_usable(np.full((32, 32), 128.0)) is False

    def test_no_pixels_is_not_a_rejection(self):
        assert census_sampling.frame_is_usable(None) is True
        assert census_sampling.frame_is_usable(np.zeros((0, 0))) is True

    def test_it_accepts_colour_or_luma(self):
        rgb = np.dstack([self._grey()] * 3)
        assert census_sampling.frame_is_usable(rgb) is True


class TestVetoTwo:
    """Per (object, frame) lower-band visibility. Zero only — never a
    ranking, because part-wise visibility separated an object with no leg
    failure mode by 5.7x and its top-ranked frames have never been
    reconstructed."""

    def test_no_depth_is_not_a_rejection(self):
        assert census_sampling.box_band_is_visible(
            object(), None, _Frame(0, (0.0, 0.0, 0.0)), None
        ) is True

    def test_no_box_is_not_a_rejection(self):
        assert census_sampling.box_band_is_visible(
            None, None, _Frame(0, (0.0, 0.0, 0.0)), lambda fi: None
        ) is True

    def test_an_error_is_not_a_rejection(self):
        def _boom(_fi):
            raise RuntimeError("depth exploded")

        assert census_sampling.box_band_is_visible(
            _box((0.0, 0.0, -3.0)), None,
            _Frame(0, (0.0, 0.0, 0.0)), _boom
        ) is True


class TestTheVetoesAreOffByDefault:
    def test_the_flag_defaults_off(self):
        assert census_sampling.VISIBILITY_VETO is False

    def test_no_accessors_means_no_veto_block(self):
        frames = [_Frame(i, (0.5 * i, 0.0, 0.0)) for i in range(8)]
        _sel, info = census_sampling.select_frames_census(
            frames, [_box((0.0, 0.0, -3.0))], 4)
        assert "veto" not in info


class TestTheVetoesShapeSelection:
    """Wired end to end over synthetic frames. The four preserved captures'
    real answers are recorded in decision 0234 — they need depth and RGB
    rasters this fixture does not carry."""

    def _run(self, monkeypatch, *, bad_frames=(), max_frames=4, n=10):
        monkeypatch.setattr(census_sampling, "VISIBILITY_VETO", True)
        frames = [_Frame(i, (0.5 * i, 0.0, 0.0)) for i in range(n)]
        seen = {"rgb": [], "depth": []}

        def get_rgb(fi):
            seen["rgb"].append(fi)
            return np.zeros((16, 16)) if fi in bad_frames else _lit()

        def get_depth(fi):
            seen["depth"].append(fi)
            return None

        sel, info = census_sampling.select_frames_census(
            frames, [_box((0.0, 0.0, -3.0))], max_frames,
            room=None, get_depth=get_depth, get_rgb=get_rgb,
        )
        return [f.frame_index for f in sel], info, seen

    def test_an_unusable_frame_never_reaches_the_selection(self, monkeypatch):
        idx, info, _ = self._run(monkeypatch, bad_frames={0, 1, 2})
        assert not ({0, 1, 2} & set(idx))
        assert set(info["veto"]["unusable_frames"]) <= {0, 1, 2}

    def test_the_residue_draws_from_survivors_too(self, monkeypatch):
        """The gap this test exists for: the cover pass and the residue pass
        pick separately, and a frame carrying no information is no more
        useful as pose spread than as coverage."""
        idx, _info, _ = self._run(monkeypatch, bad_frames={0, 1, 2}, max_frames=8)
        assert not ({0, 1, 2} & set(idx))

    def test_the_block_is_recorded(self, monkeypatch):
        _idx, info, _ = self._run(monkeypatch, bad_frames={0})
        assert info["veto"]["policy"] == "visibility_veto_v1"
        assert "unusable_frames" in info["veto"]
        assert "band_vetoed_pairs" in info["veto"]
        assert "relaxed_boxes" in info["veto"]

    def test_the_vetoes_are_asked_only_about_winners(self, monkeypatch):
        """The cost property, pinned. Scoring every candidate would fetch a
        frame's pixels AND its depth raster per keyframe — 1,444 blobs on
        the spike capture — to answer a question about the handful that get
        picked. Asked lazily, the count stays near the number selected."""
        n, max_frames = 40, 4
        idx, _info, seen = self._run(monkeypatch, max_frames=max_frames, n=n)
        assert len(set(seen["rgb"])) <= max_frames * 3
        assert len(set(seen["rgb"])) < n
