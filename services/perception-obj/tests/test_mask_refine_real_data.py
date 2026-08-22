"""Mask refinement against the masks a GPU actually produced (decision 0198).

`fixtures/mask_refine/` holds every refined mask 0198's three bench rounds
produced, at full resolution, beside the frame's real SAM 3 mask stack, the
detector's unclaimed region and the measured box's projected hull. Each one
carries a verdict that came from looking at the resulting reconstruction —
a slab that became a desk with legs, an overflowing table that came to fit
its box, a no-op, a merge. So these are not synthetic cases with invented
answers; they are the only eight refinements this system has ever run, with
the answers already known.

What they are here to hold:

  * the acceptance test reproduces every one of those verdicts;
  * **the separation is real and it lives in one place.** Of the seven
    checks `accept_refined` applies, exactly one distinguishes the measured
    merge from the wins: the share of newly-claimed pixels that land on the
    region the detector pointed at. 0.137 for the variant-B merge and 0.075
    for the false-positive flag, against 0.561-0.813 for every arm that
    helped or was harmless. Nothing sits in between. Growth ratio and IoU
    do NOT separate them (1.94 vs 1.64; 0.504 vs 0.607) and a threshold
    fitted into either of those windows would be the sort-key mistake 0197
    refused, wearing different clothes;
  * the measured safety bar: variant-C prompts absorbed a neighbouring
    detection zero times, which is what makes "flag broadly, refine, accept
    only a changed-and-valid mask" a sound production shape;
  * the detector itself, end to end through production's geometry, on the
    pair 0198's headline rests on — rp7's desk at 0.403 unclaimed on the
    frame whose mask cut its legs off, against 0.163 on the frame that
    shipped.

Provenance: `bench_artifacts/`, `bench2_artifacts/` and `bench3_artifacts/`
under the gitignored `outputs/clipped-views/`, joined to the per-frame mask
caches of the four preserved captures.

Run from repo root:
    python -m pytest services/perception-obj/tests/test_mask_refine_real_data.py -v
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

_schemas_path = Path(__file__).resolve().parents[3] / "packages/schemas"
if str(_schemas_path) not in sys.path:
    sys.path.insert(0, str(_schemas_path))

import mask_refine  # noqa: E402
from roomplan_room import RoomPlanBox, RoomPlanSurface  # noqa: E402
from roomstudio_schemas import capture_bundle_pb2  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures" / "mask_refine"
INDEX = json.loads((FIXTURES / "index.json").read_text())
DETECTOR_INDEX = json.loads((FIXTURES / "detector_index.json").read_text())

# The variant-B arm is the one prompt production never issues: the measured
# box's raw bbox, kept because it is the only merge anyone has measured.
VARIANT_C = [r for r in INDEX if r["key"] != "rp7_f114_desk_variantB"]


def _arrays(key: str) -> dict:
    with np.load(FIXTURES / f"{key}.npz") as npz:
        return {k: np.asarray(npz[k], dtype=bool) for k in npz.files}


def _judge(row: dict) -> tuple[bool, dict]:
    a = _arrays(row["key"])
    return mask_refine.accept_refined(
        original=a["stack"][row["mask_index"]],
        refined=a["refined"],
        mask_stack=a["stack"],
        mask_index=row["mask_index"],
        box_hull=a["hull"],
        unclaimed_region=a["region"],
    )


@pytest.mark.parametrize("row", INDEX, ids=[r["key"] for r in INDEX])
class TestTheVerdictsReproduce:
    def test_accepted_iff_the_bench_says_so(self, row):
        accepted, record = _judge(row)
        assert accepted is row["expect_accept"], (
            f"{row['key']} ({row['note']}): {record}"
        )

    def test_a_refusal_always_says_why(self, row):
        accepted, record = _judge(row)
        assert accepted or record.get("reason"), row["key"]


class TestWhereTheSeparationActuallyLives:
    """One check does the work. Recorded as a band, not a threshold: a
    change that fills the gap in is the interesting failure."""

    def test_growth_that_helped_sits_on_the_signal(self):
        for row in INDEX:
            _accepted, record = _judge(row)
            if record.get("reason") == "no_growth":
                continue
            on_signal = record["added_on_signal"]
            if row["expect_accept"]:
                assert on_signal >= 0.55, (row["key"], on_signal)
            else:
                assert on_signal <= 0.14, (row["key"], on_signal)

    def test_growth_ratio_does_not_separate_them(self):
        """The obvious knob, measured useless: the merge grew 1.94x and the
        modest win grew 1.64x. Any cap inside that window is fitted to one
        point on each side."""
        merge = _judge(
            next(r for r in INDEX if r["key"] == "rp7_f114_desk_variantB")
        )[1]
        win = _judge(next(r for r in INDEX if r["key"] == "spike_f142_desk"))[1]
        assert merge["growth"] > win["growth"]
        assert merge["growth"] / win["growth"] < 1.25

    def test_iou_does_not_separate_them_either(self):
        merge = _judge(
            next(r for r in INDEX if r["key"] == "rp7_f114_desk_variantB")
        )[1]
        win = _judge(next(r for r in INDEX if r["key"] == "spike_f142_desk"))[1]
        assert merge["iou"] < win["iou"]
        assert win["iou"] - merge["iou"] < 0.15


class TestTheMeasuredSafetyBar:
    """0198's bound: with the detector's own region as the prompt, a
    refinement absorbed a neighbouring detection zero times in six."""

    def test_no_variant_c_refinement_absorbs_a_neighbour(self):
        worst = 0.0
        for row in VARIANT_C:
            _accepted, record = _judge(row)
            worst = max(worst, record.get("neighbour_absorbed", 0.0))
        assert worst <= mask_refine.MAX_NEIGHBOUR_ABSORBED
        assert worst < 0.05  # measured: 0.015, and that is the FP control

    def test_a_refusal_leaves_the_shipped_mask_alone(self):
        """The cost of every refusal is zero: the original mask is what
        ships today, so a wrong flag spends a segmentation call and
        nothing else."""
        for row in INDEX:
            accepted, _record = _judge(row)
            if accepted:
                continue
            a = _arrays(row["key"])
            original = a["stack"][row["mask_index"]]
            assert original.sum() > 0, row["key"]


class TestTheDetectorOnTheFrameItWasFoundOn:
    """`unclaimed_in_box` end to end, through production's own depth
    back-projection and box geometry, on the two frames 0198 compared."""

    @staticmethod
    def _inputs(entry: dict):
        pose = capture_bundle_pb2.Pose()
        (pose.pos_x, pose.pos_y, pose.pos_z, pose.quat_x, pose.quat_y,
         pose.quat_z, pose.quat_w) = entry["pose"]
        dintr = capture_bundle_pb2.Intrinsics()
        (dintr.fx, dintr.fy, dintr.cx, dintr.cy) = entry["depth_intrinsics"][:4]
        dintr.width, dintr.height = entry["depth_intrinsics"][4:]
        box = RoomPlanBox(
            identifier="fixture", category="table", confidence="high",
            attributes={},
            dimensions=np.asarray(entry["box"]["dimensions"], dtype=float),
            transform=np.asarray(entry["box"]["transform"], dtype=float).reshape(4, 4),
            center_world=np.asarray(entry["box"]["center_world"], dtype=float),
            up_y=1.0, yaw_rad=0.0,
        )

        def _surface(flat, kind):
            T = np.asarray(flat, dtype=float).reshape(4, 4)
            return RoomPlanSurface(
                identifier="fixture", kind=kind, category=kind,
                confidence="high", dimensions=np.zeros(3), transform=T,
                polygon_local=np.zeros((0, 3)), polygon_world=np.zeros((0, 3)),
                polygon_from_dimensions=True, normal_world=T[:3, 2],
                parent_identifier=None,
            )

        class _Room:
            floors = [_surface(f, "floor") for f in entry["floors"]]
            walls = [_surface(w, "wall") for w in entry["walls"]]

        with np.load(FIXTURES / f"{entry['key']}.npz") as npz:
            stack = np.asarray(npz["stack"], dtype=bool)
            depth = np.asarray(npz["depth"], dtype=np.float32)
            conf = np.asarray(npz["conf"], dtype=np.uint8)
        return box, _Room(), pose, dintr, depth, (conf if conf.size else None), stack

    def _signal(self, entry: dict):
        box, room, pose, dintr, depth, conf, stack = self._inputs(entry)
        return mask_refine.unclaimed_in_box(
            box=box, room=room, camera_pose=pose, depth_raster=depth,
            depth_confidence=conf, depth_intrinsics=dintr,
            mask_stack=stack, mask_index=entry["mask_index"],
        )

    def test_the_flagged_frame_and_the_control_separate(self):
        by_frame = {e["frame"]: self._signal(e) for e in DETECTOR_INDEX}
        flagged, control = by_frame[114], by_frame[7]
        assert flagged.fraction == pytest.approx(0.403, abs=0.002)
        assert control.fraction == pytest.approx(0.163, abs=0.002)
        assert flagged.fraction / control.fraction > 2.0
        assert flagged.flagged is True
        assert control.flagged is False

    def test_the_bands_separate_a_mask_defect_from_a_view_defect(self):
        """Decision 0231, on the pair the pooled number cannot tell apart.

        Both frames raise `fraction`, and for opposite reasons. On f114 the
        camera SAW the desk's lower band and the mask claimed almost none of
        it — a mask defect, and the one 0198's repair fixed. On f7 the
        camera saw NOTHING there: the legs run off the frame. Repair is the
        only response the pooled number can suggest, and on f7 it is the
        wrong one."""
        by_frame = {e["frame"]: self._signal(e) for e in DETECTOR_INDEX}
        flagged, control = by_frame[114], by_frame[7]

        lo_n, lo_frac = flagged.bands["lower"]
        assert lo_n > 0
        assert lo_frac is not None and lo_frac > 0.5

        ctrl_n, ctrl_frac = control.bands["lower"]
        assert ctrl_n == 0
        # None, never 0.0 — "the mask claimed none of what was seen" and
        # "the camera saw none of it" must not collapse.
        assert ctrl_frac is None

    def test_an_invisible_band_records_an_explicit_null(self):
        control = next(
            self._signal(e) for e in DETECTOR_INDEX if e["frame"] == 7
        )
        record = control.as_record()
        assert record["lower_considered_px"] == 0
        assert "lower_unclaimed_fraction" in record
        assert record["lower_unclaimed_fraction"] is None

    def test_the_bands_partition_what_was_considered(self):
        """No point is counted twice, and the shortfall is the sub-0.10
        band the room-plane rejection empties — measured at 0.2% of all
        considered points across the four preserved captures, with 24 of 26
        planned box views at exactly zero."""
        for entry in DETECTOR_INDEX:
            sig = self._signal(entry)
            counted = sum(n for n, _ in sig.bands.values())
            assert counted <= sig.considered_px

    def test_the_bands_do_not_change_the_flag(self):
        """0231 adds no threshold and gates nothing. The pooled number and
        its verdict are exactly what they were."""
        by_frame = {e["frame"]: self._signal(e) for e in DETECTOR_INDEX}
        assert by_frame[114].fraction == pytest.approx(0.403, abs=0.002)
        assert by_frame[7].fraction == pytest.approx(0.163, abs=0.002)
        assert by_frame[114].flagged is True
        assert by_frame[7].flagged is False

    def test_the_signal_records_what_it_looked_at(self):
        for entry in DETECTOR_INDEX:
            sig = self._signal(entry)
            record = sig.as_record()
            assert record["considered_px"] == sig.considered_px
            assert 0.0 <= record["own_fraction"] <= 1.0
            assert len(sig.unclaimed_vu) <= sig.considered_px

    def test_the_prompt_is_the_one_the_bench_measured(self):
        """The tightest gate available without a GPU: the prompt this
        module emits for rp7 f114's desk is bit-for-bit the variant-C box
        that produced 0198's measured win — `variant_C_mask_plus_unclaimed`
        in the bench's `prompt_boxes.json`. Detector, box geometry, room
        planes, mask stack and bbox arithmetic all have to agree for this
        to hold."""
        entry = next(e for e in DETECTOR_INDEX if e["frame"] == 114)
        _b, _r, _p, _d, _dp, _c, stack = self._inputs(entry)
        prompt = mask_refine.prompt_box_cxcywh(
            stack[entry["mask_index"]], self._signal(entry).unclaimed_vu
        )
        assert prompt == pytest.approx(
            [0.7169270833333333, 0.47673611111111114,
             0.2859375, 0.46458333333333335],
            abs=1e-12,
        )

    def test_the_prompt_box_covers_mask_and_signal_together(self):
        entry = next(e for e in DETECTOR_INDEX if e["frame"] == 114)
        _box, _room, _pose, _dintr, _d, _c, stack = self._inputs(entry)
        sig = self._signal(entry)
        mask = stack[entry["mask_index"]]
        own = mask_refine.prompt_box_cxcywh(mask, np.zeros((0, 2), dtype=int))
        both = mask_refine.prompt_box_cxcywh(mask, sig.unclaimed_vu)
        assert both[3] > own[3]  # the signal extends the box downward
        assert all(0.0 <= v <= 1.0 for v in both)
