"""The laws: what holds in every room, whatever is in it.

1. Solids never overlap. Something lying flat on the floor, like a rug, can be
   stood on, so it collides with nothing.
2. Everything stays inside the room: on the floor polygon and under the ceiling.
3. Everything rests on something, and what rests on a piece moves with it.
4. Every place a person must stand to use something can be reached from an
   entrance by a person-sized path. The places come from the room's needs, so
   this law is checked in needs.py.
5. Fixed things don't move.
6. Nothing is made worse than the scanned room without saying so. A violation
   the scan already has is the baseline. It is kept, not counted against a
   proposal, for as long as the pieces in it stay where the scan put them or
   move together.

The laws name no furniture type and no piece. They are about solids, the shell
and people, which is why they hold in every room. Everything a room needs
beyond them comes from its needs (needs.py), which Claude writes per room.

A door or window piece fills a hole in the shell: its usable space belongs to
its needs (open, pass, light), not to law 1, so it never collides.

Read by: needs.py, analyzer.py, engine.py, motion.py (laws 1, 2, 3 and 5 hold
in transit too).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .geometry import Box, box_inside_polygon, footprint_penetration, penetration, vertical_overlap
from .model import Arrangement, Piece, Pose, Room, carry, pose_in

# Interpenetration below this is measurement noise, not a collision.
OVERLAP_EPS = 0.01
# A piece on the floor no taller than this can be stood on (a rug, a mat).
FLAT = 0.03
# How far a part may poke past the floor's edge or the ceiling before it counts.
SHELL_TOL = 0.01
# A rider's footprint centre may sit this far outside its support's top.
SUPPORT_TOL = 0.03


@dataclass(frozen=True)
class Violation:
    law: int
    kind: str                 # overlap | outside | unsupported | fixed_moved | unreachable
    pieces: tuple[str, ...]
    amount: float = 0.0       # how deep, how far, how narrow: in metres

    @property
    def key(self) -> tuple[str, tuple[str, ...]]:
        return (self.kind, tuple(sorted(self.pieces)))


def collides(piece: Piece) -> bool:
    """Whether law 1 applies to the piece at all."""
    if piece.opening is not None:
        return False
    return not (piece.support == "floor" and piece.size[1] <= FLAT)


def solids_at(piece: Piece, pose: Pose) -> list[Box]:
    return piece.solids(pose)


def pair_penetration(a: Piece, pa: Pose, b: Piece, pb: Pose) -> float:
    """How deep two pieces' solids interpenetrate at these poses (<= 0: apart).

    Each piece's parts are first tested against the other's whole box, so only
    the parts that could touch are tested against each other.
    """
    ba, bb = a.box(pa), b.box(pb)
    if footprint_penetration(ba, bb) <= 0 or vertical_overlap(ba, bb) <= 0:
        return -1.0
    sa = [s for s in a.solids(pa) if penetration(s, bb) > 0]
    if not sa:
        return -1.0
    sb = [s for s in b.solids(pb) if penetration(s, ba) > 0]
    best = -1.0
    for x in sa:
        for y in sb:
            best = max(best, penetration(x, y))
    return best


def _resting_pair(a: Piece, b: Piece) -> bool:
    return (a.support == "object" and a.on == b.id) or (b.support == "object" and b.on == a.id)


def all_poses(room: Room, arrangement: Arrangement) -> dict[str, Pose]:
    return {pid: pose_in(room, arrangement, pid) for pid in room.pieces}


def moved_ids(room: Room, arrangement: Arrangement) -> set[str]:
    return {pid for pid, p in arrangement.items() if not p.same_as(room.pieces[pid].pose)}


def overlaps(room: Room, poses: dict[str, Pose], among: Iterable[str] | None = None) -> list[Violation]:
    """Law 1. With `among`, only pairs that include one of those pieces."""
    ids = [pid for pid, p in room.pieces.items() if collides(p)]
    focus = set(among) if among is not None else None
    out = []
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            if focus is not None and a not in focus and b not in focus:
                continue
            pa, pb = room.pieces[a], room.pieces[b]
            if _resting_pair(pa, pb):
                continue
            depth = pair_penetration(pa, poses[a], pb, poses[b])
            if depth > OVERLAP_EPS:
                out.append(Violation(1, "overlap", (a, b), depth))
    return out


def outside(room: Room, poses: dict[str, Pose], among: Iterable[str] | None = None) -> list[Violation]:
    """Law 2, for everything that stands on the floor or on something that does."""
    out = []
    for pid in (among if among is not None else room.pieces):
        p = room.pieces[pid]
        if p.support in ("wall", "ceiling") or p.opening is not None:
            continue
        for s in p.solids(poses[pid]):
            if s.y1 > room.height + SHELL_TOL or not box_inside_polygon(s, room.footprint, SHELL_TOL):
                out.append(Violation(2, "outside", (pid,)))
                break
    return out


def unsupported(room: Room, poses: dict[str, Pose], among: Iterable[str] | None = None) -> list[Violation]:
    """Law 3: a rider stays on top of what it rests on."""
    out = []
    for pid in (among if among is not None else room.pieces):
        p = room.pieces[pid]
        if p.support != "object" or p.on not in room.pieces:
            continue
        s = room.pieces[p.on]
        sb = s.box(poses[s.id])
        pose = poses[pid]
        top = sb.y1
        loc = sb.to_local([[pose.x, pose.z]])[0]
        on_top = abs(loc[0]) <= sb.hx + SUPPORT_TOL and abs(loc[1]) <= sb.hz + SUPPORT_TOL
        if not on_top or abs(pose.y - top) > SUPPORT_TOL:
            out.append(Violation(3, "unsupported", (pid, s.id)))
    return out


def fixed_moved(room: Room, poses: dict[str, Pose], fixed: Iterable[str]) -> list[Violation]:
    """Law 5."""
    return [Violation(5, "fixed_moved", (pid,)) for pid in fixed
            if pid in poses and not poses[pid].same_as(room.pieces[pid].pose)]


def check(room: Room, arrangement: Arrangement, *, fixed: Iterable[str] = (),
          among: Iterable[str] | None = None) -> list[Violation]:
    """Laws 1, 2, 3 and 5 for an arrangement (law 4 needs the room's needs)."""
    poses = all_poses(room, arrangement)
    among = list(among) if among is not None else None
    return (overlaps(room, poses, among) + outside(room, poses, among)
            + unsupported(room, poses, among) + fixed_moved(room, poses, fixed))


def kept_together(room: Room, arrangement: Arrangement, ids: Iterable[str]) -> bool:
    """Whether these pieces still stand as the scan had them relative to each other:
    none moved, or all moved by one rigid motion."""
    ids = list(ids)
    poses = all_poses(room, arrangement)
    ref = ids[0]
    frm, to = room.pieces[ref].pose, poses[ref]
    for pid in ids[1:]:
        expected = carry(room.pieces[pid].pose, frm, to)
        if not expected.same_as(poses[pid], tol=1e-4):
            return False
    return True


def new_violations(room: Room, arrangement: Arrangement, baseline: list[Violation],
                   *, fixed: Iterable[str] = ()) -> list[Violation]:
    """Law 6: violations the arrangement has that the scanned room did not already.

    A baseline violation stays allowed only while its pieces keep their scanned
    relation to each other (for one piece: while it hasn't moved).
    """
    moved = moved_ids(room, arrangement)
    if not moved:
        return []
    near = set(moved)
    for pid in list(moved):
        near.update(room.riders(pid))
    base = {v.key for v in baseline}
    out = []
    for v in check(room, arrangement, fixed=fixed, among=near):
        if v.key in base and (kept_together(room, arrangement, v.pieces) if len(v.pieces) > 1
                              else v.pieces[0] not in moved):
            continue
        out.append(v)
    return out
