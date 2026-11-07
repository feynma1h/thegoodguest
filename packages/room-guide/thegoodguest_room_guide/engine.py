"""The layout engine: the only thing that writes where a piece goes.

  place(intent)        a directed change in a closed vocabulary: a solved proposal, or a reason
  explore(goal)        up to three different, valid, scored proposals toward a goal
  measure(a, b)        a framed sentence for the gap between two pieces

A piece never moves alone. Whatever rests on it is carried with it; a piece that
goes `beside` it is carried too; one that goes `at` it is seated at its front
(if it was there already, it keeps where it was); one that hangs `over` it is
re-hung over it on the wall it now backs onto.

Every candidate is checked in two tiers. The quick tier applies the laws to the
pieces that moved and recomputes only the keep-clear zones they could touch; the
finalists then get the full assessment (law 4's paths, reach, sight, light, the
bonds and the preferences). Nothing is offered that the full assessment does not
pass against the scanned room (law 6).

Proposals are relative to the room as it stands in the conversation (`base`),
and always judged against the room as scanned.

Read by: motion.py (a proposal's moves), guide.py (its tools), the harness.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from typing import Iterable

import numpy as np

from . import laws
from .analyzer import Finding, about, findings, the, wall_name
from .assess import Assessment, assess, backing_wall, bond_holds, free_depth, preferences, _blocking_solids
from .geometry import footprint_gap, footprint_penetration
from .model import Arrangement, Pose, Room, carry
from .needs import FOLLOW, WEIGHTS, RoomNeeds, zone_box, zones

STEP = 0.05               # how finely a piece is slid along a wall
GAP = 0.01                # a piece set against a wall or a neighbour stands this far off it
FINALISTS = 12
PENALTY = {"hard": 3.0, "soft": 1.5}
MOVE_COST = {"yes": 0.3, "heavy": 0.8}


class Refusal(Exception):
    """A change the room can't take, with the reason in words the guide may say."""

    def __init__(self, reason: str, code: str):
        super().__init__(reason)
        self.reason = reason
        self.code = code


@dataclass(frozen=True)
class Move:
    piece: str
    frm: Pose
    to: Pose
    role: str                 # "anchor" | "follower" | "rider"


@dataclass
class Proposal:
    id: str
    moves: list[Move]
    arrangement: Arrangement          # the whole room's overrides after the proposal
    score_before: float
    score_after: float
    words: list[str]                  # what moves where, for the guide to quote
    fixes: list[Finding]              # problems and tight spots it clears
    leaves: list[Finding]             # problems it leaves as they were
    adds: list[Finding]               # tight spots it brings
    effort: str
    goal: str

    @property
    def anchors(self) -> list[str]:
        return [m.piece for m in self.moves if m.role == "anchor"]


@dataclass
class Engine:
    room: Room
    needs: RoomNeeds
    base: Arrangement = field(default_factory=dict)   # the room as it stands now

    def __post_init__(self):
        self.fixed = self.needs.fixed_ids()
        self.scanned = assess(self.room, self.needs, {})
        self.current = assess(self.room, self.needs, self.base) if self.base else self.scanned
        self.current_findings = findings(self.room, self.needs, self.current)
        self.current_score = self.score(self.current, self.base)
        self.law_base = laws.check(self.room, {}, fixed=self.fixed)
        self._zones = zones(self.room, self.needs)

    # ------------------------------------------------------------ scoring
    def score(self, a: Assessment, arrangement: Arrangement) -> float:
        s = 0.0
        for sh in a.shortfalls:
            if sh.need == "reach":
                gap, scale = max(0.0, -sh.free + sh.comfortable), 0.6
            else:
                gap, scale = sh.short, max(sh.comfortable, 1e-6)
            weight = PENALTY.get(sh.strength, 1.5) * (0.7 if sh.need == "with" else 1.0)
            s -= weight * min(1.0, gap / scale)
        for p in a.preferences:
            s += p.weight * p.value
        s -= self.move_cost(arrangement)
        return s

    def move_cost(self, arrangement: Arrangement) -> float:
        cost = 0.0
        for pid in laws.moved_ids(self.room, arrangement):
            p = self.room.pieces[pid]
            if p.support != "floor":
                continue
            frm, to = p.pose, arrangement[pid]
            dist = math.hypot(to.x - frm.x, to.z - frm.z)
            turn = abs(math.remainder(to.yaw - frm.yaw, 2 * math.pi))
            cost += MOVE_COST.get(self.needs.moves(pid), 0.3) * (1.0 + dist + 0.3 * turn)
        return cost

    # ------------------------------------------------------------ groups
    def group(self, anchor: str, to: Pose, poses: dict[str, Pose]) -> dict[str, Pose]:
        """Where the anchor and everything that goes with it end up."""
        frm = poses[anchor]
        out = {anchor: to}
        for r in self.room.riders(anchor):
            out[r] = carry(poses[r], frm, to)
        for f in self.needs.followers(anchor):
            if f in out:
                continue
            how = next(b.how for b in self.needs.pieces[f].bonds if b.piece == anchor and b.how in FOLLOW)
            fp = self._follow(anchor, to, f, how, poses)
            if fp is None:
                continue
            out[f] = fp
            for r in self.room.riders(f):
                out[r] = carry(poses[r], poses[f], fp)
        return out

    def _follow(self, anchor: str, to: Pose, f: str, how: str, poses: dict[str, Pose]) -> Pose | None:
        frm = poses[anchor]
        if how == "over":
            wall = backing_wall(self.room, anchor, to)
            if wall is None:
                return None
            w = self.room.wall(wall)
            fpiece = self.room.pieces[f]
            u = w.u_of((to.x, to.z))
            x, z = w.point(u, fpiece.size[2] / 2)
            return Pose(x, poses[f].y, z, w.facing_yaw)
        if how == "at" and not bond_holds(self.room, f, anchor, "at", poses):
            return self.seat(anchor, to, f, poses)
        return carry(poses[f], frm, to)

    def seat(self, anchor: str, to: Pose, f: str, poses: dict[str, Pose]) -> Pose:
        """A piece used at another one, set squarely at its front and pushed in as far
        as their shapes allow, the way a chair is pushed in under a desk."""
        a, p = self.room.pieces[anchor], self.room.pieces[f]
        for tuck in (0.45, 0.35, 0.25, 0.15, 0.05, -GAP):
            x, z = to.place(0.0, a.size[2] / 2 + p.size[2] / 2 - tuck)
            pose = Pose(x, poses[f].y, z, to.yaw + math.pi)
            if laws.pair_penetration(a, to, p, pose) <= laws.OVERLAP_EPS:
                return pose
        return pose

    # ------------------------------------------------------------ checking
    def quick(self, arrangement: Arrangement, moved: set[str]) -> tuple[bool, float]:
        """Laws for what moved, and the zones it could touch: (passes, rough score)."""
        if laws.new_violations(self.room, arrangement, self.law_base, fixed=self.fixed):
            return False, -math.inf
        poses = laws.all_poses(self.room, arrangement)
        boxes = [self.room.pieces[m].box(poses[m]) for m in moved] + \
                [self.room.pieces[m].box() for m in moved]
        rough = 0.0
        for z in self._zones:
            piece = self.room.pieces[z.piece]
            zb = zone_box(piece, z, poses[z.piece], max(z.comfortable, z.hard) + 0.3)
            touched = z.piece in moved or any(footprint_penetration(zb.grown(0.3), b) > 0 for b in boxes)
            if touched:
                depth, who = free_depth(self.room, z, poses, _blocking_solids(self.room, poses, z.exempt))
            else:
                depth, who = self.current.free_depths.get((z.piece, z.need, z.side), (z.comfortable, ()))
            if z.strength == "hard" and depth < z.hard - 0.005:
                base_depth, base_who = self.scanned.free_depths.get((z.piece, z.need, z.side), (z.comfortable, ()))
                excused = (base_depth < z.hard - 0.005 and depth >= base_depth - 0.01
                           and not (set(who) & moved) and z.piece not in moved)
                if not excused:
                    return False, -math.inf
            rough -= PENALTY.get(z.strength, 1.5) * min(1.0, max(0.0, z.comfortable - depth) / max(z.comfortable, 1e-6))
        for p in preferences(self.room, self.needs, poses, None, cheap=True):
            rough += p.weight * p.value
        return True, rough - self.move_cost(arrangement)

    def full(self, arrangement: Arrangement) -> tuple[bool, Assessment, float]:
        a = assess(self.room, self.needs, arrangement)
        ok = a.valid(self.scanned, self.room, arrangement)
        return ok, a, self.score(a, arrangement)

    # ------------------------------------------------------------ candidates
    def wall_slots(self, pid: str, wall_id: str, *, step: float = STEP) -> Iterable[tuple[Pose, dict]]:
        p = self.room.pieces[pid]
        w = self.room.wall(wall_id)
        sx, _, sz = p.size
        y = p.pose.y
        lo, hi = sx / 2 + GAP, w.length - sx / 2 - GAP
        if hi < lo:
            return
        for u in np.arange(lo, hi + 1e-9, step):
            x, z = w.point(float(u), GAP + sz / 2)
            yield Pose(x, y, z, w.facing_yaw), {"wall": wall_id, "u": float(u)}

    def beside_slots(self, pid: str, other: str, poses: dict[str, Pose]) -> Iterable[tuple[Pose, dict]]:
        p, o = self.room.pieces[pid], self.room.pieces[other]
        po = poses[other]
        for sign, side in ((1, "right"), (-1, "left")):
            for slide in (0.0, 0.1, 0.2, 0.35):
                lx = sign * (o.size[0] / 2 + GAP + 0.02 + p.size[0] / 2)
                lz = -o.size[2] / 2 + p.size[2] / 2 + slide
                x, z = po.place(lx, lz)
                yield Pose(x, p.pose.y, z, po.yaw), {"beside": other, "side": side}

    def turn_slots(self, pid: str, poses: dict[str, Pose], quarter: int | None = None) -> Iterable[tuple[Pose, dict]]:
        p = poses[pid]
        turns = (quarter,) if quarter else (1, 2, 3)
        for q in turns:
            yaw = p.yaw + q * math.pi / 2
            for dx, dz in ((0, 0), (0.1, 0), (-0.1, 0), (0, 0.1), (0, -0.1), (0.2, 0), (-0.2, 0), (0, 0.2), (0, -0.2),
                           (0.3, 0), (-0.3, 0), (0, 0.3), (0, -0.3)):
                yield Pose(p.x + dx, p.y, p.z + dz, yaw), {"turn": q}

    def all_slots(self, pid: str, poses: dict[str, Pose]) -> Iterable[tuple[Pose, dict]]:
        for w in self.room.walls:
            yield from self.wall_slots(pid, w.id, step=0.15)
        for other in self.room.pieces:
            o = self.room.pieces[other]
            if other != pid and o.support == "floor" and laws.collides(o) and o.size[0] * o.size[2] > 0.3:
                yield from self.beside_slots(pid, other, poses)
        yield from self.turn_slots(pid, poses)

    # ------------------------------------------------------------ searching
    def _evaluate(self, candidates: Iterable[tuple[str, Pose, dict]], goal: str,
                  keep_best: int = FINALISTS, extra: Arrangement | None = None) -> list[tuple[float, Arrangement, list, Assessment]]:
        poses = laws.all_poses(self.room, self.base)
        ranked = []
        seen = set()
        for anchor, to, meta in candidates:
            moved_poses = self.group(anchor, to, {**poses, **(extra or {})})
            arrangement = {**self.base, **(extra or {}), **moved_poses}
            key = tuple(sorted((k, round(v.x, 3), round(v.z, 3), round(v.yaw, 3)) for k, v in moved_poses.items()))
            if key in seen:
                continue
            seen.add(key)
            moved = laws.moved_ids(self.room, arrangement)
            if not moved:
                continue
            ok, rough = self.quick(arrangement, moved)
            if ok:
                if goal.startswith("light:"):
                    rough += sum(3.0 * p.value for p in preferences(self.room, self.needs, laws.all_poses(self.room, arrangement), None, cheap=True)
                                 if p.pref == "task_light" and p.piece == goal[6:])
                ranked.append((rough, arrangement, [(anchor, to, meta)]))
        ranked.sort(key=lambda r: -r[0])
        out = []
        stopped = self.__dict__.setdefault("_stopped", {})
        for rough, arrangement, metas in ranked[: keep_best * 2]:
            ok, a, s = self.full(arrangement)
            if ok:
                out.append((s + self.goal_bonus(goal, a), arrangement, metas, a))
            else:
                for b in a.unexcused(self.scanned, self.room, arrangement):
                    k = (b.kind, b.need, b.side, b.pieces[0])
                    stopped[k] = stopped.get(k, 0) + 1
            if len(out) >= keep_best:
                break
        out.sort(key=lambda r: -r[0])
        return out

    def why_nothing(self) -> str:
        """What stopped the most promising changes, in words the guide may say."""
        stopped = self.__dict__.get("_stopped", {})
        if not stopped:
            return "nothing the room tried beats it as it stands, by its own needs"
        (kind, need, side, pid), _ = max(stopped.items(), key=lambda kv: kv[1])
        target = the(self.room, pid)
        if side in ("left", "right"):
            target = f"the side of {target}"
        elif side == "front" and need in ("use", "open"):
            target = f"the front of {target}"
        reason = {
            "unreachable": f"they closed off the way to {target}",
            "zone": f"they crowded {target}",
            "covered": f"they covered {target}",
            "out_of_reach": f"they put {target} out of reach",
            "unseen": f"they blocked the view of {target}",
            "dark": f"they blocked the light from {target}",
        }.get(kind, f"they broke something {target} needs")
        return f"the changes that would have helped most were stopped because {reason}"

    def goal_bonus(self, goal: str, a: Assessment) -> float:
        """Extra credit for what the goal asks for, on top of the room's score."""
        if goal.startswith("fix:"):
            key = goal[4:]
            still = [f for f in findings(self.room, self.needs, a) if f.key == key]
            before = [f for f in self.current_findings if f.key == key]
            if not still:
                return 4.0
            if before and still[0].severity < before[0].severity:
                return 2.0
            return 0.0
        if goal.startswith("light:"):
            pid = goal[6:]
            return sum(3.0 * p.value for p in a.preferences if p.pref == "task_light" and p.piece == pid)
        if goal == "open_floor":
            return sum(4.0 * p.value for p in a.preferences if p.pref == "open_floor")
        return 0.0

    def proposal(self, arrangement: Arrangement, metas: list, a: Assessment, goal: str, score: float) -> Proposal:
        moves = []
        poses_before = laws.all_poses(self.room, self.base)
        anchors = {m[0] for m in metas}
        for pid in laws.moved_ids(self.room, arrangement):
            if pid in self.base and self.base[pid].same_as(arrangement[pid]):
                continue
            frm = poses_before[pid]
            if frm.same_as(arrangement[pid]):
                continue
            role = "anchor" if pid in anchors else ("rider" if self.room.pieces[pid].support == "object" else "follower")
            moves.append(Move(pid, frm, arrangement[pid], role))
        after = findings(self.room, self.needs, a)
        before_keys = {f.key: f for f in self.current_findings if f.kind in ("problem", "tight", "light")}
        after_keys = {f.key: f for f in after if f.kind in ("problem", "tight", "light")}
        fixes = [f for k, f in before_keys.items() if k not in after_keys or after_keys[k].severity < f.severity]
        leaves = [f for k, f in before_keys.items() if k in after_keys and after_keys[k].severity >= f.severity]
        adds = [f for k, f in after_keys.items() if k not in before_keys]
        heavy = [m.piece for m in moves if m.role == "anchor" and self.needs.moves(m.piece) == "heavy"]
        effort = "a two-person job" if heavy else "quick to do"
        words = [self.describe(m, meta) for m in moves if m.role == "anchor"
                 for (aid, _, meta) in metas if aid == m.piece]
        words += [self.describe_follower(m) for m in moves if m.role == "follower"]
        pid = hashlib.sha1(repr(sorted((m.piece, round(m.to.x, 2), round(m.to.z, 2), round(m.to.yaw, 2))
                                       for m in moves)).encode()).hexdigest()[:8]
        return Proposal(pid, moves, arrangement, self.current_score, score, words, fixes, leaves, adds, effort, goal)

    # ------------------------------------------------------------ words
    def describe(self, m: Move, meta: dict) -> str:
        name = the(self.room, m.piece)
        dist = math.hypot(m.to.x - m.frm.x, m.to.z - m.frm.z)
        turn = math.remainder(m.to.yaw - m.frm.yaw, 2 * math.pi)
        turning = abs(turn) > 0.2
        if "wall" in meta:
            w = backing_wall(self.room, m.piece, m.to)
            if w == backing_wall(self.room, m.piece, m.frm) and not turning:
                toward = self._toward(m)
                return f"{name} slides {about(dist, down=False)} along {wall_name(self.room, w)}{toward}"
            return f"{name} goes against {wall_name(self.room, meta['wall'])}"
        if "beside" in meta:
            return f"{name} goes beside {the(self.room, meta['beside'])}"
        if "at" in meta:
            return f"{name} goes to {the(self.room, meta['at'])}, set at its front"
        if "turn" in meta:
            q = meta["turn"] % 4
            words = {1: "a quarter turn to the left", 2: "turned round", 3: "a quarter turn to the right"}[q]
            shift = f", shifted {about(dist, down=False)}" if dist > 0.04 else ""
            return f"{name} is {words}{shift}" if q == 2 else f"{name} takes {words}{shift}"
        return f"{name} moves {about(dist, down=False)}"

    def _toward(self, m: Move) -> str:
        d = np.array([m.to.x - m.frm.x, m.to.z - m.frm.z])
        if np.hypot(*d) < 1e-6:
            return ""
        d = d / np.hypot(*d)
        best, best_c = None, 0.7
        for w in self.room.walls:
            c = -float(d @ np.array(w.normal))
            if c > best_c:
                best, best_c = w.id, c
        return f", toward {wall_name(self.room, best)}" if best else ""

    def describe_follower(self, m: Move) -> str:
        name = the(self.room, m.piece)
        bond = next((b for b in self.needs.pieces[m.piece].bonds if b.how in FOLLOW), None)
        if bond is None:
            return f"{name} comes with it"
        how = {"at": "is set at", "beside": "stays beside", "over": "is re-hung over"}[bond.how]
        return f"{name} {how} {the(self.room, bond.piece)}"

    # ------------------------------------------------------------ the public surface
    def place(self, piece: str, *, wall: str | None = None, beside: str | None = None,
              under: str | None = None, facing: str | None = None, turn: str | None = None,
              at: str | None = None, along: str | None = None, goal: str = "") -> Proposal:
        """Solve one directed change. Raises Refusal with a reason the guide may say."""
        if piece not in self.room.pieces:
            raise Refusal("there's no such piece in this room", "unknown_piece")
        moves = self.needs.moves(piece)
        if piece in self.fixed and moves != "rehang":
            why = self.needs.pieces.get(piece).why if self.needs.pieces.get(piece) else "it is fixed"
            raise Refusal(f"{the(self.room, piece)} stays where it is: {why}", "fixed")
        if self.room.pieces[piece].support != "floor":
            raise Refusal(f"{the(self.room, piece)} moves with what it stands on", "rider")
        poses = laws.all_poses(self.room, self.base)
        cands: list[tuple[str, Pose, dict]] = []
        if wall:
            if wall not in {w.id for w in self.room.walls}:
                raise Refusal("there's no such wall", "unknown_wall")
            cands = [(piece, p, m) for p, m in self.wall_slots(piece, wall)]
        elif under:
            opening_id = self.room.pieces[under].opening if under in self.room.pieces else under
            op = next((o for o in self.room.openings if o.id == opening_id), None)
            if op is None:
                raise Refusal("I can't find that window or door", "unknown_opening")
            centre = (op.u0 + op.u1) / 2
            cands = [(piece, p, m) for p, m in self.wall_slots(piece, op.wall)
                     if abs(m["u"] - centre) <= max(0.15, op.width / 2)]
            cands.sort(key=lambda c: abs(c[2]["u"] - centre))
        elif beside:
            if beside not in self.room.pieces:
                raise Refusal("there's no such piece to put it beside", "unknown_piece")
            cands = [(piece, p, m) for p, m in self.beside_slots(piece, beside, poses)]
        elif at:
            if at not in self.room.pieces:
                raise Refusal("there's no such piece", "unknown_piece")
            cands = [(piece, self.seat(at, poses[at], piece, poses), {"at": at})]
        elif turn:
            q = {"left": 1, "around": 2, "right": 3}.get(turn)
            if q is None:
                raise Refusal("a turn is left, right or around", "bad_turn")
            cands = [(piece, p, m) for p, m in self.turn_slots(piece, poses, q)]
        elif facing:
            target = self.room.pieces.get(facing)
            if target is None:
                raise Refusal("there's no such piece to face", "unknown_piece")
            p, t = poses[piece], poses[facing]
            yaw = math.atan2(t.x - p.x, t.z - p.z)
            yaw = round(yaw / (math.pi / 2)) * (math.pi / 2)
            q = round(math.remainder(yaw - p.yaw, 2 * math.pi) / (math.pi / 2)) % 4
            if q == 0:
                raise Refusal(f"{the(self.room, piece)} already faces {the(self.room, facing)}", "already")
            cands = [(piece, pp, m) for pp, m in self.turn_slots(piece, poses, q)]
        elif along:
            w = backing_wall(self.room, piece, poses[piece])
            if w is None:
                raise Refusal(f"{the(self.room, piece)} isn't against a wall to slide along", "not_on_wall")
            cands = [(piece, p, m) for p, m in self.wall_slots(piece, w)]
        else:
            cands = [(piece, p, m) for p, m in self.all_slots(piece, poses)]
        if not cands:
            raise Refusal(f"{the(self.room, piece)} is too big for that", "too_big")
        results = self._evaluate(cands, goal or "place", keep_best=4)
        if not results:
            raise Refusal(self._why_not(piece, cands), "no_room")
        s, arrangement, metas, a = results[0]
        return self.proposal(arrangement, metas, a, goal or "place", s - self.goal_bonus(goal or "place", a))

    def _why_not(self, piece: str, cands) -> str:
        """What is most in the way, as a reason the guide may say.

        Blockers are ranked by how deeply they would be run into, so an air
        conditioner sticking out of a wall outranks a curtain hanging flat on it;
        a pack on a chest of drawers counts as the chest; and when it is something
        that goes with the piece that would hit, the reason says so.
        """
        poses = laws.all_poses(self.room, self.base)
        depth: dict[tuple[str, str], float] = {}
        for anchor, to, meta in list(cands)[:300]:
            group = self.group(anchor, to, poses)
            arrangement = {**self.base, **group}
            for v in laws.new_violations(self.room, arrangement, self.law_base, fixed=self.fixed):
                if v.kind == "outside":
                    key = (v.pieces[0], "wall")
                    depth[key] = depth.get(key, 0.0) + 0.05
                    continue
                mover = next((q for q in v.pieces if q in group), None)
                other = next((q for q in v.pieces if q not in group), None)
                if mover and other:
                    key = (self.room.base_of(mover), self.room.base_of(other))
                    depth[key] = depth.get(key, 0.0) + v.amount
        if not depth:
            return (f"wherever {the(self.room, piece)} goes there, something that needs to stay clear "
                    f"would be blocked")
        (mover, worst), _ = max(depth.items(), key=lambda kv: kv[1])
        who = the(self.room, piece) if mover == piece else f"{the(self.room, mover)}, which goes with it,"
        if worst == "wall":
            return f"there isn't room there: {who} would run into the wall"
        return f"{who} would run into {the(self.room, worst)} there"

    def explore(self, goal: str = "general", *, locked: Iterable[str] = (), max_pieces: int = 2) -> list[Proposal]:
        """Up to three different, valid proposals toward the goal, best first.

        Remembered for the room as it stands, so asking twice costs nothing.
        """
        key = (goal, tuple(sorted(locked)), max_pieces)
        memo = self.__dict__.setdefault("_explored", {})
        if key not in memo:
            memo[key] = self._explore(goal, locked=locked, max_pieces=max_pieces)
        return memo[key]

    def _explore(self, goal: str, *, locked: Iterable[str], max_pieces: int) -> list[Proposal]:
        locked = set(locked)
        movable = [pid for pid, p in self.room.pieces.items()
                   if p.support == "floor" and pid not in self.fixed and pid not in locked and laws.collides(p)
                   and pid not in {f for a in self.room.pieces for f in self.needs.followers(a)}]
        poses = laws.all_poses(self.room, self.base)
        cands = [(pid, to, meta) for pid in movable for to, meta in self.all_slots(pid, poses)]
        # A follower may move on its own only in its own relation: one standing away
        # from what it is used at is seated back at it; one that stands beside a piece
        # may go to its other side.
        for pid, entry in self.needs.pieces.items():
            if pid in locked or pid not in self.room.pieces:
                continue
            for b in entry.bonds:
                if b.how == "at" and not bond_holds(self.room, pid, b.piece, "at", poses):
                    cands.append((pid, self.seat(b.piece, poses[b.piece], pid, poses), {"at": b.piece}))
                elif b.how == "beside":
                    cands += [(pid, to, meta) for to, meta in self.beside_slots(pid, b.piece, poses)]
        singles = self._evaluate(cands, goal, keep_best=FINALISTS)
        target = self.current_score + self.goal_bonus(goal, self.current) + 0.05
        results = [r for r in singles if r[0] > target]
        if max_pieces >= 2 and singles:
            # A second move is looked for near the first: what the first move
            # crowds or frees is what a second move can use.
            for s1, arr1, metas1, _ in singles[:4]:
                first = {m[0] for m in metas1}
                extra = {k: v for k, v in arr1.items() if k not in self.base or not self.base[k].same_as(v)}
                here = [poses[m] for m in first] + [extra[m] for m in first if m in extra]
                nearby = [pid for pid in movable if pid not in first and any(
                    math.hypot(poses[pid].x - h.x, poses[pid].z - h.z) < 1.8 for h in here)]
                after = {**poses, **extra}
                pair_cands = []
                for pid in nearby:
                    for w in self.room.walls:
                        pair_cands += [(pid, to, meta) for to, meta in self.wall_slots(pid, w.id, step=0.2)]
                    pair_cands += [(pid, to, meta) for to, meta in self.turn_slots(pid, after)]
                for s2, arr2, metas2, a2 in self._evaluate(pair_cands, goal, keep_best=3, extra=extra):
                    if s2 > target:
                        results.append((s2, arr2, metas1 + metas2, a2))
        results.sort(key=lambda r: -r[0])
        picked, used = [], []
        for s, arrangement, metas, a in results:
            signature = frozenset((m[0], m[2].get("wall") or m[2].get("beside") or m[2].get("turn") or m[2].get("at"))
                                  for m in metas)
            if signature in used:
                continue
            used.append(signature)
            picked.append(self.proposal(arrangement, metas, a, goal, s - self.goal_bonus(goal, a)))
            if len(picked) == 3:
                break
        return picked

    def measure(self, a: str, b: str) -> str:
        """The gap between two pieces as they stand now, framed."""
        poses = laws.all_poses(self.room, self.base)
        pa, pb = self.room.pieces[a], self.room.pieces[b]
        gap = footprint_gap(pa.box(poses[a]), pb.box(poses[b]))
        net = max(0.0, gap - pa.margin - pb.margin)
        if gap <= 0.005:
            return f"{the(self.room, a)} and {the(self.room, b)} touch, by the scan."
        return f"There's {about(net)} between {the(self.room, a)} and {the(self.room, b)}, by the scan."
