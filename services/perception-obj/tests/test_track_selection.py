"""Invariants for per-object best-frame selection over tracked segments.

These pin the RULES, not an implementation: what disqualifies a frame for one
object without disqualifying it for another, what the score does when a term
cannot be measured, and -- the one this module exists for -- that nothing here
decides what an object IS. 0279 measured the tracker's ids as unstable across a
revisit, so a test suite that let `object_key` mean `obj_id` by default would
pin in the defect.

Masks are built by hand at small sizes. Every threshold in SelectionConfig is a
fraction, so a 100x100 raster exercises the same arithmetic as the 480x360 one
/track writes.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from track_selection import (  # noqa: E402
    DEFAULT_CONFIG,
    Detection,
    SelectionConfig,
    apply_key_map,
    instance_key,
    mask_bbox,
    merge_nested_instances,
    select_best_frames,
)

H = W = 100


def blob(x0, y0, x1, y1, *, shape=(H, W)) -> np.ndarray:
    m = np.zeros(shape, dtype=bool)
    m[y0:y1, x0:x1] = True
    return m


def det(key, fi, mask) -> Detection:
    return Detection(object_key=key, frame_index=fi, mask=mask)


def centred(size=30) -> np.ndarray:
    """A comfortable mask: central, well clear of the border, large enough."""
    o = (W - size) // 2
    return blob(o, o, o + size, o + size)


# ── the unit of selection ────────────────────────────────────────────────────


class TestTheModuleNeverDecidesWhatAnObjectIs:
    def test_object_key_is_taken_verbatim_from_the_caller(self):
        dets = [det("whatever-the-caller-calls-it", 0, centred())]
        out = select_best_frames(dets)
        assert list(out) == ["whatever-the-caller-calls-it"]

    def test_two_fragments_of_one_object_stay_two_objects_until_re_keyed(self):
        """0279's `nightstand#1` / `#2`: disjoint windows, so nothing in the
        data can merge them and this module must not pretend otherwise."""
        dets = [det("nightstand#1", 0, centred()), det("nightstand#2", 90, centred())]
        assert len(select_best_frames(dets)) == 2

        merged = apply_key_map(dets, {"nightstand#2": "nightstand#1"})
        out = select_best_frames(merged)
        assert list(out) == ["nightstand#1"]
        assert out["nightstand#1"].n_frames == 2

    def test_instance_key_is_offered_not_applied(self):
        assert instance_key("nightstand", 2) == "nightstand#2"


class TestMergingTheHalfThatIsMeasurable:
    def test_two_names_for_the_same_pixels_merge(self):
        """`artwork#0` and `painting#1`: 54 shared frames at containment 0.999."""
        m = centred()
        dets = [det("artwork#0", f, m) for f in range(3)]
        dets += [det("painting#1", f, m) for f in range(3)]
        km = merge_nested_instances(dets)
        assert km["artwork#0"] == km["painting#1"] == "artwork#0"

    def test_a_nested_mask_merges_even_at_low_iou(self):
        """`cabinet#1` contains `door#3` at 0.999 containment, IoU 0.493 --
        containment is the test, not IoU."""
        big, small = blob(20, 20, 80, 80), blob(30, 30, 50, 50)
        dets = [det("cabinet#1", 0, big), det("door#3", 0, small)]
        assert len(set(merge_nested_instances(dets).values())) == 1

    def test_a_genuine_partial_overlap_does_not_merge(self):
        """`desk#0` / `speaker#0` sits at containment 0.511 -- the highest
        non-nested pair in the capture, and it must stay two objects."""
        desk, speaker = blob(10, 10, 70, 70), blob(60, 60, 90, 90)
        overlap = int(np.logical_and(desk, speaker).sum())
        assert 0 < overlap / min(desk.sum(), speaker.sum()) < DEFAULT_CONFIG.nested_containment
        assert len(set(merge_nested_instances([det("desk#0", 0, desk),
                                               det("speaker#0", 0, speaker)]).values())) == 2

    def test_instances_that_share_no_frame_are_never_merged(self):
        m = centred()
        km = merge_nested_instances([det("a#0", 0, m), det("b#0", 50, m)])
        assert km["a#0"] != km["b#0"]

    def test_the_merged_key_does_not_depend_on_input_order(self):
        m = centred()
        a = [det("zebra#0", 0, m), det("apple#0", 0, m)]
        assert merge_nested_instances(a) == merge_nested_instances(list(reversed(a)))


# ── stage 1: the hard filters ────────────────────────────────────────────────


class TestFiltersAreDecidedPerObjectNotPerFrame:
    def test_one_frame_can_serve_one_object_and_fail_another(self):
        edge = blob(0, 40, 20, 60)          # touching the left border
        dets = [det("good", 0, centred()), det("cut", 0, edge)]
        out = select_best_frames(dets)
        assert out["good"].n_kept == 1
        assert out["cut"].n_kept == 0
        assert "border" in out["cut"].frames[0].reasons


class TestBorder:
    @pytest.mark.parametrize("mask,fires", [
        (centred(), False),
        (blob(0, 40, 30, 60), True),        # left edge
        (blob(40, 0, 60, 30), True),        # top edge
        (blob(70, 40, W, 60), True),        # right edge
        (blob(40, 70, 60, H), True),        # bottom edge
    ])
    def test_reaching_any_edge_band_rejects(self, mask, fires):
        out = select_best_frames([det("o", 0, mask)])
        assert ("border" in out["o"].frames[0].reasons) is fires

    def test_a_zero_margin_still_means_touching(self):
        """The comparison is inclusive on both sides on purpose. A bounding box
        is clipped to the raster by construction, so a strict test at zero
        could never fire and the knob would have no touching-only setting."""
        cfg = SelectionConfig(border_margin_frac=0.0)
        touching = select_best_frames([det("o", 0, blob(0, 40, 30, 60))], config=cfg)
        assert "border" in touching["o"].frames[0].reasons
        clear = select_best_frames([det("o", 0, blob(1, 40, 30, 60))], config=cfg)
        assert clear["o"].frames[0].reasons == []

    def test_the_margin_is_a_band_not_the_edge_itself(self):
        """2.5% of 100 px is 2.5 px, so a mask starting at x=2 is inside the
        band even though it never touches column 0."""
        out = select_best_frames([det("o", 0, blob(2, 40, 60, 60))])
        assert "border" in out["o"].frames[0].reasons

    def test_the_mask_decides_not_the_declared_bbox(self):
        """tracks.json's `bbox_px` is upstream's detector box and disagrees
        with the mask -- one preserved frame declares 1653x688 around a mask of
        28,277 px. Only the mask is read here."""
        m = centred()
        assert mask_bbox(m) == (35, 35, 64, 64)


class TestMinimumSize:
    def test_a_speck_is_rejected(self):
        tiny = blob(48, 48, 52, 52)         # 16 px of 10,000 = 0.16%
        out = select_best_frames([det("o", 0, tiny)])
        assert "too_small" in out["o"].frames[0].reasons

    def test_the_bar_is_a_fraction_of_the_raster(self):
        cfg = DEFAULT_CONFIG
        side = int(math.ceil(math.sqrt(cfg.min_area_frac * H * W)))
        just_over = blob(40, 40, 40 + side + 1, 40 + side + 1)
        out = select_best_frames([det("o", 0, just_over)], config=cfg)
        assert "too_small" not in out["o"].frames[0].reasons


class TestOcclusion:
    def test_a_neighbour_covering_a_third_rejects(self):
        target = blob(30, 30, 60, 60)
        over = blob(30, 30, 60, 40)         # a third of the target's rows
        out = select_best_frames([det("t", 0, target), det("o", 0, over)])
        assert "occluded" in out["t"].frames[0].reasons

    def test_a_neighbour_grazing_it_does_not(self):
        target = blob(30, 30, 60, 60)
        graze = blob(30, 30, 60, 32)        # ~7% of the target
        out = select_best_frames([det("t", 0, target), det("g", 0, graze)])
        assert "occluded" not in out["t"].frames[0].reasons

    def test_a_duplicate_detection_of_the_same_object_is_not_an_occluder(self):
        """The rule as literally stated -- union of all OTHER masks -- rejects
        every frame of eight instances on the preserved capture, because the
        tracker runs one concept per pass and names one surface twice."""
        m = centred()
        out = select_best_frames([det("artwork#0", 0, m), det("painting#1", 0, m)])
        assert out["artwork#0"].frames[0].reasons == []
        assert out["painting#1"].frames[0].reasons == []

    def test_a_containing_mask_is_not_an_occluder_either(self):
        """A `cabinet` mask that swallows the `door` inside it is a second
        reading of that surface, not something in front of it."""
        big, small = blob(20, 20, 80, 80), blob(30, 30, 50, 50)
        out = select_best_frames([det("cabinet#1", 0, big), det("door#3", 0, small)])
        assert "occluded" not in out["door#3"].frames[0].reasons

    def test_two_occluders_are_unioned_not_counted_twice(self):
        target = blob(30, 30, 60, 60)
        a, b = blob(30, 30, 60, 36), blob(30, 33, 60, 39)   # overlapping strips
        out = select_best_frames([det("t", 0, target), det("a", 0, a), det("b", 0, b)])
        covered = np.logical_and(target, np.logical_or(a, b)).sum() / target.sum()
        assert ("occluded" in out["t"].frames[0].reasons) is bool(
            covered > DEFAULT_CONFIG.max_occluded_frac
        )


class TestEveryReasonIsReported:
    def test_a_frame_failing_twice_names_both(self):
        tiny_edge = blob(0, 0, 4, 4)
        assert set(select_best_frames([det("o", 0, tiny_edge)])["o"].frames[0].reasons) == {
            "border", "too_small"
        }


# ── stage 2: the soft terms ──────────────────────────────────────────────────


def rgb_of(sharpness_seed: int, shape=(H * 4, W * 4)) -> np.ndarray:
    """A frame whose Laplacian variance rises with the seed. 0 is flat."""
    rng = np.random.default_rng(0)
    base = rng.integers(0, 256, size=(*shape, 3)).astype(float)
    return (base * (sharpness_seed / 10.0)).clip(0, 255)


class TestNormalisation:
    def test_a_term_with_no_variance_maps_to_one(self):
        """Two frames, identical masks: every geometric term is constant."""
        m = centred()
        out = select_best_frames([det("o", 0, m), det("o", 5, m)])
        for fr in out["o"].frames:
            assert fr.normalized["size"] == 1.0
            assert fr.normalized["solidity"] == 1.0
            assert fr.normalized["centeredness"] == 1.0

    def test_normalisation_is_scoped_to_the_object(self):
        """A big object and a small one are each normalised against their own
        frames, so the small one's best frame still scores near 1."""
        big = [det("big", f, centred(60)) for f in range(2)]
        small = [det("small", f, blob(45, 45, 45 + 12 + f, 45 + 12 + f)) for f in range(2)]
        out = select_best_frames(big + small)
        assert out["small"].score > 0.5

    def test_min_and_max_span_the_unit_interval(self):
        dets = [det("o", f, centred(20 + 10 * f)) for f in range(3)]
        vals = sorted(fr.normalized["size"] for fr in select_best_frames(dets)["o"].frames)
        assert vals[0] == pytest.approx(0.0)
        assert vals[-1] == pytest.approx(1.0)


class TestSharpness:
    def test_the_sharper_frame_wins_when_nothing_else_differs(self):
        m = centred()
        frames = {0: rgb_of(1), 1: rgb_of(10)}
        out = select_best_frames(
            [det("o", 0, m), det("o", 1, m)], get_rgb=frames.get
        )
        assert out["o"].frame_index == 1

    def test_an_unreadable_frame_is_scored_on_the_other_terms(self):
        """The repo's standing rule: an instrument that cannot ask its question
        does not get to answer it. Sharpness drops out of the weighted sum
        rather than scoring zero and dragging the frame down."""
        m = centred()
        out = select_best_frames([det("o", 0, m)], get_rgb=lambda _fi: None)
        fr = out["o"].frames[0]
        assert "sharpness" not in fr.normalized
        assert fr.score == pytest.approx(1.0)

    def test_a_missing_frame_does_not_lose_to_a_present_one_by_default(self):
        m = centred()
        frames = {1: rgb_of(10)}
        out = select_best_frames(
            [det("o", 0, m), det("o", 1, m)], get_rgb=frames.get
        )
        # frame 1 measures sharpness and scores it 1.0 (single finite value ->
        # zero variance); frame 0 spends no sharpness weight at all. Both end
        # at 1.0, and the tie resolves to the lower index.
        assert out["o"].frame_index == 0


class TestSolidity:
    def test_a_rectangle_is_solid(self):
        out = select_best_frames([det("o", 0, centred())])
        assert out["o"].frames[0].raw["solidity"] == pytest.approx(1.0, abs=0.06)

    def test_a_ring_is_not(self):
        m = blob(30, 30, 70, 70)
        m[40:60, 40:60] = False
        out = select_best_frames([det("o", 0, m)])
        assert out["o"].frames[0].raw["solidity"] < 0.8

    def test_two_disjoint_lobes_score_low(self):
        m = np.logical_or(blob(20, 45, 32, 55), blob(68, 45, 80, 55))
        out = select_best_frames([det("o", 0, m)])
        assert out["o"].frames[0].raw["solidity"] < 0.5


class TestCenteredness:
    def test_a_centred_mask_scores_higher_than_a_cornered_one(self):
        mid = select_best_frames([det("o", 0, centred(20))])["o"].frames[0]
        off = select_best_frames([det("o", 0, blob(4, 4, 24, 24))])["o"].frames[0]
        assert mid.raw["centeredness"] > off.raw["centeredness"]

    def test_it_never_leaves_the_unit_interval(self):
        for m in (centred(20), blob(0, 0, 8, 8), blob(92, 92, 100, 100)):
            v = select_best_frames([det("o", 0, m)])["o"].frames[0].raw["centeredness"]
            assert 0.0 <= v <= 1.0


class TestTemporalStability:
    def test_the_middle_of_a_run_beats_its_ends(self):
        m = centred()
        out = select_best_frames([det("o", f, m) for f in range(5)])
        raw = {fr.frame_index: fr.raw["temporal"] for fr in out["o"].frames}
        assert raw[2] == pytest.approx(1.0)
        assert raw[0] == pytest.approx(0.0)
        assert raw[4] == pytest.approx(0.0)
        assert raw[1] == pytest.approx(0.5)

    def test_a_time_gap_starts_a_new_run(self):
        m = centred()
        ts = {0: 0.0, 1: 0.2, 2: 0.4, 30: 9.0, 31: 9.2, 32: 9.4}
        out = select_best_frames(
            [det("o", f, m) for f in ts], timestamps=ts
        )
        raw = {fr.frame_index: fr.raw["temporal"] for fr in out["o"].frames}
        assert raw[1] == pytest.approx(1.0)     # centre of run one
        assert raw[31] == pytest.approx(1.0)    # centre of run two
        assert raw[2] == pytest.approx(0.0)     # end of run one, not a middle

    def test_a_frame_gap_breaks_a_run_when_there_are_no_timestamps(self):
        m = centred()
        out = select_best_frames([det("o", f, m) for f in (0, 1, 2, 40, 41, 42)])
        raw = {fr.frame_index: fr.raw["temporal"] for fr in out["o"].frames}
        assert raw[1] == pytest.approx(1.0)
        assert raw[41] == pytest.approx(1.0)

    def test_an_isolated_frame_scores_zero_not_one(self):
        """A one-frame run is entirely ends. Scoring it 1.0 would have the
        stability term reward maximally the least stable case it can see."""
        m = centred()
        out = select_best_frames([det("o", f, m) for f in (0, 50)])
        assert all(fr.raw["temporal"] == 0.0 for fr in out["o"].frames)

    def test_runs_are_built_over_survivors_not_over_the_whole_track(self):
        """Frames 1 and 2 are rejected, so 0 and 3 become consecutive
        survivors and form one run rather than two isolated glimpses."""
        m, cut = centred(), blob(0, 40, 20, 60)
        dets = [det("o", 0, m), det("o", 1, cut), det("o", 2, cut), det("o", 3, m)]
        out = select_best_frames(dets)
        kept = [fr for fr in out["o"].frames if fr.kept]
        assert [fr.frame_index for fr in kept] == [0, 3]
        assert all("temporal" in fr.raw for fr in kept)


class TestTheFallback:
    def test_an_object_with_no_surviving_frame_still_gets_one(self):
        cut = blob(0, 40, 20, 60)
        out = select_best_frames([det("o", 0, cut), det("o", 1, cut)])
        assert out["o"].is_fallback is True
        assert out["o"].frame_index is not None
        assert out["o"].n_kept == 0

    def test_a_normal_object_is_not_flagged(self):
        out = select_best_frames([det("o", 0, centred())])
        assert out["o"].is_fallback is False

    def test_the_fallback_ranks_the_whole_track(self):
        cut_small = blob(0, 48, 8, 52)
        cut_big = blob(0, 30, 40, 70)
        out = select_best_frames([det("o", 0, cut_small), det("o", 1, cut_big)])
        assert out["o"].is_fallback is True
        assert out["o"].frame_index == 1


class TestDeterminism:
    def test_input_order_does_not_change_the_answer(self):
        dets = [det("o", f, centred(20 + f)) for f in range(6)]
        a = select_best_frames(dets)["o"].frame_index
        b = select_best_frames(list(reversed(dets)))["o"].frame_index
        assert a == b

    def test_a_tie_resolves_to_the_lower_frame_index(self):
        m = centred()
        out = select_best_frames([det("o", 7, m), det("o", 3, m)])
        assert out["o"].frame_index == 3


class TestConfigurability:
    def test_every_threshold_is_overridable(self):
        near = blob(2, 40, 60, 60)      # inside the 2.5% band, not touching
        assert "border" in select_best_frames([det("o", 0, near)])["o"].frames[0].reasons
        touch_only = SelectionConfig(border_margin_frac=0.0)
        assert select_best_frames([det("o", 0, near)], config=touch_only)["o"].frames[0].reasons == []

    def test_weights_need_not_sum_to_one(self):
        cfg = SelectionConfig(w_sharpness=3.0, w_size=3.0, w_solidity=3.0,
                              w_centeredness=3.0, w_temporal=3.0)
        out = select_best_frames([det("o", f, centred(20 + 10 * f)) for f in range(3)],
                                 config=cfg)
        assert all(0.0 <= fr.score <= 1.0 for fr in out["o"].frames)
