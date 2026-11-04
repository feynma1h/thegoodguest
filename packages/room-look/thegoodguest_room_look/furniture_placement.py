"""Where each furniture twin stands: the box it hangs on, then the rules.

A twin starts where its box is (footprint centre on the floor, yaw). A spec
then says which placement rule applies to the piece (`place.rule`), and a
few rules hold for every piece whatever the spec says, so a re-scan that
moves a box moves the twin sensibly instead of leaving it in the wall.

Rules a spec can choose (default `floor`):

  floor    stands where its box is.
  wall     a flat piece: turned to face the room and backed onto the nearest
           wall with `gap` (default 5 mm) between its back-most part and the
           wall; its place along the wall is kept (`along` slides it, metres
           towards its local +x). Boxes are only roughly aligned with walls,
           so a piece placed from one would otherwise sit at a slant.
  over     like `wall`, hung in front of another twin (`target`): its back-most
           part is `gap` clear of the target's front-most part. A curtain over
           a window; a picture over a sideboard.
  on       stands on top of another twin (`target`): its base is the target's
           top, and its footprint centre is kept inside the target's.
  opening  fixed exactly at its box (a window or door slab in the wall); none
           of the invariants below move it.

Invariants applied to every piece but an `opening`, repeated until nothing
moves (at most MAX_PASSES):

  * nothing below the floor: a piece whose lowest part is under the floor is
    raised.
  * nothing through a wall: a piece with a part outside the floor polygon is
    moved inward along the wall's normal.
  * no overlaps: two pieces whose parts overlap are pushed apart along the
    shallowest horizontal way out; the later `floor` piece moves, and the
    pieces standing `on` it travel with it. An overlap that is vertical, or
    between pieces none of which may move, is not resolved: it is returned as
    a problem for the build to report (declare `on` for a stack).

A hand correction goes in `place.fix` = {dx, dy, dz, dyaw_deg, why}, offsets in
the box's own frame, and `why` is required. Every move, by a fix or by a rule,
is written into the twin's `fixes` list with its reason, so the bundle says
how far each piece is from its box and why.
"""
from __future__ import annotations

import math

import numpy as np

from .furniture_boxes import box_pose
from .furniture_clearance import find_problems, twin_parts
from .furniture_geometry import corners, part_obb, polygon_sign, worst_edge, yaw_matrix

RULES = ("floor", "wall", "over", "on", "opening")
WALL_GAP_M = 0.005
MAX_PASSES = 8
TOL_M = 0.01
NUDGE_M = 0.005  # clearance left after a push


class PlacementError(ValueError):
    pass


def place_of(spec: dict) -> dict:
    return spec.get("place") or {}


def rule_of(spec: dict) -> str:
    return place_of(spec).get("rule", "floor")


def validate_place(spec: dict) -> list[str]:
    """Problems with a spec's `place` block; [] when it is fine."""
    key = spec.get("key", "?")
    pl = place_of(spec)
    if not isinstance(pl, dict):
        return [f"{key}: place must be an object"]
    problems = []
    allowed = {"rule", "target", "gap", "along", "fix"}
    for k in pl:
        if k not in allowed:
            problems.append(f"{key}: place.{k} is not in the vocabulary {sorted(allowed)}")
    rule = pl.get("rule", "floor")
    if rule not in RULES:
        problems.append(f"{key}: place.rule must be one of {list(RULES)}, got {rule!r}")
    if rule in ("on", "over") and not isinstance(pl.get("target"), str):
        problems.append(f"{key}: place.rule {rule!r} needs a place.target (another twin's key)")
    if rule not in ("on", "over") and "target" in pl:
        problems.append(f"{key}: place.target only applies to the 'on' and 'over' rules")
    for k in ("gap", "along"):
        if k in pl and not isinstance(pl[k], (int, float)):
            problems.append(f"{key}: place.{k} must be a number of metres")
    fix = pl.get("fix")
    if fix is not None:
        if not isinstance(fix, dict):
            problems.append(f"{key}: place.fix must be an object")
        else:
            for k in fix:
                if k not in ("dx", "dy", "dz", "dyaw_deg", "why"):
                    problems.append(f"{key}: place.fix.{k} is not in the vocabulary [dx, dy, dyaw_deg, dz, why]")
            if not (isinstance(fix.get("why"), str) and fix["why"].strip()):
                problems.append(f"{key}: place.fix needs a written reason in place.fix.why")
    return problems


class Twin:
    """A spec being placed: position (footprint centre on the floor), yaw, fixes."""

    def __init__(self, spec: dict, box: dict):
        self.spec = spec
        self.key = spec["key"]
        self.category = box["category"]
        self.rule = rule_of(spec)
        self.target = place_of(spec).get("target")
        centre, yaw, self.dims = box_pose(box)
        self.pos = np.array(centre, float)
        self.yaw = yaw
        self.fixes: list[dict] = []

    def record(self, rule: str, why: str, **nums) -> None:
        for f in self.fixes:
            if f["rule"] == rule and f["why"] == why:
                for k, v in nums.items():
                    f[k] = round(f.get(k, 0.0) + v, 4)
                return
        self.fixes.append({"rule": rule, "why": why, **{k: round(v, 4) for k, v in nums.items()}})

    def obj(self) -> dict:
        return {
            "key": self.key,
            "position": [round(float(x), 4) for x in self.pos],
            "yaw": round(self.yaw, 5),
            "source": "boxes" + ("+fixed" if self.fixes else ""),
            "category": self.category,
            "rule": self.rule,
            **({"target": self.target} if self.target else {}),
            **({"mount": "wall"} if self.rule in ("wall", "over", "opening") else {}),
            **({"fixes": self.fixes} if self.fixes else {}),
            "spec": {k: v for k, v in self.spec.items() if k not in ("place", "object")},
        }

    def corners_world(self) -> np.ndarray:
        return np.vstack([corners(o) for _, o in twin_parts(self.obj())])


def nearest_wall(poly: np.ndarray, p: np.ndarray):
    """(signed distance inside, unit edge direction, edge start, unit inward normal) of the nearest wall."""
    sign = polygon_sign(poly)
    best = None
    for i in range(len(poly)):
        a, b = poly[i], poly[(i + 1) % len(poly)]
        e = (b - a) / np.linalg.norm(b - a)
        d = sign * (e[0] * (p[1] - a[1]) - e[1] * (p[0] - a[0]))
        if best is None or abs(d) < abs(best[0]):
            best = (d, e, a)
    d, e, a = best
    return d, e, a, np.array([-e[1], e[0]]) * sign


def back_extent(spec: dict, inward: np.ndarray, yaw: float) -> float:
    """How far the piece's back-most part lies behind its origin, along `inward`, at `yaw` (<= 0 typically)."""
    zero = np.zeros(3)
    return min(
        float(np.dot(c[[0, 2]], inward))
        for part in spec["parts"]
        for c in corners(part_obb(part, zero, yaw))
    )


def stand_against(t: Twin, poly: np.ndarray, wall_of: np.ndarray, front: float | None, gap: float, along: float) -> tuple[float, float]:
    """Move `t` to face the room against the wall nearest `wall_of`; `front` is the wall-distance its
    back must clear (None: the wall itself). Returns (metres moved, degrees turned)."""
    p = t.pos[[0, 2]]
    _, e, a, inward = nearest_wall(poly, wall_of)
    yaw = math.atan2(inward[0], inward[1])
    back = back_extent(t.spec, inward, yaw)
    want = (0.0 if front is None else front) + gap - back  # the origin's distance from the wall
    foot = a + e * float(np.dot(p - a, e))
    q = foot + inward * want + np.array([inward[1], -inward[0]]) * along
    moved = float(np.linalg.norm(q - p))
    turned = abs((math.degrees(yaw - t.yaw) + 180) % 360 - 180)
    t.pos[0], t.pos[2], t.yaw = q[0], q[1], yaw
    return moved, turned


def shift(t: Twin, twins: list[Twin], delta: np.ndarray) -> None:
    """Move a twin, and everything declared to stand on or hang over it, by `delta` (x, y, z)."""
    t.pos += delta
    for d in twins:
        if d.target == t.key:
            shift(d, twins, delta)


def top_of(t: Twin) -> float:
    return float(max(c[1] for c in t.corners_world()))


def apply_rule(t: Twin, twins: dict[str, Twin], poly: np.ndarray) -> None:
    pl = place_of(t.spec)
    fix = pl.get("fix")
    if fix:
        c, s = math.cos(t.yaw), math.sin(t.yaw)
        dx, dy, dz = fix.get("dx", 0.0), fix.get("dy", 0.0), fix.get("dz", 0.0)
        t.pos += np.array([c * dx + s * dz, dy, -s * dx + c * dz])  # box frame -> world
        t.yaw += math.radians(fix.get("dyaw_deg", 0.0))
        t.record("fix", fix["why"], dx=dx, dy=dy, dz=dz, dyaw_deg=fix.get("dyaw_deg", 0.0))
    gap, along = pl.get("gap", WALL_GAP_M), pl.get("along", 0.0)
    if t.rule == "wall":
        moved, turned = stand_against(t, poly, t.pos[[0, 2]], None, gap, along)
        t.record("wall", "a flat piece faces the room and backs onto the nearest wall", moved_m=moved, turned_deg=turned)
    elif t.rule == "over":
        target = twins[t.target]
        tc = target.corners_world()
        d, e, a, inward = nearest_wall(poly, target.pos[[0, 2]])
        sign = polygon_sign(poly)
        # wall-distance of the target's front-most point
        front = max(sign * (e[0] * (c[2] - a[1]) - e[1] * (c[0] - a[0])) for c in tc)
        moved, turned = stand_against(t, poly, target.pos[[0, 2]], float(front), gap, along)
        t.record("over", f"hung in front of {t.target}, clear of its front", moved_m=moved, turned_deg=turned)
    elif t.rule == "on":
        target = twins[t.target]
        tc = target.corners_world()
        lo, hi = tc[:, [0, 2]].min(0), tc[:, [0, 2]].max(0)
        p = t.pos[[0, 2]]
        q = np.minimum(np.maximum(p, lo), hi)
        if np.linalg.norm(q - p) > 1e-6:
            t.record("on", f"footprint centre brought inside {t.target}", moved_m=float(np.linalg.norm(q - p)))
            t.pos[0], t.pos[2] = q
        lift = top_of(target) - t.pos[1]
        if abs(lift) > 1e-4:
            t.record("on", f"stands on top of {t.target}", dy=lift)
            t.pos[1] += lift


def order(specs: list[dict]) -> list[dict]:
    """Specs with targets after what they depend on; the rest keep their order."""
    by_key = {s["key"]: s for s in specs}
    done: list[dict] = []
    seen: set[str] = set()

    def visit(s: dict, stack: tuple[str, ...]) -> None:
        if s["key"] in seen:
            return
        tgt = place_of(s).get("target")
        if tgt:
            if tgt not in by_key:
                raise PlacementError(f"{s['key']}: place.target {tgt!r} is not a twin in this build")
            if tgt in stack or tgt == s["key"]:
                raise PlacementError(f"{s['key']}: place.target chain loops through {tgt!r}")
            visit(by_key[tgt], stack + (s["key"],))
        seen.add(s["key"])
        done.append(s)

    for s in specs:
        visit(s, ())
    return done


def settle(twins: list[Twin], poly: np.ndarray, floor_y: float, tol: float = TOL_M) -> None:
    by_key = {t.key: t for t in twins}
    free = [t for t in twins if t.rule != "opening"]
    for _ in range(MAX_PASSES):
        moved = False
        for t in free:
            low = float(min(c[1] for c in t.corners_world()))
            if low < floor_y - 1e-3:
                t.record("floor", "nothing stands below the floor", dy=floor_y - low)
                shift(t, twins, np.array([0.0, floor_y - low, 0.0]))
                moved = True
            worst, normal = 0.0, np.zeros(2)
            for c in t.corners_world():
                if c[1] < floor_y - 0.05:
                    continue
                d, n = worst_edge(c[[0, 2]], poly)
                if d > worst:
                    worst, normal = d, n
            if worst > tol:
                push = normal * (worst + 0.002)
                shift(t, twins, np.array([push[0], 0.0, push[1]]))
                t.record("wall", "nothing passes through a wall", moved_m=float(np.linalg.norm(push)))
                moved = True
        objs = [t.obj() for t in twins]
        for p in find_problems(objs, poly, floor_y, tol):
            if p["kind"] != "overlap":
                continue
            a, b = by_key[p["a"]], by_key[p["b"]]
            mover, other, sign = (b, a, 1.0) if b.rule == "floor" else (a, b, -1.0) if a.rule == "floor" else (None, None, 0.0)
            horiz = np.array([p["axis"][0], p["axis"][2]])
            if mover is None or np.linalg.norm(horiz) < 0.5:
                continue  # vertical, or nothing may move: reported by the caller
            step = sign * horiz / np.linalg.norm(horiz) * (p["depth"] + NUDGE_M)
            shift(mover, twins, np.array([step[0], 0.0, step[1]]))
            mover.record("overlap", f"clear of {other.key}", moved_m=float(np.linalg.norm(step)))
            moved = True
            break  # positions changed: re-measure
        if not moved:
            return


def place_all(specs: list[dict], boxes: dict[str, dict], poly: np.ndarray, floor_y: float, tol: float = TOL_M):
    """Place every spec. Returns (placed objects in spec order, problems still standing)."""
    problems = [msg for s in specs for msg in validate_place(s)]
    missing = [f"{s['key']}: object {s['object']!r} is not in boxes.json or the shell's openings" for s in specs if s["object"] not in boxes]
    if problems or missing:
        raise PlacementError("\n".join(problems + missing))
    twins = {s["key"]: Twin(s, boxes[s["object"]]) for s in specs}
    for s in order(specs):
        apply_rule(twins[s["key"]], twins, poly)
    ordered = [twins[s["key"]] for s in specs]
    settle(ordered, poly, floor_y, tol)
    objects = [t.obj() for t in ordered]
    return objects, find_problems(objects, poly, floor_y, tol)
