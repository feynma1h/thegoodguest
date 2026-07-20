"""Conversation state for stage 1 (decision 0058): turns are the atomic unit.

Firestore layout (server-only writes; the web client NEVER touches Firestore):

  conversations/{scene_id}__{user_id}
    {scene_id, user_id, created_at, updated_at, turn_count,
     usage: {input_tokens, output_tokens, cache_read_input_tokens,
             cache_creation_input_tokens},
     active_turn: {client_msg_id, started_at} | None,
     day: "YYYY-MM-DD" (UTC), turns_today}

  conversations/{...}/turns/{turn_index:06d}
    {turn_index, client_msg_id, user_text, assistant_text, created_at,
     completed_at, facts_version, prompt_version, model, usage,
     finish_reason, flags}

A turn document exists only COMPLETED — a half-persisted turn is
unrepresentable. The conversation doc's counters are maintained inside the
accept/persist transactions.

Accept transaction (in order):
  1. client_msg_id dedupe — a completed turn with this id replays verbatim,
     no regeneration (replay wins even over quota: the spend already happened).
  2. daily quota — turns_today under a UTC day roll; at the limit the caller
     429s with resets_at = next UTC midnight.
  3. turn-taking reservation — active_turn is a lease. A live lease (younger
     than the TTL) means 409 turn_in_flight, INCLUDING for a retry carrying
     the same client_msg_id: the original holder may still be draining after
     a client disconnect, and re-admitting it would reopen exactly the
     parallel-generation burn the lease closes. The TTL (150 s, set by the
     caller) deliberately exceeds the full 120 s request envelope — a lease
     expiring under a legitimate in-flight turn re-admits parallelism through
     the mechanism that closed it (decision 0058; this repo has debugged
     lease-expiry-vs-live-holder before, decisions 0011/0012).

Persist transaction: create the turn doc at index=turn_count, increment
turn_count / turns_today (UTC roll) / cumulative usage, and clear active_turn
ONLY if this turn still holds it (holder guard — an expired-and-reclaimed
lease belongs to someone else). Persist itself is unconditional: the model
already spoke and the money is spent, so the transcript keeps the turn; the
transaction assigns indices serially, so even a pathological parallel pair
persists as two distinct turns.

release_reservation() is the error path's mirror: clear active_turn iff we
hold it, so a failed turn doesn't lock the composer for the lease TTL.

Implementations:
  InMemoryConversationRepository — tests/dev; the semantics oracle.
  FirestoreConversationRepository — production; mirrors the in-memory
  semantics inside Firestore transactions. google.cloud.firestore imports
  lazily per service convention.

Consumers: services/api-public/public_server.py (conversation routes).
F6 note (CLAUDE.md): Firestore never cascades deletes — when scene TTL
ships, plan per-collection-group TTL on turns.created_at + conversations,
or the sweep orphans this collection.
"""
from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone

_USAGE_KEYS = (
    "input_tokens",
    "output_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
)


def _zero_usage() -> dict:
    return dict.fromkeys(_USAGE_KEYS, 0)


def _add_usage(cumulative: dict, turn_usage: dict) -> dict:
    return {
        k: int(cumulative.get(k, 0) or 0) + int(turn_usage.get(k, 0) or 0)
        for k in _USAGE_KEYS
    }


def utc_day(now: datetime) -> str:
    return now.astimezone(timezone.utc).strftime("%Y-%m-%d")


def next_utc_midnight(now: datetime) -> datetime:
    day_after = now.astimezone(timezone.utc).date() + timedelta(days=1)
    return datetime.combine(day_after, time.min, tzinfo=timezone.utc)


@dataclass(frozen=True)
class TurnRecord:
    """One completed turn, exactly as persisted."""
    turn_index: int
    client_msg_id: str
    user_text: str
    assistant_text: str
    created_at: datetime
    completed_at: datetime
    facts_version: int
    prompt_version: int
    model: str
    usage: dict
    finish_reason: str
    flags: list[str] = field(default_factory=list)

    def to_doc(self) -> dict:
        return {
            "turn_index": self.turn_index,
            "client_msg_id": self.client_msg_id,
            "user_text": self.user_text,
            "assistant_text": self.assistant_text,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "facts_version": self.facts_version,
            "prompt_version": self.prompt_version,
            "model": self.model,
            "usage": dict(self.usage),
            "finish_reason": self.finish_reason,
            "flags": list(self.flags),
        }

    @staticmethod
    def from_doc(doc: dict) -> TurnRecord:
        return TurnRecord(
            turn_index=int(doc["turn_index"]),
            client_msg_id=str(doc["client_msg_id"]),
            user_text=str(doc["user_text"]),
            assistant_text=str(doc["assistant_text"]),
            created_at=doc["created_at"],
            completed_at=doc["completed_at"],
            facts_version=int(doc.get("facts_version", 0)),
            prompt_version=int(doc.get("prompt_version", 0)),
            model=str(doc.get("model", "")),
            usage=dict(doc.get("usage") or {}),
            finish_reason=str(doc.get("finish_reason", "")),
            flags=list(doc.get("flags") or []),
        )


@dataclass(frozen=True)
class AcceptOutcome:
    """Result of the accept transaction. kind is one of:
    "accepted" (reservation held — generate), "replay" (dedupe hit —
    replay_turn is the stored turn), "rested" (quota — resets_at set),
    "busy" (a live lease exists — 409 turn_in_flight)."""
    kind: str
    replay_turn: TurnRecord | None = None
    resets_at: datetime | None = None


@dataclass(frozen=True)
class ConversationSnapshot:
    """GET-shaped read: meta + the last `turn_limit` turns in ascending
    order. rested_until is DERIVED (quota state at read time), never stored."""
    turn_count: int
    rested_until: datetime | None
    turns: list[TurnRecord]


def _derive_rested_until(
    doc: dict | None, *, daily_quota: int, now: datetime
) -> datetime | None:
    if doc is None:
        return None
    effective = int(doc.get("turns_today", 0)) if doc.get("day") == utc_day(now) else 0
    return next_utc_midnight(now) if effective >= daily_quota else None


class ConversationRepository(ABC):
    """Interface for conversation persistence. All datetimes are tz-aware UTC."""

    @abstractmethod
    def accept_turn(
        self,
        scene_id: str,
        user_id: str,
        client_msg_id: str,
        *,
        daily_quota: int,
        reservation_ttl_s: int,
        now: datetime,
    ) -> AcceptOutcome:
        """Run the accept transaction: dedupe → quota → reservation."""

    @abstractmethod
    def persist_turn(
        self,
        scene_id: str,
        user_id: str,
        *,
        client_msg_id: str,
        user_text: str,
        assistant_text: str,
        created_at: datetime,
        completed_at: datetime,
        facts_version: int,
        prompt_version: int,
        model: str,
        usage: dict,
        finish_reason: str,
        flags: list[str],
    ) -> TurnRecord:
        """Create the completed turn doc, bump counters, clear our lease.
        Returns the persisted record (with its assigned turn_index)."""

    @abstractmethod
    def release_reservation(
        self, scene_id: str, user_id: str, client_msg_id: str
    ) -> None:
        """Clear active_turn iff client_msg_id still holds it (error path)."""

    @abstractmethod
    def get_conversation(
        self,
        scene_id: str,
        user_id: str,
        *,
        turn_limit: int,
        daily_quota: int,
        now: datetime,
    ) -> ConversationSnapshot:
        """Meta + last `turn_limit` turns ascending. A scene+user with no
        conversation yet returns turn_count=0, no turns (200-empty)."""

    @abstractmethod
    def recent_turns(self, scene_id: str, user_id: str, n: int) -> list[TurnRecord]:
        """Last n completed turns, ascending — the model's context window."""


# ---------------------------------------------------------------------------
# In-memory implementation (tests/dev) — the semantics oracle
# ---------------------------------------------------------------------------

class InMemoryConversationRepository(ConversationRepository):
    """Dict-backed store with a lock standing in for Firestore transactions."""

    def __init__(self) -> None:
        # (scene_id, user_id) → {"doc": {...}, "turns": [turn doc dicts]}
        self._store: dict[tuple[str, str], dict] = {}
        self._lock = threading.Lock()

    def _entry(self, scene_id: str, user_id: str, *, create: bool, now: datetime):
        key = (scene_id, user_id)
        entry = self._store.get(key)
        if entry is None and create:
            entry = {
                "doc": {
                    "scene_id": scene_id,
                    "user_id": user_id,
                    "created_at": now,
                    "updated_at": now,
                    "turn_count": 0,
                    "usage": _zero_usage(),
                    "active_turn": None,
                    "day": utc_day(now),
                    "turns_today": 0,
                },
                "turns": [],
            }
            self._store[key] = entry
        return entry

    def accept_turn(
        self,
        scene_id: str,
        user_id: str,
        client_msg_id: str,
        *,
        daily_quota: int,
        reservation_ttl_s: int,
        now: datetime,
    ) -> AcceptOutcome:
        with self._lock:
            entry = self._entry(scene_id, user_id, create=False, now=now)
            doc = entry["doc"] if entry else None

            # 1. Dedupe: a completed turn with this id replays.
            if entry:
                for turn_doc in entry["turns"]:
                    if turn_doc["client_msg_id"] == client_msg_id:
                        return AcceptOutcome(
                            kind="replay", replay_turn=TurnRecord.from_doc(turn_doc)
                        )

            # 2. Quota under the UTC day roll.
            effective = (
                int(doc.get("turns_today", 0))
                if doc and doc.get("day") == utc_day(now)
                else 0
            )
            if effective >= daily_quota:
                return AcceptOutcome(kind="rested", resets_at=next_utc_midnight(now))

            # 3. Reservation: a live lease (any holder) means busy.
            active = doc.get("active_turn") if doc else None
            if active is not None:
                age_s = (now - active["started_at"]).total_seconds()
                if age_s < reservation_ttl_s:
                    return AcceptOutcome(kind="busy")

            entry = self._entry(scene_id, user_id, create=True, now=now)
            entry["doc"]["active_turn"] = {
                "client_msg_id": client_msg_id,
                "started_at": now,
            }
            entry["doc"]["updated_at"] = now
            return AcceptOutcome(kind="accepted")

    def persist_turn(
        self,
        scene_id: str,
        user_id: str,
        *,
        client_msg_id: str,
        user_text: str,
        assistant_text: str,
        created_at: datetime,
        completed_at: datetime,
        facts_version: int,
        prompt_version: int,
        model: str,
        usage: dict,
        finish_reason: str,
        flags: list[str],
    ) -> TurnRecord:
        with self._lock:
            entry = self._entry(scene_id, user_id, create=True, now=completed_at)
            doc = entry["doc"]
            record = TurnRecord(
                turn_index=int(doc["turn_count"]),
                client_msg_id=client_msg_id,
                user_text=user_text,
                assistant_text=assistant_text,
                created_at=created_at,
                completed_at=completed_at,
                facts_version=facts_version,
                prompt_version=prompt_version,
                model=model,
                usage=dict(usage),
                finish_reason=finish_reason,
                flags=list(flags),
            )
            entry["turns"].append(record.to_doc())
            today = utc_day(completed_at)
            doc["turns_today"] = (
                int(doc.get("turns_today", 0)) + 1 if doc.get("day") == today else 1
            )
            doc["day"] = today
            doc["turn_count"] = int(doc["turn_count"]) + 1
            doc["usage"] = _add_usage(doc.get("usage") or {}, usage)
            doc["updated_at"] = completed_at
            active = doc.get("active_turn")
            if active is not None and active.get("client_msg_id") == client_msg_id:
                doc["active_turn"] = None
            return record

    def release_reservation(
        self, scene_id: str, user_id: str, client_msg_id: str
    ) -> None:
        with self._lock:
            entry = self._store.get((scene_id, user_id))
            if not entry:
                return
            active = entry["doc"].get("active_turn")
            if active is not None and active.get("client_msg_id") == client_msg_id:
                entry["doc"]["active_turn"] = None

    def get_conversation(
        self,
        scene_id: str,
        user_id: str,
        *,
        turn_limit: int,
        daily_quota: int,
        now: datetime,
    ) -> ConversationSnapshot:
        with self._lock:
            entry = self._store.get((scene_id, user_id))
            if not entry:
                return ConversationSnapshot(turn_count=0, rested_until=None, turns=[])
            doc = entry["doc"]
            turns = [TurnRecord.from_doc(d) for d in entry["turns"][-turn_limit:]]
            return ConversationSnapshot(
                turn_count=int(doc["turn_count"]),
                rested_until=_derive_rested_until(
                    doc, daily_quota=daily_quota, now=now
                ),
                turns=turns,
            )

    def recent_turns(self, scene_id: str, user_id: str, n: int) -> list[TurnRecord]:
        with self._lock:
            entry = self._store.get((scene_id, user_id))
            if not entry:
                return []
            return [TurnRecord.from_doc(d) for d in entry["turns"][-n:]]


# ---------------------------------------------------------------------------
# Firestore implementation (production)
# ---------------------------------------------------------------------------

class FirestoreConversationRepository(ConversationRepository):
    """Firestore-backed conversation store. Mirrors the in-memory semantics
    (which the unit tests pin) inside Firestore transactions; contention
    retries are the client library's."""

    COLLECTION = "conversations"
    TURNS = "turns"

    def __init__(self, project: str | None = None) -> None:
        from google.cloud import firestore as _fs  # deferred

        self._fs = _fs
        self._db = _fs.Client(project=project)

    def _conv_ref(self, scene_id: str, user_id: str):
        return self._db.collection(self.COLLECTION).document(
            f"{scene_id}__{user_id}"
        )

    @staticmethod
    def _turn_doc_id(turn_index: int) -> str:
        return f"{turn_index:06d}"

    def _base_doc(self, scene_id: str, user_id: str, now: datetime) -> dict:
        return {
            "scene_id": scene_id,
            "user_id": user_id,
            "created_at": now,
            "updated_at": now,
            "turn_count": 0,
            "usage": _zero_usage(),
            "active_turn": None,
            "day": utc_day(now),
            "turns_today": 0,
        }

    def accept_turn(
        self,
        scene_id: str,
        user_id: str,
        client_msg_id: str,
        *,
        daily_quota: int,
        reservation_ttl_s: int,
        now: datetime,
    ) -> AcceptOutcome:
        from google.cloud.firestore_v1.base_query import FieldFilter  # deferred

        conv_ref = self._conv_ref(scene_id, user_id)
        dedupe_query = (
            conv_ref.collection(self.TURNS)
            .where(filter=FieldFilter("client_msg_id", "==", client_msg_id))
            .limit(1)
        )
        transaction = self._db.transaction()

        @self._fs.transactional
        def _txn(txn) -> AcceptOutcome:
            snap = conv_ref.get(transaction=txn)
            doc = snap.to_dict() if snap.exists else None

            duplicates = list(dedupe_query.get(transaction=txn))
            if duplicates:
                return AcceptOutcome(
                    kind="replay",
                    replay_turn=TurnRecord.from_doc(duplicates[0].to_dict()),
                )

            effective = (
                int(doc.get("turns_today", 0))
                if doc and doc.get("day") == utc_day(now)
                else 0
            )
            if effective >= daily_quota:
                return AcceptOutcome(kind="rested", resets_at=next_utc_midnight(now))

            active = doc.get("active_turn") if doc else None
            if active is not None:
                age_s = (now - active["started_at"]).total_seconds()
                if age_s < reservation_ttl_s:
                    return AcceptOutcome(kind="busy")

            reservation = {"client_msg_id": client_msg_id, "started_at": now}
            if doc is None:
                base = self._base_doc(scene_id, user_id, now)
                base["active_turn"] = reservation
                txn.set(conv_ref, base)
            else:
                txn.update(
                    conv_ref, {"active_turn": reservation, "updated_at": now}
                )
            return AcceptOutcome(kind="accepted")

        return _txn(transaction)

    def persist_turn(
        self,
        scene_id: str,
        user_id: str,
        *,
        client_msg_id: str,
        user_text: str,
        assistant_text: str,
        created_at: datetime,
        completed_at: datetime,
        facts_version: int,
        prompt_version: int,
        model: str,
        usage: dict,
        finish_reason: str,
        flags: list[str],
    ) -> TurnRecord:
        conv_ref = self._conv_ref(scene_id, user_id)
        transaction = self._db.transaction()

        @self._fs.transactional
        def _txn(txn) -> TurnRecord:
            snap = conv_ref.get(transaction=txn)
            doc = (
                snap.to_dict()
                if snap.exists
                else self._base_doc(scene_id, user_id, completed_at)
            )
            record = TurnRecord(
                turn_index=int(doc["turn_count"]),
                client_msg_id=client_msg_id,
                user_text=user_text,
                assistant_text=assistant_text,
                created_at=created_at,
                completed_at=completed_at,
                facts_version=facts_version,
                prompt_version=prompt_version,
                model=model,
                usage=dict(usage),
                finish_reason=finish_reason,
                flags=list(flags),
            )
            turn_ref = conv_ref.collection(self.TURNS).document(
                self._turn_doc_id(record.turn_index)
            )
            txn.set(turn_ref, record.to_doc())

            today = utc_day(completed_at)
            doc["turns_today"] = (
                int(doc.get("turns_today", 0)) + 1 if doc.get("day") == today else 1
            )
            doc["day"] = today
            doc["turn_count"] = int(doc["turn_count"]) + 1
            doc["usage"] = _add_usage(doc.get("usage") or {}, usage)
            doc["updated_at"] = completed_at
            active = doc.get("active_turn")
            if active is not None and active.get("client_msg_id") == client_msg_id:
                doc["active_turn"] = None
            txn.set(conv_ref, doc)
            return record

        return _txn(transaction)

    def release_reservation(
        self, scene_id: str, user_id: str, client_msg_id: str
    ) -> None:
        conv_ref = self._conv_ref(scene_id, user_id)
        transaction = self._db.transaction()

        @self._fs.transactional
        def _txn(txn) -> None:
            snap = conv_ref.get(transaction=txn)
            if not snap.exists:
                return
            active = (snap.to_dict() or {}).get("active_turn")
            if active is not None and active.get("client_msg_id") == client_msg_id:
                txn.update(conv_ref, {"active_turn": None})

        _txn(transaction)

    def get_conversation(
        self,
        scene_id: str,
        user_id: str,
        *,
        turn_limit: int,
        daily_quota: int,
        now: datetime,
    ) -> ConversationSnapshot:
        conv_ref = self._conv_ref(scene_id, user_id)
        snap = conv_ref.get()
        if not snap.exists:
            return ConversationSnapshot(turn_count=0, rested_until=None, turns=[])
        doc = snap.to_dict() or {}
        turns = self._last_turns(conv_ref, turn_limit)
        return ConversationSnapshot(
            turn_count=int(doc.get("turn_count", 0)),
            rested_until=_derive_rested_until(doc, daily_quota=daily_quota, now=now),
            turns=turns,
        )

    def recent_turns(self, scene_id: str, user_id: str, n: int) -> list[TurnRecord]:
        return self._last_turns(self._conv_ref(scene_id, user_id), n)

    def _last_turns(self, conv_ref, n: int) -> list[TurnRecord]:
        from google.cloud import firestore as _fs  # deferred

        snaps = (
            conv_ref.collection(self.TURNS)
            .order_by("turn_index", direction=_fs.Query.DESCENDING)
            .limit(n)
            .get()
        )
        records = [TurnRecord.from_doc(s.to_dict()) for s in snaps]
        records.reverse()
        return records
