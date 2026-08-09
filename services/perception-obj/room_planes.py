"""ARKit plane-anchor interpretation — THE single module that turns a
bundle's measured PlaneAnchor set into room planes (decisions 0066/0069;
the extraction into ONE shared interpretation module is chartered by
decision 0067 and consumed by 0069's closure).

Owns: per-anchor parsing into world frame, floor selection (0066's
lowest-cluster semantics), wall coplanar merge (union-find), and the
plane/ray query helpers consumers build on. Both the shell pipeline
(shell_geometry → closure → shell_receiver) and placement's plane-anchor
contact priors (decision 0067) read anchors through here — do NOT
re-implement anchor interpretation elsewhere.

Nothing here is inferred: every emitted plane is a merge of anchors ARKit
actually detected, and extents are DETECTED extents. Envelope closure
(extending walls to the floor and to each other) lives in shell_geometry,
downstream of this module, and never mutates what this module measured.

Frame conventions (capture_bundle.proto): anchor pose is world_from_anchor;
anchor-local +Y is the plane normal; the plane lies in the anchor's X-Z
plane; center is anchor-space; the extent rectangle is width x height
rotated by rotation_on_y_rad about anchor +Y at the plane center.

Winding/orientation contract (consumed by shell_observation and the
viewer): each plane's corners are wound so cross(c1-c0, c3-c0) points
along the FRONT face — +Y (up) for the floor, the wall's detected normal
for walls. ARKit's vertical-plane normal (anchor +Y) points out of the
wall toward the camera that observed it, i.e. INTO the room, so front
face = interior side and single-sided rendering yields the dollhouse
cutaway. corners[0] is the plane-frame origin; +U runs corner0→corner1,
+V corner0→corner3.

Openings (0069): door/window-classified member anchors are PRESERVED
through the wall merge as `Opening` rects in the merged wall's measured
plane frame (meters from corner0 along axis_u/axis_v) — previously they
survived only as the merged wall's single classification string. A wall's
`classification` is the majority-by-area among its NON-opening members.

Pure numpy + proto in, dataclasses out. No GCS, no PIL, no model imports —
unit-testable against hand-built anchors with known ground truth.

Consumers: shell_geometry.py (assembly + closure), shell_receiver.py,
contact_priors.py (single-view contact priors), tests/test_shell_geometry.py.
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass, field

import numpy as np
from roomstudio_schemas import PlaneAlignment
from roomstudio_schemas.pose_math import pose_position, pose_quat, quat_to_rotmat

_HORIZONTAL = PlaneAlignment.Value("HORIZONTAL")
_VERTICAL = PlaneAlignment.Value("VERTICAL")

# ---------------------------------------------------------------------------
# Tunables (env-overridable; one-capture-calibrated defaults like the
# sampling/budget knobs). NOTE: SHELL_WALL_MERGE_GAP_M and
# SHELL_WALL_NORMAL_TOL_DEG are NOT calibrated here — the values measured
# against f3d70236 (1.0 / 15, decision 0066, commit 634038b) are set as
# deploy env in infra/deploy_perception.sh and are what production runs.
# The defaults below (0.35 / 12) are what an offline run gets unless it
# overrides them, as the real-data pins do explicitly — see
# tests/test_shell_closure_real_data.py and tools/make_shell_v3_fixtures.py.
# ---------------------------------------------------------------------------

# Minimum anchor area to be a floor candidate. Rejects noise specks that
# could hijack the "lowest cluster" rule; the height clustering does the
# real floor-vs-table separation.
SHELL_FLOOR_MIN_AREA_M2 = float(os.environ.get("SHELL_FLOOR_MIN_AREA_M2", "0.5"))

# Height tolerance for "same floor" clustering and coplanar-merge.
SHELL_FLOOR_COPLANAR_TOL_M = float(os.environ.get("SHELL_FLOOR_COPLANAR_TOL_M", "0.08"))

# Walls merge when normals agree within this angle AND plane offsets agree
# within the coplanar tolerance AND their lateral spans touch within the gap.
SHELL_WALL_NORMAL_TOL_DEG = float(os.environ.get("SHELL_WALL_NORMAL_TOL_DEG", "12"))
SHELL_WALL_COPLANAR_TOL_M = float(os.environ.get("SHELL_WALL_COPLANAR_TOL_M", "0.12"))
SHELL_WALL_MERGE_GAP_M = float(os.environ.get("SHELL_WALL_MERGE_GAP_M", "0.35"))

# Minimum vertical-anchor area to ship as a wall (drops speck anchors).
SHELL_MIN_WALL_AREA_M2 = float(os.environ.get("SHELL_MIN_WALL_AREA_M2", "0.3"))

_UP = np.array([0.0, 1.0, 0.0])

# ARKit vertical-plane classifications that are openings in a wall, not
# wall surface. Preserved through the merge as Opening rects.
OPENING_CLASSIFICATIONS = ("door", "window")


# ---------------------------------------------------------------------------
# Output shapes
# ---------------------------------------------------------------------------

@dataclass
class Opening:
    """A door/window member anchor's rect in its merged wall's MEASURED
    plane frame: meters from corners_world[0] along axis_u (u) and axis_v
    (v). Emission converts to the rendered quad's normalized UV."""

    classification: str  # "door" | "window"
    u0: float
    v0: float
    u1: float
    v1: float


@dataclass
class ShellPlaneGeom:
    """One assembled room plane (floor or wall) in world coordinates.

    corners_world is the DETECTED extent — closure (shell_geometry) never
    mutates it; rendered geometry lives on the closure output instead.
    """

    kind: str  # "floor" | "wall"
    # (4, 3) world corners, wound so cross(c1-c0, c3-c0) is the front face.
    corners_world: np.ndarray
    normal: np.ndarray  # (3,) unit front-face normal
    origin: np.ndarray  # (3,) == corners_world[0]; plane-frame (0, 0)
    axis_u: np.ndarray  # (3,) unit; plane +U, corner0 -> corner1
    axis_v: np.ndarray  # (3,) unit; plane +V, corner0 -> corner3
    width_m: float  # extent along axis_u
    height_m: float  # extent along axis_v
    classification: str | None  # majority-by-area non-opening class, or None
    member_indices: list[int] = field(default_factory=list)
    wall_id: str | None = None  # "wall_00"... for walls; None for floor
    openings: list[Opening] = field(default_factory=list)  # walls only
    area_m2: float = 0.0  # sum of member DETECTED areas (not quad area)


# ---------------------------------------------------------------------------
# Per-anchor parsing
# ---------------------------------------------------------------------------

@dataclass
class ParsedAnchor:
    index: int
    alignment: int
    classification: str
    center_world: np.ndarray  # (3,)
    normal_world: np.ndarray  # (3,) unit (anchor +Y in world)
    corners_world: np.ndarray  # (4, 3) extent rectangle
    polygon_world: np.ndarray  # (N, 3): boundary if present, else corners
    area_m2: float


def parse_anchor(index: int, anchor) -> ParsedAnchor:
    """Resolve one PlaneAnchor into world-frame geometry."""
    R = quat_to_rotmat(pose_quat(anchor.pose))
    t = pose_position(anchor.pose)
    center_a = np.array([anchor.center_x, anchor.center_y, anchor.center_z])
    center_w = t + R @ center_a
    normal_w = R @ _UP

    # Extent rectangle axes: anchor X/Z rotated by rotation_on_y about +Y.
    c, s = math.cos(anchor.rotation_on_y_rad), math.sin(anchor.rotation_on_y_rad)
    u_a = np.array([c, 0.0, -s])  # R_y(rot) @ X
    v_a = np.array([s, 0.0, c])  # R_y(rot) @ Z
    u_w, v_w = R @ u_a, R @ v_a
    hw, hh = anchor.extent_width / 2.0, anchor.extent_height / 2.0
    corners = np.stack([
        center_w - hw * u_w - hh * v_w,
        center_w + hw * u_w - hh * v_w,
        center_w + hw * u_w + hh * v_w,
        center_w - hw * u_w + hh * v_w,
    ])

    boundary = np.asarray(anchor.boundary_xz, dtype=np.float64)
    if boundary.size >= 6 and boundary.size % 2 == 0:
        # Anchor-space (x, z) pairs -> world. Boundary vertices are full
        # anchor coordinates (not center-relative), y = 0 in anchor space.
        xz = boundary.reshape(-1, 2)
        pts_a = np.column_stack([xz[:, 0], np.zeros(len(xz)), xz[:, 1]])
        polygon = pts_a @ R.T + t
    else:
        polygon = corners

    return ParsedAnchor(
        index=index,
        alignment=anchor.alignment,
        classification=anchor.classification,
        center_world=center_w,
        normal_world=normal_w,
        corners_world=corners,
        polygon_world=polygon,
        area_m2=float(anchor.extent_width) * float(anchor.extent_height),
    )


def parse_anchors(plane_anchors) -> list[ParsedAnchor]:
    """Parse a bundle's repeated PlaneAnchor field, preserving order."""
    return [parse_anchor(i, a) for i, a in enumerate(plane_anchors)]


# ---------------------------------------------------------------------------
# Plane / ray queries
# ---------------------------------------------------------------------------

def ray_plane_t(
    origin: np.ndarray,
    direction: np.ndarray,
    plane_point: np.ndarray,
    plane_normal: np.ndarray,
) -> float | None:
    """Parameter t where origin + t*direction meets the plane; None when
    the ray is parallel (within 1e-9) or the hit is behind the origin."""
    denom = float(np.dot(direction, plane_normal))
    if abs(denom) < 1e-9:
        return None
    t = float(np.dot(plane_point - origin, plane_normal)) / denom
    return t if t >= 0.0 else None


def vertical_seam_xz(
    normal_a: np.ndarray,
    point_a: np.ndarray,
    normal_b: np.ndarray,
    point_b: np.ndarray,
    *,
    min_angle_deg: float = 30.0,
) -> np.ndarray | None:
    """XZ point of the vertical seam line where two wall planes intersect,
    or None when the planes are near-parallel (seam ill-conditioned below
    min_angle_deg). Inputs are world-frame plane normals (horizontal
    components used) and any points on each plane."""
    cross_y = float(normal_a[0] * normal_b[2] - normal_a[2] * normal_b[0])
    if abs(cross_y) < math.sin(math.radians(min_angle_deg)):
        return None
    A = np.array([[normal_a[0], normal_a[2]], [normal_b[0], normal_b[2]]])
    rhs = np.array([
        float(normal_a[0] * point_a[0] + normal_a[2] * point_a[2]),
        float(normal_b[0] * point_b[0] + normal_b[2] * point_b[2]),
    ])
    xz = np.linalg.solve(A, rhs)
    return np.array([xz[0], 0.0, xz[1]])


def wall_frame(n: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(normal, lateral) for a wall: normal forced plumb-horizontal (the
    session is gravity-aligned, walls are vertical), lateral = up x n so
    cross(lateral, up) == n — the winding the front-face contract needs."""
    n_h = np.array([n[0], 0.0, n[2]])
    norm = np.linalg.norm(n_h)
    if norm < 1e-6:
        raise ValueError("wall normal has no horizontal component")
    n_h /= norm
    lateral = np.cross(_UP, n_h)
    lateral /= np.linalg.norm(lateral)
    return n_h, lateral


# ---------------------------------------------------------------------------
# Floor selection
# ---------------------------------------------------------------------------

def select_floor(parsed: list[ParsedAnchor]) -> tuple[ShellPlaneGeom | None, list[np.ndarray]]:
    """Lowest cluster of large upward-facing horizontal anchors, coplanar-
    merged. Returns (floor geom, member world polygons) or (None, [])."""
    candidates = [
        a for a in parsed
        if a.alignment == _HORIZONTAL
        and a.area_m2 >= SHELL_FLOOR_MIN_AREA_M2
        and a.normal_world[1] > 0.7  # upward — excludes ceiling anchors
        and a.classification != "ceiling"
    ]
    if not candidates:
        return None, []

    lowest_y = min(a.center_world[1] for a in candidates)
    members = [
        a for a in candidates
        if a.center_world[1] <= lowest_y + SHELL_FLOOR_COPLANAR_TOL_M
    ]

    total_area = sum(a.area_m2 for a in members)
    y_floor = sum(a.center_world[1] * a.area_m2 for a in members) / total_area

    # Flatten member polygons onto the merged floor height; the union of
    # these is the floor's shape and their XZ bbox is the quad.
    polygons = []
    for a in members:
        poly = a.polygon_world.copy()
        poly[:, 1] = y_floor
        polygons.append(poly)
    all_pts = np.vstack(polygons)
    min_x, max_x = float(all_pts[:, 0].min()), float(all_pts[:, 0].max())
    min_z, max_z = float(all_pts[:, 2].min()), float(all_pts[:, 2].max())

    # Plane frame with cross(axis_u, axis_v) == +Y: u = +X, v = -Z, origin
    # at (min_x, y, max_z).
    origin = np.array([min_x, y_floor, max_z])
    axis_u = np.array([1.0, 0.0, 0.0])
    axis_v = np.array([0.0, 0.0, -1.0])
    width, height = max_x - min_x, max_z - min_z
    corners = np.stack([
        origin,
        origin + width * axis_u,
        origin + width * axis_u + height * axis_v,
        origin + height * axis_v,
    ])

    geom = ShellPlaneGeom(
        kind="floor",
        corners_world=corners,
        normal=_UP.copy(),
        origin=origin,
        axis_u=axis_u,
        axis_v=axis_v,
        width_m=width,
        height_m=height,
        classification=_majority_classification(members),
        member_indices=[a.index for a in members],
        area_m2=total_area,
    )
    return geom, polygons


def _majority_classification(members: list[ParsedAnchor]) -> str | None:
    """Largest-area non-empty classification among members, else None."""
    best: str | None = None
    best_area = 0.0
    for a in members:
        if a.classification and a.area_m2 > best_area:
            best, best_area = a.classification, a.area_m2
    return best


# ---------------------------------------------------------------------------
# Wall merging
# ---------------------------------------------------------------------------

def _mergeable(a: ParsedAnchor, b: ParsedAnchor) -> bool:
    """Same wall? Normals agree, plane offsets agree, lateral spans touch."""
    cos_tol = math.cos(math.radians(SHELL_WALL_NORMAL_TOL_DEG))
    if float(np.dot(a.normal_world, b.normal_world)) < cos_tol:
        return False
    n = a.normal_world
    if abs(float(np.dot(n, a.center_world - b.center_world))) > SHELL_WALL_COPLANAR_TOL_M:
        return False
    # Lateral spans along the shared wall direction.
    _, lateral = wall_frame(n)
    sa = [float(np.dot(lateral, p)) for p in a.corners_world]
    sb = [float(np.dot(lateral, p)) for p in b.corners_world]
    gap = max(min(sa), min(sb)) - min(max(sa), max(sb))
    return gap <= SHELL_WALL_MERGE_GAP_M


def _merge_wall_group(members: list[ParsedAnchor]) -> ShellPlaneGeom:
    """One wall from coplanar-overlapping vertical anchors. Height is the
    DETECTED vertical extent of the members — never extrapolated. Door/
    window members become Opening rects; classification is the majority
    of the remaining (non-opening) members."""
    total_area = sum(a.area_m2 for a in members)
    # Area-weighted normal, members flipped into the first's hemisphere.
    ref = members[0].normal_world
    n_sum = np.zeros(3)
    for a in members:
        n = a.normal_world if float(np.dot(a.normal_world, ref)) >= 0 else -a.normal_world
        n_sum += a.area_m2 * n
    normal, lateral = wall_frame(n_sum / total_area)

    anchor_point = sum(
        (a.area_m2 * a.center_world for a in members), np.zeros(3)
    ) / total_area

    pts = np.vstack([a.corners_world for a in members])
    s = (pts - anchor_point) @ lateral
    lat_min, lat_max = float(s.min()), float(s.max())
    y_min, y_max = float(pts[:, 1].min()), float(pts[:, 1].max())

    def _pt(lat: float, y: float) -> np.ndarray:
        p = anchor_point + lat * lateral
        return np.array([p[0], y, p[2]])

    # cross(lateral, up) == normal, so this order fronts the interior.
    corners = np.stack([
        _pt(lat_min, y_min),
        _pt(lat_max, y_min),
        _pt(lat_max, y_max),
        _pt(lat_min, y_max),
    ])

    # Openings: door/window members' rects in the measured plane frame
    # (meters from corner0). Inside the extent union by construction.
    openings: list[Opening] = []
    for a in members:
        if a.classification not in OPENING_CLASSIFICATIONS:
            continue
        sa = (a.corners_world - anchor_point) @ lateral
        openings.append(Opening(
            classification=a.classification,
            u0=float(sa.min()) - lat_min,
            v0=float(a.corners_world[:, 1].min()) - y_min,
            u1=float(sa.max()) - lat_min,
            v1=float(a.corners_world[:, 1].max()) - y_min,
        ))
    surface_members = [
        a for a in members if a.classification not in OPENING_CLASSIFICATIONS
    ]

    return ShellPlaneGeom(
        kind="wall",
        corners_world=corners,
        normal=normal,
        origin=corners[0],
        axis_u=lateral,
        axis_v=_UP.copy(),
        width_m=lat_max - lat_min,
        height_m=y_max - y_min,
        classification=_majority_classification(surface_members),
        member_indices=[a.index for a in members],
        openings=openings,
        area_m2=total_area,
    )


def merge_walls(parsed: list[ParsedAnchor]) -> list[ShellPlaneGeom]:
    verticals = [
        a for a in parsed
        if a.alignment == _VERTICAL and a.area_m2 >= SHELL_MIN_WALL_AREA_M2
    ]
    if not verticals:
        return []

    # Union-find over mergeable pairs; deterministic (input order).
    parent = list(range(len(verticals)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(verticals)):
        for j in range(i + 1, len(verticals)):
            if _mergeable(verticals[i], verticals[j]):
                parent[find(j)] = find(i)

    groups: dict[int, list[ParsedAnchor]] = {}
    for i, a in enumerate(verticals):
        groups.setdefault(find(i), []).append(a)

    walls = [_merge_wall_group(members) for _, members in sorted(groups.items())]
    # Deterministic wall ids: sort by (normal heading, plane offset).
    walls.sort(
        key=lambda w: (
            round(math.atan2(w.normal[2], w.normal[0]), 4),
            round(float(np.dot(w.normal, w.origin)), 3),
        )
    )
    for i, w in enumerate(walls):
        w.wall_id = f"wall_{i:02d}"
    return walls
