"""Findings: what a designer would notice in a room, in sentences with their numbers.

Turns an assessment into findings, most important first. Every number in a
finding is worked out here, rounded down to 5 cm and framed ("about 0.7 m"), so
the guide can quote it word for word and never computes one itself. A rulebook
figure travels with the rulebook's own sentence for it. Pieces are named the
way a person would name them ("the white desk"), walls by what is on them
("the window wall").

A finding is one of:
  problem   a hard need or a law the room breaks
  tight     a need met, but short of comfortable
  light     where daylight falls for a task, and what that means
  good      something the room already does well (a designer says so)
  question  something the scan cannot know

Read by: brief.py (the guide's view of the room), engine.py (what a proposal
changes), the harness.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from . import laws
from .assess import Assessment, PrefResult, Shortfall, _walkable, backing_wall, floor_grid, zone_box
from .geometry import flood, footprint_distance, segment_distance
from .model import Pose, Room, spoken
from .needs import RoomNeeds, entrances, zones
from .rulebook import PERSON_PATH, size_for


@dataclass(frozen=True)
class Finding:
    key: str
    kind: str                  # problem | tight | light | good | question
    severity: int              # 3 breaks something, 2 falls short, 1 mild, 0 good news
    pieces: tuple[str, ...]
    text: str                  # the guide may quote this word for word
    standard: str = ""         # the rulebook sentence it is measured against
    numbers: dict = field(default_factory=dict)


# ---------------------------------------------------------------- words

def about(v: float, *, down: bool = True) -> str:
    """A length the way the guide says it: rounded to 5 cm (down, unless asked), "about"."""
    step = 0.05
    r = math.floor(v / step + 1e-9) * step if down else round(v / step) * step
    if r < step:
        return "almost no room"
    return f"about {r:.2f}".rstrip("0").rstrip(".") + " m"


def the(room: Room, piece_id: str) -> str:
    """A piece as a person names it: "the white desk"."""
    if piece_id == "wall":
        return "the wall"
    p = room.pieces.get(piece_id)
    if p is None:
        return piece_id
    return "the " + spoken(p.name.split(",")[0].strip())


def wall_name(room: Room, wall_id: str) -> str:
    """A wall as a person names it: by its window or door, or the piece against it."""
    kinds = {op.kind for op in room.openings if op.wall == wall_id}
    if "window" in kinds:
        return "the window wall"
    if "door" in kinds:
        return "the door wall"
    backed = [p for p in room.pieces.values() if p.wall == wall_id and p.support == "floor"]
    if backed:
        biggest = max(backed, key=lambda p: p.size[0] * p.size[2])
        return f"the wall behind {the(room, biggest.id)}"
    w = room.wall(wall_id)
    for other in room.walls:
        if other.id != wall_id and abs(other.normal[0] + w.normal[0]) < 1e-6 and abs(other.normal[1] + w.normal[1]) < 1e-6:
            if any(op.wall == other.id for op in room.openings):
                return f"the wall opposite {wall_name(room, other.id)}"
    return "the plain wall"


def _list(names: list[str]) -> str:
    names = list(dict.fromkeys(names))
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


# ---------------------------------------------------------------- where a path pinches

def _bottleneck(grid, clear: np.ndarray, sources: np.ndarray, targets: np.ndarray,
                width: float) -> np.ndarray | None:
    """The pinch on the widest way from the way in to the targets.

    Floor cells are joined from the most open down (union-find); the cell whose
    joining first links the way in to the target is the widest way's narrowest
    point. It sits on a saddle of the clearance, so the two things pinching the
    way stand about equally close to it. If the targets themselves are the
    narrowest part, there is no corridor to point at and this returns None (the
    caller names what crowds the target instead).
    """
    nz, nx = grid.shape
    n = nz * nx
    parent = list(range(n + 2))
    src, tgt = n, n + 1

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[ri] = rj

    added = np.zeros(n, dtype=bool)
    order = np.argsort(-clear)
    for i in order:
        if clear[i] <= 0:
            break
        added[i] = True
        if sources[i]:
            union(i, src)
        if targets[i]:
            union(i, tgt)
        r, c = divmod(int(i), nx)
        for rr, cc in ((r + 1, c), (r - 1, c), (r, c + 1), (r, c - 1)):
            if 0 <= rr < nz and 0 <= cc < nx and added[rr * nx + cc]:
                union(int(i), rr * nx + cc)
        if find(src) == find(tgt):
            if targets[i] and clear[i] < width / 2 + 0.03:
                return None          # the target itself is the narrowest part
            return grid.points[int(i)]
    return None


def pinch(room: Room, needs: RoomNeeds, poses: dict[str, Pose], piece_id: str, need: str, side: str,
          width: float) -> tuple[str, ...]:
    """What stands either side of the narrowest point on the way to a piece's side."""
    grid = floor_grid(room)
    clear, sources, _ = _walkable(room, needs, poses, grid)
    z = next((z for z in zones(room, needs) if (z.piece, z.need, z.side) == (piece_id, need, side)), None)
    if z is None:
        return ()
    targets = grid.inside & grid.in_box(zone_box(room.pieces[piece_id], z, poses[piece_id], max(z.hard, 0.3)))
    cell = _bottleneck(grid, clear, sources, targets, width)
    if cell is None:
        return ()
    best: dict[str, float] = {}
    for pid, p in room.pieces.items():
        body = [s for s in p.solids(poses[pid]) if s.y0 < 1.8 and s.y1 > 0.05] if laws.collides(p) else []
        if body:
            base = room.base_of(pid)          # a pack on a chest of drawers is the chest of drawers
            d = min(float(footprint_distance(s, cell[None, :])[0]) for s in body)
            best[base] = min(best.get(base, math.inf), d)
    for w in room.walls:
        best["wall:" + w.id] = float(segment_distance(cell[None, :], w.a, w.b)[0])
    out = []
    for who, d in sorted(best.items(), key=lambda kv: kv[1]):
        if d > width / 2 + 0.12 or len(out) == 2:
            break
        out.append(who)
    for door in entrances(room, needs):
        dp = poses[door]
        if math.hypot(cell[0] - dp.x, cell[1] - dp.z) <= 0.6:
            return ("door:" + door, *[w for w in out if not w.startswith("wall:")])
    return tuple(out)


# ---------------------------------------------------------------- the findings

def findings(room: Room, needs: RoomNeeds, a: Assessment) -> list[Finding]:
    out: list[Finding] = []
    short = {(s.piece, s.need, s.side): s for s in a.shortfalls}
    broken = {(b.pieces[0], b.need, b.side) for b in a.breaks if b.kind == "zone"}
    by_zone = {(z.piece, z.need, z.side): z for z in zones(room, needs)}

    for (pid, need, side), z in by_zone.items():
        s = short.get((pid, need, side))
        if s is None:
            continue
        hard = (pid, need, side) in broken
        out.append(_zone_finding(room, z, s, hard))

    for b in a.breaks:
        if b.kind == "unreachable":
            out.append(_pinch_finding(room, b.pieces[0], b.need, b.side, b.amount,
                                      _pinched_by(room, needs, a, b.pieces[0], b.need, b.side, b.amount), severity=3,
                                      goal=side_phrase(room, a, b.pieces[0], b.need, b.side)))
        elif b.kind == "covered":
            out.append(Finding(f"covered:{b.pieces[0]}", "problem", 3, b.pieces,
                               f"{_cap(_list([the(room, p) for p in b.pieces[1:]]))} "
                               f"{'stand' if len(b.pieces) > 2 else 'stands'} in front of {the(room, b.pieces[0])}."))
        elif b.kind == "unseen":
            out.append(Finding(f"unseen:{b.pieces[0]}", "problem", 3, b.pieces,
                               f"There's nowhere to stand in front of {the(room, b.pieces[0])} with a clear view of it."))
        elif b.kind == "dark":
            share = int(round(b.amount * 100 / 5) * 5)
            out.append(Finding(f"dark:{b.pieces[0]}", "problem", 3, b.pieces,
                               f"{_cap(_list([the(room, p) for p in b.pieces[1:]]))} "
                               f"{'cover' if len(b.pieces) > 2 else 'covers'} about {share}% of {the(room, b.pieces[0])}."))

    for (pid, need, side), w in a.paths.items():
        if w >= PERSON_PATH - 0.01 and w < size_for("pass").comfortable - 0.01 and (pid, need, side) not in broken:
            pieces = _pinched_by(room, needs, a, pid, need, side, w)
            if pieces:
                out.append(_pinch_finding(room, pid, need, side, w, pieces, severity=1,
                                          goal=side_phrase(room, a, pid, need, side)))

    for pid, d in a.reach.items():
        size = size_for("reach")
        if not math.isfinite(d):
            continue
        if d > size.comfortable + 0.01:
            sev = 3 if d > size.hard else 1
            out.append(Finding(f"reach:{pid}", "problem" if sev == 3 else "tight", sev, (pid,),
                               f"{_cap(the(room, pid))} is {about(d, down=False)} from the nearest place to stand.",
                               size.say, {"distance": round(d, 2)}))

    for s in a.shortfalls:
        if s.need == "with":
            out.append(_bond_finding(room, s))
        elif s.need == "light":
            share = int(round((1.0 - s.free) * 100 / 5) * 5)
            if share >= 10 and s.intruders:
                out.append(Finding(f"light:{s.piece}", "tight", 1, (s.piece, *s.intruders),
                                   f"{_cap(_list([the(room, p) for p in s.intruders]))} "
                                   f"{'cover' if len(s.intruders) > 1 else 'covers'} about {share}% of "
                                   f"{the(room, s.piece)}."))

    for p in a.preferences:
        f = _pref_finding(room, needs, p, a.poses)
        if f is not None:
            out.append(f)

    for q in needs.questions:
        out.append(Finding(f"question:{q.about or 'room'}:{q.ask[:24]}", "question", 0,
                           (q.about,) if q.about else (), q.ask, numbers={"why": q.why}))

    # One finding per key: a hard break and its shortfall say the same thing once.
    seen, unique = set(), []
    for f in sorted(out, key=lambda f: (-f.severity, f.kind == "good", f.key)):
        if f.key not in seen:
            seen.add(f.key)
            unique.append(f)
    return unique


def _pinched_by(room: Room, needs: RoomNeeds, a: Assessment, pid: str, need: str, side: str,
                width: float) -> tuple[str, ...]:
    """What makes the way to a piece's side narrow. Below a hand's width there is no
    corridor to find a gate in: the side itself is the pinch, so name what crowds it."""
    _, who = a.free_depths.get((pid, need, side), (0.0, ()))
    crowders = tuple(p for p in who if p != "wall")
    if width < 0.15:
        return crowders
    return pinch(room, needs, a.poses, pid, need, side, width) or crowders


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def _zone_finding(room: Room, z, s: Shortfall, hard: bool) -> Finding:
    owner, who = the(room, z.piece), [the(room, p) for p in s.intruders if p != "wall"]
    by = _list(who) if who else "the wall"
    sev = 3 if hard else (2 if z.strength == "hard" else 1)
    kind = "problem" if hard else "tight"
    key = f"zone:{z.piece}:{z.need}:{z.side}"
    nums = {"free": round(s.free, 2), "comfortable": round(s.comfortable, 2)}
    if z.need == "open":
        p = room.pieces[z.piece]
        verb = "swing" if p.opening else ("drawers" if z.mechanism == "drawers" else "doors")
        if s.free < 0.05:
            text = f"{_cap(by)} {'reach' if len(who) > 1 else 'reaches'} into the swing of {owner}." if verb == "swing" else \
                   f"{_cap(by)} {'stand' if len(who) > 1 else 'stands'} where {owner}'s {verb} open."
        else:
            text = (f"{_cap(owner)} has {about(s.free)} to open before {by}; "
                    f"its {'door' if verb == 'swing' else verb} {'needs' if verb == 'swing' else 'need'} "
                    f"{about(s.comfortable, down=False)}.")
        return Finding(key, kind, sev, (z.piece, *s.intruders), text, numbers=nums)
    if z.need in ("use", "get_in"):
        where = "beside" if z.side in ("left", "right") else ("behind" if z.side == "back" else "in front of")
        text = f"{_cap(where)} {owner} there's {about(s.free)} before {by}."
        if z.side in ("left", "right") and who:
            text = f"On the side of {owner} by {by}, there's {about(s.free)} of floor."
        return Finding(key, kind, sev, (z.piece, *s.intruders), text, z.say, nums)
    if z.need == "pass":
        text = f"The way through {owner} is {about(s.free)} wide where {by} {'stand' if len(who) > 1 else 'stands'}."
        return Finding(key, kind, sev, (z.piece, *s.intruders), text, z.say, nums)
    if z.need in ("air", "heat"):
        what = "in front of" if z.side == "front" else "from"
        text = f"{_cap(by)} {'are' if len(who) > 1 else 'is'} {about(s.free)} {what} {owner}."
        return Finding(key, kind, sev, (z.piece, *s.intruders), text, z.say, nums)
    text = f"{_cap(owner)} has {about(s.free)} clear where it needs {about(s.comfortable, down=False)}, by my estimate."
    return Finding(key, kind, sev, (z.piece, *s.intruders), text, numbers=nums)


def side_phrase(room: Room, a: Assessment, pid: str, need: str, side: str) -> str:
    """A piece's side the way a person points at it: "the side of the bed by the desk"."""
    if side in ("front", "back"):
        return f"the {side} of {the(room, pid)}"
    _, who = a.free_depths.get((pid, need, side), (0.0, ()))
    named = [p for p in who if p != "wall"]
    if named:
        return f"the side of {the(room, pid)} by {the(room, named[0])}"
    wall = _facing_wall(room, pid, side, a.poses[pid])
    return f"the side of {the(room, pid)} toward {wall_name(room, wall)}" if wall else f"the {side} side of {the(room, pid)}"


def _facing_wall(room: Room, pid: str, side: str, pose: Pose) -> str | None:
    p = room.pieces[pid]
    out = (math.cos(pose.yaw), -math.sin(pose.yaw)) if side == "right" else (-math.cos(pose.yaw), math.sin(pose.yaw))
    best, best_d = None, math.inf
    for w in room.walls:
        facing = -(out[0] * w.normal[0] + out[1] * w.normal[1])
        if facing < 0.9:
            continue
        d = w.offset_of((pose.x, pose.z))
        if 0 < d < best_d:
            best, best_d = w.id, d
    return best


def _pinch_finding(room: Room, pid: str, need: str, side: str, width: float, pieces: tuple[str, ...],
                   severity: int, goal: str) -> Finding:
    door = next((p[5:] for p in pieces if p.startswith("door:")), None)
    rest = [p for p in pieces if not p.startswith("door:")]
    names = [the(room, p) if not p.startswith("wall:") else wall_name(room, p[5:]) for p in rest]
    names = [n for n in names if n not in goal]          # already named in "the side ... by X"
    if door:
        where = f" at {the(room, door)}" + (f", by {_list(names)}" if names else "")
    else:
        where = f", between {_list(names)}" if len(names) == 2 else (f", by {names[0]}" if names else "")
    text = f"The way to {goal} narrows to {about(width)}{where}."
    return Finding(f"path:{pid}:{need}:{side}", "problem" if severity == 3 else "tight", severity,
                   (pid, *[p for p in pieces if not p.startswith(("wall:", "door:"))]), text,
                   size_for("pass").say, {"width": round(width, 2)})


def _bond_finding(room: Room, s: Shortfall) -> Finding:
    follower, anchor = the(room, s.piece), the(room, s.intruders[0])
    text = {
        "at": f"{_cap(follower)} isn't at {anchor}.",
        "beside": f"{_cap(follower)} isn't beside {anchor}.",
        "over": f"{_cap(follower)} no longer hangs over {anchor}.",
        "near": f"{_cap(follower)} is a long way from {anchor}.",
        "facing": f"{_cap(follower)} doesn't face {anchor}.",
    }[s.side]
    return Finding(f"with:{s.piece}:{s.side}", "tight", 2 if s.strength == "hard" else 1,
                   (s.piece, s.intruders[0]), text)


LIGHT_WORDS = {
    ("screen", "behind"): ("light", 2, "Sitting at {p}, the window is behind you, so daylight falls on the screen."),
    ("screen", "front"): ("light", 1, "At {p} you face the window, which backlights the screen."),
    ("screen", "side"): ("good", 0, "{P} takes its daylight from the side, which is kindest to a screen."),
    ("reading", "behind"): ("good", 0, "At {p} the daylight comes over your shoulder, which is good for reading."),
    ("reading", "front"): ("light", 1, "At {p} you read facing the window, into the light."),
    ("reading", "side"): ("good", 0, "At {p} the daylight falls across the page from the side."),
    ("dressing", "front"): ("good", 0, "At {p} you face the window, the best light to see yourself in."),
    ("dressing", "side"): ("light", 1, "At {p} the daylight comes from the side."),
    ("dressing", "behind"): ("light", 1, "At {p} the window is behind you, so your face is in shadow."),
    ("work", "behind"): ("light", 1, "At {p} the window is behind you, so you work in your own shadow."),
    ("work", "front"): ("light", 1, "At {p} you face the window, into the glare."),
    ("work", "side"): ("good", 0, "{P} takes its daylight from the side."),
}


def _pref_finding(room: Room, needs: RoomNeeds, p: PrefResult, poses: dict[str, Pose]) -> Finding | None:
    name = the(room, p.piece) if p.piece else ""
    if p.pref == "task_light":
        words = LIGHT_WORDS.get((p.detail.get("task"), p.detail.get("light")))
        if not words:
            return None
        kind, sev, text = words
        sev = sev + (1 if kind == "light" and p.weight >= 3 and sev else 0)
        return Finding(f"pref:task_light:{p.piece}", kind, min(sev, 2), (p.piece,),
                       text.format(p=name, P=_cap(name)), numbers={"light": p.detail.get("light")})
    if p.pref == "back_to_wall":
        if p.value >= 1.0:
            return Finding(f"pref:back:{p.piece}", "good", 0, (p.piece,), f"{_cap(name)} has its back to a solid wall.")
        if p.value > 0:
            return Finding(f"pref:back:{p.piece}", "light", 1, (p.piece,), f"{_cap(name)} has its back under a window.")
        return Finding(f"pref:back:{p.piece}", "tight", 1, (p.piece,), f"{_cap(name)} doesn't have its back to a wall.")
    if p.pref == "see_door" and p.value < 1.0:
        return Finding(f"pref:door:{p.piece}", "tight", 1, (p.piece,), f"From {name} the door is behind you.")
    if p.pref == "centred" and p.value < 0.8:
        wall = backing_wall(room, p.piece, poses[p.piece])
        where = f" on {wall_name(room, wall)}" if wall else ""
        return Finding(f"pref:centred:{p.piece}", "tight", 1, (p.piece,), f"{_cap(name)} sits off centre{where}.")
    if p.pref == "open_floor":
        area = p.detail.get("area", 0.0)
        r = math.floor(area * 4) / 4
        return Finding("pref:open_floor", "light", 0, (),
                       f"The largest clear patch of floor is about {r:g} square metres.", numbers={"area": round(area, 2)})
    if p.pref == "balance" and p.value < 0.6:
        return Finding("pref:balance", "tight", 1, (), "Most of the room's weight sits to one side.")
    return None


def room_line(room: Room) -> str:
    xs, zs = room.footprint[:, 0], room.footprint[:, 1]
    w, d = sorted((xs.max() - xs.min(), zs.max() - zs.min()), reverse=True)
    return (f"{_cap(room.kind)}, {about(w, down=False)[6:]} by {about(d, down=False)[6:]}, "
            f"with a ceiling of {about(room.height, down=False)}.")
