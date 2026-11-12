"""Where the room guide's conversations and its daily budget are kept (decision 0376).

The room guide (packages/room-guide) is the conversation a room with a diorama
scene gets. This module keeps what one person's conversation about one room needs
between requests, and what the guide has cost each person today.

Firestore layout (server-only writes; the web client never touches Firestore):

  room_guides/{scene_id}__{user_id}
    {scene_id, user_id, created_at, updated_at, turn_count,
     active: {holder, started_at} | None,
     state_json: <the room as it stands in this conversation, guide_session.GuideState>}

  room_guides/{...}/turns/{turn_index:06d}
    {turn_index, client_msg_id, opening, user_text,
     messages_json: <the messages this turn added, every content block exactly as
                     Claude returned it: the API refuses a conversation whose
                     earlier turns were edited>,
     events_json: <what the panel showed: the guide's words, cards and notes>,
     reply, flags, cost_usd, model, prompt_version, created_at, completed_at}

  room_guide_budgets/{user_id}
    {user_id, day: "YYYY-MM-DD" (UTC), spent_usd, turns, updated_at}

Messages and events are stored as JSON text, not as Firestore maps: the text comes
back byte for byte, which a reasoning block's signature needs, and Firestore never
sees an array nested in an array.

A turn document exists only completed. The conversation document's `active` field
is the turn-taking lease of the existing guest (conversation_repo.py, decision
0058): a live lease means 409 turn_in_flight, including for a retry with the same
client_msg_id, and the lease outlives the whole request envelope. Here it also
guards the "Show me" and "Put it back" buttons, which change the same state a turn
does, so a button never lands in the middle of a turn.

Accept transaction (in order), as the guest's:
  1. client_msg_id dedupe: a completed turn with this id replays.
  2. an opening asked for a conversation that already has turns: "opened".
  3. the person's daily budget, in dollars across every room (the guide prices
     every call): spent at or over it means 429 with resets_at at the next UTC
     midnight.
  4. the lease.

The budget is charged after a turn with what its calls cost, whether or not the
turn completed: money spent on a failed turn was still spent.

Implementations:
  InMemoryGuideRepository   tests and local runs; the semantics oracle.
  FirestoreGuideRepository  production; the same semantics inside transactions.

Read by: public_server.py (the guide routes), account_deletion.py (the collection
names), tests/test_guide_repo.py and tests/test_guide_routes.py.
"""
from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
from datetime import datetime

from conversation_repo import next_utc_midnight, utc_day

GUIDES_COLLECTION = "room_guides"
GUIDE_TURNS_SUBCOLLECTION = "turns"
GUIDE_BUDGETS_COLLECTION = "room_guide_budgets"


@dataclass(frozen=True)
class GuideTurn:
    """One completed turn, exactly as persisted."""

    turn_index: int
    client_msg_id: str
    opening: bool
    user_text: str
    messages_json: str
    events_json: str
    reply: str
    flags: list[str]
    cost_usd: float
    model: str
    prompt_version: str
    created_at: datetime
    completed_at: datetime

    def to_doc(self) -> dict:
        return {
            "turn_index": self.turn_index,
            "client_msg_id": self.client_msg_id,
            "opening": self.opening,
            "user_text": self.user_text,
            "messages_json": self.messages_json,
            "events_json": self.events_json,
            "reply": self.reply,
            "flags": list(self.flags),
            "cost_usd": float(self.cost_usd),
            "model": self.model,
            "prompt_version": self.prompt_version,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
        }

    @staticmethod
    def from_doc(doc: dict) -> GuideTurn:
        return GuideTurn(
            turn_index=int(doc["turn_index"]),
            client_msg_id=str(doc["client_msg_id"]),
            opening=bool(doc.get("opening", False)),
            user_text=str(doc.get("user_text", "")),
            messages_json=str(doc.get("messages_json", "[]")),
            events_json=str(doc.get("events_json", "[]")),
            reply=str(doc.get("reply", "")),
            flags=list(doc.get("flags") or []),
            cost_usd=float(doc.get("cost_usd", 0.0) or 0.0),
            model=str(doc.get("model", "")),
            prompt_version=str(doc.get("prompt_version", "")),
            created_at=doc["created_at"],
            completed_at=doc["completed_at"],
        )


@dataclass(frozen=True)
class GuideRecord:
    """The conversation document: how many turns, the kept state, the lease."""

    turn_count: int
    state_json: str
    active: dict | None


@dataclass(frozen=True)
class GuideAccept:
    """kind: accepted (lease held: generate), replay (dedupe hit), opened (an
    opening for a conversation that has begun), rested (budget spent; resets_at
    set) or busy (a live lease: 409 turn_in_flight). remaining_usd is what is
    left of today's budget, for the gateway's ceiling."""

    kind: str
    replay_turn: GuideTurn | None = None
    resets_at: datetime | None = None
    remaining_usd: float = 0.0


def _lease_live(active: dict | None, now: datetime, ttl_s: int) -> bool:
    if active is None:
        return False
    return (now - active["started_at"]).total_seconds() < ttl_s


def _spent_today(budget: dict | None, now: datetime) -> float:
    if not budget or budget.get("day") != utc_day(now):
        return 0.0
    return float(budget.get("spent_usd", 0.0) or 0.0)


class GuideRepository(ABC):
    """Interface for the guide's persistence. All datetimes are tz-aware UTC."""

    @abstractmethod
    def get(self, scene_id: str, user_id: str) -> GuideRecord | None:
        """The conversation document, or None before the first turn."""

    @abstractmethod
    def turns(self, scene_id: str, user_id: str, limit: int) -> list[GuideTurn]:
        """The last `limit` completed turns, ascending."""

    @abstractmethod
    def accept_turn(self, scene_id: str, user_id: str, client_msg_id: str, *,
                    opening: bool, daily_usd: float, ttl_s: int, now: datetime) -> GuideAccept:
        """Dedupe, then the opening check, then the budget, then the lease."""

    @abstractmethod
    def take_lease(self, scene_id: str, user_id: str, holder: str, *, ttl_s: int,
                   now: datetime) -> bool:
        """The lease for a button (show, undo): False when a live lease exists."""

    @abstractmethod
    def persist_turn(self, scene_id: str, user_id: str, turn: GuideTurn, *, state_json: str,
                     now: datetime) -> GuideTurn:
        """Store the completed turn at index turn_count, keep the state, and clear
        the lease if this turn still holds it. Returns the turn with its index."""

    @abstractmethod
    def save_state(self, scene_id: str, user_id: str, holder: str, *, state_json: str,
                   now: datetime) -> bool:
        """Keep the state and clear the lease, only while `holder` holds it."""

    @abstractmethod
    def release(self, scene_id: str, user_id: str, holder: str) -> None:
        """Clear the lease iff `holder` holds it (the error path)."""

    @abstractmethod
    def spent_today(self, user_id: str, now: datetime) -> float:
        """Dollars the guide has cost this person today (UTC)."""

    @abstractmethod
    def charge(self, user_id: str, usd: float, now: datetime) -> float:
        """Add a turn's cost to today's spend. Returns the new total."""


# ---------------------------------------------------------------------------
# In-memory implementation (tests and local runs): the semantics oracle
# ---------------------------------------------------------------------------

class InMemoryGuideRepository(GuideRepository):
    """Dict-backed store with a lock standing in for Firestore transactions."""

    def __init__(self) -> None:
        self._docs: dict[tuple[str, str], dict] = {}
        self._turns: dict[tuple[str, str], list[dict]] = {}
        self._budgets: dict[str, dict] = {}
        self._lock = threading.Lock()

    def _doc(self, scene_id: str, user_id: str, now: datetime) -> dict:
        key = (scene_id, user_id)
        if key not in self._docs:
            self._docs[key] = {"scene_id": scene_id, "user_id": user_id, "created_at": now,
                               "updated_at": now, "turn_count": 0, "active": None,
                               "state_json": ""}
            self._turns[key] = []
        return self._docs[key]

    def get(self, scene_id, user_id):
        with self._lock:
            doc = self._docs.get((scene_id, user_id))
            if doc is None:
                return None
            return GuideRecord(int(doc["turn_count"]), doc["state_json"], doc["active"])

    def turns(self, scene_id, user_id, limit):
        with self._lock:
            docs = self._turns.get((scene_id, user_id), [])
            return [GuideTurn.from_doc(d) for d in docs[-limit:]] if limit > 0 else []

    def accept_turn(self, scene_id, user_id, client_msg_id, *, opening, daily_usd, ttl_s, now):
        with self._lock:
            doc = self._docs.get((scene_id, user_id))
            for d in self._turns.get((scene_id, user_id), []):
                if d["client_msg_id"] == client_msg_id:
                    return GuideAccept("replay", replay_turn=GuideTurn.from_doc(d))
            if opening and doc is not None and int(doc["turn_count"]) > 0:
                return GuideAccept("opened")
            spent = _spent_today(self._budgets.get(user_id), now)
            if spent >= daily_usd:
                return GuideAccept("rested", resets_at=next_utc_midnight(now))
            if doc is not None and _lease_live(doc["active"], now, ttl_s):
                return GuideAccept("busy")
            doc = self._doc(scene_id, user_id, now)
            doc["active"] = {"holder": client_msg_id, "started_at": now}
            doc["updated_at"] = now
            return GuideAccept("accepted", remaining_usd=daily_usd - spent)

    def take_lease(self, scene_id, user_id, holder, *, ttl_s, now):
        with self._lock:
            doc = self._docs.get((scene_id, user_id))
            if doc is not None and _lease_live(doc["active"], now, ttl_s):
                return False
            doc = self._doc(scene_id, user_id, now)
            doc["active"] = {"holder": holder, "started_at": now}
            return True

    def persist_turn(self, scene_id, user_id, turn, *, state_json, now):
        with self._lock:
            doc = self._doc(scene_id, user_id, now)
            stored = replace(turn, turn_index=int(doc["turn_count"]))
            self._turns[(scene_id, user_id)].append(stored.to_doc())
            doc["turn_count"] = int(doc["turn_count"]) + 1
            doc["state_json"] = state_json
            doc["updated_at"] = now
            if doc["active"] is not None and doc["active"].get("holder") == turn.client_msg_id:
                doc["active"] = None
            return stored

    def save_state(self, scene_id, user_id, holder, *, state_json, now):
        with self._lock:
            doc = self._docs.get((scene_id, user_id))
            if doc is None or doc["active"] is None or doc["active"].get("holder") != holder:
                return False
            doc["state_json"] = state_json
            doc["updated_at"] = now
            doc["active"] = None
            return True

    def release(self, scene_id, user_id, holder):
        with self._lock:
            doc = self._docs.get((scene_id, user_id))
            if doc is not None and doc["active"] is not None and doc["active"].get("holder") == holder:
                doc["active"] = None

    def spent_today(self, user_id, now):
        with self._lock:
            return _spent_today(self._budgets.get(user_id), now)

    def charge(self, user_id, usd, now):
        with self._lock:
            budget = self._budgets.get(user_id)
            today = utc_day(now)
            spent = _spent_today(budget, now) + max(0.0, float(usd))
            turns = (int(budget.get("turns", 0)) if budget and budget.get("day") == today else 0) + 1
            self._budgets[user_id] = {"user_id": user_id, "day": today, "spent_usd": spent,
                                      "turns": turns, "updated_at": now}
            return spent


# ---------------------------------------------------------------------------
# Firestore implementation (production)
# ---------------------------------------------------------------------------

class FirestoreGuideRepository(GuideRepository):
    """Firestore-backed store. Mirrors the in-memory semantics (which the unit tests
    pin) inside Firestore transactions; contention retries are the client library's."""

    COLLECTION = GUIDES_COLLECTION
    TURNS = GUIDE_TURNS_SUBCOLLECTION
    BUDGETS = GUIDE_BUDGETS_COLLECTION

    def __init__(self, project: str | None = None) -> None:
        from google.cloud import firestore as _fs  # deferred

        self._fs = _fs
        self._db = _fs.Client(project=project)

    def _ref(self, scene_id: str, user_id: str):
        return self._db.collection(self.COLLECTION).document(f"{scene_id}__{user_id}")

    def _budget_ref(self, user_id: str):
        return self._db.collection(self.BUDGETS).document(user_id)

    @staticmethod
    def _base(scene_id: str, user_id: str, now: datetime) -> dict:
        return {"scene_id": scene_id, "user_id": user_id, "created_at": now, "updated_at": now,
                "turn_count": 0, "active": None, "state_json": ""}

    def get(self, scene_id, user_id):
        snap = self._ref(scene_id, user_id).get()
        if not snap.exists:
            return None
        doc = snap.to_dict() or {}
        return GuideRecord(int(doc.get("turn_count", 0)), str(doc.get("state_json", "")),
                           doc.get("active"))

    def turns(self, scene_id, user_id, limit):
        if limit <= 0:
            return []
        snaps = (self._ref(scene_id, user_id).collection(self.TURNS)
                 .order_by("turn_index", direction=self._fs.Query.DESCENDING).limit(limit).get())
        out = [GuideTurn.from_doc(s.to_dict()) for s in snaps]
        out.reverse()
        return out

    def accept_turn(self, scene_id, user_id, client_msg_id, *, opening, daily_usd, ttl_s, now):
        from google.cloud.firestore_v1.base_query import FieldFilter  # deferred

        ref = self._ref(scene_id, user_id)
        budget_ref = self._budget_ref(user_id)
        dedupe = (ref.collection(self.TURNS)
                  .where(filter=FieldFilter("client_msg_id", "==", client_msg_id)).limit(1))

        @self._fs.transactional
        def _txn(txn) -> GuideAccept:
            snap = ref.get(transaction=txn)
            doc = snap.to_dict() if snap.exists else None
            duplicates = list(dedupe.get(transaction=txn))
            budget_snap = budget_ref.get(transaction=txn)
            if duplicates:
                return GuideAccept("replay", replay_turn=GuideTurn.from_doc(duplicates[0].to_dict()))
            if opening and doc is not None and int(doc.get("turn_count", 0)) > 0:
                return GuideAccept("opened")
            spent = _spent_today(budget_snap.to_dict() if budget_snap.exists else None, now)
            if spent >= daily_usd:
                return GuideAccept("rested", resets_at=next_utc_midnight(now))
            if doc is not None and _lease_live(doc.get("active"), now, ttl_s):
                return GuideAccept("busy")
            lease = {"holder": client_msg_id, "started_at": now}
            if doc is None:
                txn.set(ref, {**self._base(scene_id, user_id, now), "active": lease})
            else:
                txn.update(ref, {"active": lease, "updated_at": now})
            return GuideAccept("accepted", remaining_usd=daily_usd - spent)

        return _txn(self._db.transaction())

    def take_lease(self, scene_id, user_id, holder, *, ttl_s, now):
        ref = self._ref(scene_id, user_id)

        @self._fs.transactional
        def _txn(txn) -> bool:
            snap = ref.get(transaction=txn)
            doc = snap.to_dict() if snap.exists else None
            if doc is not None and _lease_live(doc.get("active"), now, ttl_s):
                return False
            lease = {"holder": holder, "started_at": now}
            if doc is None:
                txn.set(ref, {**self._base(scene_id, user_id, now), "active": lease})
            else:
                txn.update(ref, {"active": lease})
            return True

        return _txn(self._db.transaction())

    def persist_turn(self, scene_id, user_id, turn, *, state_json, now):
        ref = self._ref(scene_id, user_id)

        @self._fs.transactional
        def _txn(txn) -> GuideTurn:
            snap = ref.get(transaction=txn)
            doc = snap.to_dict() if snap.exists else self._base(scene_id, user_id, now)
            stored = replace(turn, turn_index=int(doc.get("turn_count", 0)))
            txn.set(ref.collection(self.TURNS).document(f"{stored.turn_index:06d}"), stored.to_doc())
            doc["turn_count"] = stored.turn_index + 1
            doc["state_json"] = state_json
            doc["updated_at"] = now
            active = doc.get("active")
            if active is not None and active.get("holder") == turn.client_msg_id:
                doc["active"] = None
            txn.set(ref, doc)
            return stored

        return _txn(self._db.transaction())

    def save_state(self, scene_id, user_id, holder, *, state_json, now):
        ref = self._ref(scene_id, user_id)

        @self._fs.transactional
        def _txn(txn) -> bool:
            snap = ref.get(transaction=txn)
            active = (snap.to_dict() or {}).get("active") if snap.exists else None
            if active is None or active.get("holder") != holder:
                return False
            txn.update(ref, {"state_json": state_json, "updated_at": now, "active": None})
            return True

        return _txn(self._db.transaction())

    def release(self, scene_id, user_id, holder):
        ref = self._ref(scene_id, user_id)

        @self._fs.transactional
        def _txn(txn) -> None:
            snap = ref.get(transaction=txn)
            if not snap.exists:
                return
            active = (snap.to_dict() or {}).get("active")
            if active is not None and active.get("holder") == holder:
                txn.update(ref, {"active": None})

        _txn(self._db.transaction())

    def spent_today(self, user_id, now):
        snap = self._budget_ref(user_id).get()
        return _spent_today(snap.to_dict() if snap.exists else None, now)

    def charge(self, user_id, usd, now):
        ref = self._budget_ref(user_id)

        @self._fs.transactional
        def _txn(txn) -> float:
            snap = ref.get(transaction=txn)
            budget = snap.to_dict() if snap.exists else None
            today = utc_day(now)
            spent = _spent_today(budget, now) + max(0.0, float(usd))
            turns = (int(budget.get("turns", 0)) if budget and budget.get("day") == today else 0) + 1
            txn.set(ref, {"user_id": user_id, "day": today, "spent_usd": spent, "turns": turns,
                          "updated_at": now})
            return spent

        return _txn(self._db.transaction())
