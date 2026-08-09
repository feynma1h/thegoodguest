"""CapturedRoom JSON interpretation — THE single module that turns a
bundle's RoomPlan `room.json` (Apple's Codable JSONEncoder output, shipped
verbatim per decision 0077) into typed room geometry, plus adapters onto the
`room_planes` dataclass surface so placement's contact priors (decision
0067) and the room-sanity gate consume RoomPlan planes exactly as they
consume ARKit anchor planes.

Owns: Codable-document parsing (column-major 16-float transforms, single-key
category/confidence dicts, local polygon corners with the rect-from-
dimensions fallback, door/window/opening parenting via parentIdentifier),
and the ShellPlaneGeom adaptation (interior-oriented wall rects + floor
rect). Do NOT parse room.json anywhere else.

Wire facts this parser is built on (measured on the spike probe run,
probe-20260728-143602 — the 0077 design session's parser probe):

  * Every surface (wall/floor/door/window/opening) shares ONE local frame
    convention: the polygon lies in local X-Y with local +Z the surface
    normal (walls: X lateral, Y up; floor: +Z is world up). `transform` is
    world_from_local as 16 floats, COLUMN-MAJOR.
  * `polygonCorners` is usually EMPTY — 12 of the 13 probe walls and every
    door/window/opening serialize no polygon; geometry then comes from
    `dimensions` as a centered rectangle (the rect-from-dimensions
    fallback). Only surfaces
    with non-rectangular outlines (the probe's wall_00, 6 corners) carry
    explicit polygons.
  * RoomPlan does NOT orient wall normals consistently: 11 of the probe's
    13 walls have local +Z toward the room interior, 2 point away. The
    wall adapter re-orients every normal toward the interior reference
    (the floor centroid) so the front-face winding contract room_planes
    documents (interior side, dollhouse cutaway) holds for every wall.
  * `category` and `confidence` are single-key dicts ({"wall": {}},
    {"high": {}}); objects carry `attributes` (verbatim dict) and pure-yaw
    transforms (probe: worst |up_y - 1| = 1e-7 across all 9 boxes).
  * `coreModel` is an opaque Apple blob (~178 KB base64) — carried on the
    wire, NEVER read here. `version` (2 today) is the drift pin: an
    unsupported value fails the parse rather than risking a misparse.

Degrade contract (decision 0077): a missing or corrupt room.json NEVER
fails the scene — parse failures raise the typed RoomPlanParseError (or
return a reason from try_parse_captured_room), and callers degrade to
LIDAR_ARKIT semantics with a structured log + manifest note.

Pure json + numpy + room_planes dataclasses; no GCS, no proto, no model
imports — unit-testable against the committed spike fixture. Deterministic:
array order is preserved everywhere, no RNG.

Consumers: shell_receiver.py (shell.json v3 walls/floor as polygons),
process_receiver.py (try_parse_captured_room), fusion.py (box association +
wall geoms). box_placement.py and census_sampling.py consume the
RoomPlanBox dataclasses produced here rather than importing this module,
and contact_priors / fusion's room-sanity gate consume the ShellPlaneGeom
adapters unchanged.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

import numpy as np
from room_planes import Opening, ShellPlaneGeom, wall_frame

_UP = np.array([0.0, 1.0, 0.0])

# CapturedRoom Codable `version` values this parser understands. An Apple
# schema change bumps the version; refusing unknown values turns silent
# misparses into the explicit degrade path (decision 0077).
SUPPORTED_CAPTURED_ROOM_VERSIONS = frozenset({2})


class RoomPlanParseError(Exception):
    """room.json cannot be interpreted. Callers degrade the scene to
    LIDAR_ARKIT semantics (structured log + manifest note) — NEVER
    failed_invalid: the frames + depth are still a good capture."""


# ---------------------------------------------------------------------------
# Parsed shapes
# ---------------------------------------------------------------------------

@dataclass
class RoomPlanSurface:
    """One CapturedRoom surface (wall / floor / door / window / opening)."""

    identifier: str
    kind: str  # "wall" | "floor" | "door" | "window" | "opening"
    category: str  # single key of the category dict, e.g. "wall"
    confidence: str  # "high" | "medium" | "low"
    dimensions: np.ndarray  # (3,) — [width, height, 0] in the local frame
    transform: np.ndarray  # (4, 4) world_from_local
    polygon_local: np.ndarray  # (N, 3) local X-Y plane corners
    polygon_world: np.ndarray  # (N, 3)
    polygon_from_dimensions: bool  # True when polygonCorners was empty
    normal_world: np.ndarray  # (3,) local +Z in world — RAW, unoriented
    parent_identifier: str | None


@dataclass
class RoomPlanBox:
    """One CapturedRoom object box (the placement skeleton, decision 0077)."""

    identifier: str
    category: str
    confidence: str
    attributes: dict
    dimensions: np.ndarray  # (3,) LOCAL dims — the long axis may be X or Z
    transform: np.ndarray  # (4, 4) world_from_local
    center_world: np.ndarray  # (3,)
    up_y: float  # world-Y component of local +Y; pure-yaw boxes → +1.0
    yaw_rad: float  # heading of local +X in world XZ: atan2(x.z, x.x)
    # (the parser probe's convention — NOT the signed rotation about +Y,
    # which is its negation; box_placement's axis-mapping enumeration works
    # from the full transform, this field is provenance + regression pins)


@dataclass
class RoomPlanRoom:
    """A parsed CapturedRoom document. Lists preserve Apple's array order."""

    version: int
    walls: list[RoomPlanSurface] = field(default_factory=list)
    floors: list[RoomPlanSurface] = field(default_factory=list)
    doors: list[RoomPlanSurface] = field(default_factory=list)
    windows: list[RoomPlanSurface] = field(default_factory=list)
    openings: list[RoomPlanSurface] = field(default_factory=list)
    objects: list[RoomPlanBox] = field(default_factory=list)

    @property
    def has_geometry(self) -> bool:
        """The 0077 tier condition: a built room with >= 1 wall or floor."""
        return bool(self.walls) or bool(self.floors)

    def wall_index_by_identifier(self) -> dict[str, int]:
        return {w.identifier: i for i, w in enumerate(self.walls)}


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def _single_key(d, what: str, ident: str) -> str:
    if not isinstance(d, dict) or len(d) != 1:
        raise RoomPlanParseError(
            f"{what} of {ident} is not a single-key dict: {d!r}"
        )
    return next(iter(d))


def _transform_4x4(vals, ident: str) -> np.ndarray:
    arr = np.asarray(vals, dtype=np.float64)
    if arr.shape != (16,):
        raise RoomPlanParseError(
            f"transform of {ident} is not 16 floats (got shape {arr.shape})"
        )
    # Column-major: simd_float4x4 serializes column by column.
    return arr.reshape(4, 4, order="F")


def _polygon_local(entity: dict, dims: np.ndarray, ident: str) -> tuple[np.ndarray, bool]:
    """(corners (N,3) in the local X-Y plane, from_dimensions). Empty
    polygonCorners → the centered rectangle from dimensions — the dominant
    real case (12/13 probe walls, every probe door/window/opening)."""
    pc = entity.get("polygonCorners") or []
    if pc:
        corners = np.asarray(pc, dtype=np.float64)
        if corners.ndim != 2 or corners.shape[1] != 3 or corners.shape[0] < 3:
            raise RoomPlanParseError(
                f"polygonCorners of {ident} malformed: shape {corners.shape}"
            )
        return corners, False
    hw, hh = float(dims[0]) / 2.0, float(dims[1]) / 2.0
    return (
        np.array([[-hw, -hh, 0.0], [hw, -hh, 0.0], [hw, hh, 0.0], [-hw, hh, 0.0]]),
        True,
    )


def _parse_surface(entity: dict, kind: str) -> RoomPlanSurface:
    ident = str(entity.get("identifier", "?"))
    dims = np.asarray(entity["dimensions"], dtype=np.float64)
    if dims.shape != (3,):
        raise RoomPlanParseError(f"dimensions of {ident} malformed: {dims!r}")
    T = _transform_4x4(entity["transform"], ident)
    R, o = T[:3, :3], T[:3, 3]
    poly_local, from_dims = _polygon_local(entity, dims, ident)
    return RoomPlanSurface(
        identifier=ident,
        kind=kind,
        category=_single_key(entity["category"], "category", ident),
        confidence=_single_key(entity["confidence"], "confidence", ident),
        dimensions=dims,
        transform=T,
        polygon_local=poly_local,
        polygon_world=poly_local @ R.T + o,
        polygon_from_dimensions=from_dims,
        normal_world=R[:, 2].copy(),
        parent_identifier=entity.get("parentIdentifier") or None,
    )


def _parse_box(entity: dict) -> RoomPlanBox:
    ident = str(entity.get("identifier", "?"))
    dims = np.asarray(entity["dimensions"], dtype=np.float64)
    if dims.shape != (3,):
        raise RoomPlanParseError(f"dimensions of object {ident} malformed: {dims!r}")
    T = _transform_4x4(entity["transform"], ident)
    R = T[:3, :3]
    attrs = entity.get("attributes") or {}
    if not isinstance(attrs, dict):
        raise RoomPlanParseError(f"attributes of object {ident} not a dict: {attrs!r}")
    return RoomPlanBox(
        identifier=ident,
        category=_single_key(entity["category"], "category", ident),
        confidence=_single_key(entity["confidence"], "confidence", ident),
        attributes=attrs,
        dimensions=dims,
        transform=T,
        center_world=T[:3, 3].copy(),
        up_y=float(R[1, 1]),
        yaw_rad=float(np.arctan2(R[2, 0], R[0, 0])),
    )


def parse_captured_room(raw: bytes | str) -> RoomPlanRoom:
    """Parse a CapturedRoom Codable JSON document.

    Raises RoomPlanParseError — and ONLY RoomPlanParseError — on any
    structural surprise (bad JSON, unsupported version, malformed entity),
    so callers can catch narrowly and run the degrade path. `coreModel` is
    never read.
    """
    try:
        doc = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise RoomPlanParseError(f"room.json is not valid JSON: {e}") from e
    if not isinstance(doc, dict):
        raise RoomPlanParseError(
            f"room.json top level is {type(doc).__name__}, expected object"
        )

    version = doc.get("version")
    if version not in SUPPORTED_CAPTURED_ROOM_VERSIONS:
        raise RoomPlanParseError(
            f"unsupported CapturedRoom version {version!r}; supported: "
            f"{sorted(SUPPORTED_CAPTURED_ROOM_VERSIONS)} — Apple Codable "
            "schema drift; re-verify the parser against the new format"
        )

    try:
        room = RoomPlanRoom(version=version)
        for kind, target in (
            ("walls", room.walls),
            ("floors", room.floors),
            ("doors", room.doors),
            ("windows", room.windows),
            ("openings", room.openings),
        ):
            entities = doc.get(kind)
            if entities is None:
                raise RoomPlanParseError(f"room.json has no {kind!r} list")
            for e in entities:
                target.append(_parse_surface(e, kind.rstrip("s")))
        objects = doc.get("objects")
        if objects is None:
            raise RoomPlanParseError("room.json has no 'objects' list")
        for e in objects:
            room.objects.append(_parse_box(e))
    except RoomPlanParseError:
        raise
    except (KeyError, ValueError, TypeError, IndexError) as e:
        raise RoomPlanParseError(f"room.json entity malformed: {e!r}") from e
    return room


def try_parse_captured_room(raw: bytes | str) -> tuple[RoomPlanRoom | None, str | None]:
    """(room, None) on success; (None, reason) on any parse failure. Never
    raises — the seam /process and /shell call so a corrupt room.json is a
    logged degrade (`roomplan_parse_failed`), not an exception path."""
    try:
        return parse_captured_room(raw), None
    except RoomPlanParseError as e:
        return None, str(e)


# ---------------------------------------------------------------------------
# room_planes adaptation (contact priors + sanity gate consume these UNCHANGED)
# ---------------------------------------------------------------------------

def _polygon_area(poly_local: np.ndarray) -> float:
    """Shoelace area over the local X-Y polygon."""
    x, y = poly_local[:, 0], poly_local[:, 1]
    return 0.5 * abs(float(np.dot(x, np.roll(y, -1)) - np.dot(np.roll(x, -1), y)))


def interior_reference(room: RoomPlanRoom) -> np.ndarray | None:
    """A world point inside the room, for orienting wall normals: the floor
    polygon centroid when a floor exists, else the mean of wall polygon
    centroids (a convex-ish room's walls surround their own centroid).
    None when the room has no surfaces at all."""
    if room.floors:
        fl = max(room.floors, key=lambda f: _polygon_area(f.polygon_local))
        return fl.polygon_world.mean(axis=0)
    if room.walls:
        return np.mean([w.polygon_world.mean(axis=0) for w in room.walls], axis=0)
    return None


def roomplan_floor_geom(room: RoomPlanRoom) -> ShellPlaneGeom | None:
    """The floor as a ShellPlaneGeom rect — the XZ bounding box of the floor
    polygon at the measured floor height, in select_floor's exact frame
    convention (origin (min_x, y, max_z), axis_u +X, axis_v -Z, so
    cross(axis_u, axis_v) == +Y). The full polygon stays on the
    RoomPlanSurface for the shell build; this rect is the query surface the
    sanity gate and floor-contact prior read (floor bounds + floor_y)."""
    if not room.floors:
        return None
    # Largest floor by polygon area; ties by array order (RoomPlan emits one
    # floor for single-story scans — this is deterministic robustness).
    fl = max(room.floors, key=lambda f: _polygon_area(f.polygon_local))
    poly = fl.polygon_world
    y = float(poly[:, 1].mean())
    min_x, max_x = float(poly[:, 0].min()), float(poly[:, 0].max())
    min_z, max_z = float(poly[:, 2].min()), float(poly[:, 2].max())
    origin = np.array([min_x, y, max_z])
    axis_u = np.array([1.0, 0.0, 0.0])
    axis_v = np.array([0.0, 0.0, -1.0])
    width, height = max_x - min_x, max_z - min_z
    corners = np.stack([
        origin,
        origin + width * axis_u,
        origin + width * axis_u + height * axis_v,
        origin + height * axis_v,
    ])
    return ShellPlaneGeom(
        kind="floor",
        corners_world=corners,
        normal=_UP.copy(),
        origin=origin,
        axis_u=axis_u,
        axis_v=axis_v,
        width_m=width,
        height_m=height,
        classification="floor",
        member_indices=[],  # RoomPlan-sourced: no anchor members
        area_m2=_polygon_area(fl.polygon_local),
    )


def _opening_rect(surface: RoomPlanSurface, wall_origin: np.ndarray,
                  lateral: np.ndarray) -> Opening:
    """A door/window/opening's rect in its parent wall's measured plane
    frame (meters from corner0 along axis_u / axis_v) — room_planes.Opening
    semantics. Projects the surface's own world corners (probe measurement:
    coplanar with the parent wall to 0.0 m), so any in-plane offset or
    rotation is captured exactly."""
    rel = surface.polygon_world - wall_origin
    u = rel @ lateral
    v = surface.polygon_world[:, 1] - wall_origin[1]  # axis_v == world up
    return Opening(
        classification=surface.kind,
        u0=float(u.min()),
        v0=float(v.min()),
        u1=float(u.max()),
        v1=float(v.max()),
    )


def roomplan_primary_floor(room: RoomPlanRoom) -> RoomPlanSurface | None:
    """The floor surface the shell renders: largest by polygon area, ties by
    array order — the SAME selection roomplan_floor_geom uses, exposed so
    doc assembly (shell v3) and the query-surface adapter can never pick
    different floors."""
    if not room.floors:
        return None
    return max(room.floors, key=lambda f: _polygon_area(f.polygon_local))


def roomplan_wall_pairs(
    room: RoomPlanRoom,
) -> list[tuple[RoomPlanSurface, ShellPlaneGeom]]:
    """(surface, geom) pairs for every non-degenerate wall, in geom order.
    The pairing key is the geom's wall_id index (roomplan_wall_geoms stamps
    wall_id from the room.walls array index, so a skipped degenerate wall
    never misaligns the zip). Shell v3 needs both halves: the surface for
    the verbatim polygon + confidence, the geom for the oriented frame and
    openings."""
    geoms = roomplan_wall_geoms(room)
    return [(room.walls[int(g.wall_id.rsplit("_", 1)[-1])], g) for g in geoms]


def roomplan_wall_geoms(room: RoomPlanRoom) -> list[ShellPlaneGeom]:
    """Every CapturedRoom wall as a ShellPlaneGeom rect, in Apple's array
    order (wall_id = "wall_{index:02d}" — stable against the JSON, no
    re-sorting). The normal is re-oriented toward the room interior when
    RoomPlan's local +Z points away (2 of the probe's 13 — RoomPlan makes
    no interior guarantee), so the room_planes front-face winding contract
    (interior side; cross(c1-c0, c3-c0) along the normal) holds for every
    wall, and _wall_hit / the dollhouse cutaway work unchanged. Parented
    doors/windows/openings attach as Opening rects in the measured plane
    frame. A wall whose normal has no horizontal component (degenerate,
    never seen in real output) is skipped deterministically."""
    ref = interior_reference(room)
    openings_by_wall: dict[str, list[RoomPlanSurface]] = {}
    for s in (*room.doors, *room.windows, *room.openings):
        if s.parent_identifier:
            openings_by_wall.setdefault(s.parent_identifier, []).append(s)

    geoms: list[ShellPlaneGeom] = []
    for i, w in enumerate(room.walls):
        try:
            n_h, lateral = wall_frame(w.normal_world)
        except ValueError:
            continue  # degenerate normal — skip, never guess
        anchor = w.polygon_world.mean(axis=0)
        if ref is not None and float(np.dot(n_h, ref - anchor)) < 0.0:
            n_h = -n_h
            lateral = np.cross(_UP, n_h)
            lateral /= np.linalg.norm(lateral)

        s = (w.polygon_world - anchor) @ lateral
        lat_min, lat_max = float(s.min()), float(s.max())
        y_min, y_max = float(w.polygon_world[:, 1].min()), float(w.polygon_world[:, 1].max())

        p_min, p_max = anchor + lat_min * lateral, anchor + lat_max * lateral
        # cross(lateral, up) == normal → this order fronts the interior.
        corners = np.stack([
            [p_min[0], y_min, p_min[2]],
            [p_max[0], y_min, p_max[2]],
            [p_max[0], y_max, p_max[2]],
            [p_min[0], y_max, p_min[2]],
        ])
        geom = ShellPlaneGeom(
            kind="wall",
            corners_world=corners,
            normal=n_h,
            origin=corners[0],
            axis_u=lateral,
            axis_v=_UP.copy(),
            width_m=lat_max - lat_min,
            height_m=y_max - y_min,
            classification=w.category,
            member_indices=[],  # RoomPlan-sourced: no anchor members
            wall_id=f"wall_{i:02d}",
            openings=[
                _opening_rect(s, corners[0], lateral)
                for s in openings_by_wall.get(w.identifier, [])
            ],
            area_m2=_polygon_area(w.polygon_local),
        )
        geoms.append(geom)
    return geoms
