"""Assessing an arrangement: which laws and needs it breaks, and how well it meets the rest.

One assessment of a room arrangement gives:
  - breaks: laws 1, 2, 3 and 5; law 4 (every place a person uses something can
    be reached from a way in by a person-sized path); and the hard needs (a
    keep-clear zone intruded below its hard depth, a reach target covered or
    out of reach, a sight line blocked, a window mostly covered).
  - shortfalls: how far each zone falls short of comfortable, and soft needs.
  - paths: the widest way from a way in to each place a person uses.
  - preferences: how well the room meets each preference, 0 to 1, with what
    decided it (where the window falls, whether a back is to a wall).

Law 6, extended to needs: a break the scanned room already has is excused
while the pieces in it keep their scanned relation to each other (and, for a
path, while it gets no narrower). An arrangement is valid when every break it
has is excused.

Read by: analyzer.py, engine.py.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from . import laws
from .geometry import Box, FloorGrid, box_inside_polygon, clearance, flood, footprint_penetration, \
    largest_open_rectangle, penetration, widest_path
from .model import Arrangement, Pose, Room
from .needs import WEIGHTS, RoomNeeds, Target, Zone, entrances, targets, zone_box, zones
from .rulebook import BODY_TOP, EYE_HEIGHT, LIGHT_DEPTH, PERSON_PATH, size_for

GRID_CELL = 0.05
DOORWAY_DEPTH = 0.35      # how far into the room a doorway's threshold cells reach
USER_OFFSET = 0.45        # where a person using a piece from the front stands or sits
STEP_HEIGHT = 0.05        # solids lower than this don't block walking

_grids: dict[tuple, FloorGrid] = {}


def floor_grid(room: Room) -> FloorGrid:
    key = (room.footprint.tobytes(), GRID_CELL)
    if key not in _grids:
        _grids[key] = FloorGrid.over(room.footprint, GRID_CELL)
    return _grids[key]


@dataclass(frozen=True)
class Break:
    kind: str                  # overlap | outside | unsupported | fixed_moved | unreachable |
                               # zone | covered | out_of_reach | unseen | dark
    pieces: tuple[str, ...]    # the piece the need belongs to first, then what breaks it
    law: int | None = None
    need: str | None = None
    side: str | None = None
    amount: float = 0.0        # free depth, path width, distance or covered share

    @property
    def key(self) -> tuple:
        return (self.kind, self.need, self.side, self.pieces[0], tuple(sorted(self.pieces[1:])))


@dataclass(frozen=True)
class Shortfall:
    piece: str
    need: str
    side: str
    free: float
    comfortable: float
    intruders: tuple[str, ...]
    strength: str

    @property
    def short(self) -> float:
        return max(0.0, self.comfortable - self.free)


@dataclass(frozen=True)
class PrefResult:
    pref: str
    piece: str | None
    value: float               # 0 (badly met) .. 1 (fully met)
    weight: float
    detail: dict = field(default_factory=dict)


@dataclass
class Assessment:
    breaks: list[Break]
    shortfalls: list[Shortfall]
    paths: dict[tuple[str, str, str], float]
    preferences: list[PrefResult]
    poses: dict[str, Pose]
    free_depths: dict[tuple[str, str, str], tuple[float, tuple[str, ...]]] = field(default_factory=dict)
    reach: dict[str, float] = field(default_factory=dict)

    def unexcused(self, baseline: "Assessment", room: Room, arrangement: Arrangement) -> list[Break]:
        """Breaks this arrangement has that the scanned room does not excuse (law 6)."""
        base = {b.key: b for b in baseline.breaks}
        out = []
        for b in self.breaks:
            old = base.get(b.key)
            if old is None:
                out.append(b)
            elif b.kind == "unreachable":
                if b.amount < old.amount - 0.01:
                    out.append(b)
            elif b.kind == "out_of_reach":
                if b.amount > old.amount + 0.01:
                    out.append(b)
            elif b.kind in ("unseen", "dark"):
                if b.amount > old.amount + 0.01 or not _unchanged(room, arrangement, b.pieces):
                    out.append(b)
            elif not _unchanged(room, arrangement, b.pieces):
                out.append(b)
        return out

    def valid(self, baseline: "Assessment", room: Room, arrangement: Arrangement) -> bool:
        return not self.unexcused(baseline, room, arrangement)


def _unchanged(room: Room, arrangement: Arrangement, pieces: tuple[str, ...]) -> bool:
    """Whether these pieces stand as the scan had them relative to each other
    (one piece: where the scan put it)."""
    real = [p for p in pieces if p in room.pieces]
    if not real:
        return True
    if len(real) == 1:
        return real[0] not in laws.moved_ids(room, arrangement)
    return laws.kept_together(room, arrangement, real)


# ---------------------------------------------------------------- solids at poses

def _blocking_solids(room: Room, poses: dict[str, Pose], exempt: frozenset[str]) -> list[tuple[str, Box]]:
    out = []
    for pid, p in room.pieces.items():
        if pid in exempt or not laws.collides(p):
            continue
        for s in p.solids(poses[pid]):
            out.append((pid, s))
    return out


def _intruders(box: Box, solids: list[tuple[str, Box]]) -> list[str]:
    hit = []
    for pid, s in solids:
        if pid in hit:
            continue
        if penetration(box, s) > laws.OVERLAP_EPS:
            hit.append(pid)
    return hit


def free_depth(room: Room, zone: Zone, poses: dict[str, Pose],
               solids: list[tuple[str, Box]] | None = None) -> tuple[float, tuple[str, ...]]:
    """How deep the zone is clear, up to its comfortable depth, and what stops it.

    "wall" stands for the room's edge.
    """
    piece = room.pieces[zone.piece]
    pose = poses[zone.piece]
    solids = solids if solids is not None else _blocking_solids(room, poses, zone.exempt)
    top = max(zone.comfortable, zone.hard)
    full = zone_box(piece, zone, pose, top)
    near = [(pid, s) for pid, s in solids if footprint_penetration(full, s) > 0]

    def blocked(d: float) -> list[str]:
        b = zone_box(piece, zone, pose, d)
        hit = _intruders(b, near)
        if not box_inside_polygon(b, room.footprint, laws.SHELL_TOL):
            hit.append("wall")
        return hit

    at_top = blocked(top)
    if not at_top:
        return top, ()
    lo, hi = 0.0, top
    while hi - lo > 0.005:
        mid = (lo + hi) / 2
        if blocked(mid):
            hi = mid
        else:
            lo = mid
    return lo, tuple(blocked(min(top, hi + 0.01)) or at_top)


# ---------------------------------------------------------------- the assessment

def assess(room: Room, needs: RoomNeeds, arrangement: Arrangement | None = None,
           *, paths: bool = True) -> Assessment:
    arrangement = arrangement or {}
    poses = laws.all_poses(room, arrangement)
    breaks: list[Break] = [Break(v.kind, v.pieces, v.law, amount=v.amount)
                           for v in laws.check(room, arrangement, fixed=needs.fixed_ids())]
    shortfalls: list[Shortfall] = []
    depths: dict[tuple[str, str, str], tuple[float, tuple[str, ...]]] = {}

    all_zones = zones(room, needs)
    for z in all_zones:
        solids = _blocking_solids(room, poses, z.exempt)
        depth, who = free_depth(room, z, poses, solids)
        depths[(z.piece, z.need, z.side)] = (depth, who)
        if z.strength == "hard" and depth < z.hard - 0.005:
            breaks.append(Break("zone", (z.piece, *who), need=z.need, side=z.side, amount=depth))
        if depth < z.comfortable - 0.005:
            shortfalls.append(Shortfall(z.piece, z.need, z.side, depth, z.comfortable, who, z.strength))

    path_widths: dict[tuple[str, str, str], float] = {}
    reach_dist: dict[str, float] = {}
    grid = floor_grid(room)
    walk = None
    if paths or any(t.need in ("reach", "see") for t in targets(room, needs)):
        walk = _walkable(room, needs, poses, grid)

    if paths and walk is not None:
        clear, sources, reachable = walk
        for z in all_zones:
            if z.need not in ("use", "get_in"):
                continue
            box = zone_box(room.pieces[z.piece], z, poses[z.piece], max(z.hard, 0.3))
            cells = grid.inside & grid.in_box(box)
            w = widest_path(clear, sources, cells, grid.shape) if cells.any() and sources.any() else 0.0
            path_widths[(z.piece, z.need, z.side)] = w
            if w < PERSON_PATH - 0.01:
                if z.strength == "hard":
                    breaks.append(Break("unreachable", (z.piece,), 4, z.need, z.side, w))
                else:
                    shortfalls.append(Shortfall(z.piece, "pass", z.side, w, PERSON_PATH, (), "soft"))

    for t in targets(room, needs):
        if t.need == "reach":
            breaks_, short_, dist = _reach(room, t, poses, grid, walk)
            breaks += breaks_
            shortfalls += short_
            reach_dist[t.piece] = dist
        elif t.need == "see":
            b, s = _see(room, t, poses, grid, walk)
            breaks += b
            shortfalls += s
        elif t.need == "light":
            b, s = _light(room, t, poses)
            breaks += b
            shortfalls += s

    prefs = preferences(room, needs, poses, grid) if paths else []
    return Assessment(breaks, shortfalls, path_widths, prefs, poses, depths, reach_dist)


def solid_walls(room: Room) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """The stretches of wall a person can't walk through: every wall minus its doorways."""
    out = []
    for w in room.walls:
        cuts = sorted((op.u0, op.u1) for op in room.openings if op.wall == w.id and op.kind == "door")
        u = 0.0
        for u0, u1 in cuts:
            if u0 > u:
                out.append((w.point(u), w.point(u0)))
            u = max(u, u1)
        if u < w.length:
            out.append((w.point(u), w.point(w.length)))
    return out


def _walkable(room: Room, needs: RoomNeeds, poses: dict[str, Pose], grid: FloorGrid):
    blockers = [s for pid, p in room.pieces.items() if laws.collides(p)
                for s in p.solids(poses[pid]) if s.y0 < BODY_TOP and s.y1 > STEP_HEIGHT]
    clear = clearance(grid, blockers, room.footprint, solid_walls(room))
    sources = np.zeros(len(grid.points), dtype=bool)
    for door in entrances(room, needs):
        piece = room.pieces[door]
        pose = poses[door]
        threshold = Box(*pose.place(0.0, DOORWAY_DEPTH / 2), piece.size[0] / 2, DOORWAY_DEPTH / 2,
                        pose.yaw, 0.0, 2.0)
        sources |= grid.inside & grid.in_box(threshold)
    walk_ok = clear >= PERSON_PATH / 2
    reachable = flood(sources & walk_ok, walk_ok, grid.shape)
    return clear, sources, reachable


def _face(room: Room, piece_id: str, pose: Pose) -> tuple[np.ndarray, np.ndarray, float, float, float]:
    """A piece's front face: centre (x, z), front direction, width, bottom and top."""
    p = room.pieces[piece_id]
    sx, sy, sz = p.size
    c = np.array(pose.place(0.0, sz / 2))
    f = np.array([math.sin(pose.yaw), math.cos(pose.yaw)])
    return c, f, sx, pose.y, pose.y + sy


def _reach(room: Room, t: Target, poses, grid: FloorGrid, walk):
    size = size_for("reach")
    piece = room.pieces[t.piece]
    pose = poses[t.piece]
    sx, sy, sz = piece.size
    front = Box(*pose.place(0.0, sz / 2 + 0.1), sx / 2, 0.1, pose.yaw, pose.y, pose.y + sy)
    solids = _blocking_solids(room, poses, t.exempt)
    breaks, shorts = [], []
    covering = _intruders(front, solids)
    if covering and t.strength == "hard":
        breaks.append(Break("covered", (t.piece, *covering), need="reach"))
    dist = math.inf
    if walk is not None:
        _, _, reachable = walk
        c, _, _, _, _ = _face(room, t.piece, pose)
        pts = grid.points[reachable]
        if len(pts):
            # Reach is measured from the front of the body, which stands half a
            # person's width in front of the spot it occupies.
            centre = float(np.min(np.hypot(pts[:, 0] - c[0], pts[:, 1] - c[1])))
            dist = max(0.0, centre - PERSON_PATH / 2)
    if dist > size.hard and t.strength == "hard":
        breaks.append(Break("out_of_reach", (t.piece,), need="reach", amount=dist))
    if dist > size.comfortable:
        shorts.append(Shortfall(t.piece, "reach", "front", -dist, -size.comfortable, tuple(covering), t.strength))
    return breaks, shorts, dist


def _see(room: Room, t: Target, poses, grid: FloorGrid, walk):
    size = size_for("see")
    pose = poses[t.piece]
    c, f, width, y0, y1 = _face(room, t.piece, pose)
    target = np.array([c[0], (y0 + y1) / 2, c[1]])
    eye = EYE_HEIGHT.get(t.posture or "standing", 1.6)
    seen = False
    if walk is not None:
        _, _, reachable = walk
        pts = grid.points[reachable]
        rel = pts - c
        dist = np.hypot(rel[:, 0], rel[:, 1])
        ahead = (rel @ f) >= 0.3 * dist
        ok = ahead & (dist >= size.comfortable) & (dist <= size.hard)
        cand = pts[ok]
        order = np.argsort(np.abs(dist[ok] - 1.2))[:40]
        solids = [s for _, s in _blocking_solids(room, poses, t.exempt)]
        for i in order:
            p = cand[i]
            start = np.array([p[0], eye, p[1]])
            n = max(2, int(np.linalg.norm(target - start) / 0.05))
            samples = start + (target - start) * np.linspace(0.0, 0.95, n)[:, None]
            if not any(_points_in_box(samples, s) for s in solids):
                seen = True
                break
    breaks, shorts = [], []
    if not seen:
        if t.strength == "hard":
            breaks.append(Break("unseen", (t.piece,), need="see", amount=1.0))
        shorts.append(Shortfall(t.piece, "see", "front", 0.0, 1.0, (), t.strength))
    return breaks, shorts


def _points_in_box(pts: np.ndarray, b: Box) -> bool:
    loc = b.to_local(pts[:, [0, 2]])
    inside = (np.abs(loc[:, 0]) < b.hx) & (np.abs(loc[:, 1]) < b.hz) & (pts[:, 1] > b.y0) & (pts[:, 1] < b.y1)
    return bool(inside.any())


def window_cover(room: Room, piece_id: str, poses: dict[str, Pose], exempt=frozenset()) -> tuple[float, tuple[str, ...]]:
    """Share of a window's opening hidden by solids standing in its light, and what hides it."""
    piece = room.pieces[piece_id]
    if piece.opening is None:
        return 0.0, ()
    op = room.opening(piece.opening)
    wall = room.wall(op.wall)
    us = np.arange(op.u0 + 0.025, op.u1, 0.05)
    vs = np.arange(op.v0 + 0.025, op.v1, 0.05)
    if not len(us) or not len(vs):
        return 0.0, ()
    covered = np.zeros((len(vs), len(us)), dtype=bool)
    who = []
    for pid, s in _blocking_solids(room, poses, exempt | {piece_id}):
        corners = s.corners()
        offs = [wall.offset_of(tuple(c)) for c in corners]
        if min(offs) > LIGHT_DEPTH:
            continue
        u = [wall.u_of(tuple(c)) for c in corners]
        mask = ((us >= min(u)) & (us <= max(u)))[None, :] & ((vs >= s.y0) & (vs <= s.y1))[:, None]
        if mask.any():
            covered |= mask
            if pid not in who:
                who.append(pid)
    return float(covered.mean()), tuple(who)


def _light(room: Room, t: Target, poses):
    share, who = window_cover(room, t.piece, poses, t.exempt)
    breaks, shorts = [], []
    if share > 0.5 and t.strength == "hard":
        breaks.append(Break("dark", (t.piece, *who), need="light", amount=share))
    if share > 0.05:
        shorts.append(Shortfall(t.piece, "light", "front", 1.0 - share, 1.0, who, t.strength))
    return breaks, shorts


# ---------------------------------------------------------------- preferences

TASK_LIGHT = {
    "screen": {"side": 1.0, "front": 0.5, "behind": 0.0},
    "reading": {"side": 1.0, "behind": 0.8, "front": 0.5},
    "dressing": {"front": 1.0, "side": 0.8, "behind": 0.3},
    "work": {"side": 1.0, "front": 0.6, "behind": 0.3},
    "conversation": {"side": 0.9, "front": 0.8, "behind": 0.8},
    "sleep": {"side": 1.0, "front": 1.0, "behind": 1.0},
}


def user_at(room: Room, piece_id: str, pose: Pose, viewer: str) -> tuple[np.ndarray, np.ndarray]:
    """Where a person using the piece is, and which way they face."""
    sz = room.pieces[piece_id].size[2]
    f = np.array([math.sin(pose.yaw), math.cos(pose.yaw)])
    if viewer == "facing_piece":
        return np.array(pose.place(0.0, sz / 2 + USER_OFFSET)), -f
    return np.array([pose.x, pose.z]), f


def windows(room: Room) -> list[tuple[str, np.ndarray, float]]:
    """Each window piece with its opening's centre on the floor plan and its area."""
    out = []
    for pid, p in room.pieces.items():
        if p.opening is None:
            continue
        op = room.opening(p.opening)
        if op.kind != "window":
            continue
        wall = room.wall(op.wall)
        out.append((pid, np.array(wall.point((op.u0 + op.u1) / 2)), op.width * (op.v1 - op.v0)))
    return out


def light_direction(room: Room, user: np.ndarray, facing: np.ndarray) -> tuple[str | None, str | None]:
    """Where the strongest window falls for a person here: "front", "side" or "behind"."""
    best, best_w = None, 0.0
    for pid, c, area in windows(room):
        d = c - user
        dist = float(np.hypot(*d))
        if dist < 1e-6:
            continue
        w = area / max(dist, 0.5) ** 2
        if w > best_w:
            best, best_w = (pid, d / dist), w
    if best is None:
        return None, None
    cos = float(best[1] @ facing)
    kind = "front" if cos > math.cos(math.radians(50)) else "behind" if cos < math.cos(math.radians(130)) else "side"
    return kind, best[0]


def backing_wall(room: Room, piece_id: str, pose: Pose, tol: float = 0.1) -> str | None:
    """The wall the piece's back is against at this pose, if any."""
    sz = room.pieces[piece_id].size[2]
    back = pose.place(0.0, -sz / 2)
    f = (math.sin(pose.yaw), math.cos(pose.yaw))
    for w in room.walls:
        if abs(w.offset_of(back)) <= tol and f[0] * w.normal[0] + f[1] * w.normal[1] > 0.97:
            u = w.u_of(back)
            if -0.05 <= u <= w.length + 0.05:
                return w.id
    return None


def preferences(room: Room, needs: RoomNeeds, poses: dict[str, Pose], grid: FloorGrid) -> list[PrefResult]:
    out = []
    for p in needs.preferences:
        weight = WEIGHTS[p.weight]
        if p.pref == "task_light" and p.piece:
            user, facing = user_at(room, p.piece, poses[p.piece], p.viewer or "facing_piece")
            kind, win = light_direction(room, user, facing)
            if kind is None:
                continue
            out.append(PrefResult("task_light", p.piece, TASK_LIGHT[p.task or "work"][kind], weight,
                                  {"light": kind, "window": win, "task": p.task}))
        elif p.pref == "back_to_wall" and p.piece:
            w = backing_wall(room, p.piece, poses[p.piece])
            value = 1.0 if w else 0.0
            if w and _window_behind(room, p.piece, poses[p.piece], w):
                value = 0.6
            out.append(PrefResult("back_to_wall", p.piece, value, weight, {"wall": w}))
        elif p.pref == "see_door" and p.piece:
            user, facing = user_at(room, p.piece, poses[p.piece], p.viewer or "facing_piece")
            best = 0.0
            for door in entrances(room, needs):
                d = np.array([poses[door].x, poses[door].z]) - user
                n = float(np.hypot(*d))
                if n > 1e-6:
                    best = max(best, 1.0 if float(d @ facing) / n > math.cos(math.radians(100)) else 0.3)
            out.append(PrefResult("see_door", p.piece, best, weight, {}))
        elif p.pref == "centred" and p.piece:
            w = backing_wall(room, p.piece, poses[p.piece])
            if w:
                wall = room.wall(w)
                u = wall.u_of((poses[p.piece].x, poses[p.piece].z))
                off = abs(u - wall.length / 2)
                out.append(PrefResult("centred", p.piece, max(0.0, 1.0 - off / (wall.length / 2)), weight,
                                      {"off_centre": off}))
        elif p.pref == "open_floor":
            out.append(PrefResult("open_floor", None, open_floor(room, poses, grid) / floor_area(room), weight,
                                  {"area": open_floor(room, poses, grid)}))
        elif p.pref == "balance":
            out.append(PrefResult("balance", None, _balance(room, poses), weight, {}))
    return out


def _window_behind(room: Room, piece_id: str, pose: Pose, wall_id: str) -> bool:
    p = room.pieces[piece_id]
    wall = room.wall(wall_id)
    u = wall.u_of((pose.x, pose.z))
    half = p.size[0] / 2
    for op in room.openings:
        if op.wall == wall_id and op.kind == "window" and op.u0 < u + half and op.u1 > u - half:
            return True
    return False


def floor_area(room: Room) -> float:
    x, z = room.footprint[:, 0], room.footprint[:, 1]
    return float(abs(np.dot(x, np.roll(z, -1)) - np.dot(z, np.roll(x, -1))) / 2)


def open_floor(room: Room, poses: dict[str, Pose], grid: FloorGrid) -> float:
    """Area of the largest clear rectangle of floor, in square metres."""
    occupied = np.zeros(len(grid.points), dtype=bool)
    for pid, p in room.pieces.items():
        if not laws.collides(p) or p.support in ("wall", "ceiling"):
            continue
        for s in p.solids(poses[pid]):
            if s.y0 < BODY_TOP:
                occupied |= grid.in_box(s, grow=GRID_CELL / 2)
    free = grid.inside & ~occupied
    return largest_open_rectangle(free, grid.shape) * grid.cell ** 2


def _balance(room: Room, poses: dict[str, Pose]) -> float:
    total, cx, cz = 0.0, 0.0, 0.0
    for pid, p in room.pieces.items():
        if not laws.collides(p) or p.support != "floor":
            continue
        v = p.size[0] * p.size[1] * p.size[2]
        total += v
        cx += v * poses[pid].x
        cz += v * poses[pid].z
    if total == 0:
        return 1.0
    centre = room.footprint.mean(axis=0)
    half_diag = float(np.hypot(*(room.footprint.max(axis=0) - room.footprint.min(axis=0)))) / 2
    off = float(np.hypot(cx / total - centre[0], cz / total - centre[1]))
    return max(0.0, 1.0 - off / half_diag)
