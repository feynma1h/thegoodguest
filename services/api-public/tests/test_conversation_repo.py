"""Tests for conversation_repo.py (decision 0058) — the in-memory
implementation is the semantics oracle the Firestore implementation mirrors.

Pinned invariants:
  - accept ordering: dedupe → quota → reservation (replay wins even at quota)
  - reservation: a live lease means busy for EVERY caller, including a retry
    carrying the same client_msg_id; an expired lease is reclaimed
  - the lease TTL boundary: expiry vs live holder (0011/0012 lineage)
  - persist: sequential indexes, cumulative usage, UTC day roll, and the
    holder guard (only the owning client_msg_id clears active_turn)
  - release: holder-guarded error-path mirror
  - reads: 200-empty semantics, ascending order, limits, derived
    rested_until (never stored)

Run from repo root:
  pytest services/api-public/tests/test_conversation_repo.py -v
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from conversation_repo import (
    InMemoryConversationRepository,
    next_utc_midnight,
)

_SCENE = "scene-1"
_USER = "user-abc"
_T0 = datetime(2026, 7, 21, 12, 0, 0, tzinfo=timezone.utc)
_TTL = 150
_QUOTA = 100


def _accept(repo, client_msg_id: str, *, now=_T0, quota=_QUOTA, user=_USER):
    return repo.accept_turn(
        _SCENE, user, client_msg_id,
        daily_quota=quota, reservation_ttl_s=_TTL, now=now,
    )


def _persist(repo, client_msg_id: str, *, at=_T0, user=_USER, usage=None):
    return repo.persist_turn(
        _SCENE, user,
        client_msg_id=client_msg_id,
        user_text=f"question for {client_msg_id}",
        assistant_text=f"answer for {client_msg_id}",
        created_at=at,
        completed_at=at,
        facts_version=1,
        prompt_version=1,
        model="claude-sonnet-5",
        usage=usage or {"input_tokens": 100, "output_tokens": 50},
        finish_reason="end_turn",
        flags=[],
    )


class TestAccept:
    def test_fresh_conversation_accepted(self):
        repo = InMemoryConversationRepository()
        assert _accept(repo, "msg-1").kind == "accepted"

    def test_live_reservation_means_busy_for_other_ids(self):
        repo = InMemoryConversationRepository()
        _accept(repo, "msg-1")
        assert _accept(repo, "msg-2", now=_T0 + timedelta(seconds=10)).kind == "busy"

    def test_live_reservation_means_busy_even_for_same_id(self):
        # A same-id retry while the original holder may still be draining
        # would re-admit parallel generation — the exact burn the lease closes.
        repo = InMemoryConversationRepository()
        _accept(repo, "msg-1")
        assert _accept(repo, "msg-1", now=_T0 + timedelta(seconds=10)).kind == "busy"

    def test_expired_reservation_is_reclaimed(self):
        repo = InMemoryConversationRepository()
        _accept(repo, "msg-1")
        outcome = _accept(repo, "msg-2", now=_T0 + timedelta(seconds=_TTL + 1))
        assert outcome.kind == "accepted"

    def test_reservation_expiry_boundary_vs_live_holder(self):
        # 1 s inside the TTL is still a live holder — 0011/0012's lesson.
        repo = InMemoryConversationRepository()
        _accept(repo, "msg-1")
        assert _accept(repo, "msg-2", now=_T0 + timedelta(seconds=_TTL - 1)).kind == "busy"


class TestDedupeReplay:
    def test_completed_turn_replays(self):
        repo = InMemoryConversationRepository()
        persisted = _persist(repo, "msg-1")
        outcome = _accept(repo, "msg-1")
        assert outcome.kind == "replay"
        assert outcome.replay_turn == persisted

    def test_replay_wins_over_quota(self):
        # The spend already happened — replay costs nothing, so a duplicate
        # of an existing turn replays even when the quota is exhausted.
        repo = InMemoryConversationRepository()
        _persist(repo, "msg-1")
        assert _accept(repo, "msg-1", quota=1).kind == "replay"

    def test_replay_does_not_take_the_reservation(self):
        repo = InMemoryConversationRepository()
        _persist(repo, "msg-1")
        _accept(repo, "msg-1")  # replay
        assert _accept(repo, "msg-2").kind == "accepted"


class TestQuota:
    def test_quota_exhausted_rests_with_utc_midnight(self):
        repo = InMemoryConversationRepository()
        _persist(repo, "msg-1", at=_T0)
        outcome = _accept(repo, "msg-2", now=_T0, quota=1)
        assert outcome.kind == "rested"
        assert outcome.resets_at == next_utc_midnight(_T0)
        assert outcome.resets_at == datetime(2026, 7, 22, 0, 0, 0, tzinfo=timezone.utc)

    def test_utc_day_roll_resets_the_count(self):
        repo = InMemoryConversationRepository()
        _persist(repo, "msg-1", at=_T0)
        next_day = _T0 + timedelta(days=1)  # 2026-07-22 12:00 UTC
        assert _accept(repo, "msg-2", now=next_day, quota=1).kind == "accepted"

    def test_roll_boundary_is_utc_midnight_exactly(self):
        repo = InMemoryConversationRepository()
        _persist(repo, "msg-1", at=_T0)
        just_before = datetime(2026, 7, 21, 23, 59, 59, tzinfo=timezone.utc)
        just_after = datetime(2026, 7, 22, 0, 0, 0, tzinfo=timezone.utc)
        assert _accept(repo, "msg-2", now=just_before, quota=1).kind == "rested"
        assert _accept(repo, "msg-3", now=just_after, quota=1).kind == "accepted"


class TestPersist:
    def test_sequential_indexes_and_doc_shape(self):
        repo = InMemoryConversationRepository()
        first = _persist(repo, "msg-1")
        second = _persist(repo, "msg-2")
        assert (first.turn_index, second.turn_index) == (0, 1)
        assert first.model == "claude-sonnet-5"
        assert first.prompt_version == 1 and first.facts_version == 1

    def test_persist_clears_own_lease(self):
        repo = InMemoryConversationRepository()
        _accept(repo, "msg-1")
        _persist(repo, "msg-1")
        assert _accept(repo, "msg-2").kind == "accepted"

    def test_persist_holder_guard_leaves_foreign_lease(self):
        # If our lease expired and someone else reclaimed it, persisting our
        # (completed, paid-for) turn must not clear THEIR reservation.
        repo = InMemoryConversationRepository()
        _accept(repo, "msg-1")
        reclaim_at = _T0 + timedelta(seconds=_TTL + 1)
        assert _accept(repo, "msg-2", now=reclaim_at).kind == "accepted"
        _persist(repo, "msg-1", at=reclaim_at)
        # msg-2's lease still stands: a third caller is busy.
        assert _accept(repo, "msg-3", now=reclaim_at + timedelta(seconds=1)).kind == "busy"

    def test_cumulative_usage(self):
        repo = InMemoryConversationRepository()
        _persist(repo, "msg-1", usage={"input_tokens": 100, "output_tokens": 50})
        _persist(repo, "msg-2", usage={
            "input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 90,
        })
        doc = repo._store[(_SCENE, _USER)]["doc"]
        assert doc["usage"] == {
            "input_tokens": 110,
            "output_tokens": 55,
            "cache_read_input_tokens": 90,
            "cache_creation_input_tokens": 0,
        }

    def test_persist_rolls_turns_today(self):
        repo = InMemoryConversationRepository()
        _persist(repo, "msg-1", at=_T0)
        _persist(repo, "msg-2", at=_T0)
        doc = repo._store[(_SCENE, _USER)]["doc"]
        assert (doc["day"], doc["turns_today"]) == ("2026-07-21", 2)
        _persist(repo, "msg-3", at=_T0 + timedelta(days=1))
        doc = repo._store[(_SCENE, _USER)]["doc"]
        assert (doc["day"], doc["turns_today"]) == ("2026-07-22", 1)
        assert doc["turn_count"] == 3  # lifetime count never rolls


class TestRelease:
    def test_holder_releases(self):
        repo = InMemoryConversationRepository()
        _accept(repo, "msg-1")
        repo.release_reservation(_SCENE, _USER, "msg-1")
        assert _accept(repo, "msg-2").kind == "accepted"

    def test_non_holder_cannot_release(self):
        repo = InMemoryConversationRepository()
        _accept(repo, "msg-1")
        repo.release_reservation(_SCENE, _USER, "msg-other")
        assert _accept(repo, "msg-2").kind == "busy"

    def test_release_on_missing_conversation_is_a_noop(self):
        InMemoryConversationRepository().release_reservation(_SCENE, _USER, "x")


class TestReads:
    def test_empty_conversation(self):
        repo = InMemoryConversationRepository()
        snap = repo.get_conversation(
            _SCENE, _USER, turn_limit=50, daily_quota=_QUOTA, now=_T0
        )
        assert (snap.turn_count, snap.rested_until, snap.turns) == (0, None, [])

    def test_turns_ascending_and_limited(self):
        repo = InMemoryConversationRepository()
        for i in range(5):
            _persist(repo, f"msg-{i}")
        snap = repo.get_conversation(
            _SCENE, _USER, turn_limit=3, daily_quota=_QUOTA, now=_T0
        )
        assert snap.turn_count == 5
        assert [t.turn_index for t in snap.turns] == [2, 3, 4]

    def test_rested_until_derived_not_stored(self):
        repo = InMemoryConversationRepository()
        _persist(repo, "msg-1", at=_T0)
        snap = repo.get_conversation(
            _SCENE, _USER, turn_limit=50, daily_quota=1, now=_T0
        )
        assert snap.rested_until == next_utc_midnight(_T0)
        # Same store, read the next day: the rest lifted without any write.
        snap = repo.get_conversation(
            _SCENE, _USER, turn_limit=50, daily_quota=1,
            now=_T0 + timedelta(days=1),
        )
        assert snap.rested_until is None

    def test_recent_turns_window(self):
        repo = InMemoryConversationRepository()
        for i in range(4):
            _persist(repo, f"msg-{i}")
        window = repo.recent_turns(_SCENE, _USER, 2)
        assert [t.turn_index for t in window] == [2, 3]

    def test_conversations_are_scoped_per_user(self):
        # Per-scene+user doc id: a shared viewer must not inherit the
        # owner's transcript.
        repo = InMemoryConversationRepository()
        _persist(repo, "msg-1", user="user-abc")
        assert repo.recent_turns(_SCENE, "user-other", 10) == []
