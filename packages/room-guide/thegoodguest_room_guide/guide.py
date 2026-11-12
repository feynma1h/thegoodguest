"""The guide: Claude as the guest, with hands that reach the room only through the engine.

One turn: the person's words go in; the guide reads its charter (prompts.GUIDE_SYSTEM)
and THE ROOM (brief.py), may call its tools, and its words stream out as it writes.
Each tool is answered by the room:

  look_for_changes  the engine's search toward a goal: checked proposals, or why none
  move              one change the person asked for: a checked proposal, or a refusal
  offer             puts a proposal in front of the person as a "Show me" card
  show              plays a proposal on their screen now (put_back undoes it)
  put_back          one step back
  measure           a gap between two pieces, in words the guide may quote
  point_at          lights up pieces, or a finding's space, on their screen
  note              records what the person said that the scan can't know, as a need

Every number the guide may say is in THE ROOM or a tool result; every move it can
make is a proposal the engine solved and the motion planner checked. After each
turn the reply is checked for numbers that came from nowhere (observe-only: logged,
never blocking).

Events to the panel (server-sent): delta, card, play, focus, note, done, error.

Read by: harness.py (mount adds the endpoints).
"""
import json
import logging
import queue
import re
import threading

from .brief import brief, plan_image
from .engine import Refusal
from .gateway import BudgetExceeded, ModelNotAllowed, OracleNeeded, TurnRequest
from .motion import NoPath
from .needs import NEED_TYPES, SIDES, Need, with_change, zone_box, zones
from .prompts import GUIDE_SYSTEM, GUIDE_VERSION, OPENING

log = logging.getLogger("room-guide")

MAX_ROUNDS = 5
MODEL = "claude-opus-5-5"
EFFORT = "medium"


def _tool(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {"name": name, "description": description, "strict": True,
            "input_schema": {"type": "object", "additionalProperties": False,
                             "properties": properties, "required": required}}


TOOLS = [
    _tool("look_for_changes",
          "Search the room for better arrangements. goal: general (the room as a whole), fix (one finding, "
          "by its key from THE ROOM), light (daylight for one piece's task), open_floor. Returns up to "
          "three proposals the room has checked, each with an id, the words for what moves, what it "
          "fixes, what it brings, and the effort; or why there is none.",
          {"goal": {"enum": ["general", "fix", "light", "open_floor"]},
           "finding": {"type": "string", "description": "a finding key, for goal fix"},
           "piece": {"type": "string", "description": "a piece id, for goal light"},
           "keep_still": {"type": "array", "items": {"type": "string"}, "description": "piece ids not to move"}},
          ["goal"]),
    _tool("move",
          "Solve one change the person asked for. how: wall (its back to a wall id), under (centred under an "
          "opening, by its piece id), beside (beside a piece id), at (set at a piece id's front), facing (turned "
          "to face a piece id), turn (left, right or around), along (slid along its own wall). Returns a "
          "checked proposal, or a refusal with its reason.",
          {"piece": {"type": "string"}, "how": {"enum": ["wall", "under", "beside", "at", "facing", "turn", "along"]},
           "target": {"type": "string", "description": "a wall id, piece id, or for turn: left, right, around"}},
          ["piece", "how"]),
    _tool("offer", "Put a proposal in front of the person as a 'Show me' card, without moving anything.",
          {"proposal": {"type": "string"}}, ["proposal"]),
    _tool("show", "Play a proposal on the person's screen now. Use when they asked for it or said yes.",
          {"proposal": {"type": "string"}}, ["proposal"]),
    _tool("put_back", "Undo the last change on the person's screen.", {}, []),
    _tool("measure", "The gap between two pieces as they stand now, in words you may quote.",
          {"a": {"type": "string"}, "b": {"type": "string"}}, ["a", "b"]),
    _tool("point_at", "Light up pieces on the person's screen, or the space a finding is about (its key).",
          {"pieces": {"type": "array", "items": {"type": "string"}}, "finding": {"type": "string"}}, []),
    _tool("note",
          "Record something the person told you that the scan can't know, as a change to one piece's needs: "
          "require adds a need (or makes it hard), relax drops it. fact is their words, short.",
          {"fact": {"type": "string"}, "piece": {"type": "string"}, "change": {"enum": ["require", "relax"]},
           "need": {"enum": list(NEED_TYPES)}, "side": {"enum": list(SIDES)},
           "strength": {"enum": ["hard", "soft"]}},
          ["fact", "piece", "change", "need"]),
]


# A card or a move with no words beside it reaches the person as a silent
# change, so the room asks for the words. A card's words start from the problem:
# "I've put up a card" alone leaves the person asking what for.
SAY_AFTER = {
    "offer": "now tell them what you found, in the room's words, and what this would change",
    "show": "now tell them what changed on their screen and what it fixed",
    "put_back": "now tell them it is back as it was",
    "note": "now tell them what you noted and what it changes",
}


class Turn:
    """One turn's tool calls against the harness session, with events for the panel."""

    def __init__(self, session, emit):
        self.s = session
        self.emit = emit
        self.tool_texts: list[str] = []

    def call(self, name: str, args: dict) -> str:
        try:
            out = getattr(self, f"t_{name}")(**args)
        except Refusal as r:
            out = {"refused": r.reason}
        except NoPath as e:
            out = {"refused": f"there's no clear way to move it there ({e.piece})"}
        except (KeyError, TypeError, ValueError) as e:
            out = {"error": f"{type(e).__name__}: {e}"}
        if name in SAY_AFTER and isinstance(out, dict) and "error" not in out and "refused" not in out:
            out["then"] = SAY_AFTER[name]
        text = json.dumps(out, ensure_ascii=False)
        self.tool_texts.append(text)
        return text

    def _proposals(self, props) -> list[dict]:
        return self.s.offer(props)

    def _finding_key(self, finding: str) -> str | None:
        """The finding meant: its exact key, else the most serious one naming that piece or need."""
        keys = [f.key for f in self.s.engine.current_findings if f.kind not in ("good", "question")]
        if finding in keys:
            return finding
        named = [k for k in keys if finding in k.split(":") or k.endswith(finding)]
        return named[0] if named else None

    def t_look_for_changes(self, goal: str, finding: str | None = None, piece: str | None = None,
                           keep_still: list[str] | None = None):
        key = {"general": "general", "open_floor": "open_floor", "fix": "general",
               "light": f"light:{piece}" if piece else "general"}[goal]
        if goal == "fix" and finding:
            found = self._finding_key(finding)
            if found is None:
                return {"proposals": [], "why": f"there is no finding {finding!r} in the room now; "
                                               "use a key from WHAT THE ROOM SHOWS"}
            # A daylight or open-floor finding is a preference: its own search scores it.
            key = ("light:" + found.split(":", 2)[2] if found.startswith("pref:task_light:")
                   else "open_floor" if found == "pref:open_floor" else f"fix:{found}")
        self.emit("note", {"text": "Looking at every place each piece could go…"})
        props = self._proposals(self.s.engine.explore(key, locked=keep_still or []))
        if not props:
            return {"proposals": [], "why": self.s.engine.why_nothing()}
        return {"proposals": props}

    def t_move(self, piece: str, how: str, target: str | None = None):
        kwargs = {"turn" if how == "turn" else how: target or True}
        if how == "along":
            kwargs = {"along": True}
        props = self._proposals([self.s.engine.place(piece, **kwargs)])
        if not props:
            return {"refused": "there's no clear way to move it there"}
        return {"proposal": props[0]}

    def t_offer(self, proposal: str):
        p = self.s.proposals[proposal]
        self.emit("card", self.s.proposal_json(p))
        return {"offered": proposal}

    def t_show(self, proposal: str):
        p = self.s.proposals[proposal]
        result = self.s.show(proposal)
        self.s.changes.extend(p.words)
        self.emit("play", result)
        # What changed, as the engine judged it, not a list for the guide to diff.
        return {"shown": p.words, "fixed": [f.text for f in p.fixes],
                "still": [f.text for f in p.leaves if f.kind == "problem"],
                "brings": [f.text for f in p.adds]}

    def t_put_back(self):
        if len(self.s.history) < 2:
            return {"refused": "nothing has been moved yet"}
        result = self.s.undo()
        if self.s.changes:
            self.s.changes.pop()
        self.emit("play", result)
        return {"put_back": True}

    def t_measure(self, a: str, b: str):
        return {"said": self.s.engine.measure(a, b)}

    def t_point_at(self, pieces: list[str] | None = None, finding: str | None = None):
        focus = {"pieces": [p for p in (pieces or []) if p in self.s.room.pieces], "zones": []}
        if finding:
            parts = finding.split(":")
            if parts[0] == "zone" and len(parts) == 4:
                z = next((z for z in zones(self.s.room, self.s.needs) if (z.piece, z.need, z.side) == tuple(parts[1:])), None)
                if z:
                    pose = self.s.engine.current.poses[z.piece]
                    b = zone_box(self.s.room.pieces[z.piece], z, pose, max(z.comfortable, z.hard))
                    focus["zones"].append({"x": b.x, "z": b.z, "hx": b.hx, "hz": b.hz, "yaw": b.yaw})
            if len(parts) > 1 and parts[1] in self.s.room.pieces:
                focus["pieces"].append(parts[1])
        self.emit("focus", focus)
        return {"pointed": True}

    def t_note(self, fact: str, piece: str, change: str, need: str, side: str | None = None,
               strength: str | None = None):
        if piece not in self.s.room.pieces:
            return {"error": f"no piece {piece}"}
        if change == "relax":
            self.s.needs = with_change(self.s.needs, piece, drop=need, side=side)
        else:
            self.s.needs = with_change(self.s.needs, piece, add=Need(
                need, side or "front", strength or "hard", fact[:200], source="person",
                posture={"use": "standing", "get_in": "lying", "see": "standing"}.get(need)))
        self.s.told.append(fact[:200])
        self.s.rebuild()
        return {"noted": fact[:200]}


_NUMBER = re.compile(r"\d+(?:\.\d+)?\s*(?:m|cm|mm|metres?|meters?)\b")


def foreign_numbers(reply: str, allowed: list[str]) -> list[str]:
    """Measurements in the reply that appear in none of the allowed texts."""
    pool = " ".join(allowed)
    return [n for n in _NUMBER.findall(reply) if n not in pool]


def run_turn(session, text: str, emit) -> str:
    """One turn of the conversation. Returns the guide's reply; emits events as it goes."""
    first = not session.messages
    start = len(session.messages)
    try:
        return _turn(session, text, emit, session.room, first)
    except BaseException:
        # A turn that didn't finish leaves no half of itself behind, so asking
        # again sends the same request (and an answered one replays free).
        del session.messages[start:]
        raise


def _turn(session, text, emit, room, first) -> str:
    content = [{"type": "text", "text": text}]
    if first:
        content = [plan_image(room, {}).block(),
                   {"type": "text", "text": "The plan above is the room as scanned, drawn from the scan."},
                   {"type": "text", "text": text}]
    session.messages.append({"role": "user", "content": content})
    turn = Turn(session, emit)
    reply = []
    briefs = session.__dict__.setdefault("briefs", [])     # every room brief the guide has been sent
    for _ in range(MAX_ROUNDS):
        told = brief(room, session.needs, session.arrangement, session.engine.current_findings,
                     session.told, session.changes)
        if not briefs or briefs[-1] != told:
            briefs.append(told)
        system = [{"type": "text", "text": GUIDE_SYSTEM, "cache_control": {"type": "ephemeral"}},
                  {"type": "text", "text": told, "cache_control": {"type": "ephemeral"}}]
        req = TurnRequest(stage="guide", prompt_version=GUIDE_VERSION, system=system,
                          messages=session.messages, tools=TOOLS, model=getattr(session, "model", MODEL),
                          effort=EFFORT)
        answer = session.gateway.ask_turn(req, on_text=lambda t: emit("delta", {"text": t}))
        blocks = answer["content"]
        session.messages.append({"role": "assistant", "content": blocks})
        reply += [b["text"] for b in blocks if b.get("type") == "text"]
        calls = [b for b in blocks if b.get("type") == "tool_use"]
        if not calls:
            break
        results = [{"type": "tool_result", "tool_use_id": c["id"], "content": turn.call(c["name"], c["input"])}
                   for c in calls]
        session.messages.append({"role": "user", "content": results})
    said = " ".join(reply)
    # A number may come from any brief the guide was sent, any tool result in the
    # conversation, or anything the person said; never from the guide's own replies.
    heard = [b.get("text") or b.get("content") for m in session.messages if m["role"] == "user"
             for b in (m["content"] if isinstance(m["content"], list) else [{"text": m["content"]}])]
    allowed = [*briefs, *turn.tool_texts, *[h for h in heard if isinstance(h, str)]]
    stray = foreign_numbers(said, allowed)
    if stray:
        log.warning("guide said numbers from nowhere: %s", stray)
    flags = [f"foreign_number:{n}" for n in stray]
    sentences = len(re.findall(r"[.!?](?:\s|$)", said.strip()))
    if sentences > 4:
        flags.append(f"long:{sentences}")
    emit("done", {"flags": flags, "spend": session.gateway.report()})
    return said


def mount(app, session) -> None:
    """Add the guide's endpoints to the harness app."""
    from fastapi import Request
    from fastapi.responses import Response, StreamingResponse

    session.transcript = []          # what the panel showed, to show again after a reload

    def stream(text: str, person: bool = True):
        events: queue.Queue = queue.Queue()
        if person:
            session.transcript.append(("person", {"text": text}))

        def emit(kind: str, data: dict) -> None:
            if kind in ("delta", "card", "note", "focus"):
                session.transcript.append((kind, data))
            events.put((kind, data))

        def work():
            try:
                run_turn(session, text, emit)
            except OracleNeeded as e:
                emit("note", {"text": f"Waiting for an answer to {e.folder.name} (offline mode)."})
                emit("done", {})
            except KeyError as e:
                emit("note", {"text": f"No saved answer for this turn and no live key ({e})."})
                emit("done", {})
            except (BudgetExceeded, ModelNotAllowed) as e:
                emit("error", {"message": str(e)})
                emit("done", {})
            except Exception as e:      # the panel must always hear the turn end
                log.exception("turn failed")
                emit("error", {"message": f"{type(e).__name__}: {e}"})
                emit("done", {})

        threading.Thread(target=work, daemon=True).start()
        while True:
            kind, data = events.get()
            yield f"event: {kind}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"
            if kind == "done":
                break

    @app.post("/api/turn")
    async def turn(request: Request):
        body = await request.json()
        return StreamingResponse(stream(str(body.get("text", ""))[:2000]), media_type="text/event-stream")

    @app.post("/api/open")
    def open_room():
        if session.messages:
            again = [f"event: {k}\ndata: {json.dumps(d, ensure_ascii=False)}\n\n" for k, d in session.transcript]
            return StreamingResponse(iter(again + ["event: done\ndata: {}\n\n"]), media_type="text/event-stream")
        return StreamingResponse(stream(OPENING, person=False), media_type="text/event-stream")

    @app.get("/plan.png")
    def plan_png():
        return Response(plan_image(session.room, session.arrangement).png, media_type="image/png")

