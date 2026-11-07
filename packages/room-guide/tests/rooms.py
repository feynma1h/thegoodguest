"""Synthetic rooms for the room-guide tests, written as diorama scenes.

The repository is public and holds no room data, so every test room is built
here from numbers. The builders mirror the diorama scene's conventions: a
rectangular footprint centred on the origin, walls named by the side they
close (`wall_-x`, `wall_+z`, `wall_+x`, `wall_-z`) with inward normals, and
local +Z as each piece's front.

Read by: every test module in this directory.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass
class SceneBuilder:
    width: float = 4.0          # along x
    depth: float = 3.0          # along z
    height: float = 2.7
    kind: str = "test room"
    objects: list = field(default_factory=list)
    openings: list = field(default_factory=list)
    lights: list = field(default_factory=list)

    # ------------------------------------------------------------ the shell
    def walls(self) -> list[dict]:
        hx, hz = self.width / 2, self.depth / 2
        return [
            {"id": "wall_-x", "a": [-hx, -hz], "b": [-hx, hz], "normal": [1.0, 0.0], "measured": True},
            {"id": "wall_+z", "a": [-hx, hz], "b": [hx, hz], "normal": [0.0, -1.0], "measured": True},
            {"id": "wall_+x", "a": [hx, hz], "b": [hx, -hz], "normal": [-1.0, 0.0], "measured": True},
            {"id": "wall_-z", "a": [hx, -hz], "b": [-hx, -hz], "normal": [0.0, 1.0], "measured": True},
        ]

    def wall(self, wall_id: str) -> dict:
        return next(w for w in self.walls() if w["id"] == wall_id)

    def wall_point(self, wall_id: str, u: float, off: float = 0.0) -> tuple[float, float]:
        w = self.wall(wall_id)
        ax, az = w["a"]
        bx, bz = w["b"]
        n = math.hypot(bx - ax, bz - az)
        dx, dz = (bx - ax) / n, (bz - az) / n
        nx, nz = w["normal"]
        return (ax + dx * u + nx * off, az + dz * u + nz * off)

    @staticmethod
    def facing_yaw(wall: dict) -> float:
        nx, nz = wall["normal"]
        return math.atan2(nx, nz)

    # ------------------------------------------------------------ pieces
    def add(self, pid: str, category: str, xz: tuple[float, float], size: tuple[float, float, float],
            yaw: float = 0.0, *, support: str = "floor", on: str | None = None, bottom: float = 0.0,
            name: str | None = None, wall: str | None = None, against: str | None = None,
            params: dict | None = None, size_from: str = "measured", description: str = "") -> dict:
        sx, sy, sz = size
        obj = {
            "id": pid, "source": "shell" if support == "wall" else "inventory",
            "category": category, "name": name or pid.replace("_", " ").capitalize(),
            "description": description, "support": support, "on": on,
            "against_wall": against or "none",
            "center": [xz[0], bottom + sy / 2, xz[1]], "size": [sx, sy, sz], "yaw": yaw,
            "colors": {"main": "#cccccc"}, "material": "painted", "params": params or {},
            "light": {"emits": False}, "confidence": {"size_from": size_from, "position_from": "points"},
        }
        if wall:
            obj["wall"] = wall
        self.objects.append(obj)
        return obj

    def against(self, pid: str, category: str, wall_id: str, u: float, size: tuple[float, float, float],
                *, gap: float = 0.01, **kw) -> dict:
        """A floor piece with its back to a wall, `u` metres along it (its centre)."""
        w = self.wall(wall_id)
        x, z = self.wall_point(wall_id, u, gap + size[2] / 2)
        return self.add(pid, category, (x, z), size, self.facing_yaw(w), against=wall_id, **kw)

    def on(self, pid: str, category: str, support_id: str, offset: tuple[float, float],
           size: tuple[float, float, float], **kw) -> dict:
        """A piece standing on another one, `offset` from its centre in room x, z."""
        s = next(o for o in self.objects if o["id"] == support_id)
        top = s["center"][1] + s["size"][1] / 2
        x, z = s["center"][0] + offset[0], s["center"][2] + offset[1]
        return self.add(pid, category, (x, z), size, s["yaw"], support="on_object", on=support_id,
                        bottom=top, **kw)

    def on_wall(self, pid: str, category: str, wall_id: str, u: float, v0: float,
                size: tuple[float, float, float], **kw) -> dict:
        """Something hanging on a wall: its centre `u` along it, its bottom at `v0`."""
        w = self.wall(wall_id)
        x, z = self.wall_point(wall_id, u, size[2] / 2)
        return self.add(pid, category, (x, z), size, self.facing_yaw(w), support="wall", wall=wall_id,
                        bottom=v0, against=wall_id, **kw)

    def door(self, pid: str, wall_id: str, u0: float, u1: float, *, height: float = 2.0,
             closed: bool = True, swing: str = "left") -> None:
        self.openings.append({"id": pid, "kind": "door", "wall": wall_id, "u0": u0, "u1": u1,
                              "v0": 0.0, "v1": height, "depth": 0.05, "closed": closed})
        self.on_wall(pid, "door", wall_id, (u0 + u1) / 2, 0.0, (u1 - u0, height, 0.05),
                     params={"swing": swing, "state": "closed" if closed else "open"})

    def window(self, pid: str, wall_id: str, u0: float, u1: float, v0: float, v1: float) -> None:
        self.openings.append({"id": pid, "kind": "window", "wall": wall_id, "u0": u0, "u1": u1,
                              "v0": v0, "v1": v1, "depth": 0.2, "closed": False})
        self.on_wall(pid, "window", wall_id, (u0 + u1) / 2, v0, (u1 - u0, v1 - v0, 0.1))

    # ------------------------------------------------------------ out
    def scene(self) -> dict:
        hx, hz = self.width / 2, self.depth / 2
        return {
            "schema": "diorama.scene/1",
            "capture": {"bundle_id": "synthetic"},
            "room": {
                "type": self.kind,
                "footprint": [[-hx, -hz], [-hx, hz], [hx, hz], [hx, -hz]],
                "height": self.height, "walls": self.walls(), "openings": self.openings,
                "wall_thickness": 0.12,
            },
            "objects": self.objects,
            "lights": self.lights,
        }


def bedroom() -> SceneBuilder:
    """A plain 4 x 3.6 m bedroom that works.

    The bed's head is on the back wall (`wall_-z`) with a bedside table each
    side, a lamp on the right one; the door is on `wall_+x` near the front;
    the window is on `wall_-x`; a dresser stands on the front wall, clear of
    the door.
    """
    b = SceneBuilder(depth=3.6, kind="bedroom")
    b.door("door", "wall_+x", 0.3, 1.2)
    b.window("window", "wall_-x", 1.3, 2.3, 0.9, 2.1)
    b.against("bed", "bed", "wall_-z", 2.4, (1.4, 0.5, 2.0))
    b.against("bedside", "side_table", "wall_-z", 1.3, (0.45, 0.55, 0.4))
    b.against("bedside_2", "side_table", "wall_-z", 3.45, (0.45, 0.55, 0.4))
    b.on("lamp", "table_lamp", "bedside", (0.0, 0.0), (0.25, 0.45, 0.25))
    b.against("dresser", "dresser", "wall_+z", 1.0, (1.0, 0.8, 0.45))
    return b
