"""The boxes the furniture twins hang on.

A box says where a thing stands in the room and how big it is: it is the one
input the furniture tools need about the scan's objects, whatever produced it
(a person boxing objects on the phone, a detector, a hand edit). It lives in
`<scene>/boxes.json`:

    {
      "boxes_version": 1,
      "boxes": [
        {"id": "box_0", "category": "bed", "label": "double bed",
         "center": [1.20, 0.30, -2.10],   # world metres, y up; the BOX centre
         "yaw": 0.35,                     # radians about +y; local +x goes to (cos, 0, -sin)
         "size": [1.60, 0.60, 2.00]}      # extents along the box's own x, y, z
      ]
    }

`label` is optional and free text. `id` is what a furniture spec names in its
`object` field. Windows and doors need no entry: they come from the shell's
openings (`window_0`, `door_0`, ... in wall order), as flat slabs 0.12 m deep.

`load_boxes` returns {id: box} with `center`, `yaw`, `size` and `category`.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

BOXES_VERSION = 1
OPENING_DEPTH_M = 0.12
MAX_SIZE_M = 12.0


class BoxesError(ValueError):
    """Every problem found in a boxes document, one per line."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("invalid boxes.json:\n  " + "\n  ".join(problems))


def _vec(v, n: int = 3) -> bool:
    return (
        isinstance(v, list)
        and len(v) == n
        and all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) for x in v)
    )


def parse_boxes(doc) -> dict[str, dict]:
    """Validate a boxes document; return {id: box}. Raises BoxesError."""
    if not isinstance(doc, dict) or doc.get("boxes_version") != BOXES_VERSION or not isinstance(doc.get("boxes"), list):
        raise BoxesError([f"expected an object with boxes_version {BOXES_VERSION} and a boxes list"])
    problems: list[str] = []
    out: dict[str, dict] = {}
    for i, b in enumerate(doc["boxes"]):
        where = f"boxes[{i}]"
        if not isinstance(b, dict):
            problems.append(f"{where} must be an object")
            continue
        bid = b.get("id")
        if not isinstance(bid, str) or not bid:
            problems.append(f"{where}.id must be a non-empty string")
            continue
        where = f"box {bid}"
        if bid in out:
            problems.append(f"{where}: duplicate id")
        if not isinstance(b.get("category"), str) or not b["category"]:
            problems.append(f"{where}.category must be a non-empty string")
        if not _vec(b.get("center")):
            problems.append(f"{where}.center must be [x, y, z] in metres")
        if not (isinstance(b.get("yaw"), (int, float)) and not isinstance(b.get("yaw"), bool) and math.isfinite(b["yaw"])):
            problems.append(f"{where}.yaw must be a number (radians)")
        if not (_vec(b.get("size")) and all(0 < x <= MAX_SIZE_M for x in b["size"])):
            problems.append(f"{where}.size must be [x, y, z] extents, each in (0, {MAX_SIZE_M}] metres")
        if "label" in b and not isinstance(b["label"], str):
            problems.append(f"{where}.label must be a string")
        extra = set(b) - {"id", "category", "label", "center", "yaw", "size"}
        if extra:
            problems.append(f"{where}: unknown keys {sorted(extra)}")
        out[bid] = b
    if problems:
        raise BoxesError(problems)
    return out


def opening_boxes(shell: dict) -> dict[str, dict]:
    """A flat box per window and door in the shell's walls, facing the room."""
    from .shell_finish import wall_frame

    out: dict[str, dict] = {}
    counts = {"window": 0, "door": 0}
    floor = (shell.get("floor") or {}).get("polygon") or []
    centroid = np.mean([[p[0], p[2]] for p in floor], axis=0) if floor else None
    for wall in shell.get("walls", []):
        fr = wall_frame(np.array(wall.get("polygon") or wall.get("quad"), float))
        if fr is None:
            continue
        for op in wall.get("openings", []):
            kind = op.get("classification")
            if kind not in counts:
                continue
            (u0, v0), (u1, v1) = op["rect_uv"]
            mid = fr["origin"] + fr["axis_u"] * ((u0 + u1) / 2 * fr["w"]) + np.array([0.0, (v0 + v1) / 2 * fr["h"], 0.0])
            n = fr["normal"]
            if centroid is not None and float(np.dot(centroid - mid[[0, 2]], n[[0, 2]])) < 0:
                n = -n  # the winding said outward: a window faces the room whatever the file says
            out[f"{kind}_{counts[kind]}"] = {
                "id": f"{kind}_{counts[kind]}",
                "category": kind,
                "center": [round(float(x), 4) for x in mid],
                "yaw": math.atan2(n[0], n[2]),
                "size": [round(float((u1 - u0) * fr["w"]), 4), round(float((v1 - v0) * fr["h"]), 4), OPENING_DEPTH_M],
            }
            counts[kind] += 1
    return out


def load_shell(scene: Path) -> dict:
    """<scene>/shell.json: the shell itself, or an assets response carrying `shell`."""
    doc = json.loads((scene / "shell.json").read_text())
    return doc if "walls" in doc else doc["shell"]


def load_boxes(scene: Path) -> dict[str, dict]:
    """The scene's boxes.json (if any) plus the shell's openings."""
    boxes: dict[str, dict] = {}
    bp = scene / "boxes.json"
    if bp.exists():
        boxes.update(parse_boxes(json.loads(bp.read_text())))
    if (scene / "shell.json").exists():
        boxes.update(opening_boxes(load_shell(scene)))
    return boxes


def box_pose(box: dict) -> tuple[np.ndarray, float, np.ndarray]:
    """(footprint centre on the floor, yaw about +y in radians, size) of a box."""
    c = np.array(box["center"], float)
    size = np.array(box["size"], float)
    c[1] -= size[1] / 2
    return c, float(box["yaw"]), size


def box_corners(box: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(corners 8x3 in world, centre, 3x3 rotation) of a box."""
    from .furniture_geometry import yaw_matrix

    rot = yaw_matrix(float(box["yaw"]))
    size = np.array(box["size"], float)
    signs = np.array([[x, y, z] for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)], float)
    centre = np.array(box["center"], float)
    return (rot @ (signs * size / 2).T).T + centre, centre, rot
