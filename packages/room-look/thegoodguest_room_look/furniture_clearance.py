"""Check that no furniture twin pokes into another twin or through a wall.

    python tools/furniture_clearance.py outputs/scene-<id> [--tol 0.01]

Reads <scene>/furniture.json (the placed twins) and <scene>/shell.json (the floor
polygon, whose edges are the walls' room-side faces). Every part becomes an
oriented box (its own rotation applied about its centre, then the twin's yaw and
position); curved parts use their bounding box, so a curved part can be flagged
slightly early — a flagged pair is a place to look, not proof.

  * overlap  — any two parts of different twins whose boxes overlap by more
    than `tol` metres along every separating axis (penetration depth reported).
    A twin that stands `on` another and a wall piece hung `over` another are
    meant to touch it, so that pair is not flagged.
  * inside a twin — a spec may list `separate_groups` (lists of part-name
    prefixes, e.g. a desk's stool); each group is checked against the twin's
    other parts.
  * in wall  — a part whose box corner lies more than `tol` outside the floor
    polygon, i.e. inside the wall slab. Twins placed by the `opening` rule sit
    in the wall on purpose and are not checked.

The same checks run inside furniture_models.py's placement loop, so a twin it
places clears them or the build says why not. Exit code 1 if anything is flagged.
"""
from __future__ import annotations

import argparse
import itertools
import json
from pathlib import Path

import numpy as np

from .furniture_boxes import load_shell
from .furniture_geometry import corners, obb_penetration, part_obb, point_outside_polygon

DEFAULT_TOL_M = 0.01


def is_glow(part: dict) -> bool:
    return bool(part.get("noShadow") and part["kind"] == "sphere" and part.get("name", "").startswith("glow"))


def twin_parts(obj: dict) -> list[tuple[str, np.ndarray]]:
    """[(part name, world obb)] for the parts that take up room."""
    origin = np.array(obj["position"], float)
    return [
        (p.get("name", p["kind"]), part_obb(p, origin, obj["yaw"]))
        for p in obj["spec"]["parts"]
        if not is_glow(p)
    ]


def related(a: dict, b: dict) -> bool:
    """True when one twin is declared to stand on, or hang over, the other."""
    return (a.get("target") == b["key"] and a.get("rule") in ("on", "over")) or (
        b.get("target") == a["key"] and b.get("rule") in ("on", "over")
    )


def worst_overlap(a: dict, b: dict, tol: float):
    """(depth, axis a->b, part of a, part of b) of the deepest part overlap, or None."""
    worst = None
    for na, oa in twin_parts(a):
        for nb, ob in twin_parts(b):
            depth, axis = obb_penetration(oa, ob)
            if depth > tol and (worst is None or depth > worst[0]):
                worst = (depth, axis, na, nb)
    return worst


def find_problems(objects: list[dict], poly: np.ndarray, floor_y: float, tol: float = DEFAULT_TOL_M) -> list[dict]:
    """Every clearance problem in a placed bundle, worst first within a kind.
    Each is {kind: overlap|inside|wall, ...} with the keys and depth in metres."""
    problems: list[dict] = []
    for a, b in itertools.combinations(objects, 2):
        if related(a, b):
            continue
        w = worst_overlap(a, b, tol)
        if w:
            problems.append({"kind": "overlap", "depth": w[0], "a": a["key"], "b": b["key"], "part_a": w[2], "part_b": w[3], "axis": w[1]})
    problems.sort(key=lambda p: -p["depth"])

    for o in objects:
        origin = np.array(o["position"], float)
        for group in o["spec"].get("separate_groups", []):
            ins = [p for p in o["spec"]["parts"] if p.get("name", "").startswith(tuple(group))]
            out = [p for p in o["spec"]["parts"] if p not in ins]
            worst = (0.0, "", "")
            for pa in ins:
                for pb in out:
                    d = obb_penetration(part_obb(pa, origin, o["yaw"]), part_obb(pb, origin, o["yaw"]))[0]
                    if d > worst[0]:
                        worst = (d, pa.get("name", ""), pb.get("name", ""))
            if worst[0] > tol:
                problems.append({"kind": "inside", "depth": worst[0], "a": o["key"], "part_a": worst[1], "part_b": worst[2]})

    for o in objects:
        if o.get("rule") == "opening":
            continue
        worst = (0.0, "")
        for name, ob in twin_parts(o):
            for c in corners(ob):
                if c[1] < floor_y - 0.05:
                    continue
                out = point_outside_polygon(c[[0, 2]], poly)
                if out > tol and out > worst[0]:
                    worst = (out, name)
        if worst[0] > 0:
            problems.append({"kind": "wall", "depth": worst[0], "a": o["key"], "part_a": worst[1]})
    return problems


def describe(p: dict) -> str:
    cm = p["depth"] * 100
    if p["kind"] == "overlap":
        return f"OVERLAP {cm:5.1f} cm  {p['a']}.{p['part_a']}  x  {p['b']}.{p['part_b']}"
    if p["kind"] == "inside":
        return f"INSIDE  {cm:5.1f} cm  {p['a']}: {p['part_a']}  x  {p['part_b']}"
    return f"IN WALL {cm:5.1f} cm  {p['a']}.{p['part_a']}"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scene", type=Path)
    ap.add_argument("--tol", type=float, default=DEFAULT_TOL_M)
    a = ap.parse_args()
    bundle = json.loads((a.scene / "furniture.json").read_text())
    shell = load_shell(a.scene)
    poly = np.array([[p[0], p[2]] for p in shell["floor"]["polygon"]], float)
    problems = find_problems(bundle["objects"], poly, float(shell["floor"]["y"]), a.tol)
    for p in problems:
        print(describe(p))
    print(f"{len(problems)} problem(s)" if problems else "clear: no twin overlaps another or pokes through a wall")
    raise SystemExit(1 if problems else 0)


if __name__ == "__main__":
    main()
