"""mask_refine's contract, on synthetic inputs (decision 0198, 0201).

The real-data companion holds the verdicts; this holds the invariants that
have to be true whatever the numbers are — that the pass is off unless
asked for, that every refusal names itself, that the detector degrades to
None rather than raising on a frame it cannot read, and that the prompt is
the detector's own region rather than the measured box's bbox.

Run from repo root:
    python -m pytest services/perception-obj/tests/test_mask_refine.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

_schemas_path = Path(__file__).resolve().parents[3] / "packages/schemas"
if str(_schemas_path) not in sys.path:
    sys.path.insert(0, str(_schemas_path))

import mask_refine  # noqa: E402


def _stack(*masks: np.ndarray) -> np.ndarray:
    return np.stack([np.asarray(m, dtype=bool) for m in masks])


def _rect(h, w, r0, r1, c0, c1) -> np.ndarray:
    m = np.zeros((h, w), dtype=bool)
    m[r0:r1, c0:c1] = True
    return m


class TestTheDefaultIsTodaysBehaviour:
    def test_the_pass_is_off_unless_asked_for(self):
        assert mask_refine.MASK_REFINE_ENABLED is False

    def test_every_threshold_is_env_overridable(self, monkeypatch):
        monkeypatch.setenv("PERCEPTION_MASK_REFINE_MIN_UNCLAIMED", "0.9")
        import importlib

        reloaded = importlib.reload(mask_refine)
        try:
            assert reloaded.MIN_UNCLAIMED_FRACTION == 0.9
        finally:
            monkeypatch.delenv("PERCEPTION_MASK_REFINE_MIN_UNCLAIMED")
            importlib.reload(mask_refine)


class TestAcceptance:
    def _judge(self, original, refined, others=(), **kw):
        stack = _stack(original, *others)
        return mask_refine.accept_refined(
            original=original, refined=refined, mask_stack=stack,
            mask_index=0, **kw,
        )

    def test_a_mask_that_did_not_grow_is_refused(self):
        m = _rect(40, 40, 5, 20, 5, 20)
        accepted, rec = self._judge(m, m.copy())
        assert accepted is False
        assert rec["reason"] == "no_growth"

    def test_a_mask_that_shrank_is_refused(self):
        m = _rect(40, 40, 5, 20, 5, 20)
        accepted, rec = self._judge(m, _rect(40, 40, 5, 15, 5, 15))
        assert accepted is False
        assert rec["reason"] == "no_growth"

    def test_a_mask_that_moved_off_the_original_is_refused(self):
        original = _rect(40, 40, 0, 10, 0, 10)
        refined = _rect(40, 40, 20, 35, 20, 35)
        accepted, rec = self._judge(original, refined)
        assert accepted is False
        assert rec["reason"] in ("iou_too_low", "original_not_contained")

    def test_runaway_growth_is_refused(self):
        original = _rect(40, 40, 0, 4, 0, 4)
        refined = _rect(40, 40, 0, 40, 0, 40)
        accepted, rec = self._judge(original, refined)
        assert accepted is False
        assert rec["reason"] in ("iou_too_low", "grew_too_much")

    def test_growth_that_eats_a_neighbour_is_refused(self):
        original = _rect(40, 40, 0, 20, 0, 20)
        neighbour = _rect(40, 40, 22, 30, 0, 20)
        refined = original | neighbour
        accepted, rec = self._judge(original, refined, others=(neighbour,))
        assert accepted is False
        assert rec["reason"] == "absorbed_a_neighbour"
        assert rec["neighbour_mask_index"] == 1

    def test_growth_away_from_the_signal_is_refused(self):
        original = _rect(40, 40, 0, 20, 0, 20)
        refined = original | _rect(40, 40, 20, 26, 0, 20)
        region = _rect(40, 40, 0, 20, 30, 40)  # signal points elsewhere
        accepted, rec = self._judge(original, refined, unclaimed_region=region)
        assert accepted is False
        assert rec["reason"] == "growth_is_not_what_the_signal_pointed_at"

    def test_growth_outside_the_measured_box_is_refused(self):
        original = _rect(40, 40, 0, 20, 0, 20)
        refined = original | _rect(40, 40, 20, 26, 0, 20)
        hull = _rect(40, 40, 0, 20, 0, 20)
        region = _rect(40, 40, 20, 26, 0, 20)
        accepted, rec = self._judge(
            original, refined, box_hull=hull, unclaimed_region=region
        )
        assert accepted is False
        assert rec["reason"] == "grew_outside_the_measured_box"

    def test_growth_onto_the_signal_inside_the_box_is_accepted(self):
        original = _rect(40, 40, 0, 20, 0, 20)
        added = _rect(40, 40, 20, 26, 0, 20)
        hull = _rect(40, 40, 0, 30, 0, 30)
        accepted, rec = self._judge(
            original, original | added, box_hull=hull, unclaimed_region=added
        )
        assert accepted is True
        assert rec["added_on_signal"] == 1.0
        assert rec["added_inside_box"] == 1.0
        assert "reason" not in rec

    def test_a_missing_refinement_is_refused_not_raised(self):
        m = _rect(40, 40, 5, 20, 5, 20)
        accepted, rec = self._judge(m, None)
        assert accepted is False
        assert rec["reason"] == "no_mask_returned"

    def test_a_wrong_shaped_refinement_is_refused_not_raised(self):
        m = _rect(40, 40, 5, 20, 5, 20)
        accepted, rec = self._judge(m, np.zeros((10, 10), dtype=bool))
        assert accepted is False
        assert rec["reason"] == "shape_mismatch"


class TestThePrompt:
    def test_the_prompt_is_normalized_cxcywh(self):
        mask = _rect(100, 200, 10, 30, 40, 60)
        box = mask_refine.prompt_box_cxcywh(mask, np.zeros((0, 2), dtype=int))
        assert box == pytest.approx([0.25, 0.2, 0.1, 0.2])

    def test_the_prompt_grows_to_hold_the_signal(self):
        mask = _rect(100, 200, 10, 30, 40, 60)
        signal = np.array([[80, 50]], dtype=int)
        grown = mask_refine.prompt_box_cxcywh(mask, signal)
        assert grown[3] > 0.2
        assert grown[1] > 0.2

    def test_an_empty_mask_has_no_prompt(self):
        assert mask_refine.prompt_box_cxcywh(
            np.zeros((10, 10), dtype=bool), np.zeros((0, 2), dtype=int)
        ) is None


class TestTheSignalRegion:
    def test_a_sample_paints_its_own_footprint(self):
        region = mask_refine.unclaimed_region_mask(
            np.array([[50, 50]]), (100, 100), (10, 10)
        )
        assert region[50, 50]
        assert region[40, 40]      # radius is ceil(100/10) = 10: 21x21
        assert not region[39, 39]
        assert region.sum() == 21 * 21

    def test_no_samples_paint_nothing(self):
        region = mask_refine.unclaimed_region_mask(
            np.zeros((0, 2), dtype=int), (20, 20), (10, 10)
        )
        assert not region.any()


class TestTheDetectorDegrades:
    def test_no_depth_is_none_not_an_error(self):
        assert mask_refine.unclaimed_in_box(
            box=None, room=None, camera_pose=None, depth_raster=None,
            depth_confidence=None, depth_intrinsics=None,
            mask_stack=_stack(_rect(8, 8, 0, 4, 0, 4)), mask_index=0,
        ) is None

    def test_a_mask_index_off_the_end_is_none(self):
        assert mask_refine.unclaimed_in_box(
            box=None, room=None, camera_pose=None,
            depth_raster=np.ones((4, 4), dtype=np.float32),
            depth_confidence=None, depth_intrinsics=None,
            mask_stack=_stack(_rect(8, 8, 0, 4, 0, 4)), mask_index=7,
        ) is None
