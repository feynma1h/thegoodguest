"""A room's needs: what each thing in it needs to stay usable, in a fixed vocabulary.

The vocabulary is about human actions and physical processes, not objects:

  open    a part swings or slides out (doors, drawers, a window that opens in)
  use     someone stands or sits in front of it to use it
  get_in  someone gets in or sits down on it
  reach   a hand must get to it
  air     it breathes
  heat    it is hot
  see     it is looked at from somewhere
  light   it lets light in
  pass    it is a way through (a doorway)
  other   anything the types above can't say: a described keep-clear box

Per piece, the file also says whether it moves (`yes`, `heavy`, `fixed`, or
`rehang`: it moves only to hang over the piece it belongs with) and what it goes
with (`with`: at, beside, over, facing, near). A piece that goes `at`,
`beside` or `over` another follows it when that piece moves.

Claude writes a room's needs once, in this vocabulary (rules_pass.py); the
person can add or relax them; code (assess.py) enforces them. Claude names no
sizes. A zone's depth comes from the piece's own measured parts (a door leaf's
width, a drawer's depth) or from the rulebook by need and posture. The one
exception is `other`, whose estimate is kept marked as an estimate.

Sides are in the piece's own frame: front is local +Z. Standing in front of
the piece and facing it, its right is local +X.

Read by: assess.py, analyzer.py, engine.py, rules_pass.py, brief.py.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from .geometry import Box
from .model import Piece, Pose, Room
from .rulebook import BODY_TOP, size_for

NEED_TYPES = ("open", "use", "get_in", "reach", "air", "heat", "see", "light", "pass", "other")
SIDES = ("front", "back", "left", "right", "sides", "either", "all")
STRENGTHS = ("hard", "soft")
POSTURES = ("standing", "seated", "lying")
MECHANISMS = ("hinged", "drawers", "sliding")
MOVES = ("yes", "heavy", "fixed", "rehang")
HOWS = ("at", "beside", "over", "facing", "near")
FOLLOW = ("at", "beside", "over")
PREFERENCES = ("task_light", "back_to_wall", "see_door", "centred", "open_floor", "balance")
TASKS = ("screen", "reading", "dressing", "work", "conversation", "sleep")
VIEWERS = ("facing_piece", "facing_out")
WEIGHTS = {"low": 1.0, "medium": 2.0, "high": 3.0}

DEFAULT_SIDE = {"open": "front", "use": "front", "get_in": "sides", "air": "front", "heat": "all",
                "see": "front", "light": "front", "other": "front", "reach": "front", "pass": "front"}
NEEDS_POSTURE = ("use", "get_in", "see")
ZONE_NEEDS = ("open", "use", "get_in", "air", "heat", "pass", "other")
PERSON_NEEDS = ("use", "get_in")

# What a companion may stand in. A seat set at a piece stands where it is used
# from, and is pulled away to open it (a chair at a desk). Something hung over a
# piece stands above whatever it is seen or reached from (a mirror over a
# dresser). Nothing else is excused: not the room to get into a seat or a bed
# (that is the knee room a low table must leave), and never where a piece
# heats, breathes, lets daylight in or lets people through.
COMPANION_ROOM = {"use": ("at",), "open": ("at",), "see": ("over",), "reach": ("over",)}

MAX_NEEDS_PER_PIECE = 8
MAX_BONDS_PER_PIECE = 4
MAX_PREFERENCES = 12
MAX_QUESTIONS = 5
MAX_TEXT = 240


class NeedsError(ValueError):
    """A needs file that does not fit the vocabulary. `problems` lists each reason."""

    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


@dataclass(frozen=True)
class Need:
    need: str
    side: str
    strength: str
    why: str
    posture: str | None = None
    mechanism: str | None = None
    leaves: int = 1
    depth_estimate: float | None = None
    what: str | None = None
    source: str = "rules"            # "rules" | "person" | "critic" | "default"


@dataclass(frozen=True)
class Bond:
    piece: str
    how: str
    strength: str
    why: str


@dataclass(frozen=True)
class PieceNeeds:
    moves: str
    why: str
    needs: tuple[Need, ...] = ()
    bonds: tuple[Bond, ...] = ()


@dataclass(frozen=True)
class Preference:
    pref: str
    weight: str
    why: str
    piece: str | None = None
    task: str | None = None
    viewer: str | None = None


@dataclass(frozen=True)
class Question:
    about: str | None
    ask: str
    why: str


@dataclass(frozen=True)
class RoomNeeds:
    pieces: dict[str, PieceNeeds]
    preferences: tuple[Preference, ...] = ()
    questions: tuple[Question, ...] = ()
    origin: str = "rules pass"
    settled: tuple[str, ...] = ()      # bonds set aside or turned round after reading, and why

    def fixed_ids(self) -> set[str]:
        return {pid for pid, p in self.pieces.items() if p.moves in ("fixed", "rehang")}

    def moves(self, piece_id: str) -> str:
        p = self.pieces.get(piece_id)
        return p.moves if p else "fixed"

    def followers(self, anchor: str, hard_only: bool = False) -> list[str]:
        """Pieces that go with `anchor` and follow it when it moves (only hard bonds, if asked)."""
        return [pid for pid, p in self.pieces.items()
                if any(b.piece == anchor and b.how in FOLLOW and (b.strength == "hard" or not hard_only)
                       for b in p.bonds)]

    def bonded(self, piece_id: str, hows: tuple[str, ...] = HOWS) -> set[str]:
        """Every piece bonded to this one either way, by one of `hows`."""
        out = {b.piece for b in self.pieces.get(piece_id, PieceNeeds("fixed", "")).bonds if b.how in hows}
        for pid, p in self.pieces.items():
            if any(b.piece == piece_id and b.how in hows for b in p.bonds):
                out.add(pid)
        return out

    def needs_of(self, piece_id: str, need: str | None = None) -> list[Need]:
        p = self.pieces.get(piece_id)
        if not p:
            return []
        return [n for n in p.needs if need is None or n.need == need]


# ---------------------------------------------------------------- reading a needs file

def _text(value, problems: list[str], where: str, required: bool = True) -> str:
    if value is None or value == "":
        if required:
            problems.append(f"{where}: missing")
        return ""
    if not isinstance(value, str):
        problems.append(f"{where}: not text")
        return ""
    if len(value) > MAX_TEXT:
        problems.append(f"{where}: longer than {MAX_TEXT} characters")
        return value[:MAX_TEXT]
    return value.strip()


def _choice(value, allowed, problems: list[str], where: str, default=None):
    if value is None and default is not None:
        return default
    if value not in allowed:
        problems.append(f"{where}: {value!r} is not one of {', '.join(map(str, allowed))}")
        return default if default is not None else allowed[0]
    return value


def _need(raw: dict, piece: Piece, problems: list[str], where: str) -> Need | None:
    if not isinstance(raw, dict):
        problems.append(f"{where}: not an object")
        return None
    kind = _choice(raw.get("need"), NEED_TYPES, problems, f"{where}.need")
    side = _choice(raw.get("side"), SIDES, problems, f"{where}.side", DEFAULT_SIDE[kind])
    if kind in ("pass", "light", "reach"):
        side = "front"               # a way through, daylight and a hand's reach face the room
    strength = _choice(raw.get("strength"), STRENGTHS, problems, f"{where}.strength")
    why = _text(raw.get("why"), problems, f"{where}.why")
    posture = None
    if kind in NEEDS_POSTURE:
        posture = _choice(raw.get("posture"), POSTURES, problems, f"{where}.posture")
    mechanism, leaves = None, 1
    if kind == "open":
        mechanism = _choice(raw.get("mechanism"), MECHANISMS, problems, f"{where}.mechanism")
        leaves = raw.get("leaves", 1)
        if not isinstance(leaves, int) or not 1 <= leaves <= 4:
            problems.append(f"{where}.leaves: a whole number from 1 to 4")
            leaves = 1
    depth, what = None, None
    if kind == "other":
        depth = raw.get("depth_estimate_m")
        if not isinstance(depth, (int, float)) or not 0.05 <= float(depth) <= 2.0:
            problems.append(f"{where}.depth_estimate_m: a number of metres from 0.05 to 2")
            depth = 0.3
        depth = float(depth)
        what = _text(raw.get("what"), problems, f"{where}.what")
    return Need(kind, side, strength, why, posture, mechanism, leaves, depth, what)


def parse_needs(room: Room, data: dict) -> RoomNeeds:
    """Read a needs file against the room it describes, or raise NeedsError."""
    problems: list[str] = []
    if not isinstance(data, dict):
        raise NeedsError(["the file is not an object"])
    unknown_keys = set(data) - {"rules_version", "pieces", "preferences", "questions", "settled"}
    if unknown_keys:
        problems.append(f"unknown keys: {', '.join(sorted(unknown_keys))}")
    raw_pieces = data.get("pieces")
    if isinstance(raw_pieces, list):
        # The rules pass answers with a list of entries, each carrying its id.
        by_id: dict = {}
        for i, entry in enumerate(raw_pieces):
            if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
                problems.append(f"pieces[{i}]: needs an id")
                continue
            if entry["id"] in by_id:
                problems.append(f"pieces: {entry['id']} appears twice")
            by_id[entry["id"]] = {k: v for k, v in entry.items() if k != "id"}
        raw_pieces = by_id
    if not isinstance(raw_pieces, dict):
        raise NeedsError(problems + ["pieces: missing or not an object"])
    missing = [pid for pid in room.pieces if pid not in raw_pieces]
    if missing:
        problems.append(f"pieces: no entry for {', '.join(missing)}")
    strangers = [pid for pid in raw_pieces if pid not in room.pieces]
    if strangers:
        problems.append(f"pieces: no such piece {', '.join(strangers)}")

    pieces: dict[str, PieceNeeds] = {}
    for pid, raw in raw_pieces.items():
        if pid not in room.pieces:
            continue
        where = f"pieces.{pid}"
        if not isinstance(raw, dict):
            problems.append(f"{where}: not an object")
            continue
        piece = room.pieces[pid]
        moves = _choice(raw.get("moves"), MOVES, problems, f"{where}.moves")
        if piece.support in ("wall", "ceiling") or piece.opening is not None:
            if moves in ("yes", "heavy"):
                problems.append(f"{where}.moves: something on a wall or ceiling is fixed or re-hung")
                moves = "fixed"
        why = _text(raw.get("why"), problems, f"{where}.why", required=moves != "yes")
        raw_needs = raw.get("needs") or []
        if not isinstance(raw_needs, list) or len(raw_needs) > MAX_NEEDS_PER_PIECE:
            problems.append(f"{where}.needs: a list of at most {MAX_NEEDS_PER_PIECE}")
            raw_needs = []
        needs = tuple(n for i, r in enumerate(raw_needs)
                      if (n := _need(r, piece, problems, f"{where}.needs[{i}]")) is not None)
        raw_bonds = raw.get("with") or []
        if not isinstance(raw_bonds, list) or len(raw_bonds) > MAX_BONDS_PER_PIECE:
            problems.append(f"{where}.with: a list of at most {MAX_BONDS_PER_PIECE}")
            raw_bonds = []
        bonds = []
        for i, b in enumerate(raw_bonds):
            bw = f"{where}.with[{i}]"
            if not isinstance(b, dict):
                problems.append(f"{bw}: not an object")
                continue
            other = b.get("piece")
            if other not in room.pieces or other == pid:
                problems.append(f"{bw}.piece: {other!r} is not another piece in the room")
                continue
            bonds.append(Bond(other, _choice(b.get("how"), HOWS, problems, f"{bw}.how"),
                              _choice(b.get("strength"), STRENGTHS, problems, f"{bw}.strength"),
                              _text(b.get("why"), problems, f"{bw}.why")))
        if moves == "rehang" and not any(b.how == "over" for b in bonds):
            problems.append(f"{where}: re-hung only over a piece it goes `over`")
        pieces[pid] = PieceNeeds(moves, why, needs, tuple(bonds))

    prefs = []
    raw_prefs = data.get("preferences") or []
    if not isinstance(raw_prefs, list) or len(raw_prefs) > MAX_PREFERENCES:
        problems.append(f"preferences: a list of at most {MAX_PREFERENCES}")
        raw_prefs = []
    for i, p in enumerate(raw_prefs):
        where = f"preferences[{i}]"
        if not isinstance(p, dict):
            problems.append(f"{where}: not an object")
            continue
        kind = _choice(p.get("pref"), PREFERENCES, problems, f"{where}.pref")
        piece = p.get("piece")
        if kind not in ("open_floor", "balance") and piece not in room.pieces:
            problems.append(f"{where}.piece: {piece!r} is not a piece in the room")
            continue
        task = _choice(p.get("task"), TASKS, problems, f"{where}.task") if kind == "task_light" else None
        viewer = (_choice(p.get("viewer"), VIEWERS, problems, f"{where}.viewer")
                  if kind in ("task_light", "see_door") else None)
        prefs.append(Preference(kind, _choice(p.get("weight"), tuple(WEIGHTS), problems, f"{where}.weight"),
                                _text(p.get("why"), problems, f"{where}.why"),
                                piece if kind not in ("open_floor", "balance") else None, task, viewer))

    questions = []
    raw_q = data.get("questions") or []
    if not isinstance(raw_q, list) or len(raw_q) > MAX_QUESTIONS:
        problems.append(f"questions: a list of at most {MAX_QUESTIONS}")
        raw_q = []
    for i, q in enumerate(raw_q):
        where = f"questions[{i}]"
        if not isinstance(q, dict):
            problems.append(f"{where}: not an object")
            continue
        about = q.get("about")
        if about is not None and about not in room.pieces:
            problems.append(f"{where}.about: {about!r} is not a piece in the room")
            about = None
        questions.append(Question(about, _text(q.get("ask"), problems, f"{where}.ask"),
                                  _text(q.get("why"), problems, f"{where}.why")))

    # A file written back out (needs_to_json) lists what settling set aside or turned.
    settled = data.get("settled") or []
    if not isinstance(settled, list) or not all(isinstance(x, str) for x in settled):
        problems.append("settled: a list of notes")
        settled = []

    if problems:
        raise NeedsError(problems)
    return RoomNeeds(pieces, tuple(prefs), tuple(questions), "rules pass", tuple(settled))


def default_needs(room: Room) -> RoomNeeds:
    """What holds with no needs file: shell pieces are fixed, everything else may move, and
    every door is a way in. The laws still apply in full; the guide says less."""
    pieces = {}
    for pid, p in room.pieces.items():
        if p.support in ("wall", "ceiling") or p.opening is not None:
            needs = ()
            if p.opening and room.opening(p.opening).kind == "door":
                needs = (Need("pass", "front", "soft", "a doorway is a way in", source="default"),)
            pieces[pid] = PieceNeeds("fixed", "part of the shell", needs)
        else:
            pieces[pid] = PieceNeeds("yes", "")
    return RoomNeeds(pieces, (), (), "defaults")


def with_change(needs: RoomNeeds, piece_id: str, *, add: Need | None = None,
                drop: str | None = None, side: str | None = None, moves: str | None = None) -> RoomNeeds:
    """The same needs with one piece's needs changed (by the person or the critic).

    Dropping with a side drops that side only: a need declared on both sides keeps
    the other one.
    """
    entry = needs.pieces.get(piece_id, PieceNeeds("yes", ""))
    kept: tuple[Need, ...] = ()
    for n in entry.needs:
        if drop is None or n.need != drop:
            kept += (n,)
        elif side and side not in concrete_sides(n.side):
            kept += (n,)
        elif side and n.side != side:
            rest = [s for s in concrete_sides(n.side) if s != side]
            kept += tuple(replace(n, side=s) for s in rest)
    if add is not None:
        kept = tuple(n for n in kept if not (n.need == add.need and n.side == add.side)) + (add,)
    entry = replace(entry, needs=kept, moves=moves or entry.moves)
    pieces = dict(needs.pieces)
    pieces[piece_id] = entry
    return replace(needs, pieces=pieces)


# ---------------------------------------------------------------- zones

@dataclass(frozen=True)
class Zone:
    """A keep-clear volume beside one side of a piece, in that piece's frame.

    Its depth runs out from the side; `hard` is the depth below which the need
    is broken, `comfortable` the depth at which it is fully met. `floor_based`
    zones (where a person stands or sits) run from the floor to head height;
    the others span the piece's own height.
    """

    piece: str
    need: str
    side: str
    strength: str
    hard: float
    comfortable: float
    width: float
    y0: float
    y1: float
    floor_based: bool
    posture: str | None
    exempt: frozenset[str]
    why: str
    estimate: bool = False
    say: str = ""
    mechanism: str | None = None
    either: bool = False         # one of left and right is enough


def concrete_sides(side: str) -> tuple[str, ...]:
    return {"sides": ("left", "right"), "either": ("left", "right"),
            "all": ("front", "back", "left", "right")}.get(side, (side,))


def _exempt(room: Room, needs: RoomNeeds, piece_id: str, need: str) -> frozenset[str]:
    """What may stand in this need's room: the piece, what rests on it, and its companions."""
    out = {piece_id, *room.riders(piece_id)}
    for other in needs.bonded(piece_id, COMPANION_ROOM.get(need, ())):
        out.add(other)
        out.update(room.riders(other))
    return frozenset(out)


def zones(room: Room, needs: RoomNeeds) -> list[Zone]:
    """Every keep-clear zone the room's needs ask for."""
    out = []
    for pid, entry in needs.pieces.items():
        piece = room.pieces.get(pid)
        if piece is None:
            continue
        sx, sy, sz = piece.size
        for n in entry.needs:
            if n.need not in ZONE_NEEDS:
                continue
            exempt = _exempt(room, needs, pid, n.need)
            if n.need == "open":
                if n.mechanism == "sliding":
                    continue
                depth = sz if n.mechanism == "drawers" else sx / max(1, n.leaves)
                hard = comfortable = depth
                say, estimate = "", False
            elif n.need == "other":
                hard = comfortable = float(n.depth_estimate or 0.3)
                say, estimate = "", True
            else:
                s = size_for(n.need, n.posture)
                hard, comfortable, say, estimate = s.hard, s.comfortable, s.say, False
            floor_based = n.need in PERSON_NEEDS or n.need == "pass"
            if floor_based:
                y0, y1 = 0.0, BODY_TOP
            elif n.need == "heat":
                y0, y1 = 0.0, sy + 0.5
            else:
                y0, y1 = 0.0, sy
            sides = concrete_sides(n.side)
            if piece.opening is not None:
                sides = ("front",)       # a door or window's other sides are wall, or outside
            for side in sides:
                width = sx if side in ("front", "back") else sz
                out.append(Zone(pid, n.need, side, n.strength, hard, comfortable, width, y0, y1,
                                floor_based, n.posture, exempt, n.why, estimate, say, n.mechanism,
                                either=n.side == "either" and piece.opening is None))
    return out


def zone_box(piece: Piece, zone: Zone, pose: Pose, depth: float) -> Box:
    """The zone's volume in the room, at the piece's pose, `depth` deep."""
    sx, _, sz = piece.size
    d = max(depth, 1e-4)
    if zone.side == "front":
        lx, lz, hx, hz = 0.0, sz / 2 + d / 2, zone.width / 2, d / 2
    elif zone.side == "back":
        lx, lz, hx, hz = 0.0, -sz / 2 - d / 2, zone.width / 2, d / 2
    elif zone.side == "right":
        lx, lz, hx, hz = sx / 2 + d / 2, 0.0, d / 2, zone.width / 2
    else:
        lx, lz, hx, hz = -sx / 2 - d / 2, 0.0, d / 2, zone.width / 2
    x, z = pose.place(lx, lz)
    base = 0.0 if zone.floor_based else pose.y
    return Box(x, z, hx, hz, pose.yaw, base + zone.y0, base + zone.y1)


@dataclass(frozen=True)
class Target:
    """A spot on a piece that a person must reach, see, or let light through."""

    piece: str
    need: str            # "reach" | "see" | "light"
    strength: str
    posture: str | None
    exempt: frozenset[str]
    why: str


def targets(room: Room, needs: RoomNeeds) -> list[Target]:
    out = []
    for pid, entry in needs.pieces.items():
        if pid not in room.pieces:
            continue
        for n in entry.needs:
            if n.need in ("reach", "see", "light"):
                out.append(Target(pid, n.need, n.strength, n.posture, _exempt(room, needs, pid, n.need), n.why))
    return out


def entrances(room: Room, needs: RoomNeeds) -> list[str]:
    """Door pieces that are ways in: those with a `pass` need. With none declared, every door."""
    doors = [pid for pid, p in room.pieces.items()
             if p.opening is not None and room.opening(p.opening).kind == "door"]
    declared = [pid for pid in doors if needs.needs_of(pid, "pass")]
    if any(needs.needs_of(pid, "pass") for pid in needs.pieces):
        return declared
    return doors
