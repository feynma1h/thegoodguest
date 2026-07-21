"""Invariant tests for budget.BudgetTracker.

Pin the admission contract (remaining minus reserve must fit the current
estimate), the estimate policy (prior until observed, then the per-run
maximum), and the unlimited (deadline=None) mode. Injected clock — no real
time passes.

Run from repo root:
  pytest services/perception-obj/tests/test_budget.py -v
"""
from __future__ import annotations

import math

from budget import BudgetTracker  # conftest adds the service dir to sys.path


class _FakeClock:
    def __init__(self, t: float = 0.0):
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


def _tracker(budget_s: float, clock: _FakeClock, **kw) -> BudgetTracker:
    return BudgetTracker(clock.t + budget_s, clock=clock, **kw)


class TestUnlimitedMode:
    def test_none_deadline_admits_everything(self):
        t = BudgetTracker(None)
        assert t.remaining() == math.inf
        assert t.can_start_frame()
        assert t.can_start_object()
        t.note_frame(10_000)
        assert t.can_start_frame()


class TestAdmission:
    def test_admits_while_estimate_fits(self):
        clock = _FakeClock()
        t = _tracker(900, clock, reserve_s=60, frame_cost_prior_s=130)
        assert t.can_start_frame()  # 900 - 60 >= 130

    def test_refuses_frame_when_estimate_no_longer_fits(self):
        clock = _FakeClock()
        t = _tracker(900, clock, reserve_s=60, frame_cost_prior_s=130)
        clock.advance(715)  # remaining 185; 185 - 60 = 125 < 130
        assert not t.can_start_frame()

    def test_reserve_is_held_back(self):
        clock = _FakeClock()
        t = _tracker(200, clock, reserve_s=60, frame_cost_prior_s=130)
        # 200 - 60 = 140 >= 130 admits; with reserve 80 it must not.
        assert t.can_start_frame()
        t2 = _tracker(200, clock, reserve_s=80, frame_cost_prior_s=130)
        assert not t2.can_start_frame()

    def test_object_admission_uses_object_estimate(self):
        clock = _FakeClock()
        t = _tracker(100, clock, reserve_s=60, object_cost_prior_s=30)
        assert t.can_start_object()  # 100 - 60 = 40 >= 30
        clock.advance(15)  # 85 - 60 = 25 < 30
        assert not t.can_start_object()

    def test_remaining_can_go_negative_and_still_refuses(self):
        clock = _FakeClock()
        t = _tracker(50, clock, reserve_s=10, frame_cost_prior_s=30)
        clock.advance(120)
        assert t.remaining() < 0
        assert not t.can_start_frame()
        assert not t.can_start_object()


class TestEstimatePolicy:
    def test_prior_used_before_any_observation(self):
        t = BudgetTracker(None, frame_cost_prior_s=130, object_cost_prior_s=30)
        assert t.frame_estimate_s == 130
        assert t.object_estimate_s == 30

    def test_observed_replaces_prior_even_when_cheaper(self):
        """A run of cheap frames earns more frames than the worst-case prior
        would allow — the estimate follows evidence, not pessimism."""
        t = BudgetTracker(None, frame_cost_prior_s=130)
        t.note_frame(45)
        assert t.frame_estimate_s == 45

    def test_estimate_is_running_maximum(self):
        t = BudgetTracker(None, frame_cost_prior_s=130)
        t.note_frame(45)
        t.note_frame(90)
        t.note_frame(60)
        assert t.frame_estimate_s == 90

    def test_cheap_first_frame_admits_more_then_object_level_guards(self):
        clock = _FakeClock()
        t = _tracker(300, clock, reserve_s=60, frame_cost_prior_s=130,
                     object_cost_prior_s=30)
        t.note_frame(45)
        clock.advance(190)  # remaining 110; 110 - 60 = 50 >= 45 → admit
        assert t.can_start_frame()
        clock.advance(25)  # remaining 85; 85 - 60 = 25 < 30 → object refused
        assert not t.can_start_object()

    def test_object_estimate_tracks_observed_max(self):
        t = BudgetTracker(None, object_cost_prior_s=30)
        t.note_object(8)
        assert t.object_estimate_s == 8
        t.note_object(22)
        assert t.object_estimate_s == 22


class TestSnapshot:
    def test_snapshot_fields(self):
        clock = _FakeClock()
        t = _tracker(500, clock, reserve_s=60)
        snap = t.snapshot()
        assert snap["remaining_s"] == 500.0
        assert snap["reserve_s"] == 60
        assert "frame_estimate_s" in snap and "object_estimate_s" in snap

    def test_snapshot_unlimited(self):
        assert BudgetTracker(None).snapshot()["remaining_s"] is None
