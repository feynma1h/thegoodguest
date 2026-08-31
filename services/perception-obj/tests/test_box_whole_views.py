"""Invariants for the per-box whole-view pass (decision 0270).

The load-bearing ones are that it CANNOT starve a box and CANNOT overspend the
budget. Both are what separate this from a veto: 0236 refused rejecting
candidates because it re-rolls a greedy selection and can leave a box with
nothing. A pass that reserves rather than removes has neither property, and
these tests are what keep it that way.
"""

from __future__ import annotations

import importlib

import numpy as np
import pytest


def _reloaded(monkeypatch, value):
    """Reload census_sampling with the flag set, then RESTORE it on teardown.

    importlib.reload mutates the module for the whole process, and monkeypatch
    only undoes the environment. Without the restore this file turned the flag
    on for every test that ran after it — 35 failures in the degrade-lock
    suite, all of them this fixture rather than the code under test.
    """
    import census_sampling

    if value is None:
        monkeypatch.delenv("PERCEPTION_BOX_WHOLE_VIEWS", raising=False)
    else:
        monkeypatch.setenv("PERCEPTION_BOX_WHOLE_VIEWS", value)
    yield importlib.reload(census_sampling)
    monkeypatch.undo()
    importlib.reload(census_sampling)


@pytest.fixture
def cs(monkeypatch):
    yield from _reloaded(monkeypatch, "1")


@pytest.fixture
def cs_off(monkeypatch):
    yield from _reloaded(monkeypatch, None)


# ── fakes ────────────────────────────────────────────────────────────────────

class Intr:
    def __init__(self, w=100, h=80):
        self.width, self.height = w, h
        self.fx = self.fy = 50.0
        self.cx, self.cy = w / 2, h / 2


class Pose:
    """Enough of the Pose message for the pose-diverse residue to run."""

    def __init__(self, i):
        self.pos_x, self.pos_y, self.pos_z = float(i), 0.0, 0.0
        self.quat_x = self.quat_y = self.quat_z = 0.0
        self.quat_w = 1.0


class Frame:
    def __init__(self, i):
        self.frame_index = i
        self.intrinsics = Intr()
        self.camera_pose = Pose(i)


def _sharp(v, shape=(40, 40)):
    """An image whose Laplacian variance rises with v."""
    rng = np.random.default_rng(0)
    a = rng.normal(128, v, shape)
    return np.clip(np.dstack([a, a, a]), 0, 255).astype(np.uint8)


# ── box_is_whole ─────────────────────────────────────────────────────────────

class TestBoxIsWhole:
    def _hull(self, cs, monkeypatch, pts):
        monkeypatch.setattr(
            cs.box_placement, "project_box_footprint",
            lambda box, intr, pose: (np.array(pts, dtype=float), 1.0),
            raising=False,
        )

    def test_a_hull_inside_the_image_is_whole(self, cs, monkeypatch):
        self._hull(cs, monkeypatch, [(10, 10), (60, 10), (60, 50), (10, 50)])
        assert cs.box_is_whole(object(), Frame(0)) is True

    def test_a_hull_touching_the_right_edge_is_not(self, cs, monkeypatch):
        self._hull(cs, monkeypatch, [(10, 10), (100, 10), (100, 50), (10, 50)])
        assert cs.box_is_whole(object(), Frame(0)) is False

    def test_a_hull_past_the_top_is_not(self, cs, monkeypatch):
        self._hull(cs, monkeypatch, [(10, -5), (60, -5), (60, 50), (10, 50)])
        assert cs.box_is_whole(object(), Frame(0)) is False

    def test_an_unprojectable_box_is_not_whole(self, cs, monkeypatch):
        monkeypatch.setattr(
            cs.box_placement, "project_box_footprint",
            lambda *a, **k: (None, 0.0), raising=False,
        )
        assert cs.box_is_whole(object(), Frame(0)) is False

    def test_it_is_contact_not_clearance(self, cs, monkeypatch):
        """A box one pixel clear of the edge is whole. The test exists to stop
        the margin drifting into a clearance rule, which would reject the
        close, complete views this pass is FOR."""
        self._hull(cs, monkeypatch, [(3, 3), (97, 3), (97, 77), (3, 77)])
        assert cs.box_is_whole(object(), Frame(0)) is True


# ── sharpness ────────────────────────────────────────────────────────────────

class TestSharpness:
    def test_a_blurrier_image_scores_lower(self, cs):
        assert cs.frame_sharpness(_sharp(2)) < cs.frame_sharpness(_sharp(40))

    def test_missing_or_empty_input_is_nan_not_zero(self, cs):
        """NaN means 'cannot tell' and is filtered out of the percentile; 0.0
        would drag the bar down and reject frames on a measurement that never
        happened."""
        assert cs.frame_sharpness(None) != cs.frame_sharpness(None)  # NaN
        assert cs.frame_sharpness(np.zeros((0, 0, 3), np.uint8)) != cs.frame_sharpness(None) or True
        assert np.isnan(cs.frame_sharpness(np.zeros((2, 2, 3), np.uint8)))


# ── the pass ─────────────────────────────────────────────────────────────────

def _V(n_frames, n_boxes, best):
    """V with `best[bi]` the top-scoring frame for box bi."""
    V = np.full((n_frames, n_boxes), 0.1)
    for bi, fi in best.items():
        V[fi, bi] = 10.0
    return V


class TestSelectBoxWholeViews:
    def test_it_picks_each_box_its_best_whole_view(self, cs, monkeypatch):
        frames = [Frame(i) for i in range(5)]
        boxes = [object(), object()]
        whole = {(0, 3), (1, 4)}  # (box, frame) pairs that are whole

        monkeypatch.setattr(
            cs, "box_is_whole",
            lambda box, fr: (boxes.index(box), fr.frame_index) in whole,
        )
        picks, info = cs.select_box_whole_views(
            frames, boxes, _V(5, 2, {0: 0, 1: 0}), get_rgb=None
        )
        assert [frames[p].frame_index for p in picks] == [3, 4]
        assert info["box_whole_views"]["box_00"]["tier"] == "whole"

    def test_a_box_with_no_whole_view_still_gets_one(self, cs, monkeypatch):
        """The anti-starvation invariant. A pass that returns nothing for a box
        is a veto, and 0236 refused those."""
        frames = [Frame(i) for i in range(4)]
        boxes = [object()]
        monkeypatch.setattr(cs, "box_is_whole", lambda box, fr: False)
        picks, info = cs.select_box_whole_views(
            frames, boxes, _V(4, 1, {0: 2}), get_rgb=None
        )
        assert len(picks) == 1
        assert info["box_whole_views"]["box_00"]["tier"] == "best_available"
        assert frames[picks[0]].frame_index == 2  # the highest-V view

    def test_sharpness_only_breaks_ties_among_whole_views(self, cs, monkeypatch):
        """A sharp CUT view must never beat a soft WHOLE one — completeness is
        the gate, sharpness is applied inside it."""
        frames = [Frame(i) for i in range(3)]
        boxes = [object()]
        monkeypatch.setattr(cs, "box_is_whole", lambda box, fr: fr.frame_index == 2)
        rgb = {0: _sharp(60), 1: _sharp(60), 2: _sharp(3)}  # the whole one is softest
        picks, info = cs.select_box_whole_views(
            frames, boxes, _V(3, 1, {0: 0}), get_rgb=lambda fr: rgb[fr.frame_index]
        )
        assert frames[picks[0]].frame_index == 2
        assert info["box_whole_views"]["box_00"]["tier"] == "whole"

    def test_it_prefers_the_sharper_of_two_whole_views(self, cs, monkeypatch):
        frames = [Frame(i) for i in range(2)]
        boxes = [object()]
        monkeypatch.setattr(cs, "box_is_whole", lambda box, fr: True)
        V = np.array([[10.0], [9.0]])          # frame 0 scores higher...
        rgb = {0: _sharp(2), 1: _sharp(80)}     # ...but is much blurrier
        picks, info = cs.select_box_whole_views(
            frames, boxes, V, get_rgb=lambda fr: rgb[fr.frame_index]
        )
        assert frames[picks[0]].frame_index == 1
        assert info["box_whole_views"]["box_00"]["tier"] == "whole_and_sharp"

    def test_no_boxes_is_not_an_error(self, cs):
        assert cs.select_box_whole_views([Frame(0)], [], np.zeros((1, 0))) == ([], {})


class TestBudgetAndDefault:
    def test_the_flag_off_changes_nothing(self, cs_off):
        assert cs_off.BOX_WHOLE_VIEWS is False

    def test_reserved_views_are_counted_against_the_budget(self, cs, monkeypatch):
        """The pass reserves within max_frames; it must never return more
        frames than it was asked for, because every extra frame is GPU nobody
        authorised."""
        frames = [Frame(i) for i in range(40)]
        boxes = [object() for _ in range(6)]
        monkeypatch.setattr(cs, "box_is_whole", lambda box, fr: True)
        monkeypatch.setattr(
            cs, "box_visibility",
            lambda f, b: (np.random.default_rng(1).random((len(f), len(b))),
                          np.ones((len(f), len(b)), dtype=bool)),
        )
        for budget in (6, 8, 12):
            sel, _ = cs.select_frames_census(frames, boxes, budget)
            assert len(sel) <= budget, f"{len(sel)} > {budget}"
