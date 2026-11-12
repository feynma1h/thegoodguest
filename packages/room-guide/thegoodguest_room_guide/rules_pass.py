"""The rules pass: Claude writes one room's needs, once, in the fixed vocabulary.

The request carries the room in words (every piece with its id, name, kind,
what it stands on or hangs from, its size and the scan's description) and,
when one is given, a plan of the room drawn from the model (never a camera
frame). The answer is JSON in the needs vocabulary, checked by
`needs.parse_needs`. An answer that doesn't fit is asked once more with the
problems listed; if that fails too, the room falls back to the defaults (laws
only), and says so. Bonds that can't be true of any arrangement are set aside,
and bonds written the wrong way round are turned; both are listed
(`settle_bonds`).

The answer is cached by the gateway, so the same room and prompt cost nothing
the second time.

Read by: the harness, the analyzer's callers, the engine's callers.
"""
from __future__ import annotations

from dataclasses import replace

from .gateway import DEFAULT_MODEL, Gateway, Image, JsonRequest
from .model import Room
from .needs import (FOLLOW, HOWS, MECHANISMS, MOVES, NEED_TYPES, POSTURES, PREFERENCES, SIDES, STRENGTHS, TASKS,
                    VIEWERS, WEIGHTS, NeedsError, RoomNeeds, default_needs, parse_needs)
from .prompts import RULES_SYSTEM, RULES_VERSION


def rules_schema(room: Room) -> dict:
    """The JSON Schema the answer must match: the vocabulary, and this room's piece ids."""
    ids = list(room.pieces)
    text = {"type": "string"}
    need = {"type": "object", "additionalProperties": False, "required": ["need", "side", "strength", "why"],
            "properties": {"need": {"enum": list(NEED_TYPES)}, "side": {"enum": list(SIDES)},
                           "strength": {"enum": list(STRENGTHS)}, "why": text,
                           "posture": {"enum": list(POSTURES)}, "mechanism": {"enum": list(MECHANISMS)},
                           "leaves": {"type": "integer"}, "what": text, "depth_estimate_m": {"type": "number"}}}
    bond = {"type": "object", "additionalProperties": False, "required": ["piece", "how", "strength", "why"],
            "properties": {"piece": {"enum": ids}, "how": {"enum": list(HOWS)},
                           "strength": {"enum": list(STRENGTHS)}, "why": text}}
    piece = {"type": "object", "additionalProperties": False, "required": ["id", "moves", "why", "needs", "with"],
             "properties": {"id": {"enum": ids}, "moves": {"enum": list(MOVES)}, "why": text,
                            "needs": {"type": "array", "items": need}, "with": {"type": "array", "items": bond}}}
    pref = {"type": "object", "additionalProperties": False, "required": ["pref", "weight", "why"],
            "properties": {"pref": {"enum": list(PREFERENCES)}, "weight": {"enum": list(WEIGHTS)}, "why": text,
                           "piece": {"enum": ids}, "task": {"enum": list(TASKS)}, "viewer": {"enum": list(VIEWERS)}}}
    question = {"type": "object", "additionalProperties": False, "required": ["about", "ask", "why"],
                "properties": {"about": {"anyOf": [{"enum": ids}, {"type": "null"}]}, "ask": text, "why": text}}
    return {"type": "object", "additionalProperties": False, "required": ["pieces", "preferences", "questions"],
            "properties": {"pieces": {"type": "array", "items": piece},
                           "preferences": {"type": "array", "items": pref},
                           "questions": {"type": "array", "items": question}}}


def _m(v: float) -> str:
    return f"{v:.2f}".rstrip("0").rstrip(".")


def room_summary(room: Room) -> str:
    """The room in words, for the rules pass."""
    xs, zs = room.footprint[:, 0], room.footprint[:, 1]
    lines = [f"Room: {room.kind}, about {_m(xs.max() - xs.min())} by {_m(zs.max() - zs.min())} m, "
             f"ceiling about {_m(room.height)} m.", "", "Walls:"]
    for w in room.walls:
        on = [p for p in room.pieces.values() if p.wall == w.id and p.support in ("wall", "ceiling")]
        backed = [p for p in room.pieces.values() if p.wall == w.id and p.support == "floor"]
        bits = [f"{p.id} ({p.name})" for p in on]
        if backed:
            bits.append("with " + ", ".join(f"{p.id}" for p in backed) + " standing against it")
        lines.append(f"- {w.id}, {_m(w.length)} m long: " + ("; ".join(bits) if bits else "bare"))
    lines += ["", "Pieces (id: name, kind; where; width x height x depth):"]
    for p in room.pieces.values():
        if p.support == "object":
            where = f"standing on {p.on}"
        elif p.support == "wall":
            where = f"on {p.wall}, {_m(p.pose.y)} to {_m(p.pose.y + p.size[1])} m up"
        elif p.support == "ceiling":
            where = "on the ceiling"
        else:
            where = f"on the floor, its back to {p.wall}" if p.wall else "on the floor, free-standing"
        params = ", ".join(f"{k} {v}" for k, v in p.params.items() if v not in ("", None, "none"))
        desc = p.description.strip()
        lines.append(f"- {p.id}: {p.name}, {p.category}; {where}; "
                     f"{_m(p.size[0])} x {_m(p.size[1])} x {_m(p.size[2])} m"
                     + (f"; {params}" if params else "") + (f". {desc}" if desc else ""))
    return "\n".join(lines)


def rules_request(room: Room, images: list[Image] | None = None, *, model: str = DEFAULT_MODEL,
                  effort: str = "medium", feedback: list[str] | None = None) -> JsonRequest:
    text = room_summary(room)
    if images:
        text += "\n\nThe image is a plan of this room drawn from the scan, looking down, with each piece labelled."
    text += "\n\nWrite this room's needs as JSON."
    if feedback:
        text += ("\n\nAn earlier answer did not fit the vocabulary. Fix these and answer again:\n- "
                 + "\n- ".join(feedback[:30]))
    return JsonRequest(stage="rules", prompt_version=RULES_VERSION, system=RULES_SYSTEM, text=text,
                       schema=rules_schema(room), images=list(images or []), model=model, effort=effort)


def run_rules_pass(room: Room, gateway: Gateway, images: list[Image] | None = None, *,
                   model: str = DEFAULT_MODEL, effort: str = "medium") -> RoomNeeds:
    """This room's needs from Claude, checked; the defaults if Claude's answer won't fit twice."""
    data = gateway.ask_json(rules_request(room, images, model=model, effort=effort))
    try:
        return settle_bonds(room, parse_needs(room, data))
    except NeedsError as first:
        data = gateway.ask_json(rules_request(room, images, model=model, effort=effort, feedback=first.problems))
        try:
            return settle_bonds(room, parse_needs(room, data))
        except NeedsError:
            return default_needs(room)


HANG_SLACK = 0.05      # how far a hung piece may dip below the top of what it hangs over


def settle_bonds(room: Room, needs: RoomNeeds) -> RoomNeeds:
    """The bonds that could be true of this room, each pointing the right way.

    Set aside:
      - a bond between pieces in one stack (a television on its unit): the scan
        already keeps them together, and the bond would pull one off the other;
      - `over` from something that doesn't hang, or that hangs lower than the
        top of the piece it would be over (a mirror behind a tall wardrobe).
    Turned round: `at` or `beside` written from the larger piece to the smaller
    one (a desk "at" its stool, a bed "beside" its table). The smaller piece is
    the one that goes with the larger, and the engine moves it, not the other.
    Kept: a bond the scan doesn't satisfy. A chair left away from its desk
    still belongs at it.
    Everything set aside or turned is listed in `settled`.
    """
    settled = list(needs.settled)
    bonds: dict[str, list] = {pid: [] for pid in needs.pieces}

    def area(pid: str) -> float:
        sx, _, sz = room.pieces[pid].size
        return sx * sz

    def add(pid, b):
        if not any(o.piece == b.piece for o in bonds[pid]) and not any(
                o.piece == pid and o.how in FOLLOW for o in bonds.get(b.piece, [])):
            bonds[pid].append(b)

    for pid, entry in needs.pieces.items():
        for b in entry.bonds:
            p, other = room.pieces[pid], room.pieces[b.piece]
            if room.base_of(pid) == room.base_of(b.piece):
                settled.append(f"{pid} {b.how} {b.piece}: set aside, one rests on the other, so they move together")
            elif b.how == "over" and p.support not in ("wall", "ceiling"):
                settled.append(f"{pid} over {b.piece}: set aside, only something that hangs can hang over a piece")
            elif b.how == "over" and p.pose.y < other.pose.y + other.size[1] - HANG_SLACK:
                settled.append(f"{pid} over {b.piece}: set aside, it hangs lower than the top of {b.piece}")
            elif (b.how in ("at", "beside") and area(pid) > area(b.piece) and b.piece in bonds
                  and needs.moves(b.piece) in ("yes", "heavy") and other.opening is None
                  and other.support not in ("wall", "ceiling")):
                settled.append(f"{pid} {b.how} {b.piece}: turned round, the smaller piece goes with the larger")
                add(b.piece, replace(b, piece=pid))
            else:
                add(pid, b)
    pieces = {pid: entry if list(entry.bonds) == bonds[pid] else replace(entry, bonds=tuple(bonds[pid]))
              for pid, entry in needs.pieces.items()}
    return replace(needs, pieces=pieces, settled=tuple(settled))


def needs_to_json(needs: RoomNeeds) -> dict:
    """A needs file, as the rules pass writes one (for the person's edits and the harness)."""
    def clean(d: dict) -> dict:
        return {k: v for k, v in d.items() if v not in (None, "", ()) and not (k == "leaves" and v == 1)
                and k != "source"}

    pieces = []
    for pid, p in needs.pieces.items():
        pieces.append({"id": pid, "moves": p.moves, "why": p.why,
                       "needs": [clean({**n.__dict__, "depth_estimate_m": n.depth_estimate,
                                        "depth_estimate": None}) for n in p.needs],
                       "with": [dict(b.__dict__) for b in p.bonds]})
    return {"pieces": pieces,
            "preferences": [clean(dict(p.__dict__)) for p in needs.preferences],
            "questions": [dict(q.__dict__) for q in needs.questions],
            "settled": list(needs.settled)}

