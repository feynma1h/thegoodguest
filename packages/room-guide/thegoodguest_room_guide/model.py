"""The room the guide reasons about: its shell, its pieces and their solids.

Built from a diorama scene (`diorama.scene/1`, the semantic room the diorama
pipeline writes) by `room_from_scene`. Nothing downstream reads the scene file
itself, so a second source of rooms needs only a second adapter here.

Frames. The room frame is the scene's: +Y up, metres. A piece's local frame has
its origin at the centre of its footprint at its lowest point, +Y up, +Z its
front (where you sit, where its doors open, a bed's foot) and +X across.
`Pose(x, y, z, yaw)` places that origin in the room. It is exactly the diorama
viewer's group.position and group.rotation.y, so a motion plan needs no
conversion on its way to the screen.

Solids. A piece's solids are boxes in its local frame. They come from the
builder that draws the piece when that export exists (the `solids` argument);
otherwise a piece is its whole box. What collides is what you see.

Categories, names and descriptions are carried as data, for the rules pass and
for speech. Nothing that decides what is allowed reads them
(tests/test_generic.py enforces that).

Read by every other module in this package.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np

from .geometry import Box

SCENE_SCHEMA = "diorama.scene/1"

Vec2 = tuple[float, float]

# Uncertainty in a piece's size, from how it was measured. Read as a margin:
# a gap is spoken net of both pieces' margins, and nothing is called a fit
# inside them.
MARGIN_MEASURED = 0.02
MARGIN_HELD = 0.04
MARGIN_ESTIMATED = 0.06

@dataclass(frozen=True)
class Part:
    """A solid box in a piece's local frame: centre and half extents."""

    cx: float
    cy: float
    cz: float
    hx: float
    hy: float
    hz: float


@dataclass(frozen=True)
class Pose:
    """Where a piece's local origin sits in the room, and its turn about +Y."""

    x: float
    y: float
    z: float
    yaw: float

    def place(self, lx: float, lz: float) -> Vec2:
        """The room position of the local floor point (lx, lz)."""
        c, s = math.cos(self.yaw), math.sin(self.yaw)
        return (self.x + lx * c + lz * s, self.z - lx * s + lz * c)

    def same_as(self, other: "Pose", tol: float = 1e-6) -> bool:
        d_yaw = math.remainder(self.yaw - other.yaw, 2 * math.pi)
        return (abs(self.x - other.x) <= tol and abs(self.y - other.y) <= tol
                and abs(self.z - other.z) <= tol and abs(d_yaw) <= tol)


def carry(p: Pose, frm: Pose, to: Pose) -> Pose:
    """Where `p` ends up when whatever it rides on moves rigidly from `frm` to `to`."""
    d_yaw = to.yaw - frm.yaw
    rx, rz = p.x - frm.x, p.z - frm.z
    c, s = math.cos(d_yaw), math.sin(d_yaw)
    return Pose(to.x + rx * c + rz * s, p.y + (to.y - frm.y), to.z - rx * s + rz * c, p.yaw + d_yaw)


@dataclass(frozen=True)
class Wall:
    """A wall's inner face, from `a` to `b` along the floor, with its inward normal."""

    id: str
    a: Vec2
    b: Vec2
    normal: Vec2

    @property
    def length(self) -> float:
        return math.hypot(self.b[0] - self.a[0], self.b[1] - self.a[1])

    @property
    def direction(self) -> Vec2:
        n = self.length
        return ((self.b[0] - self.a[0]) / n, (self.b[1] - self.a[1]) / n)

    def point(self, u: float, off: float = 0.0) -> Vec2:
        """The floor point `u` along the wall from `a`, `off` out into the room."""
        d = self.direction
        return (self.a[0] + d[0] * u + self.normal[0] * off, self.a[1] + d[1] * u + self.normal[1] * off)

    def u_of(self, p: Vec2) -> float:
        d = self.direction
        return (p[0] - self.a[0]) * d[0] + (p[1] - self.a[1]) * d[1]

    def offset_of(self, p: Vec2) -> float:
        """How far `p` stands out from the wall's face, into the room."""
        return (p[0] - self.a[0]) * self.normal[0] + (p[1] - self.a[1]) * self.normal[1]

    @property
    def facing_yaw(self) -> float:
        """The yaw that turns a piece's front to face out of this wall into the room."""
        return math.atan2(self.normal[0], self.normal[1])


@dataclass(frozen=True)
class Opening:
    """A hole in a wall: `u0`..`u1` along it from its start, `v0`..`v1` up it."""

    id: str
    kind: str
    wall: str
    u0: float
    u1: float
    v0: float
    v1: float
    depth: float
    closed: bool

    @property
    def width(self) -> float:
        return self.u1 - self.u0


@dataclass(frozen=True)
class Light:
    id: str
    piece: str | None
    position: tuple[float, float, float]
    kind: str
    on_at_night: bool


@dataclass(frozen=True)
class Piece:
    """One thing in the room, as the scene states it."""

    id: str
    name: str
    category: str
    description: str
    support: str              # "floor" | "object" | "wall" | "ceiling"
    on: str | None            # what it rests on, when support == "object"
    wall: str | None          # the wall it hangs on or backs onto
    size: tuple[float, float, float]
    pose: Pose
    parts: tuple[Part, ...]
    margin: float
    opening: str | None = None   # the shell opening this piece fills (a door leaf, a window)
    params: dict = field(default_factory=dict)
    colors: dict = field(default_factory=dict)
    material: str | None = None
    parts_from: str = "box"      # "box" | "builder"

    def solids(self, pose: Pose | None = None) -> list[Box]:
        """The piece's solid boxes in the room, at `pose` (its scanned pose by default)."""
        p = pose or self.pose
        out = []
        for q in self.parts:
            x, z = p.place(q.cx, q.cz)
            out.append(Box(x, z, q.hx, q.hz, p.yaw, p.y + q.cy - q.hy, p.y + q.cy + q.hy))
        return out

    def box(self, pose: Pose | None = None) -> Box:
        """The piece's whole box in the room."""
        p = pose or self.pose
        return Box(p.x, p.z, self.size[0] / 2, self.size[2] / 2, p.yaw, p.y, p.y + self.size[1])


@dataclass(frozen=True)
class Room:
    kind: str
    footprint: np.ndarray
    height: float
    walls: tuple[Wall, ...]
    openings: tuple[Opening, ...]
    pieces: dict[str, Piece]
    lights: tuple[Light, ...]
    source: dict

    def wall(self, wall_id: str) -> Wall:
        for w in self.walls:
            if w.id == wall_id:
                return w
        raise KeyError(wall_id)

    def opening(self, opening_id: str) -> Opening:
        for o in self.openings:
            if o.id == opening_id:
                return o
        raise KeyError(opening_id)

    def riders(self, piece_id: str) -> list[str]:
        """Everything resting on the piece, and on those, in order."""
        out: list[str] = []
        frontier = [piece_id]
        while frontier:
            current = frontier.pop(0)
            for p in self.pieces.values():
                if p.support == "object" and p.on == current and p.id not in out:
                    out.append(p.id)
                    frontier.append(p.id)
        return out

    def base_of(self, piece_id: str) -> str:
        """The piece at the bottom of the stack this piece rests in."""
        seen = set()
        p = self.pieces[piece_id]
        while p.support == "object" and p.on in self.pieces and p.id not in seen:
            seen.add(p.id)
            p = self.pieces[p.on]
        return p.id


Arrangement = dict[str, Pose]


def pose_in(room: Room, arrangement: Arrangement, piece_id: str) -> Pose:
    """A piece's pose in an arrangement: its override, or where the scan put it."""
    return arrangement.get(piece_id, room.pieces[piece_id].pose)


def spoken(name: str) -> str:
    """A scene name as it sits inside a sentence: "Double bed" -> "double bed", "AC unit" stays."""
    if len(name) > 1 and name[0].isupper() and name[1].islower():
        return name[0].lower() + name[1:]
    return name


def _margin(confidence: dict) -> float:
    size_from = str(confidence.get("size_from", "")).strip().lower()
    if size_from == "measured":
        return MARGIN_MEASURED
    if size_from.startswith("measured"):
        return MARGIN_HELD
    return MARGIN_ESTIMATED


_SUPPORT = {"floor": "floor", "on_object": "object", "wall": "wall", "ceiling": "ceiling"}


def _parts(piece_id: str, size: tuple[float, float, float], exported: list | None) -> tuple[tuple[Part, ...], str]:
    """A piece's solids: the exported part boxes, each trimmed to the piece's own box
    (a pillow drawn a little proud of the bed is still the bed), or the whole box."""
    whole = (Part(0.0, size[1] / 2, 0.0, size[0] / 2, size[1] / 2, size[2] / 2),)
    if not exported:
        return whole, "box"
    hx, hy, hz = size[0] / 2, size[1], size[2] / 2
    parts = []
    for row in exported:
        cx, cy, cz, px, py, pz = (float(v) for v in row)
        x0, x1 = max(cx - px, -hx), min(cx + px, hx)
        y0, y1 = max(cy - py, 0.0), min(cy + py, hy)
        z0, z1 = max(cz - pz, -hz), min(cz + pz, hz)
        if x1 - x0 <= 1e-3 or y1 - y0 <= 1e-3 or z1 - z0 <= 1e-3:
            continue
        parts.append(Part((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2, (x1 - x0) / 2, (y1 - y0) / 2, (z1 - z0) / 2))
    if not parts:
        return whole, "box"
    return tuple(_reduce(parts)), "builder"


MAX_PARTS = 8


def _vol(q: Part) -> float:
    return 8 * q.hx * q.hy * q.hz


def _merged(a: Part, b: Part) -> Part:
    x0, x1 = min(a.cx - a.hx, b.cx - b.hx), max(a.cx + a.hx, b.cx + b.hx)
    y0, y1 = min(a.cy - a.hy, b.cy - b.hy), max(a.cy + a.hy, b.cy + b.hy)
    z0, z1 = min(a.cz - a.hz, b.cz - b.hz), max(a.cz + a.hz, b.cz + b.hz)
    return Part((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2, (x1 - x0) / 2, (y1 - y0) / 2, (z1 - z0) / 2)


def _inside(a: Part, b: Part, tol: float = 1e-3) -> bool:
    return (abs(a.cx - b.cx) + a.hx <= b.hx + tol and abs(a.cy - b.cy) + a.hy <= b.hy + tol
            and abs(a.cz - b.cz) + a.hz <= b.hz + tol)


def _reduce(parts: list[Part]) -> list[Part]:
    """At most MAX_PARTS boxes covering every part: parts inside others are dropped,
    then the pair whose joint box adds the least empty space is merged, until few
    enough remain. A desk keeps its top and legs apart (merging them would fill the
    knee space, the costliest merge there is); a shelf of books becomes one block."""
    parts = sorted(parts, key=_vol, reverse=True)
    kept: list[Part] = []
    for q in parts:
        if not any(_inside(q, k) for k in kept):
            kept.append(q)
    while len(kept) > MAX_PARTS:
        best, pair = None, None
        for i in range(len(kept)):
            for j in range(i + 1, len(kept)):
                m = _merged(kept[i], kept[j])
                waste = _vol(m) - _vol(kept[i]) - _vol(kept[j])
                if best is None or waste < best:
                    best, pair = waste, (i, j, m)
        i, j, m = pair
        kept = [k for n, k in enumerate(kept) if n not in (i, j)]
        kept = [k for k in kept if not _inside(k, m)] + [m]
    return kept


def room_from_scene(scene: dict, solids: dict | None = None) -> Room:
    """The room a diorama scene describes. `solids` maps piece ids to exported part boxes
    (`[cx, cy, cz, hx, hy, hz]` rows in the piece's local frame)."""
    if scene.get("schema") != SCENE_SCHEMA:
        raise ValueError(f"not a {SCENE_SCHEMA} scene: {scene.get('schema')!r}")
    r = scene["room"]
    walls = tuple(
        Wall(w["id"], tuple(w["a"]), tuple(w["b"]), tuple(w["normal"])) for w in r["walls"]
    )
    openings = tuple(
        Opening(o["id"], o["kind"], o["wall"], float(o["u0"]), float(o["u1"]), float(o["v0"]),
                float(o["v1"]), float(o.get("depth", 0.0)), bool(o.get("closed", False)))
        for o in r.get("openings", [])
    )
    opening_ids = {o.id for o in openings}
    pieces: dict[str, Piece] = {}
    for o in scene["objects"]:
        size = tuple(float(v) for v in o["size"])
        cx, cy, cz = (float(v) for v in o["center"])
        parts, parts_from = _parts(o["id"], size, (solids or {}).get(o["id"]))
        against = o.get("against_wall")
        pieces[o["id"]] = Piece(
            id=o["id"],
            name=o.get("name") or o["id"],
            category=o.get("category", ""),
            description=o.get("description", ""),
            support=_SUPPORT.get(o.get("support", "floor"), "floor"),
            on=o.get("on"),
            wall=o.get("wall") or (against if against and against != "none" else None),
            size=size,
            pose=Pose(cx, cy - size[1] / 2, cz, float(o.get("yaw", 0.0))),
            parts=parts,
            margin=_margin(o.get("confidence") or {}),
            opening=o["id"] if o["id"] in opening_ids else None,
            params=dict(o.get("params") or {}),
            colors=dict(o.get("colors") or {}),
            material=o.get("material"),
            parts_from=parts_from,
        )
    lights = tuple(
        Light(L["id"], L.get("object"), tuple(L["position"]), L.get("kind", ""), bool(L.get("on_at_night", False)))
        for L in scene.get("lights", [])
    )
    return Room(
        kind=r.get("type", "room"),
        footprint=np.asarray(r["footprint"], dtype=float),
        height=float(r["height"]),
        walls=walls,
        openings=openings,
        pieces=pieces,
        lights=lights,
        source={"schema": scene["schema"], **(scene.get("capture") or {})},
    )


def load_room(scene_path: str | Path, solids_path: str | Path | None = None) -> Room:
    scene = json.loads(Path(scene_path).read_text())
    solids = json.loads(Path(solids_path).read_text()) if solids_path and Path(solids_path).exists() else None
    return room_from_scene(scene, solids)


def with_poses(room: Room, poses: Arrangement) -> Room:
    """The same room with some pieces standing elsewhere (used to treat an
    arrangement as the new scanned state, e.g. after the person keeps it)."""
    pieces = dict(room.pieces)
    for pid, pose in poses.items():
        pieces[pid] = replace(pieces[pid], pose=pose)
    return replace(room, pieces=pieces)
