"""The room guide inside api-public: one person's conversation about one room, rebuilt
for each request from what is kept (decision 0376).

The guide itself lives in packages/room-guide and is not changed here: its
`run_turn(session, text, emit)` plays one turn against a session object. The local
harness keeps that session in memory for one room; here it is rebuilt per request
from Firestore (guide_repo.py) and from the files the pipeline wrote beside the
room's manifest:

  scene.json   the diorama scene (`diorama.scene/1`): the room the guide reasons about
  solids.json  part boxes per piece, when the pipeline writes one; otherwise each
               piece collides as its whole box. Never taken from a browser.
  needs.json   this room's needs from the rules pass: written the first time a turn
               needs them, read every time after. The gateway's own file cache does
               not outlive a Cloud Run request, so this file is the once-per-scene.

`GuideSession` is the harness's session with its file handling taken out: it has
every attribute `run_turn` uses (room, needs, engine, messages, arrangement, history,
told, changes, proposals, gateway, model) and reuses the harness's offer, show, undo
and motion planning, so a turn here is the same code as a turn there.

`GuideState` is what a conversation keeps between requests: the arrangement history
(so putting something back is one step), the proposals by id with the arrangement
each was offered against, what the person told the guide and the needs it changed,
and the words for what is on their screen. Every number goes through JSON, which
gives a float back exactly, so a reloaded room is the room that was saved and a
replayed request is byte for byte the one that was cached.

Read by: public_server.py (the guide routes); tests/test_guide_session.py and
tests/test_guide_routes.py.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from guide_repo import GuideRepository, GuideTurn
from thegoodguest_room_guide.analyzer import Finding
from thegoodguest_room_guide.engine import Engine, Move, Proposal
from thegoodguest_room_guide.gateway import BudgetExceeded, Gateway, ModelNotAllowed
from thegoodguest_room_guide.guide import run_turn
from thegoodguest_room_guide.harness import Session as HarnessSession
from thegoodguest_room_guide.model import Arrangement, Pose, Room, room_from_scene
from thegoodguest_room_guide.needs import (
    Bond,
    Need,
    PieceNeeds,
    Preference,
    Question,
    RoomNeeds,
    default_needs,
)
from thegoodguest_room_guide.prompts import GUIDE_VERSION, OPENING, RULES_VERSION
from thegoodguest_room_guide.rules_pass import run_rules_pass

logger = logging.getLogger(__name__)

NEEDS_SCHEMA = "room-guide.needs/1"
STATE_VERSION = 1
MAX_PROPOSALS = 60          # kept per conversation; the oldest unoffered go first
MAX_HISTORY = 60            # arrangements kept for putting back, the scanned room included


# ---------------------------------------------------------------- JSON

def _jsonable(v):
    """numpy scalars and tuples, for json.dumps."""
    if hasattr(v, "item"):
        return v.item()
    if isinstance(v, (tuple, set)):
        return list(v)
    raise TypeError(f"not JSON: {type(v).__name__}")


def dumps(v) -> str:
    return json.dumps(v, ensure_ascii=False, default=_jsonable)


# ---------------------------------------------------------------- the room's files

@dataclass(frozen=True)
class SceneInputs:
    """A room's files as the pipeline wrote them, and the room they make."""

    scene_dir: str        # gs://<bucket>/scenes/<id>, the manifest's folder
    scene_sha: str        # sha256 of scene.json: needs.json is kept against it
    room: Room
    solids_from: str      # "pipeline" or "boxes"


def scene_dir_of(result_uri: str) -> str:
    return result_uri.rsplit("/", 1)[0]


def load_scene(fetch_optional: Callable[[str], bytes | None], scene_dir: str) -> SceneInputs | None:
    """The room from scene.json and, when present, solids.json. None when the scene has
    no scene.json. A solids file that can't be read leaves the pieces as whole boxes;
    a scene.json that isn't a diorama scene raises ValueError."""
    raw = fetch_optional(f"{scene_dir}/scene.json")
    if raw is None:
        return None
    scene = json.loads(raw)
    solids = None
    try:
        solids_raw = fetch_optional(f"{scene_dir}/solids.json")
        if solids_raw is not None:
            doc = json.loads(solids_raw)
            solids = doc if isinstance(doc, dict) else None
    except Exception as exc:  # optional: whole boxes are the honest fallback
        logger.warning("guide: solids.json unreadable in %s, using whole boxes: %s", scene_dir, exc)
    try:
        room = room_from_scene(scene, solids)
    except (TypeError, ValueError, IndexError) as exc:
        if solids is None:
            raise
        logger.warning("guide: solids.json does not fit %s, using whole boxes: %s", scene_dir, exc)
        room, solids = room_from_scene(scene, None), None
    return SceneInputs(scene_dir, hashlib.sha256(raw).hexdigest(), room,
                       "pipeline" if solids else "boxes")


# ---------------------------------------------------------------- needs

def needs_to_doc(needs: RoomNeeds) -> dict:
    return {
        "origin": needs.origin,
        "pieces": {pid: {"moves": p.moves, "why": p.why, "needs": [asdict(n) for n in p.needs],
                         "bonds": [asdict(b) for b in p.bonds]} for pid, p in needs.pieces.items()},
        "preferences": [asdict(p) for p in needs.preferences],
        "questions": [asdict(q) for q in needs.questions],
    }


def needs_from_doc(doc: dict) -> RoomNeeds:
    pieces = {pid: PieceNeeds(e["moves"], e["why"], tuple(Need(**n) for n in e.get("needs", [])),
                              tuple(Bond(**b) for b in e.get("bonds", [])))
              for pid, e in doc["pieces"].items()}
    return RoomNeeds(pieces, tuple(Preference(**p) for p in doc.get("preferences", [])),
                     tuple(Question(**q) for q in doc.get("questions", [])), doc.get("origin", "rules pass"))


def read_needs(fetch_optional, inputs: SceneInputs) -> RoomNeeds | None:
    """needs.json, if it was written for this scene.json by this rules prompt."""
    raw = fetch_optional(f"{inputs.scene_dir}/needs.json")
    if raw is None:
        return None
    doc = json.loads(raw)
    if (doc.get("schema") != NEEDS_SCHEMA or doc.get("rules_version") != RULES_VERSION
            or doc.get("scene_sha256") != inputs.scene_sha):
        return None
    needs = needs_from_doc(doc["needs"])
    if set(needs.pieces) - set(inputs.room.pieces):
        return None
    return needs


def write_needs(put, inputs: SceneInputs, needs: RoomNeeds, model: str, now: datetime) -> None:
    doc = {"schema": NEEDS_SCHEMA, "rules_version": RULES_VERSION, "scene_sha256": inputs.scene_sha,
           "model": model, "made_at": now.isoformat(), "needs": needs_to_doc(needs)}
    put(f"{inputs.scene_dir}/needs.json", dumps(doc).encode(), "application/json")


def ensure_needs(fetch_optional, put, inputs: SceneInputs, gateway: Gateway, model: str,
                 now: datetime) -> RoomNeeds:
    """This room's needs: needs.json when it fits, else the rules pass, kept for next
    time. The rules pass raising (the model unreachable, the budget spent) is the
    caller's to handle; a failure to keep its answer is only logged."""
    try:
        cached = read_needs(fetch_optional, inputs)
    except Exception as exc:
        logger.warning("guide: needs.json unreadable in %s: %s", inputs.scene_dir, exc)
        cached = None
    if cached is not None:
        return cached
    needs = run_rules_pass(inputs.room, gateway, model=model)
    try:
        write_needs(put, inputs, needs, model, now)
    except Exception as exc:
        logger.warning("guide: needs.json not kept for %s: %s", inputs.scene_dir, exc)
    return needs


# ---------------------------------------------------------------- what a conversation keeps

def _pose_doc(p: Pose) -> list[float]:
    return [float(p.x), float(p.y), float(p.z), float(p.yaw)]


def _pose(v) -> Pose:
    return Pose(float(v[0]), float(v[1]), float(v[2]), float(v[3]))


def arrangement_doc(a: Arrangement) -> dict:
    return {pid: _pose_doc(p) for pid, p in a.items()}


def arrangement_from(doc: dict) -> Arrangement:
    return {pid: _pose(v) for pid, v in doc.items()}


def arrangement_key(a: Arrangement) -> str:
    """Which arrangement this is, to the millimetre: the same key means the same room."""
    rows = sorted((pid, round(float(p.x), 3), round(float(p.y), 3), round(float(p.z), 3),
                   round(math.remainder(float(p.yaw), 2 * math.pi), 3)) for pid, p in a.items())
    return hashlib.sha1(repr(rows).encode()).hexdigest()[:16]


def _finding_doc(f: Finding) -> dict:
    return {"key": f.key, "kind": f.kind, "severity": int(f.severity), "pieces": list(f.pieces),
            "text": f.text, "standard": f.standard, "numbers": dict(f.numbers)}


def _finding(d: dict) -> Finding:
    return Finding(d["key"], d["kind"], int(d["severity"]), tuple(d.get("pieces") or ()), d["text"],
                   d.get("standard", ""), dict(d.get("numbers") or {}))


def proposal_doc(p: Proposal) -> dict:
    return {"id": p.id,
            "moves": [{"piece": m.piece, "frm": _pose_doc(m.frm), "to": _pose_doc(m.to), "role": m.role}
                      for m in p.moves],
            "arrangement": arrangement_doc(p.arrangement),
            "score_before": float(p.score_before), "score_after": float(p.score_after),
            "words": list(p.words), "fixes": [_finding_doc(f) for f in p.fixes],
            "leaves": [_finding_doc(f) for f in p.leaves], "adds": [_finding_doc(f) for f in p.adds],
            "effort": p.effort, "goal": p.goal}


def proposal_from(d: dict) -> Proposal:
    return Proposal(d["id"], [Move(m["piece"], _pose(m["frm"]), _pose(m["to"]), m["role"]) for m in d["moves"]],
                    arrangement_from(d["arrangement"]), float(d["score_before"]), float(d["score_after"]),
                    list(d["words"]), [_finding(f) for f in d["fixes"]], [_finding(f) for f in d["leaves"]],
                    [_finding(f) for f in d["adds"]], d["effort"], d["goal"])


def card_status(pid: str, arrangement: Arrangement, proposals: dict[str, Proposal],
                bases: dict[str, str]) -> str:
    """A card's button: "ready" when the room is as it was when the card was offered,
    "shown" while its change is on screen, "stale" once the room has moved on, "gone"
    when the proposal is no longer kept."""
    p = proposals.get(pid)
    if p is None:
        return "gone"
    now = arrangement_key(arrangement)
    if now == arrangement_key(p.arrangement):
        return "shown"
    return "ready" if bases.get(pid) == now else "stale"


@dataclass
class GuideState:
    """Everything about one conversation's room that outlives a request."""

    history: list[Arrangement] = field(default_factory=lambda: [{}])
    marks: list[int] = field(default_factory=list)      # lines each step added to `changes`
    told: list[str] = field(default_factory=list)
    changes: list[str] = field(default_factory=list)
    needs: RoomNeeds | None = None                      # set once the person's words change them
    proposals: dict[str, Proposal] = field(default_factory=dict)
    bases: dict[str, str] = field(default_factory=dict)  # proposal id -> arrangement it was offered on
    offered: list[str] = field(default_factory=list)     # ids shown to the person as cards

    @property
    def arrangement(self) -> Arrangement:
        return self.history[-1]

    def view(self) -> dict:
        """What the panel needs to draw the room as it stands."""
        return {"poses": {pid: {"x": float(p.x), "y": float(p.y), "z": float(p.z), "yaw": float(p.yaw)}
                          for pid, p in self.arrangement.items()},
                "can_undo": len(self.history) > 1,
                "cards": {pid: card_status(pid, self.arrangement, self.proposals, self.bases)
                          for pid in self.offered}}

    def to_json(self) -> str:
        return dumps({"v": STATE_VERSION,
                      "history": [arrangement_doc(a) for a in self.history],
                      "marks": self.marks, "told": self.told, "changes": self.changes,
                      "needs": needs_to_doc(self.needs) if self.needs is not None else None,
                      "proposals": {pid: proposal_doc(p) for pid, p in self.proposals.items()},
                      "bases": self.bases, "offered": self.offered})

    @classmethod
    def from_json(cls, text: str) -> GuideState:
        if not text:
            return cls()
        d = json.loads(text)
        return cls(history=[arrangement_from(a) for a in d.get("history") or [{}]] or [{}],
                   marks=[int(m) for m in d.get("marks") or []],
                   told=list(d.get("told") or []), changes=list(d.get("changes") or []),
                   needs=needs_from_doc(d["needs"]) if d.get("needs") else None,
                   proposals={pid: proposal_from(p) for pid, p in (d.get("proposals") or {}).items()},
                   bases=dict(d.get("bases") or {}), offered=list(d.get("offered") or []))


# ---------------------------------------------------------------- the session run_turn plays against

class CardRefused(Exception):
    """A "Show me" or "Put it back" that can't be done: `code` is the client's word for why."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class GuideSession(HarnessSession):
    """The harness's session, built from what is kept instead of from files.

    It never reads or writes a file and never runs the rules pass: the room, its needs
    and the kept state arrive from the caller.
    """

    def __init__(self, room: Room, needs: RoomNeeds, state: GuideState, *, model: str,
                 gateway: Gateway | None = None, messages: list[dict] | None = None):
        # Not HarnessSession.__init__: that one reads a scene from disk and runs the rules
        # pass itself. Every attribute it sets that run_turn and its tools read is set here.
        self.model = model
        self.room = room
        self.base_needs = needs
        self.needs = state.needs if state.needs is not None else needs
        self.gateway = gateway
        self.messages = list(messages or [])
        self.told = list(state.told)
        self.changes = list(state.changes)
        self.history = [dict(a) for a in state.history] or [{}]
        self.marks = list(state.marks)
        self.proposals = dict(state.proposals)
        self.bases = dict(state.bases)
        self.offered = list(state.offered)
        self.notes = []
        self.engine = Engine(room, self.needs, self.arrangement)

    def load(self) -> None:
        raise NotImplementedError("a product session is built from what Firestore keeps")

    def take_solids(self, solids: dict) -> dict:
        raise NotImplementedError("part shapes come from the pipeline's solids.json, never a browser")

    # ------------------------------------------------------------ the harness's moves, kept track of
    def offer(self, proposals: list[Proposal]) -> list[dict]:
        key = arrangement_key(self.arrangement)
        out = super().offer(proposals)
        for item in out:
            self.bases[item["id"]] = key
        return out

    def show(self, proposal_id: str) -> dict:
        before = len(self.history)
        result = super().show(proposal_id)
        if len(self.history) > before:
            self.marks.append(len(self.proposals[proposal_id].words))
        return result

    def undo(self) -> dict:
        before = len(self.history)
        result = super().undo()
        if len(self.history) < before and self.marks:
            self.marks.pop()
        return result

    def kept(self) -> GuideState:
        return GuideState(list(self.history), list(self.marks), list(self.told), list(self.changes),
                          self.needs if self.needs != self.base_needs else None,
                          dict(self.proposals), dict(self.bases), list(self.offered))

    def state(self) -> dict:
        return self.kept().view()

    # ------------------------------------------------------------ the panel's two buttons
    def show_card(self, proposal_id: str) -> dict:
        """The person pressed "Show me": play the card's change, and tell the guide it is
        on their screen, as its own show does."""
        if proposal_id not in self.offered or proposal_id not in self.proposals:
            raise CardRefused("no_such_proposal")
        status = card_status(proposal_id, self.arrangement, self.proposals, self.bases)
        if status != "ready":
            raise CardRefused("proposal_stale" if status == "stale" else "proposal_shown")
        p = self.proposals[proposal_id]
        result = self.show(proposal_id)
        self.changes.extend(p.words)
        return result

    def put_back(self) -> dict:
        """The person pressed "Put it back": one step back, and its words off the screen."""
        if len(self.history) < 2:
            raise CardRefused("nothing_to_undo")
        lines = self.marks[-1] if self.marks else 1
        result = self.undo()
        del self.changes[max(0, len(self.changes) - lines):]
        return result


def trimmed(state: GuideState) -> GuideState:
    """The state with its lists held to their ceilings, for keeping."""
    history, marks = state.history, state.marks
    if len(history) > MAX_HISTORY:
        history = [history[0], *history[-(MAX_HISTORY - 1):]]
        marks = marks[-(MAX_HISTORY - 1):]
    proposals = dict(state.proposals)
    for pid in list(proposals):
        if len(proposals) <= MAX_PROPOSALS:
            break
        if pid not in state.offered:
            del proposals[pid]
    while len(proposals) > MAX_PROPOSALS:
        del proposals[next(iter(proposals))]
    return GuideState(history, marks, state.told, state.changes, state.needs, proposals,
                      {k: v for k, v in state.bases.items() if k in proposals},
                      [pid for pid in state.offered if pid in proposals])


# ---------------------------------------------------------------- what the panel shows of a turn

def fold_events(events: list[tuple[str, dict]]) -> list[dict]:
    """A turn as the panel shows it: the guide's words joined into paragraphs (a move,
    a card or a note between them starts a new one), with cards and notes in order."""
    items: list[dict] = []
    prev = None
    for kind, data in events:
        if kind == "delta":
            if prev == "delta" and items and items[-1]["kind"] == "say":
                items[-1]["text"] += data["text"]
            else:
                items.append({"kind": "say", "text": data["text"]})
        elif kind == "card":
            items.append({"kind": "card", "card": {k: v for k, v in data.items() if k != "status"}})
        elif kind == "note":
            items.append({"kind": "note", "text": data["text"]})
        prev = kind
    return items


def transcript(turns: list[GuideTurn], state: GuideState) -> list[dict]:
    """Every kept turn as the panel shows it, each card with its button as of now."""
    out = []
    for t in turns:
        items = json.loads(t.events_json)
        for it in items:
            if it.get("kind") == "card":
                it["card"]["status"] = card_status(it["card"]["id"], state.arrangement, state.proposals,
                                                   state.bases)
        out.append({"turn_index": t.turn_index, "client_msg_id": t.client_msg_id, "opening": t.opening,
                    "person": None if t.opening else t.user_text, "items": items})
    return out


# ---------------------------------------------------------------- one turn

class TurnCancelled(Exception):
    """The request gave up on this turn; raised at the turn's next event."""


@dataclass
class TurnOutcome:
    turn: GuideTurn | None = None
    state: dict | None = None
    error: str | None = None
    cost_usd: float = 0.0
    calls: int = 0


def _error_code(exc: BaseException) -> str:
    """Our word for why a turn failed. Upstream details stay in the logs."""
    try:
        import anthropic  # deferred: tests never reach a live call
    except ImportError:  # pragma: no cover
        anthropic = None
    if isinstance(exc, BudgetExceeded):
        return "budget_exhausted"
    if isinstance(exc, ModelNotAllowed):
        return "model_not_allowed"
    if anthropic is not None:
        if isinstance(exc, anthropic.APIStatusError):
            return "model_unavailable" if exc.status_code == 429 or exc.status_code >= 500 else "model_error"
        if isinstance(exc, (anthropic.APIConnectionError, anthropic.AnthropicError)):
            return "model_unavailable"
    return "turn_failed"


def run_guide_turn(*, repo: GuideRepository, scene_id: str, user_id: str, client_msg_id: str,
                   text: str, opening: bool, inputs: SceneInputs, fetch_optional, put,
                   make_gateway: Callable[[Path], Gateway], spend_of: Callable[[Gateway], float],
                   model: str, history_turns: int, emit: Callable[[str, dict], None], cancel,
                   created_at: datetime, now: Callable[[], datetime] | None = None) -> TurnOutcome:
    """One turn, start to finish, on the calling thread: the kept conversation is read,
    the room's needs found (or made), `run_turn` played with its events relayed through
    `emit`, and the completed turn kept. Whatever the turn cost is charged to the
    person's day, whether or not it completed; a turn that did not complete releases
    the lease it was accepted under."""
    now = now or (lambda: datetime.now(tz=UTC))
    work = Path(tempfile.mkdtemp(prefix="guide-"))
    gateway = make_gateway(work)
    outcome = TurnOutcome()
    persisted = False
    try:
        record = repo.get(scene_id, user_id)
        state = GuideState.from_json(record.state_json if record else "")
        turns = repo.turns(scene_id, user_id, history_turns)
        messages = [m for t in turns for m in json.loads(t.messages_json)]
        try:
            needs = ensure_needs(fetch_optional, put, inputs, gateway, model, now())
        except (BudgetExceeded, ModelNotAllowed):
            raise
        except Exception:
            logger.exception("guide: rules pass failed for scene %s; laws only this turn", scene_id)
            needs = default_needs(inputs.room)
        session = GuideSession(inputs.room, needs, state, model=model, gateway=gateway, messages=messages)
        start = len(session.messages)
        recorded: list[tuple[str, dict]] = []
        flags: list[str] = []

        def relay(kind: str, data: dict) -> None:
            if cancel.is_set():
                raise TurnCancelled()
            if kind == "done":           # the guide's own ending: ours follows the save
                flags.extend(data.get("flags") or [])
                return
            if kind == "card":
                if data["id"] not in session.offered:
                    session.offered.append(data["id"])
                data = {**data, "status": card_status(data["id"], session.arrangement,
                                                      session.proposals, session.bases)}
            recorded.append((kind, data if kind in ("delta", "card", "note") else {}))
            emit(kind, data)

        reply = run_turn(session, OPENING if opening else text, relay)
        if cancel.is_set():
            raise TurnCancelled()
        outcome.cost_usd = spend_of(gateway)
        turn = GuideTurn(turn_index=-1, client_msg_id=client_msg_id, opening=opening,
                         user_text="" if opening else text,
                         messages_json=dumps(session.messages[start:]),
                         events_json=dumps(fold_events(recorded)), reply=reply, flags=flags,
                         cost_usd=outcome.cost_usd, model=model, prompt_version=GUIDE_VERSION,
                         created_at=created_at, completed_at=now())
        outcome.turn = repo.persist_turn(scene_id, user_id, turn, state_json=trimmed(session.kept()).to_json(),
                                         now=now())
        persisted = True
        outcome.state = session.state()
    except TurnCancelled:
        outcome.error = "model_timeout"
    except Exception as exc:
        outcome.error = _error_code(exc)
        if outcome.error == "turn_failed":
            logger.exception("guide: turn failed for scene %s", scene_id)
        else:
            logger.warning("guide: turn for scene %s ended with %s: %s", scene_id, outcome.error, exc)
    finally:
        try:
            outcome.cost_usd = spend_of(gateway)
            outcome.calls = int(gateway.report().get("calls", 0))
            if outcome.cost_usd > 0:
                repo.charge(user_id, outcome.cost_usd, now())
        except Exception:
            logger.exception("guide: could not charge the turn's cost for scene %s", scene_id)
        if not persisted:
            try:
                repo.release(scene_id, user_id, client_msg_id)
            except Exception:
                logger.exception("guide: lease release failed for scene %s", scene_id)
        shutil.rmtree(work, ignore_errors=True)
    return outcome


def run_guide_button(*, repo: GuideRepository, scene_id: str, user_id: str, inputs: SceneInputs,
                     fetch_optional, model: str, press: Callable[[GuideSession], dict]) -> tuple[dict, str]:
    """A button press against the kept conversation: "Show me" or "Put it back". Never
    calls Claude and never runs the rules pass. Returns what to send back and the state
    to keep."""
    record = repo.get(scene_id, user_id)
    state = GuideState.from_json(record.state_json if record else "")
    try:
        needs = read_needs(fetch_optional, inputs)
    except Exception as exc:
        logger.warning("guide: needs.json unreadable for scene %s: %s", scene_id, exc)
        needs = None
    session = GuideSession(inputs.room, needs or default_needs(inputs.room), state, model=model)
    result = press(session)
    return result, trimmed(session.kept()).to_json()
