"""Regenerate the furniture twins' placement bundle from the scan's boxes and
the Claude-written parameter files.

    python tools/furniture_models.py build outputs/scene-<id>
        -> outputs/scene-<id>/furniture.json   (served by tools/serve_scene.py,
           drawn by /shell-finish?...&furniture=<url>)

Inputs
  <scene>/boxes.json                 where each piece stands, its footprint,
                                     height and yaw (tools/furniture_boxes.py
                                     documents the format); windows and doors
                                     come from <scene>/shell.json's openings
  <scene>/shell.json                 the floor polygon the walls stand on
  <scene>/furniture/specs/<key>.json one parameter file per piece — parts,
                                     materials, dimensions — written by Claude
                                     from the photos and revised in the render
                                     loop (tools/FURNITURE_TWIN_FLOW.md);
                                     --specs picks another folder
Output
  furniture.json: each spec with its world placement resolved by the rules in
  tools/furniture_placement.py, and the fixes those rules made, with reasons,
  so a re-scan moves every twin with its box.

Checks (printed to stderr, non-fatal unless --strict): the spec's declared
box_dims must match its box (a spec written for another scan, or a box that
was resized, shows up here); every part must stay within a margin of the box
footprint (a twin that has wandered off its box is a bug); and the placed
twins must clear each other and the walls.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

from .furniture_boxes import BoxesError, box_pose, load_boxes, load_shell
from .furniture_clearance import describe
from .furniture_geometry import part_extent
from .furniture_placement import PlacementError, place_all, validate_place

FURNITURE_VERSION = 1
PART_KINDS = ("box", "cyl", "sphere", "lathe", "tube", "extrude", "books", "drape")
SPEC_KEYS = {"key", "object", "label", "revision", "note", "box_dims", "materials", "parts", "place", "separate_groups"}


def validate_spec(spec: dict) -> list[str]:
    """Problems with one parameter file; [] when it is fine."""
    key = spec.get("key", "?")
    problems = []
    for k in ("key", "object", "box_dims", "materials", "parts"):
        if k not in spec:
            problems.append(f"{key}: missing {k}")
    problems += [f"{key}: {k} is not a spec field {sorted(SPEC_KEYS)}" for k in spec if k not in SPEC_KEYS]
    if any("missing" in m for m in problems):
        return problems
    d = spec["box_dims"]
    if not (isinstance(d, list) and len(d) == 3 and all(isinstance(x, (int, float)) and x > 0 for x in d)):
        problems.append(f"{key}: box_dims must be three positive metres")
    mats = spec["materials"]
    if not isinstance(mats, dict):
        return problems + [f"{key}: materials must be an object"]
    if not (isinstance(spec["parts"], list) and spec["parts"]):
        return problems + [f"{key}: parts must be a non-empty list"]
    for i, p in enumerate(spec["parts"]):
        name = f"{key}.parts[{i}]"
        if not isinstance(p, dict) or p.get("kind") not in PART_KINDS:
            problems.append(f"{name}: kind must be one of {list(PART_KINDS)}, got {p.get('kind') if isinstance(p, dict) else p!r}")
            continue
        if p.get("mat") not in mats and p["kind"] != "books":
            problems.append(f"{name}: mat {p.get('mat')!r} is not in materials")
        try:
            part_extent(p)
        except (KeyError, TypeError, ValueError) as exc:
            problems.append(f"{name}: a {p['kind']} part is missing or has a bad field ({exc!r})")
    return problems + validate_place(spec)


def load_specs(spec_dir: Path) -> list[dict]:
    specs = [json.loads(p.read_text()) for p in sorted(spec_dir.glob("*.json"))]
    problems = [m for s in specs for m in validate_spec(s)]
    keys = [s.get("key") for s in specs]
    problems += [f"duplicate spec key {k!r}" for k in sorted({k for k in keys if keys.count(k) > 1})]
    if problems:
        raise SystemExit("invalid furniture specs:\n  " + "\n  ".join(problems))
    return specs


def box_problems(spec: dict, box: dict) -> list[str]:
    """Is the spec still the piece its box describes?"""
    _, _, dims = box_pose(box)
    problems = []
    want = np.array(spec["box_dims"], float)
    if np.abs(want - dims).max() > 0.03:
        problems.append(f"{spec['key']}: spec box_dims {want.tolist()} vs box {np.round(dims, 3).tolist()}")
    lo, hi = np.full(3, np.inf), np.full(3, -np.inf)
    for part in spec["parts"]:
        a, b = part_extent(part)
        lo, hi = np.minimum(lo, a), np.maximum(hi, b)
    margin = np.array([0.3, 0.6, 0.3])  # y: props and lamps may stand well above the box
    half = dims / 2
    if (lo < np.array([-half[0], 0, -half[2]]) - margin).any() or (hi > np.array([half[0], dims[1], half[2]]) + margin).any():
        problems.append(f"{spec['key']}: parts extend {np.round(lo, 2).tolist()}..{np.round(hi, 2).tolist()} beyond the box {np.round(half, 2).tolist()}")
    return problems


def build(scene: Path, spec_dir: Path, strict: bool = False) -> dict:
    boxes = load_boxes(scene)
    shell = load_shell(scene)
    poly = np.array([[p[0], p[2]] for p in shell["floor"]["polygon"]], float)
    specs = load_specs(spec_dir)
    objects, clearance = place_all(specs, boxes, poly, float(shell["floor"]["y"]))
    problems = [m for s in specs for m in box_problems(s, boxes[s["object"]])]
    problems += [describe(p) for p in clearance]
    for p in problems:
        print("WARN", p, file=sys.stderr)
    if strict and problems:
        raise SystemExit(1)
    return {"furniture_version": FURNITURE_VERSION, "scene_id": shell.get("scene_id"), "objects": objects}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["build"])
    ap.add_argument("scene", type=Path)
    ap.add_argument("--specs", type=Path, help="default <scene>/furniture/specs")
    ap.add_argument("--strict", action="store_true", help="exit 1 on any warning")
    a = ap.parse_args()
    try:
        bundle = build(a.scene, a.specs or a.scene / "furniture" / "specs", a.strict)
    except (BoxesError, PlacementError) as exc:
        raise SystemExit(str(exc))
    path = a.scene / "furniture.json"
    path.write_text(json.dumps(bundle, indent=1))
    print(f"wrote {path} ({len(bundle['objects'])} twins: {', '.join(o['key'] for o in bundle['objects'])})")


if __name__ == "__main__":
    main()
