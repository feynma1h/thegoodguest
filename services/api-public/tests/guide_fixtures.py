"""A synthetic room and a scripted stand-in for Claude, for the room-guide tests.

The repository is public and holds no room data, so the room here is built from
numbers: a 4 x 3.6 m study written as a diorama scene (`diorama.scene/1`, the
conventions of packages/room-guide/tests/rooms.py: a footprint centred on the
origin, walls named by the side they close with inward normals, +Z each piece's
front). A desk stands against `wall_+x` with its chair at it, a window is on
`wall_-x` and the door on `wall_+z`.

`Script` plays Claude: the rules pass gets STUDY_NEEDS, each guide request the
next scripted step. `StubGateway` is the gateway's stub mode, except that a text
block reaches the panel as a delta the way a replayed or live answer does (stub
mode alone never calls on_text).

Read by: test_guide_session.py, test_guide_routes.py.
"""
from __future__ import annotations

import copy
import json
import math

from thegoodguest_room_guide.gateway import Gateway, JsonRequest

W, D, H = 4.0, 3.6, 2.7


def _walls() -> list[dict]:
    hx, hz = W / 2, D / 2
    return [
        {"id": "wall_-x", "a": [-hx, -hz], "b": [-hx, hz], "normal": [1.0, 0.0]},
        {"id": "wall_+z", "a": [-hx, hz], "b": [hx, hz], "normal": [0.0, -1.0]},
        {"id": "wall_+x", "a": [hx, hz], "b": [hx, -hz], "normal": [-1.0, 0.0]},
        {"id": "wall_-z", "a": [hx, -hz], "b": [-hx, -hz], "normal": [0.0, 1.0]},
    ]


def _on_wall(wall_id: str, u: float, off: float) -> tuple[float, float, float]:
    """(x, z, yaw) of a point `u` along a wall and `off` out from it, facing the room."""
    w = next(w for w in _walls() if w["id"] == wall_id)
    (ax, az), (bx, bz), (nx, nz) = w["a"], w["b"], w["normal"]
    n = math.hypot(bx - ax, bz - az)
    dx, dz = (bx - ax) / n, (bz - az) / n
    return ax + dx * u + nx * off, az + dz * u + nz * off, math.atan2(nx, nz)


def _piece(pid: str, category: str, x: float, z: float, size, yaw: float, *, support="floor",
           bottom=0.0, wall=None, against=None, params=None) -> dict:
    obj = {"id": pid, "source": "shell" if support == "wall" else "inventory", "category": category,
           "name": pid.replace("_", " ").capitalize(), "description": "", "support": support, "on": None,
           "against_wall": against or "none", "center": [x, bottom + size[1] / 2, z], "size": list(size),
           "yaw": yaw, "colors": {"main": "#cccccc"}, "material": "painted", "params": params or {},
           "light": {"emits": False}, "confidence": {"size_from": "measured", "position_from": "points"}}
    if wall:
        obj["wall"] = wall
    return obj


def study_scene() -> dict:
    """The study as a diorama scene."""
    dx, dz, dyaw = _on_wall("wall_+x", 1.8, 0.01 + 0.3)
    door_x, door_z, door_yaw = _on_wall("wall_+z", 3.4, 0.025)
    win_x, win_z, win_yaw = _on_wall("wall_-x", 1.8, 0.05)
    objects = [
        _piece("door", "door", door_x, door_z, (0.8, 2.0, 0.05), door_yaw, support="wall", wall="wall_+z",
               against="wall_+z", params={"swing": "left", "state": "closed"}),
        _piece("window", "window", win_x, win_z, (1.0, 1.2, 0.1), win_yaw, support="wall", bottom=0.9,
               wall="wall_-x", against="wall_-x"),
        _piece("desk", "desk", dx, dz, (1.2, 0.74, 0.6), dyaw, against="wall_+x"),
        _piece("chair", "office_chair", 1.05, 0.0, (0.55, 1.0, 0.55), math.pi / 2),
    ]
    hx, hz = W / 2, D / 2
    return {
        "schema": "diorama.scene/1",
        "capture": {"bundle_id": "synthetic"},
        "room": {"type": "study", "footprint": [[-hx, -hz], [-hx, hz], [hx, hz], [hx, -hz]], "height": H,
                 "walls": _walls(), "wall_thickness": 0.12,
                 "openings": [
                     {"id": "door", "kind": "door", "wall": "wall_+z", "u0": 3.0, "u1": 3.8, "v0": 0.0,
                      "v1": 2.0, "depth": 0.05, "closed": True},
                     {"id": "window", "kind": "window", "wall": "wall_-x", "u0": 1.3, "u1": 2.3, "v0": 0.9,
                      "v1": 2.1, "depth": 0.2, "closed": False}]},
        "objects": objects,
        "lights": [],
    }


STUDY_NEEDS = {
    "pieces": {
        "door": {"moves": "fixed", "why": "part of the wall", "needs": [
            {"need": "open", "side": "front", "mechanism": "hinged", "leaves": 1, "strength": "hard",
             "why": "it swings into the room"},
            {"need": "pass", "strength": "hard", "why": "it is the way in"}]},
        "window": {"moves": "fixed", "why": "part of the wall",
                   "needs": [{"need": "light", "strength": "soft", "why": "the room's daylight"}]},
        "desk": {"moves": "yes", "needs": [
            {"need": "use", "posture": "seated", "strength": "hard", "why": "worked at"}]},
        "chair": {"moves": "yes", "with": [{"piece": "desk", "how": "at", "strength": "hard", "why": "its chair"}]},
    },
    "preferences": [{"pref": "task_light", "piece": "desk", "task": "screen", "viewer": "facing_piece",
                     "weight": "high", "why": "screen work"}],
    "questions": [],
}


def last_tool_result(req) -> dict:
    return json.loads(req.messages[-1]["content"][-1]["content"])


def text(t: str):
    return lambda req: [{"type": "text", "text": t}]


def tool(name: str, args, i: int):
    return lambda req: [{"type": "tool_use", "id": f"toolu_{i:02d}", "name": name,
                         "input": args(req) if callable(args) else args}]


def look_then_offer(i: int = 1):
    """Two steps: search the room for the desk's light, then offer the first result."""
    return [tool("look_for_changes", {"goal": "light", "piece": "desk"}, i),
            tool("offer", lambda req: {"proposal": last_tool_result(req)["proposals"][0]["id"]}, i + 1)]


class Script:
    """A stand-in model: the rules pass gets the needs, each turn request the next step.
    `requests` keeps every guide request, `rules_calls` counts the rules pass."""

    def __init__(self, steps, needs: dict | None = None):
        self.steps = list(steps)
        self.needs = copy.deepcopy(needs or STUDY_NEEDS)
        self.requests: list = []
        self.rules_calls = 0

    def __call__(self, req):
        if isinstance(req, JsonRequest):
            self.rules_calls += 1
            return copy.deepcopy(self.needs)
        self.requests.append(copy.deepcopy(req))
        step = self.steps.pop(0)
        return {"content": step(req), "stop_reason": "end_turn"}


class StubGateway(Gateway):
    """Stub mode, with each text block delivered as a delta, as replay delivers it."""

    def ask_turn(self, req, on_text=None):
        data = super().ask_turn(req, on_text)
        if on_text is not None and self.mode == "stub":
            for block in data.get("content", []):
                if block.get("type") == "text":
                    on_text(block["text"])
        return data
