"""Tests for guide_repo.py (decision 0376): the in-memory implementation is the
semantics oracle the Firestore implementation mirrors.

Pinned invariants:
  - accept order: dedupe, then the opening check, then the daily budget, then
    the lease (a replay wins even over a spent budget: the spend already happened)
  - the lease: live means busy for every caller, buttons included; an expired one
    is taken over; only its holder clears it, by persisting, saving or releasing
  - persist: sequential indexes, the kept state replaced, messages kept as text
  - the budget: dollars per person per UTC day, across every room

Run from repo root:
  pytest services/api-public/tests/test_guide_repo.py -v
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from conversation_repo import next_utc_midnight
from guide_repo import GuideTurn, InMemoryGuideRepository

S, U = "scene-1", "user-1"
T0 = datetime(2026, 11, 12, 10, 0, tzinfo=UTC)
TTL = 150


def accept(repo, msg="m1", *, now=T0, opening=False, daily=2.0, scene=S, user=U):
    return repo.accept_turn(scene, user, msg, opening=opening, daily_usd=daily, ttl_s=TTL, now=now)


def turn(msg="m1", *, opening=False, messages='[{"role": "user", "content": "hi"}]') -> GuideTurn:
    return GuideTurn(turn_index=-1, client_msg_id=msg, opening=opening, user_text="" if opening else "hi",
                     messages_json=messages, events_json="[]", reply="hello", flags=[], cost_usd=0.03,
                     model="claude-opus-5-5", prompt_version="guide/5", created_at=T0, completed_at=T0)


class TestAccept:
    def test_a_first_turn_is_accepted_with_its_budget(self):
        repo = InMemoryGuideRepository()
        out = accept(repo, daily=2.0)
        assert out.kind == "accepted" and out.remaining_usd == 2.0
        assert repo.get(S, U).active["holder"] == "m1"

    def test_a_live_lease_is_busy_for_everyone(self):
        repo = InMemoryGuideRepository()
        accept(repo, "m1")
        assert accept(repo, "m2", now=T0 + timedelta(seconds=10)).kind == "busy"
        assert accept(repo, "m1", now=T0 + timedelta(seconds=10)).kind == "busy", "a retry waits too"
        assert not repo.take_lease(S, U, "button:1", ttl_s=TTL, now=T0 + timedelta(seconds=10))

    def test_an_expired_lease_is_taken_over(self):
        repo = InMemoryGuideRepository()
        accept(repo, "m1")
        assert accept(repo, "m2", now=T0 + timedelta(seconds=TTL)).kind == "accepted"
        assert repo.get(S, U).active["holder"] == "m2"

    def test_a_kept_turn_replays_even_on_a_spent_day(self):
        repo = InMemoryGuideRepository()
        accept(repo, "m1")
        repo.persist_turn(S, U, turn("m1"), state_json="{}", now=T0)
        repo.charge(U, 5.0, T0)
        out = accept(repo, "m1", daily=2.0)
        assert out.kind == "replay" and out.replay_turn.reply == "hello"

    def test_an_opening_once_the_conversation_has_begun(self):
        repo = InMemoryGuideRepository()
        assert accept(repo, "o1", opening=True).kind == "accepted"
        repo.persist_turn(S, U, turn("o1", opening=True), state_json="", now=T0)
        assert accept(repo, "o2", opening=True).kind == "opened"
        assert accept(repo, "m2").kind == "accepted"

    def test_a_spent_day_rests_until_midnight(self):
        repo = InMemoryGuideRepository()
        repo.charge(U, 1.5, T0)
        repo.charge(U, 0.5, T0)
        out = accept(repo, daily=2.0)
        assert out.kind == "rested" and out.resets_at == next_utc_midnight(T0)
        tomorrow = T0 + timedelta(days=1)
        assert accept(repo, now=tomorrow, daily=2.0).kind == "accepted"

    def test_the_budget_spans_every_room(self):
        repo = InMemoryGuideRepository()
        repo.charge(U, 2.0, T0)
        assert accept(repo, scene="another-room").kind == "rested"
        assert accept(repo, user="someone-else").kind == "accepted"

    def test_a_zero_budget_turns_the_guide_off(self):
        assert accept(InMemoryGuideRepository(), daily=0.0).kind == "rested"


class TestPersist:
    def test_indexes_are_sequential_and_the_lease_clears(self):
        repo = InMemoryGuideRepository()
        accept(repo, "m1")
        first = repo.persist_turn(S, U, turn("m1"), state_json='{"v": 1}', now=T0)
        accept(repo, "m2")
        second = repo.persist_turn(S, U, turn("m2"), state_json='{"v": 2}', now=T0)
        assert (first.turn_index, second.turn_index) == (0, 1)
        record = repo.get(S, U)
        assert record.turn_count == 2 and record.state_json == '{"v": 2}' and record.active is None
        assert [t.client_msg_id for t in repo.turns(S, U, 10)] == ["m1", "m2"]
        assert [t.client_msg_id for t in repo.turns(S, U, 1)] == ["m2"]

    def test_messages_come_back_as_the_text_that_was_kept(self):
        repo = InMemoryGuideRepository()
        accept(repo)
        raw = '[{"role": "assistant", "content": [{"type": "thinking", "thinking": "…", "signature": "c2ln"}]}]'
        repo.persist_turn(S, U, turn(messages=raw), state_json="", now=T0)
        assert repo.turns(S, U, 1)[0].messages_json == raw

    def test_a_turn_that_lost_its_lease_is_kept_but_leaves_the_new_holder(self):
        repo = InMemoryGuideRepository()
        accept(repo, "m1")
        accept(repo, "m2", now=T0 + timedelta(seconds=TTL))
        repo.persist_turn(S, U, turn("m1"), state_json="", now=T0)
        assert repo.get(S, U).active["holder"] == "m2"


class TestButtonsAndRelease:
    def test_save_state_only_while_holding(self):
        repo = InMemoryGuideRepository()
        assert repo.take_lease(S, U, "button:a", ttl_s=TTL, now=T0)
        assert not repo.save_state(S, U, "button:b", state_json="x", now=T0)
        assert repo.save_state(S, U, "button:a", state_json="kept", now=T0)
        record = repo.get(S, U)
        assert record.state_json == "kept" and record.active is None

    def test_release_is_holder_guarded(self):
        repo = InMemoryGuideRepository()
        accept(repo, "m1")
        repo.release(S, U, "someone-else")
        assert repo.get(S, U).active is not None
        repo.release(S, U, "m1")
        assert repo.get(S, U).active is None

    def test_nothing_kept_reads_as_nothing(self):
        repo = InMemoryGuideRepository()
        assert repo.get(S, U) is None and repo.turns(S, U, 10) == []
        assert repo.spent_today(U, T0) == 0.0
