"""The motion planner: a proposal's moves, played so nothing passes through anything.

A proposal says where pieces end up; this says how they get there. Pieces move
one unit at a time (a unit is a piece standing on the floor together with
whatever rests on it), in an order that never asks a piece to move into a spot
another still occupies. When two pieces need each other's places, one waits in
a parking spot on free floor first, the way people shuffle furniture.

Each unit's path is the first of these that stays clear:
  1. straight there, turning as it goes;
  2. pulled out from its wall first, moved, then pushed back in;
  3. a search over the floor (10 cm steps, eighth turns);
  4. lifted just clear of what is in the way, carried over, and set down.

The whole plan is then sampled at 60 frames a second, with the same easing the
viewer uses, and refused unless every frame keeps laws 1 and 2 for every piece.

The plan is the viewer's contract (`plan_json`): per piece, keyframes of time,
position and turn; between two keyframes the viewer moves along the straight
line with smoothstep easing. It never overshoots, which is what lets a check of
the path stand for a check of the screen.

Read by: guide.py (a proposal's motion), the harness (sent to the viewer).
"""
from __future__ import annotations

import heapq
import math
import time
from dataclasses import dataclass, field

import numpy as np

from . import laws
from .assess import backing_wall, floor_grid
from .geometry import box_inside_polygon, penetration
from .model import Pose, Room, carry

PLAN_VERSION = 1
SPEED = 0.6               # metres a second
TURN_SPEED = math.pi / 2  # a quarter turn a second
MIN_SEGMENT = 0.5         # seconds
LIFT_TIME = 0.45
PAUSE = 0.15
FPS = 60
CHECK_STEP = 0.02         # metres between path checks while planning
CHECK_TURN = math.radians(3)
GRID = 0.1
YAWS = 8
SEARCH_SECONDS = 1.0     # a floor search that finds nothing by then is given up for a lift


class NoPath(Exception):
    def __init__(self, piece: str):
        super().__init__(f"no clear way to move {piece}")
        self.piece = piece


@dataclass(frozen=True)
class Key:
    t: float
    x: float
    y: float
    z: float
    yaw: float


@dataclass
class Plan:
    tracks: dict[str, list[Key]]
    order: list[str]
    duration: float
    frames_checked: int = 0
    parked: list[str] = field(default_factory=list)
    methods: dict[str, str] = field(default_factory=dict)


def smoothstep(u: float) -> float:
    u = min(1.0, max(0.0, u))
    return u * u * (3 - 2 * u)


def pose_at(keys: list[Key], t: float) -> Key:
    """Where a track is at time t, exactly as the viewer computes it."""
    if t <= keys[0].t:
        return keys[0]
    for a, b in zip(keys, keys[1:]):
        if t <= b.t:
            if b.t - a.t <= 1e-9:
                return b
            s = smoothstep((t - a.t) / (b.t - a.t))
            return Key(t, a.x + (b.x - a.x) * s, a.y + (b.y - a.y) * s, a.z + (b.z - a.z) * s,
                       a.yaw + (b.yaw - a.yaw) * s)
    return keys[-1]


# ---------------------------------------------------------------- collision while moving

@dataclass
class _World:
    room: Room
    static: dict[str, Pose]          # every piece not in the moving unit, where it stands now

    def unit_clear(self, unit: list[str], poses: dict[str, Pose]) -> bool:
        """Whether the unit, at these poses, keeps laws 1 and 2 against everything else."""
        for pid in unit:
            piece = self.room.pieces[pid]
            if not laws.collides(piece):
                continue
            for s in piece.solids(poses[pid]):
                if s.y1 > self.room.height + laws.SHELL_TOL:
                    return False
                if piece.support == "floor" and not box_inside_polygon(s, self.room.footprint, laws.SHELL_TOL):
                    return False
            for oid, op in self.static.items():
                other = self.room.pieces[oid]
                if oid in unit or not laws.collides(other):
                    continue
                if not _overlap_allowed(self.room, piece, poses[pid], other, op):
                    return False
        return True


def _overlap_allowed(room: Room, a, pa: Pose, b, pb: Pose) -> bool:
    """Law 1 in transit. An overlap the scan itself has (a stool drawn as a whole box
    inside a desk drawn as a whole box) may stay, or shrink, but never deepen."""
    depth = laws.pair_penetration(a, pa, b, pb)
    if depth <= laws.OVERLAP_EPS:
        return True
    scanned = laws.pair_penetration(a, a.pose, b, b.pose)
    return scanned > laws.OVERLAP_EPS and depth <= scanned + laws.OVERLAP_EPS


def _unit_poses(room: Room, unit: list[str], start: dict[str, Pose], lead: str, at: Pose) -> dict[str, Pose]:
    frm = start[lead]
    return {pid: (at if pid == lead else carry(start[pid], frm, at)) for pid in unit}


def _segment_clear(world: _World, room: Room, unit: list[str], start: dict[str, Pose], lead: str,
                   a: Pose, b: Pose) -> bool:
    dist = math.hypot(b.x - a.x, b.z - a.z) + abs(b.y - a.y)
    turn = abs(b.yaw - a.yaw)
    n = max(2, int(math.ceil(max(dist / CHECK_STEP, turn / CHECK_TURN))) + 1)
    for s in np.linspace(0.0, 1.0, n):
        p = Pose(a.x + (b.x - a.x) * s, a.y + (b.y - a.y) * s, a.z + (b.z - a.z) * s, a.yaw + (b.yaw - a.yaw) * s)
        if not world.unit_clear(unit, _unit_poses(room, unit, start, lead, p)):
            return False
    return True


def _unwrap(frm: float, to: float) -> float:
    """`to` as the nearest equivalent angle to `frm`, so a turn goes the short way."""
    return frm + math.remainder(to - frm, 2 * math.pi)


# ---------------------------------------------------------------- paths

def _path(world: _World, room: Room, unit: list[str], start: dict[str, Pose], lead: str,
          goal: Pose) -> tuple[list[Pose], str]:
    a = start[lead]
    g = Pose(goal.x, goal.y, goal.z, _unwrap(a.yaw, goal.yaw))
    if _segment_clear(world, room, unit, start, lead, a, g):
        return [a, g], "straight"
    # Pulled out from the wall first, the way a piece really leaves one.
    for out in (0.15, 0.3, 0.5):
        fa = (math.sin(a.yaw), math.cos(a.yaw))
        fg = (math.sin(g.yaw), math.cos(g.yaw))
        a2 = Pose(a.x + fa[0] * out, a.y, a.z + fa[1] * out, a.yaw)
        g2 = Pose(g.x + fg[0] * out, g.y, g.z + fg[1] * out, g.yaw)
        legs = [(a, a2), (a2, g2), (g2, g)]
        if all(_segment_clear(world, room, unit, start, lead, p, q) for p, q in legs):
            return [a, a2, g2, g], "pulled out"
    found = _search(world, room, unit, start, lead, a, g)
    if found:
        return found, "searched"
    lifted = _lift(world, room, unit, start, lead, a, g)
    if lifted:
        return lifted, "lifted"
    raise NoPath(lead)


def _search(world: _World, room: Room, unit, start, lead, a: Pose, g: Pose, budget: int = 4000) -> list[Pose] | None:
    """A* over the floor in 10 cm steps and eighth turns, joined to the exact start and goal."""
    def node_pose(n):
        ix, iz, iy = n
        return Pose(ix * GRID, a.y, iz * GRID, a.yaw + (iy - YAWS * 4) * (2 * math.pi / YAWS))

    def snap(p: Pose):
        iy = YAWS * 4 + int(round((p.yaw - a.yaw) / (2 * math.pi / YAWS)))
        return (int(round(p.x / GRID)), int(round(p.z / GRID)), iy)

    s_node, g_node = snap(a), snap(g)
    if not _segment_clear(world, room, unit, start, lead, a, node_pose(s_node)):
        return None
    if not _segment_clear(world, room, unit, start, lead, node_pose(g_node), g):
        return None
    ok_cache: dict = {}

    def ok(n) -> bool:
        if n not in ok_cache:
            ok_cache[n] = world.unit_clear(unit, _unit_poses(room, unit, start, lead, node_pose(n)))
        return ok_cache[n]

    def h(n):
        return math.hypot(n[0] - g_node[0], n[1] - g_node[1]) * GRID + abs(n[2] - g_node[2]) * 0.15

    frontier = [(h(s_node), 0.0, s_node)]
    came = {s_node: None}
    cost = {s_node: 0.0}
    expanded = 0
    deadline = time.monotonic() + SEARCH_SECONDS
    while frontier and expanded < budget and time.monotonic() < deadline:
        _, c, n = heapq.heappop(frontier)
        if n == g_node:
            nodes = []
            while n is not None:
                nodes.append(n)
                n = came[n]
            nodes.reverse()
            poses = [a] + [node_pose(x) for x in nodes] + [g]
            return _simplify(world, room, unit, start, lead, poses)
        expanded += 1
        for d in ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)):
            m = (n[0] + d[0], n[1] + d[1], n[2] + d[2])
            step = GRID if d[2] == 0 else 0.15
            nc = c + step
            if nc < cost.get(m, math.inf) and ok(m):
                cost[m] = nc
                came[m] = n
                heapq.heappush(frontier, (nc + h(m), nc, m))
    return None


def _simplify(world: _World, room: Room, unit, start, lead, poses: list[Pose]) -> list[Pose]:
    """Drop waypoints a straight segment can skip."""
    out = [poses[0]]
    i = 0
    while i < len(poses) - 1:
        j = len(poses) - 1
        while j > i + 1 and not _segment_clear(world, room, unit, start, lead, poses[i], poses[j]):
            j -= 1
        out.append(poses[j])
        i = j
    return out


def _lift(world: _World, room: Room, unit, start, lead, a: Pose, g: Pose) -> list[Pose] | None:
    """Raised just clear of everything on the way, carried over, set down."""
    top_of_unit = max(s.y1 for pid in unit for s in room.pieces[pid].solids(start[pid]))
    bottom = a.y
    highest = 0.0
    for oid, op in world.static.items():
        if oid in unit or not laws.collides(room.pieces[oid]):
            continue
        highest = max(highest, max(s.y1 for s in room.pieces[oid].solids(op)))
    lift = highest - bottom + 0.05
    if top_of_unit + lift > room.height - 0.02:
        lift = room.height - 0.02 - top_of_unit
    if lift <= 0.05:
        return None
    up = Pose(a.x, a.y + lift, a.z, a.yaw)
    over = Pose(g.x, g.y + lift, g.z, g.yaw)
    legs = [(a, up), (up, over), (over, g)]
    if all(_segment_clear(world, room, unit, start, lead, p, q) for p, q in legs):
        return [a, up, over, g]
    return None


# ---------------------------------------------------------------- the plan

def plan(room: Room, before: dict[str, Pose], after: dict[str, Pose]) -> Plan:
    """How to get every piece from `before` to `after` with nothing passing through anything.

    `before` and `after` are whole-room poses (laws.all_poses); only pieces whose
    pose differs move.
    """
    moving = [pid for pid in room.pieces if not before[pid].same_as(after[pid])]
    units: dict[str, list[str]] = {}
    for pid in moving:
        base = room.base_of(pid)
        if room.pieces[base].support != "floor":
            base = pid
        units.setdefault(base, [])
        if base not in units[base]:
            units[base].insert(0, base)
        if pid != base:
            units[base].append(pid)
    for lead in units:
        for r in room.riders(lead):
            if r not in units[lead]:
                units[lead].append(r)
    # Pieces that overlap where the scan has them and make the same rigid move
    # travel as one: with whole-box shapes they could not part any other way.
    for lead in list(units):
        for other in list(units):
            if other == lead or other not in units or lead not in units:
                continue
            same = carry(before[other], before[lead], after[lead]).same_as(after[other], tol=1e-3)
            touching = laws.pair_penetration(room.pieces[lead], before[lead], room.pieces[other],
                                             before[other]) > -0.05
            if same and touching:
                units[lead] += [p for p in units.pop(other) if p not in units[lead]]

    current = dict(before)
    tracks: dict[str, list[Key]] = {}
    order: list[str] = []
    parked: list[str] = []
    methods: dict[str, str] = {}
    t = 0.0
    pending = list(units)

    def blocks(u: str, v: str) -> bool:
        """Whether unit u's goal is where unit v still stands."""
        for p in units[u]:
            for q in units[v]:
                if laws.pair_penetration(room.pieces[p], after[p], room.pieces[q], current[q]) > laws.OVERLAP_EPS:
                    return True
        return False

    def run(lead: str, goal: Pose, t0: float) -> float:
        nonlocal current
        unit = units[lead]
        world = _World(room, {pid: current[pid] for pid in room.pieces if pid not in unit})
        start = {pid: current[pid] for pid in unit}
        path, how = _path(world, room, unit, start, lead, goal)
        methods[lead] = how if lead not in methods else methods[lead] + ", then " + how
        times = [t0]
        for p, q in zip(path, path[1:]):
            dist = math.hypot(q.x - p.x, q.z - p.z)
            if abs(q.y - p.y) > 1e-6 and dist < 1e-6:
                times.append(times[-1] + LIFT_TIME)
            else:
                times.append(times[-1] + max(MIN_SEGMENT, dist / SPEED, abs(q.yaw - p.yaw) / TURN_SPEED))
        for pid in unit:
            keys = tracks.setdefault(pid, [Key(0.0, start[pid].x, start[pid].y, start[pid].z, start[pid].yaw)])
            if keys[-1].t < t0:
                k = keys[-1]
                keys.append(Key(t0, k.x, k.y, k.z, k.yaw))
            for ti, p in zip(times[1:], path[1:]):
                q = p if pid == lead else carry(start[pid], start[lead], p)
                keys.append(Key(ti, q.x, q.y, q.z, q.yaw))
        for pid in unit:
            last = tracks[pid][-1]
            current[pid] = Pose(last.x, last.y, last.z, last.yaw)
        return times[-1] + PAUSE

    guard = 0
    while pending and guard < 3 * len(units) + 3:
        guard += 1
        free = [u for u in pending if not any(blocks(u, v) for v in pending if v != u)]
        if free:
            u = free[0]
            t = run(u, after[u], t)
            order.append(u)
            pending.remove(u)
            continue
        # Everyone waits for someone: park one on free floor and go on.
        u = pending[0]
        spot = _parking(room, units[u], current, after, pending)
        if spot is None:
            raise NoPath(u)
        t = run(u, spot, t)
        parked.append(u)
        order.append(u + " (parked)")
    if pending:
        raise NoPath(pending[0])

    duration = max((k[-1].t for k in tracks.values()), default=0.0)
    for pid, keys in tracks.items():
        if keys[-1].t < duration:
            k = keys[-1]
            keys.append(Key(duration, k.x, k.y, k.z, k.yaw))
    result = Plan(tracks, order, duration, 0, parked, methods)
    result.frames_checked = verify(room, before, result)
    return result


def _parking(room: Room, unit: list[str], current: dict[str, Pose], after: dict[str, Pose],
             pending: list[str]) -> Pose | None:
    """A spot on free floor for the unit to wait in, out of everyone's way, near where it is."""
    lead = unit[0]
    grid = floor_grid(room)
    start = current[lead]
    world = _World(room, {pid: current[pid] for pid in room.pieces if pid not in unit})
    goals = [b for v in pending for b in (room.pieces[v].box(after[v]),)]
    order = np.argsort(np.hypot(grid.points[:, 0] - start.x, grid.points[:, 1] - start.z))
    for i in order[::3]:
        if not grid.inside[i]:
            continue
        x, z = grid.points[i]
        for yaw in (start.yaw, start.yaw + math.pi / 2):
            p = Pose(float(x), start.y, float(z), yaw)
            if not world.unit_clear(unit, _unit_poses(room, unit, current, lead, p)):
                continue
            box = room.pieces[lead].box(p)
            if any(penetration(box, g) > 0 for g in goals):
                continue
            return p
    return None


def verify(room: Room, before: dict[str, Pose], p: Plan) -> int:
    """Sample the plan as the viewer plays it; raise if any frame breaks law 1 or 2."""
    frames = int(math.ceil(p.duration * FPS)) + 1
    moving = list(p.tracks)
    for f in range(frames):
        t = min(p.duration, f / FPS)
        poses = dict(before)
        for pid, keys in p.tracks.items():
            k = pose_at(keys, t)
            poses[pid] = Pose(k.x, k.y, k.z, k.yaw)
        for pid in moving:
            piece = room.pieces[pid]
            if not laws.collides(piece):
                continue
            for s in piece.solids(poses[pid]):
                if s.y1 > room.height + laws.SHELL_TOL or (
                        piece.support == "floor" and not box_inside_polygon(s, room.footprint, laws.SHELL_TOL)):
                    raise NoPath(pid)
            for oid, other in room.pieces.items():
                if oid == pid or not laws.collides(other) or room.base_of(oid) == room.base_of(pid):
                    continue
                if not _overlap_allowed(room, piece, poses[pid], other, poses[oid]):
                    raise NoPath(pid)
    return frames


def plan_json(p: Plan) -> dict:
    """The viewer's contract."""
    return {
        "plan_version": PLAN_VERSION,
        "easing": "smoothstep",
        "duration": round(p.duration, 3),
        "order": p.order,
        "tracks": {pid: [{"t": round(k.t, 3), "x": round(k.x, 4), "y": round(k.y, 4), "z": round(k.z, 4),
                          "yaw": round(k.yaw, 4)} for k in keys] for pid, keys in p.tracks.items()},
        "checked": {"frames": p.frames_checked, "fps": FPS},
    }
