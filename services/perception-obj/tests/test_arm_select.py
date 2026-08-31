"""Arm selection unit invariants (decision 0204): which of an object's
already-reconstructed arms supplies its appearance.

Two halves, because the pass has two halves. `choose_arm` is the decision
and is pinned here against synthetic fits AND, in the real-data class
below, against the eight multi-arm boxes of the four preserved captures —
committed as `fixtures/arm_select/sweep.json`, which is the sweep 0197
measured, in kilobytes rather than a gigabyte of PLY. `select_arm` is the
measurement plus the reorder, and is pinned on stubs.

The load-bearing pin is `TestMarginIsNotFitted`: the measured gains are
bimodal (0.000 six times, then 0.018, then 0.590), and every margin in the
whole 33x window between the two live values produces the same eight
answers. A rule that only works at its default is a rule fitted to its
answer, which is the habit that produced eleven refuted input measures in
this repo.

Run from repo root:
    python -m pytest services/perception-obj/tests/test_arm_select.py -v
"""
from __future__ import annotations

import json
from pathlib import Path

import box_placement
import pytest

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "arm_select" / "sweep.json"
SWEEP = json.loads(FIXTURE.read_text())["boxes"]


def _fit(index, fill, residual_m):
    return box_placement.ArmFit(index=index, fill=fill, residual_m=residual_m)


def _fits(box: dict) -> list:
    return [_fit(a["rank"], a["fill"], a["residual_m"]) for a in box["arms"]]


def _acts(box: dict, margin: float | None = None) -> bool:
    """Does the rule move this box off the arm that ships today?"""
    if margin is None:
        best, _ = box_placement.choose_arm(_fits(box))
    else:
        fits = _fits(box)
        shipped = fits[0]
        best = shipped
        for f in fits[1:]:
            gain = shipped.fill_dist - f.fill_dist
            if gain >= margin and f.residual_m < shipped.residual_m:
                if gain > shipped.fill_dist - best.fill_dist:
                    best = f
    return best.index != box["arms"][0]["rank"]


# ---------------------------------------------------------------------------
# The instrument's own arithmetic
# ---------------------------------------------------------------------------

class TestFillDist:
    def test_overshoot_is_penalised_like_truncation(self):
        """Mass outside the measurement is not legs. A splat spanning 1.9x
        its measured box height is not more complete than one spanning
        1.15x, and a rule that only ever rewards MORE fill would prefer it
        (spike/box_00 is exactly that pair)."""
        assert _fit(0, 1.9192, 0.0).fill_dist > _fit(1, 1.1502, 0.0).fill_dist

    def test_exact_span_is_zero(self):
        assert _fit(0, 1.0, 0.0).fill_dist == 0.0

    def test_equal_deficit_and_excess_tie(self):
        assert _fit(0, 0.8, 0.0).fill_dist == pytest.approx(
            _fit(1, 1.2, 0.0).fill_dist
        )


# ---------------------------------------------------------------------------
# The decision
# ---------------------------------------------------------------------------

class TestChooseArm:
    def test_a_clear_gain_with_both_checks_agreeing_wins(self):
        best, rec = box_placement.choose_arm([
            _fit(0, 0.406, 0.793), _fit(1, 1.004, 0.341),
        ])
        assert best.index == 1
        assert rec["chosen_rank"] == 1
        assert rec["fill_gain"] == pytest.approx(0.590, abs=5e-4)

    def test_a_gain_inside_the_margin_is_refused(self):
        """0.018 is the noise end of the measured bimodal gap."""
        best, rec = box_placement.choose_arm([
            _fit(0, 0.9506, 0.0646), _fit(1, 0.9683, 0.0518),
        ])
        assert best.index == 0
        assert rec["chosen_rank"] == 0

    def test_the_two_checks_disagreeing_refuses(self):
        """Fill prefers the shipped arm, the residual prefers the other.
        That is the instrument saying it cannot tell — not a tie to be
        broken by weights."""
        best, _ = box_placement.choose_arm([
            _fit(0, 1.0291, 0.8941), _fit(1, 0.8161, 0.2383),
        ])
        assert best.index == 0

    def test_a_big_fill_gain_alone_is_not_enough(self):
        """Both checks must prefer the challenger. A fill gain that the
        residual contradicts is refused however large it is."""
        best, _ = box_placement.choose_arm([
            _fit(0, 0.30, 0.10), _fit(1, 1.00, 0.90),
        ])
        assert best.index == 0

    def test_ties_keep_the_arm_that_ships_today(self):
        a, _ = box_placement.choose_arm([
            _fit(0, 0.40, 0.50), _fit(1, 1.00, 0.40), _fit(2, 1.00, 0.30),
        ])
        assert a.index == 1  # strict improvement only; first winner holds

    def test_the_record_names_both_arms_either_way(self):
        """A refusal is recorded as fully as an action — the manifest says
        what was compared, not just what happened.

        Re-pinned for decision 0233's third axis. The record now also names
        WHICH axes split, which the two-axis form could not: here `residual`
        preferred the challenger and `fill` did not, and `s2c` abstained
        because these synthetic fits carry no cloud."""
        _, rec = box_placement.choose_arm([
            _fit(0, 0.9506, 0.0646), _fit(1, 0.9683, 0.0518),
        ])
        assert rec == {
            "arms": 2,
            "axes": ["fill", "residual", "s2c"],
            "shipped_fill": 0.9506, "shipped_residual_m": 0.0646,
            "shipped_s2c_m": None,
            "chosen_rank": 0, "chosen_fill": 0.9506,
            "chosen_residual_m": 0.0646, "chosen_s2c_m": None,
            "fill_gain": 0.0,
            "refused": [
                {"rank": 1, "agreed": ["residual"], "dissented": ["fill"]}
            ],
        }

    def test_it_is_deterministic(self):
        fits = [_fit(0, 0.40, 0.50), _fit(1, 1.00, 0.30)]
        assert box_placement.choose_arm(fits)[1] == box_placement.choose_arm(fits)[1]


# ---------------------------------------------------------------------------
# The eight real boxes
# ---------------------------------------------------------------------------

class TestPreservedCaptures:
    """`fixtures/arm_select/sweep.json` — every box in the four preserved
    captures with more than one cached reconstruction, measured through
    `arm_fit`. Provenance: outputs/selection/make_fixture.py over the
    room-quality harness; the fills reproduce 0197's own sweep to 3dp."""

    def test_the_population_is_the_one_that_was_measured(self):
        assert len(SWEEP) == 8
        assert all(len(b["arms"]) == 2 for b in SWEEP)
        assert sorted({b["room"] for b in SWEEP}) == ["rp6g1", "rp7", "spike"]

    @pytest.mark.parametrize(
        "room,box_index,verdict",
        [("rp6g1", 0, "switch"), ("rp7", 2, "keep")],
    )
    def test_it_reproduces_both_walked_verdicts(self, room, box_index, verdict):
        """The only two arms in this table anyone has looked at, and they
        are opposite-signed: rp6g1's table gains a set of legs by
        switching, rp7's desk loses the ones it has. An instrument that
        'improves' the second is wrong."""
        box = next(
            b for b in SWEEP if b["room"] == room and b["box_index"] == box_index
        )
        assert box["walked"] == verdict
        assert _acts(box) is (verdict == "switch")

    def test_it_acts_on_exactly_one_of_the_eight(self):
        acted = [b for b in SWEEP if _acts(b)]
        assert [(b["room"], b["box_index"]) for b in acted] == [("rp6g1", 0)]

    def test_the_two_checks_agree_on_seven_of_eight(self):
        agree = sum(
            1 for b in SWEEP
            if min(_fits(b), key=lambda f: (f.fill_dist, f.index)).index
            == min(_fits(b), key=lambda f: (f.residual_m, f.index)).index
        )
        assert agree == 7

    def test_the_one_disagreement_is_the_spike_bed(self):
        disagree = [
            (b["room"], b["box_index"]) for b in SWEEP
            if min(_fits(b), key=lambda f: (f.fill_dist, f.index)).index
            != min(_fits(b), key=lambda f: (f.residual_m, f.index)).index
        ]
        assert disagree == [("spike", 3)]

    def test_the_gains_are_bimodal(self):
        gains = sorted(
            round(_fits(b)[0].fill_dist - min(f.fill_dist for f in _fits(b)), 4)
            for b in SWEEP
        )
        assert gains[:6] == [0.0] * 6
        assert gains[6] == pytest.approx(0.0177, abs=5e-4)
        assert gains[7] == pytest.approx(0.5899, abs=5e-4)
        assert gains[7] / gains[6] > 30.0


class TestMarginIsNotFitted:
    """The default margin is the geometric centre of the measured gap, and
    the answers do not depend on landing there."""

    def test_the_default_sits_between_the_two_live_gains(self):
        assert 0.0177 < box_placement._ARM_FILL_MARGIN < 0.5899

    def test_it_is_the_geometric_centre_of_the_gap(self):
        assert box_placement._ARM_FILL_MARGIN == pytest.approx(
            (0.0177 * 0.5899) ** 0.5, abs=0.01
        )

    @pytest.mark.parametrize("margin", [0.02, 0.05, 0.10, 0.25, 0.45, 0.58])
    def test_every_margin_in_the_window_gives_the_same_eight_answers(self, margin):
        assert [_acts(b, margin) for b in SWEEP] == [_acts(b) for b in SWEEP]


# ---------------------------------------------------------------------------
# The measurement, the reorder, and the gates around them
# ---------------------------------------------------------------------------

import numpy as np  # noqa: E402
from dataclasses import dataclass, field  # noqa: E402

from roomplan_room import RoomPlanBox  # noqa: E402
from thegoodguest_schemas.placement_math import prepare_mask  # noqa: E402

TRUNCATED = "gs://o/truncated.ply"  # spans 0.4 of its box, residual 0.3
COMPLETE = "gs://o/complete.ply"  # spans it exactly, residual 0.0


@dataclass
class FakeIntrinsics:
    fx: float = 60.0
    fy: float = 60.0
    cx: float = 32.0
    cy: float = 32.0
    width: int = 64
    height: int = 64


@dataclass
class FakePose:
    pos_x: float = 0.0
    pos_y: float = 0.0
    pos_z: float = 0.0
    quat_x: float = 0.0
    quat_y: float = 0.0
    quat_z: float = 0.0
    quat_w: float = 1.0


@dataclass
class CountingCtx:
    """RefinementContext stand-in that records which splats were parsed —
    the only cost this pass adds."""

    cameras: dict = field(default_factory=dict)
    masks: dict = field(default_factory=dict)
    splats: dict = field(default_factory=dict)
    requested: list = field(default_factory=list)
    get_appearance: object = None
    get_rgb: object = None

    def get_camera(self, frame_index):
        return self.cameras.get(frame_index)

    def mask_for(self, frame_index, mask_index):
        return self.masks.get((frame_index, mask_index))

    def evidence_for(self, frame_index, mask_index):
        m = self.mask_for(frame_index, mask_index)
        return None if m is None else prepare_mask(m)

    def get_splat(self, uri):
        self.requested.append(uri)
        return self.splats.get(uri)


def _cloud(ext, n=800) -> np.ndarray:
    rng = np.random.default_rng(7)
    return rng.uniform(-0.5, 0.5, size=(n, 3)) * np.asarray(ext)


def _box(dims=(1.0, 0.5, 1.0), center=(0.0, 0.0, -3.0), category="bed"):
    T = np.eye(4)
    T[:3, 3] = np.asarray(center, dtype=float)
    return RoomPlanBox(
        identifier="B1", category=category, confidence="high", attributes={},
        dimensions=np.asarray(dims, dtype=float), transform=T,
        center_world=T[:3, 3].copy(), up_y=1.0, yaw_rad=0.0,
    )


def _two_arm_scene(uris=(TRUNCATED, COMPLETE), extra=()):
    """One box seen in as many frames as there are uris, the first — the
    arm that ships today — truncated. Cameras and masks are identical, so
    the association sort has nothing to separate them but frame index."""
    box = _box()
    ctx = CountingCtx()
    ctx.splats[TRUNCATED] = _cloud((0.5, 0.1, 0.5))
    ctx.splats[COMPLETE] = _cloud((0.5, 0.25, 0.5))
    for uri, ext in extra:
        ctx.splats[uri] = _cloud(ext)
    hull, _ = box_placement.project_box_footprint(box, FakeIntrinsics(), FakePose())
    ys, xs = np.mgrid[0:64, 0:64]
    pts = np.column_stack([xs.ravel() + 0.5, ys.ravel() + 0.5]).astype(float)
    mask = box_placement._points_in_hull(pts, hull).reshape((64, 64))
    observations = []
    for fi, uri in enumerate(uris):
        ctx.cameras[fi] = (FakePose(), FakeIntrinsics())
        ctx.masks[(fi, 0)] = mask
        observations.append({
            "frame_index": fi, "label": "bed", "score": 0.9, "mask_index": 0,
            "splat_gcs_uri": uri, "placement": {}, "view_ray": None,
        })
    assoc = box_placement.associate_observations([box], observations, ctx)[0]
    return box, ctx, assoc


def _build(box, ctx, assoc, **kw):
    return box_placement.build_box_object(
        box=box, box_index=0, object_id="obj_000",
        associations=assoc, ctx=ctx, **kw
    )


class TestDegradeLock:
    """Off is what ships. Byte-identical is proven offline against all 31
    boxes of the four preserved captures (outputs/selection/probe2_degrade.py);
    these hold the seams that proof cannot see from outside."""

    def test_the_flag_is_off_by_default(self):
        assert box_placement._ARM_SELECT is False

    def test_the_shipped_arm_still_wins_by_position_alone(self):
        box, ctx, assoc = _two_arm_scene()
        obj = _build(box, ctx, assoc)
        assert obj["splat_gcs_uri"] == TRUNCATED
        assert obj["source"]["frame_index"] == 0

    def test_no_record_appears_in_quality(self):
        box, ctx, assoc = _two_arm_scene()
        assert "arm_select" not in _build(box, ctx, assoc)["quality"]

    def test_the_second_arm_is_never_parsed(self):
        """The cost is the extra splat, and off it is not paid."""
        box, ctx, assoc = _two_arm_scene()
        _build(box, ctx, assoc)
        assert COMPLETE not in ctx.requested


@pytest.fixture
def armselect_on(monkeypatch):
    monkeypatch.setattr(box_placement, "_ARM_SELECT", True)


class TestSelectArmInBuild:
    def test_the_better_arm_ships(self, armselect_on):
        box, ctx, assoc = _two_arm_scene()
        obj = _build(box, ctx, assoc)
        assert obj["splat_gcs_uri"] == COMPLETE
        assert obj["source"]["frame_index"] == 1
        assert obj["quality"]["arm_select"]["chosen_rank"] == 1

    def test_it_carries_the_geometry_of_the_arm_it_chose(self, armselect_on):
        """Not just the uri: the transform, the fit and the seating all
        come from the chosen arm, because the reorder happens before any
        of them are computed."""
        box, ctx, assoc = _two_arm_scene()
        obj = _build(box, ctx, assoc)
        # 0.016 against the truncated arm's 0.3085, and no vertical seating
        # at all: the chosen arm fills its box, so there is no deficit to
        # anchor at one end (`vertical_seat_offset` returns None).
        assert sum(obj["box_fit_residual"]) == pytest.approx(0.016, abs=5e-4)
        assert "box_height_fill" not in obj["quality"]
        assert "vertical_seat_m" not in obj["quality"]

    def test_a_worse_arm_is_refused(self, armselect_on):
        box, ctx, assoc = _two_arm_scene(uris=(COMPLETE, TRUNCATED))
        obj = _build(box, ctx, assoc)
        assert obj["splat_gcs_uri"] == COMPLETE
        assert obj["quality"]["arm_select"]["chosen_rank"] == 0

    def test_the_reorder_does_not_drop_associations(self, armselect_on):
        """Move-to-front, not replacement: everything counted before is
        still counted, so `frames_observed` means what it always did."""
        box, ctx, assoc = _two_arm_scene()
        on = _build(box, ctx, assoc)["quality"]["frames_observed"]
        assert on == len(assoc) == 2

    def test_a_single_arm_records_nothing(self, armselect_on):
        box, ctx, assoc = _two_arm_scene(uris=(TRUNCATED,))
        assert "arm_select" not in _build(box, ctx, assoc)["quality"]

    def test_an_arm_with_no_splat_is_not_an_arm(self, armselect_on):
        """A missing reconstruction is skipped, not scored as a bad one —
        and with only one real arm left there is nothing to choose."""
        box, ctx, assoc = _two_arm_scene(uris=("gs://o/missing.ply", COMPLETE))
        obj = _build(box, ctx, assoc)
        assert obj["splat_gcs_uri"] == COMPLETE
        assert "arm_select" not in obj["quality"]

    def test_no_appearance_survives_with_no_arms_at_all(self, armselect_on):
        box, ctx, assoc = _two_arm_scene(uris=("gs://o/a.ply", "gs://o/b.ply"))
        obj = _build(box, ctx, assoc)
        assert obj["placed"] is False and obj["reason"] == "no_appearance"

    def test_it_stops_at_the_cap(self, armselect_on, monkeypatch):
        monkeypatch.setattr(box_placement, "_ARM_SELECT_MAX", 2)
        extra = [("gs://o/third.ply", (0.5, 0.25, 0.5))]
        box, ctx, assoc = _two_arm_scene(
            uris=(TRUNCATED, COMPLETE, "gs://o/third.ply"), extra=extra
        )
        obj = _build(box, ctx, assoc)
        assert obj["quality"]["arm_select"]["arms"] == 2
        assert "gs://o/third.ply" not in ctx.requested


class TestBudgetGate:
    """A starved scene loses this the way it loses every other post-pass —
    and `allow_scoring=False` is the recursion guard as well, since the
    scorer places each arm through this same function."""

    def test_an_unscored_build_does_not_select(self, armselect_on):
        box, ctx, assoc = _two_arm_scene()
        obj = _build(box, ctx, assoc, allow_scoring=False)
        assert obj["splat_gcs_uri"] == TRUNCATED
        assert "arm_select" not in obj["quality"]

    def test_the_scorer_does_not_re_enter_itself(self, armselect_on):
        """If it did, `arm_fit`'s single-arm build would recurse until the
        stack gave out. The pin is that a two-arm scene terminates and
        parses each splat's worth of work once per arm."""
        box, ctx, assoc = _two_arm_scene()
        obj = _build(box, ctx, assoc)
        assert obj["quality"]["arm_select"]["arms"] == 2


class TestTheInstrumentReadsWhatShips:
    """Both checks read extents under the CHOSEN axis mapping, and the
    instrument reads each arm through an unscored build — so the cloud can
    ship a mapping the instrument never saw. Measured on all sixteen arms
    (outputs/selection/probe4_scored_vs_unscored.py), and the answer is
    sharper than a caveat: the divergence happens once, on the one box
    where the two checks disagree."""

    def test_the_residual_the_instrument_reads_is_the_shipped_one(self):
        diverged = [
            (b["room"], b["box_index"], a["frame_index"])
            for b in SWEEP for a in b["arms"]
            if abs(a["residual_m"] - a["residual_m_shipped"]) > 5e-4
        ]
        assert diverged == [("spike", 3, 10)]

    def test_the_one_divergence_is_the_one_disagreement(self):
        """Not a coincidence to be tidied away: an arm whose mapping the
        cloud overrules is an arm whose extents the instrument measured
        under a different frame, and that is what a disagreement between
        two extent-derived checks looks like from the inside. Refusing on
        disagreement therefore also refuses the stale reading."""
        disagree = {
            (b["room"], b["box_index"]) for b in SWEEP
            if min(_fits(b), key=lambda f: (f.fill_dist, f.index)).index
            != min(_fits(b), key=lambda f: (f.residual_m, f.index)).index
        }
        diverged = {
            (b["room"], b["box_index"]) for b in SWEEP for a in b["arms"]
            if abs(a["residual_m"] - a["residual_m_shipped"]) > 5e-4
        }
        assert disagree == diverged == {("spike", 3)}

    def test_the_instrument_never_loads_depth(self):
        """Why it is left unscored rather than 'fixed': the cloud costs a
        depth load per arm, and a ranking whose arms were each measured
        under a mapping their own cloud chose is not comparing like with
        like. The extent-best mapping is one rule for everyone, and it is
        free. This ctx makes the cost loud — reading depth raises."""
        box, ctx, assoc = _two_arm_scene()

        def _explode(frame_index):
            raise AssertionError("arm_fit read depth")

        ctx.get_depth = _explode
        fits = [box_placement.arm_fit(box, 0, "obj_000", a, ctx) for a in assoc]
        assert [round(f.fill, 3) for f in fits] == [0.414, 1.021]


# ---------------------------------------------------------------------------
# The conditional second arm (decision 0229)
# ---------------------------------------------------------------------------

def _passes(box: dict) -> bool:
    """Would this box's tier-1 arm make its tier-2 view unnecessary?"""
    a0 = box["arms"][0]
    return box_placement.arm_passes(_fit(0, a0["fill"], a0["residual_m"]))


class TestArmPasses:
    """The gate that decides whether a planned second view is worth a
    reconstruction. Smaller-is-better on both axes, and BOTH must hold."""

    def test_an_unbuildable_arm_never_passes(self):
        """The safety property. `arm_fit` returns None when the arm cannot
        be placed or parsed — which is the shape an OOMed tier-1 leaves —
        and 0228 measured the second arm rescuing six of nine boxes whose
        first view failed. None must therefore keep the second view."""
        assert box_placement.arm_passes(None) is False

    def test_a_good_arm_passes(self):
        assert box_placement.arm_passes(_fit(0, 1.02, 0.09)) is True

    def test_overshoot_is_penalised_like_truncation(self):
        """`fill_dist` is |fill - 1|, so mass outside the measurement is not
        a better arm than mass missing from it."""
        assert box_placement.arm_passes(_fit(0, 1.40, 0.05)) is False
        assert box_placement.arm_passes(_fit(0, 0.60, 0.05)) is False

    def test_fill_alone_is_not_enough(self):
        """0205's spike bed: fill_dist 0.029, the BEST in the corpus, and
        residual 0.894, the worst — a hollow shell of the right height that
        overflows its measurement by nearly a metre across the other two
        axes. A fill-only gate drops the second arm of the one box 0205
        says nobody can adjudicate."""
        assert box_placement.arm_passes(_fit(0, 1.0291, 0.8941)) is False

    def test_residual_alone_is_not_enough(self):
        assert box_placement.arm_passes(_fit(0, 0.40, 0.05)) is False


class TestConditionalSecondArmOnPreservedCaptures:
    """The gate against the same eight real boxes `choose_arm` is pinned on.

    Recorded because these numbers are the decision: the boxes it skips are
    exactly the boxes whose second arm is provably unused, and the boxes it
    keeps include every box anyone has walked."""

    def test_it_passes_exactly_four_of_the_eight(self):
        passed = sorted(
            (b["room"], b["box_index"]) for b in SWEEP if _passes(b)
        )
        assert passed == [
            ("rp6g1", 2), ("rp6g1", 3), ("spike", 5), ("spike", 6),
        ]

    def test_every_skipped_box_has_a_second_arm_choose_arm_never_uses(self):
        """The whole claim, stated as a test: a skipped second view is one
        `choose_arm` would have looked at and declined. If this ever fails,
        the gate is dropping an arm that changes what ships."""
        for b in SWEEP:
            if _passes(b):
                assert _acts(b) is False, (b["room"], b["box_index"])

    def test_the_one_box_that_switches_keeps_its_second_view(self):
        """rp6g1 b00 — 0197's floating slab, which gains a full set of legs
        from its second arm and is the only walked `switch` in the corpus."""
        box = next(
            b for b in SWEEP if b["room"] == "rp6g1" and b["box_index"] == 0
        )
        assert _acts(box) is True
        assert _passes(box) is False

    def test_both_0197_boxes_keep_their_second_view(self):
        """The legless pair. Their rank-0 fills are 0.406 and 0.415 — the
        two values above the gap the threshold sits in — so the gate keeps
        precisely the views worth reconstructing."""
        for room, bi in (("rp6g1", 0), ("rp7", 2)):
            box = next(
                b for b in SWEEP if b["room"] == room and b["box_index"] == bi
            )
            assert _passes(box) is False

    def test_it_does_not_touch_the_oom_fallback_population(self):
        """0228: of the nine boxes that hit an OOM on a box view, another
        view rescued SEVEN — and in six of the nine the view that OOMed was
        rank 1. The set below is the seven rescued. Those boxes have one
        successful arm, so
        they are not in this multi-arm table at all — and the rule cannot
        reach them anyway, because an OOMed tier-1 yields no ArmFit. Pinned
        because the disjointness is what makes the rule safe, and a future
        change that scores a box from a cached sibling would break it
        silently."""
        oom_rescued = {
            ("rp7", 0), ("rp7", 1), ("rp7", 4), ("rp7", 5),
            ("rp6g1", 1), ("rp6g2", 0), ("rp6g2", 10),
        }
        multi_arm = {(b["room"], b["box_index"]) for b in SWEEP}
        assert multi_arm & oom_rescued == set()


class TestThresholdsAreNotFitted:
    """Both gates sit at the geometric centre of a gap in the same sweep,
    the way `_ARM_FILL_MARGIN` does. The pin is that the answer is stable
    across the whole gap, not just at the default — a rule that only works
    at its own constant is fitted to its answer."""

    @pytest.mark.parametrize("fill_pass", [0.20, 0.25, 0.31, 0.40, 0.50])
    def test_the_fill_gate_gives_the_same_answer_across_its_gap(
        self, fill_pass, monkeypatch
    ):
        monkeypatch.setattr(box_placement, "_SECOND_ARM_FILL_PASS", fill_pass)
        passed = sorted(
            (b["room"], b["box_index"]) for b in SWEEP if _passes(b)
        )
        assert passed == [
            ("rp6g1", 2), ("rp6g1", 3), ("spike", 5), ("spike", 6),
        ]

    @pytest.mark.parametrize("res_pass", [0.20, 0.25, 0.30, 0.40, 0.48])
    def test_the_residual_gate_gives_the_same_answer_across_its_gap(
        self, res_pass, monkeypatch
    ):
        monkeypatch.setattr(
            box_placement, "_SECOND_ARM_RESIDUAL_PASS_M", res_pass
        )
        passed = sorted(
            (b["room"], b["box_index"]) for b in SWEEP if _passes(b)
        )
        assert passed == [
            ("rp6g1", 2), ("rp6g1", 3), ("spike", 5), ("spike", 6),
        ]


# ---------------------------------------------------------------------------
# The third axis (decision 0233)
# ---------------------------------------------------------------------------

def _fit3(index, fill, residual_m, s2c_m=None):
    return box_placement.ArmFit(
        index=index, fill=fill, residual_m=residual_m, s2c_m=s2c_m
    )


class TestTheThirdAxisIsAVeto:
    """k-of-n with k = n: every axis that can express an opinion must prefer
    the challenger. Adding an axis can therefore only make `choose_arm` act
    LESS often, never more — which is what makes it safe against the
    population 0228 measured, where the second arm is carrying an OOM
    fallback in six of nine affected boxes. A third axis that could ENABLE
    switches would be interacting with those boxes; a veto cannot."""

    def test_it_vetoes_a_switch_the_two_axes_would_have_made(self):
        two = [_fit3(0, 0.40, 0.50), _fit3(1, 1.00, 0.30)]
        assert box_placement.choose_arm(two)[0].index == 1
        three = [_fit3(0, 0.40, 0.50, 0.05), _fit3(1, 1.00, 0.30, 0.19)]
        assert box_placement.choose_arm(three)[0].index == 0

    def test_it_lets_an_agreed_switch_through(self):
        three = [_fit3(0, 0.40, 0.50, 0.19), _fit3(1, 1.00, 0.30, 0.05)]
        assert box_placement.choose_arm(three)[0].index == 1

    def test_it_can_never_enable_a_switch_the_two_axes_refuse(self):
        """Whatever the third axis says, a fill or residual dissent still
        refuses. Swept rather than asserted once."""
        for s_ship, s_chal in ((0.9, 0.01), (0.01, 0.9), (None, None)):
            fits = [_fit3(0, 0.99, 0.10, s_ship), _fit3(1, 0.98, 0.90, s_chal)]
            assert box_placement.choose_arm(fits)[0].index == 0

    def test_abstention_does_not_veto(self):
        """A depth-less or starved room yields no cloud, so `s2c_m` is None.
        That must fall back to the two-axis rule that ships today, not
        silently disable arm selection — otherwise turning the axis on is a
        behaviour change wearing the costume of a stricter rule."""
        for pair in ((None, None), (None, 0.05), (0.05, None)):
            fits = [_fit3(0, 0.40, 0.50, pair[0]), _fit3(1, 1.00, 0.30, pair[1])]
            assert box_placement.choose_arm(fits)[0].index == 1

    def test_abstention_is_byte_identical_to_the_two_axis_rule(self):
        """The degrade lock. With no cloud anywhere, every answer over the
        real sweep is the one that shipped before the axis existed."""
        for b in SWEEP:
            two = _fits(b)
            three = [_fit3(a["rank"], a["fill"], a["residual_m"], None)
                     for a in b["arms"]]
            assert (box_placement.choose_arm(two)[0].index
                    == box_placement.choose_arm(three)[0].index)

    def test_a_split_is_recorded_with_the_axes_that_disagreed(self):
        _, rec = box_placement.choose_arm(
            [_fit3(0, 0.40, 0.50, 0.05), _fit3(1, 1.00, 0.30, 0.19)]
        )
        assert rec["refused"] == [
            {"rank": 1, "agreed": ["fill", "residual"], "dissented": ["s2c"]}
        ]

    def test_all_three_readings_are_recorded_whether_it_acts_or_not(self):
        for fits in (
            [_fit3(0, 0.40, 0.50, 0.19), _fit3(1, 1.00, 0.30, 0.05)],   # acts
            [_fit3(0, 0.99, 0.10, 0.05), _fit3(1, 0.98, 0.90, 0.19)],   # refuses
        ):
            _, rec = box_placement.choose_arm(fits)
            assert rec["axes"] == ["fill", "residual", "s2c"]
            for k in ("shipped_fill", "shipped_residual_m", "shipped_s2c_m",
                      "chosen_fill", "chosen_residual_m", "chosen_s2c_m"):
                assert k in rec


class TestTheThirdAxisOnPreservedCaptures:
    """The eight real boxes, with the s2c readings production's own
    `select_arm` path computes — measured against a cloud built from each
    box's own association frames, which is what a RefinementContext can
    reach. Production has no fused cloud and 0233 does not propose one."""

    def _fits3(self, b):
        return [_fit3(a["rank"], a["fill"], a["residual_m"], a.get("s2c_m"))
                for a in b["arms"]]

    def test_every_arm_carries_a_reading(self):
        for b in SWEEP:
            for a in b["arms"]:
                assert a.get("s2c_m") is not None, (b["room"], b["box_index"])
                assert 0.0 < a["s2c_m"] < 1.0

    def test_the_third_axis_changes_nothing_on_this_corpus(self):
        """Insurance, not improvement — and recorded as such. The rule acts
        on the same single box with two axes and with three."""
        two = [b for b in SWEEP if _acts(b)]
        three = [b for b in SWEEP
                 if box_placement.choose_arm(self._fits3(b))[0].index != 0]
        assert [(b["room"], b["box_index"]) for b in two] == [("rp6g1", 0)]
        assert [(b["room"], b["box_index"]) for b in three] == [("rp6g1", 0)]

    def test_it_agrees_with_the_only_walked_switch(self):
        """rp6g1 b00 — 0197's floating slab. The one case in this corpus
        anyone has adjudicated, and the veto does not fire on it."""
        b = next(x for x in SWEEP
                 if x["room"] == "rp6g1" and x["box_index"] == 0)
        assert b["walked"] == "switch"
        assert b["arms"][1]["s2c_m"] < b["arms"][0]["s2c_m"]

    def test_spike_bed_is_now_a_two_to_one_refusal(self):
        """0205's bed, where fill and the residual disagree and nobody can
        adjudicate. On the LOCAL cloud — the one production builds, and the
        one this sweep holds — the third axis sides with fill, so the record
        reads 2-vs-1. Read it as a mechanism pin and not as added evidence:
        spike b03 is one of the two boxes whose s2c ranking flips between the
        local and fused clouds, at a margin of 0.014, so the third vote here
        states which cloud was used rather than which arm is better (0233)."""
        b = next(x for x in SWEEP
                 if x["room"] == "spike" and x["box_index"] == 3)
        _, rec = box_placement.choose_arm(self._fits3(b))
        assert rec["chosen_rank"] == 0
        split = rec["refused"][0]
        assert split["agreed"] == ["residual"]
        assert split["dissented"] == ["fill", "s2c"]
