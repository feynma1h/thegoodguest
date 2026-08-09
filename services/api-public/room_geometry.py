"""The room as measured GEOMETRY — the solver's world (decision 0132).

`derive_room_geometry(manifest, shell)` turns the two documents api-public
already fetches into oriented boxes, a floor polygon and interior-wound walls
with their openings. It is the geometric counterpart of `scene_facts`, and the
split between them is the whole of 0132:

  scene_facts  → the GUEST's world: names, framed strings, honest limits.
                 No coordinates, ever, because the guest may not compute.
  room_geometry → the SOLVER's world: coordinates and nothing else.
                 No prose, no names the model reads back.

Neither is derivable from the other, and that is deliberate. A tool shaped
`move(object, x, y, z)` would need the guest to author coordinates from a
world where rule 5 says walls and footprints do not exist — 0132 calls that
inverting the honesty contract rather than stretching it.

WHAT THE BOX TRIPLE MEANS. `roomplan_box.dims` is (width, height, depth) in
the box's own yaw frame — dims[1] is world-up because RoomPlan boxes are
pure-yaw (0076). Measured here rather than assumed, across the four preserved
walk rooms (2026-08-09):

  - 31 boxes across 4 rooms. The largest dimension sits at index 1 in 16 of
    them, index 0 in 12, index 2 in 3 — so the triple is NOT sorted, in any
    order, and the axis semantics survive.
  - Component ORDER is preserved end to end: on all 9 boxes that ship a clip
    volume, `splat_clip.half_extents_m == dims/2 + margin` component by
    component, to 2e-4.
  - Every box with dims[1] > 1.5 m is a wardrobe or a refrigerator; no box
    reads as a 2 m wide, 0.5 m tall anything.

This matters beyond the solver, so it is written here rather than in a
comment: `scene_facts` restricts the guest to a longest dimension, and the
reason it originally gave — that the triple is descending-sorted and its axis
semantics therefore unrecoverable — is what this measurement refuted. That
note has been corrected; the RESTRICTION still stands, because changing what
the guest may SAY is decision 0096's call and needs a FACTS_VERSION bump and
its own voice evals. Nothing here touches it — the measurement above is the
evidence that change would rest on.

Consumers: spec_solver.py, guest_tools.py.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

Vec3 = tuple[float, float, float]
Vec2 = tuple[float, float]

# A wall polygon whose Newell normal is this close to vertical is a floor or
# ceiling fragment, not a wall — it has no horizontal interior direction.
_MIN_HORIZONTAL_NORMAL = 1e-9


@dataclass(frozen=True)
class OrientedBox:
    """A yaw-only world box: the shape of every RoomPlan measurement.

    `dims` is (width, height, depth) in the box's own frame; `center` is the
    box centre in world coordinates, so the base sits at center[1] - dims[1]/2.
    """
    center: Vec3
    dims: Vec3
    yaw_rad: float

    @property
    def half_extents(self) -> Vec3:
        return (self.dims[0] / 2.0, self.dims[1] / 2.0, self.dims[2] / 2.0)

    @property
    def base_y(self) -> float:
        return self.center[1] - self.dims[1] / 2.0

    @property
    def footprint_radius(self) -> float:
        """Circumradius of the FOOTPRINT — the smallest disc containing the
        box's floor rectangle under any yaw. Used for cheap rejection and for
        the same reason 0096 uses a circumradius: it is yaw-true."""
        return math.hypot(self.dims[0], self.dims[2]) / 2.0

    def moved_to(self, center: Vec3) -> "OrientedBox":
        return OrientedBox(center=center, dims=self.dims, yaw_rad=self.yaw_rad)

    def local_axes_xz(self) -> tuple[Vec2, Vec2]:
        """The box's local +x and +z as world XZ unit vectors.

        THE YAW CONVENTION, measured (2026-08-09) rather than assumed —
        `yaw_rad` rotates (x, z) as an ordinary 2D plane:

            x = u·cos θ − v·sin θ
            z = u·sin θ + v·cos θ

        Two independent instruments agree on all four preserved walk rooms,
        and they agree because RoomPlan furniture is aligned to the walls it
        stands against (0076's operator walk: 9/9 on position, extent AND
        facing):

          - Angle between a box's local +x and the nearest wall's lateral
            axis, mod 90°: 0.0° on 14 of 15 boxes in the three four-wall
            rooms under this convention; 19–27° under the opposite sign.
          - Flush-edge test — a box standing against a wall presents an EDGE,
            so its two nearest footprint corners sit at equal distance from
            the wall plane. Spread is 0.000 m under this convention across
            all four rooms; 0.02–0.55 m under the opposite sign.

        The opposite sign is what a three.js `setFromAxisAngle([0,1,0], yaw)`
        produces, and SplatViewer builds every `splat_clip` volume that way —
        see the note at that call site. Deliberately NOT changed here: the
        clip was adjudicated by eye (0104) and re-rendering every existing
        room is the operator's call, not a side effect of this module.
        """
        cos, sin = math.cos(self.yaw_rad), math.sin(self.yaw_rad)
        return ((cos, sin), (-sin, cos))

    def footprint_corners(self) -> tuple[Vec2, Vec2, Vec2, Vec2]:
        """The four floor corners in world XZ, in order."""
        hx, _, hz = self.half_extents
        (ax, az), (bx, bz) = self.local_axes_xz()
        cx, _, cz = self.center
        return tuple(  # type: ignore[return-value]
            (cx + u * ax + v * bx, cz + u * az + v * bz)
            for u, v in ((-hx, -hz), (hx, -hz), (hx, hz), (-hx, hz))
        )


@dataclass(frozen=True)
class RoomOpening:
    """A door, window or through-opening, at its world centre on its wall."""
    classification: str
    wall_id: str
    center: Vec3


@dataclass(frozen=True)
class RoomWall:
    """One shell wall. `normal` points INTO the room — the winding contract
    the server test-pins and lib/shell3d mirrors — horizontalized, since
    walls are vertical."""
    wall_id: str
    normal: Vec2          # (nx, nz), unit
    axis_u: Vec2          # unit lateral axis in the wall plane: up x normal
    origin: Vec3          # bounding-rect (min-u, min-y) corner
    width_m: float
    height_m: float
    openings: tuple[RoomOpening, ...]

    def point_at(self, u_frac: float) -> Vec3:
        """A world point on the wall's base line at a lateral fraction."""
        return (
            self.origin[0] + u_frac * self.width_m * self.axis_u[0],
            self.origin[1],
            self.origin[2] + u_frac * self.width_m * self.axis_u[1],
        )

    def signed_distance(self, x: float, z: float) -> float:
        """Distance from the wall plane, positive on the room side."""
        dx = x - self.origin[0]
        dz = z - self.origin[2]
        return dx * self.normal[0] + dz * self.normal[1]

    def lateral(self, x: float, z: float) -> float:
        """Position along the wall in meters from its (min-u) end."""
        return (x - self.origin[0]) * self.axis_u[0] + (
            z - self.origin[2]
        ) * self.axis_u[1]


@dataclass(frozen=True)
class RoomObject:
    """One fused object, as geometry. `name` mirrors scene_facts' spoken name
    so a tool call and a sentence refer to the same thing."""
    key: str
    object_id: str
    box_identifier: str | None
    name: str
    label: str
    placed: bool
    box: OrientedBox | None
    position: Vec3 | None


@dataclass(frozen=True)
class RoomGeometry:
    objects: tuple[RoomObject, ...]
    floor_polygon: tuple[Vec2, ...]   # world XZ, empty when no floor measured
    floor_y: float | None
    walls: tuple[RoomWall, ...]

    def by_key(self, key: str) -> RoomObject | None:
        for obj in self.objects:
            if obj.key == key:
                return obj
        return None

    @property
    def openings(self) -> tuple[RoomOpening, ...]:
        return tuple(o for w in self.walls for o in w.openings)


# ---------------------------------------------------------------------------
# Keying (decision 0131)
# ---------------------------------------------------------------------------

def spec_key(obj: dict) -> str:
    """The Design Specification's key for a manifest object.

    `roomplan_box.identifier` where the object has a box, `object_id`
    otherwise. Object ids are assigned by fusion and this project re-drives
    scenes constantly (0080's four warm re-drives changed object counts on
    every room), so an id-keyed entry would silently re-point at a different
    object. Box identifiers are UUIDs carried verbatim from the capture's
    own room.json, which perception caches in the outputs bucket
    (scenes/{scene_id}/roomplan/room.json) and re-reads verbatim on every
    re-drive.

    Verified rather than inferred (2026-08-09): all 9 identifiers in the spike
    room's LIVE manifest — staged after its warm re-drives and again after the
    0104 re-drive — are byte-identical to the ones in the capture's
    `captured_room_built.json`, committed 11 days earlier as a verbatim
    fixture. The key survives re-drives because it belongs to the capture,
    not to the pipeline.

    The `obj:` prefix keeps the two namespaces from ever colliding, so an
    unstable key is visibly unstable.
    """
    box = obj.get("roomplan_box")
    if isinstance(box, dict):
        ident = box.get("identifier")
        if isinstance(ident, str) and ident:
            return f"box:{ident}"
    return f"obj:{obj.get('object_id') or ''}"


# ---------------------------------------------------------------------------
# Derivation
# ---------------------------------------------------------------------------

def _vec3(value: object) -> Vec3 | None:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return None
    try:
        out = tuple(float(v) for v in value)
    except (TypeError, ValueError):
        return None
    if any(math.isnan(v) or math.isinf(v) for v in out):
        return None
    return out  # type: ignore[return-value]


def _box(obj: dict) -> OrientedBox | None:
    raw = obj.get("roomplan_box")
    if not isinstance(raw, dict):
        return None
    dims = _vec3(raw.get("dims"))
    center = _vec3(raw.get("center_world"))
    yaw = raw.get("yaw_rad")
    if dims is None or center is None or not isinstance(yaw, (int, float)):
        return None
    if any(d <= 0 for d in dims) or math.isnan(yaw) or math.isinf(yaw):
        return None
    return OrientedBox(center=center, dims=dims, yaw_rad=float(yaw))


def _newell_normal(corners: list[Vec3]) -> Vec3:
    nx = ny = nz = 0.0
    n = len(corners)
    for i in range(n):
        ax, ay, az = corners[i]
        bx, by, bz = corners[(i + 1) % n]
        nx += (ay - by) * (az + bz)
        ny += (az - bz) * (ax + bx)
        nz += (ax - bx) * (ay + by)
    return (nx, ny, nz)


def _wall(entry: dict) -> RoomWall | None:
    """One shell wall in the frame lib/shell3d.ts mirrors — bounding rect
    in-plane, NOT corner 0, because v3 winding normalization may rotate the
    start vertex (0077's measured lesson, ported here unchanged)."""
    raw = entry.get("polygon") or entry.get("quad")
    if not isinstance(raw, (list, tuple)) or len(raw) < 3:
        return None
    corners = [c for c in (_vec3(c) for c in raw) if c is not None]
    if len(corners) < 3:
        return None
    nx, _, nz = _newell_normal(corners)
    h = math.hypot(nx, nz)
    if h < _MIN_HORIZONTAL_NORMAL:
        return None
    normal = (nx / h, nz / h)
    axis_u = (normal[1], -normal[0])  # up x normal
    us = [c[0] * axis_u[0] + c[2] * axis_u[1] for c in corners]
    ys = [c[1] for c in corners]
    width, height = max(us) - min(us), max(ys) - min(ys)
    if width < 1e-9 or height < 1e-9:
        return None
    c0 = corners[0]
    du = min(us) - us[0]
    origin = (c0[0] + du * axis_u[0], min(ys), c0[2] + du * axis_u[1])

    wall_id = str(entry.get("wall_id") or "")
    openings: list[RoomOpening] = []
    for op in entry.get("openings") or []:
        if not isinstance(op, dict):
            continue
        rect = op.get("rect_uv")
        if (
            not isinstance(rect, (list, tuple))
            or len(rect) != 2
            or any(not isinstance(p, (list, tuple)) or len(p) != 2 for p in rect)
        ):
            continue
        try:
            (u0, v0), (u1, v1) = ((float(a), float(b)) for a, b in rect)
        except (TypeError, ValueError):
            continue
        uc, vc = (u0 + u1) / 2.0, (v0 + v1) / 2.0
        openings.append(RoomOpening(
            classification=str(op.get("classification") or "opening"),
            wall_id=wall_id,
            center=(
                origin[0] + uc * width * axis_u[0],
                origin[1] + vc * height,
                origin[2] + uc * width * axis_u[1],
            ),
        ))
    return RoomWall(
        wall_id=wall_id,
        normal=normal,
        axis_u=axis_u,
        origin=origin,
        width_m=width,
        height_m=height,
        openings=tuple(openings),
    )


def derive_room_geometry(
    manifest: dict,
    shell: dict | None,
    *,
    names: dict[str, str] | None = None,
) -> RoomGeometry:
    """Pure derivation: the two fetched documents → the solver's world.

    `names` maps object_id → the spoken name scene_facts derived, so the
    solver's refusals and descriptions call things what the guest calls them.
    Absent, labels are used verbatim.

    Degrades rather than raising, everywhere: a missing shell yields no floor
    and no walls (and the solver then refuses wall relations by its own rule),
    a malformed wall is skipped, a box without dims is simply a box-less
    object. Nothing here is allowed to take a conversation down.
    """
    objects: list[RoomObject] = []
    raw_objects = sorted(
        (o for o in manifest.get("objects", []) if isinstance(o, dict)),
        key=lambda o: str(o.get("object_id") or ""),
    )
    for obj in raw_objects:
        object_id = str(obj.get("object_id") or "")
        box_raw = obj.get("roomplan_box")
        ident = (
            box_raw.get("identifier") if isinstance(box_raw, dict) else None
        )
        label = str(obj.get("label") or "unidentified object")
        wt = obj.get("world_transform")
        position = _vec3(wt.get("position")) if isinstance(wt, dict) else None
        objects.append(RoomObject(
            key=spec_key(obj),
            object_id=object_id,
            box_identifier=ident if isinstance(ident, str) and ident else None,
            name=(names or {}).get(object_id, label),
            label=label,
            placed=bool(obj.get("placed")),
            box=_box(obj),
            position=position,
        ))

    floor_polygon: tuple[Vec2, ...] = ()
    floor_y: float | None = None
    walls: list[RoomWall] = []
    if isinstance(shell, dict) and shell.get("status") == "ready":
        floor = shell.get("floor")
        if isinstance(floor, dict):
            poly = [c for c in (_vec3(c) for c in floor.get("polygon") or [])
                    if c is not None]
            if len(poly) >= 3:
                floor_polygon = tuple((c[0], c[2]) for c in poly)
                y = floor.get("y")
                floor_y = (
                    float(y)
                    if isinstance(y, (int, float))
                    else sum(c[1] for c in poly) / len(poly)
                )
        for entry in shell.get("walls") or []:
            if not isinstance(entry, dict):
                continue
            wall = _wall(entry)
            if wall is not None:
                walls.append(wall)

    return RoomGeometry(
        objects=tuple(objects),
        floor_polygon=floor_polygon,
        floor_y=floor_y,
        walls=tuple(walls),
    )


# ---------------------------------------------------------------------------
# 2D predicates (the constraints a proposal must satisfy)
# ---------------------------------------------------------------------------

def point_in_polygon(point: Vec2, polygon: tuple[Vec2, ...]) -> bool:
    """Ray casting in XZ. Boundary cases are not distinguished — a footprint
    grazing the floor edge is not the failure this guards against."""
    if len(polygon) < 3:
        return False
    x, z = point
    inside = False
    n = len(polygon)
    for i in range(n):
        x0, z0 = polygon[i]
        x1, z1 = polygon[(i + 1) % n]
        if (z0 > z) != (z1 > z):
            t = (z - z0) / (z1 - z0)
            if x < x0 + t * (x1 - x0):
                inside = not inside
    return inside


def footprint_inside_floor(box: OrientedBox, polygon: tuple[Vec2, ...]) -> bool:
    """Every floor corner of the box inside the measured floor.

    Corner containment, not centre containment: a piece half out of the room
    is exactly the failure this exists to catch, and it is the same
    conservative posture as the single-view contact priors' floor-bounds gate
    (decision 0067) — reject to unplaced rather than ship a wrong placement.
    """
    if len(polygon) < 3:
        return False
    return all(point_in_polygon(c, polygon) for c in box.footprint_corners())


def _project(corners: tuple[Vec2, ...], axis: Vec2) -> tuple[float, float]:
    vals = [c[0] * axis[0] + c[1] * axis[1] for c in corners]
    return min(vals), max(vals)


def footprints_overlap(a: OrientedBox, b: OrientedBox, gap_m: float = 0.0) -> bool:
    """Separating-axis test between two yaw-oriented floor rectangles.

    Four candidate axes (two per rectangle) are sufficient for rectangles.
    `gap_m` inflates the test, so it also answers "are these closer than
    this?". Collision is the specification's own problem — 0129 watched a
    moved bed pass through a chair and a nightstand and recorded that no
    rendering treatment fixes it.
    """
    ca, cb = a.footprint_corners(), b.footprint_corners()
    for box in (a, b):
        for axis in box.local_axes_xz():
            amin, amax = _project(ca, axis)
            bmin, bmax = _project(cb, axis)
            if amax + gap_m <= bmin or bmax + gap_m <= amin:
                return False
    return True
