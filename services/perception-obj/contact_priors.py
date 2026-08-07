"""Measured-plane contact priors for single-view object placement
(decision 0067 chunk D).

A single ARKIT_ONLY view of an object gives one camera ray and no baseline,
so most single-frame objects can't triangulate a position and ship
`insufficient_observations`. On the real capture f3d70236, 15 of 18 fused
objects are exactly this. This module recovers a position for them from the
ONE thing a single view still measures against a KNOWN surface: where the
object touches the measured room.

  * A floor-standing object (chair, bed, table…) rests ON the detected
    floor — its bottom at the floor height closes the depth ambiguity.
  * A wall-mounted object (door, artwork, mirror…) hangs ON a detected
    wall — the ray's intersection with that wall fixes its depth, and the
    wall's measured normal orients it.

The geometry of each closure is pure math in
roomstudio_schemas.placement_math (solve_floor_contact / solve_wall_contact,
unit-tested against synthetic ground truth). This module holds the POLICY
around it: which object classes are trusted to touch which surface (a
conservative, env-overridable class map — ambiguous classes like `table
lamp`, `speaker`, `plant` map to NONE and stay unplaced), how the measured
planes are read (through room_planes — THE single anchor-interpretation
module, shared with the shell build; anchor interpretation is never
duplicated here), and which wall a wall object hangs on.

The evidence rule (decision 0067) is enforced by the CALLER (fusion.py): a
prior only proposes a candidate transform here; fusion scores it against
the object's own SAM mask (tier 1) and drops it if it doesn't reproject —
so "a guessed transform is never emitted" survives priors. No planes in the
bundle → every prior is inert and the caller's single-view objects stay
`insufficient_observations`, unchanged (the degrade lock).

Determinism: pure numpy, fixed evaluation order, no RNG — identical inputs
produce identical candidates.

Consumers: fusion.py (single-view placement in the refined fusion pass),
process_receiver.py (extract_room_planes when building the refinement ctx).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

import numpy as np
import room_planes as rp
from roomstudio_schemas.placement_math import (
    DegenerateGeometryError,
    solve_floor_contact,
    solve_wall_contact,
)
from roomstudio_schemas.pose_math import quat_to_rotmat, rotmat_to_quat

# ---------------------------------------------------------------------------
# Class -> prior map (decision 0067 lock 5). Conservative buckets over the
# fixed SAM 3 prompt vocabulary; anything unmapped stays NONE (unplaced on a
# single view). Env-overridable (comma lists) so a prompt-vocabulary change
# doesn't need a code edit — policy, not measurement.
# ---------------------------------------------------------------------------

def _class_set(env_name: str, default: str) -> frozenset:
    return frozenset(
        s.strip().lower() for s in os.environ.get(env_name, default).split(",") if s.strip()
    )


_FLOOR_CLASSES = _class_set(
    "PLACEMENT_FLOOR_CLASSES",
    "bed,sofa,chair,table,desk,nightstand,cabinet,dresser,bookshelf,rug,couch,stool,bench",
)
_WALL_CLASSES = _class_set(
    "PLACEMENT_WALL_CLASSES",
    "door,window,curtain,artwork,painting,mirror,poster,frame,clock",
)

# How far outside a wall's measured rectangle the ray hit may land and still
# count as "on that wall" (walls are detected extents, not full surfaces).
_WALL_HIT_MARGIN_M = float(os.environ.get("PLACEMENT_WALL_HIT_MARGIN_M", "0.4"))
# How far a floor object's mask-centroid ray may miss the detected floor
# rectangle in XZ and still be accepted (the floor is a measured extent too).
_FLOOR_HIT_MARGIN_M = float(os.environ.get("PLACEMENT_FLOOR_HIT_MARGIN_M", "0.5"))


def prior_class(label: str | None) -> str | None:
    """"floor" | "wall" | None for an object label. None = no measured-
    surface prior applies; the object stays unplaced on a single view."""
    if not label:
        return None
    key = label.strip().lower()
    if key in _FLOOR_CLASSES:
        return "floor"
    if key in _WALL_CLASSES:
        return "wall"
    return None


# ---------------------------------------------------------------------------
# Room planes (read once per scene through room_planes; shared with shell).
# ---------------------------------------------------------------------------

@dataclass
class RoomPlanes:
    """The measured room geometry a placement pass needs: the floor plane
    (or None) and the merged wall set. Built from a bundle's plane_anchors
    via room_planes — the SAME interpretation the shell renders."""

    floor: rp.ShellPlaneGeom | None
    walls: list = field(default_factory=list)

    @property
    def has_geometry(self) -> bool:
        return self.floor is not None or bool(self.walls)

    @property
    def floor_y(self) -> float | None:
        if self.floor is None:
            return None
        return float(self.floor.corners_world[0][1])


def extract_room_planes(plane_anchors) -> RoomPlanes:
    """Parse a bundle's repeated PlaneAnchor field into floor + walls. Empty
    (no anchors) yields an empty RoomPlanes — every prior then inert."""
    parsed = rp.parse_anchors(plane_anchors)
    if not parsed:
        return RoomPlanes(floor=None, walls=[])
    floor, _polys = rp.select_floor(parsed)
    walls = rp.merge_walls(parsed)
    return RoomPlanes(floor=floor, walls=walls)


# ---------------------------------------------------------------------------
# Wall selection
# ---------------------------------------------------------------------------

def _wall_hit(wall, o: np.ndarray, d: np.ndarray, margin: float):
    """(t_hit, uv_inside) for a ray meeting a wall's FRONT face inside its
    detected rectangle (padded by margin), or None. Front face = the ray
    travels into the wall (dot(d, normal) < 0), so we never place an object
    on a wall the camera was behind."""
    n = wall.normal
    denom = float(np.dot(d, n))
    if denom >= -1e-6:  # parallel, or hitting the back face
        return None
    t = float(np.dot(wall.origin - o, n)) / denom
    if t <= 1e-6:
        return None
    hit = o + t * d
    rel = hit - wall.origin
    u = float(np.dot(rel, wall.axis_u))
    v = float(np.dot(rel, wall.axis_v))
    if -margin <= u <= wall.width_m + margin and -margin <= v <= wall.height_m + margin:
        return t
    return None


def _nearest_wall(walls, o: np.ndarray, d: np.ndarray, margin: float):
    """The wall whose front face the ray meets nearest, inside its detected
    extent. None if the ray hits no detected wall."""
    best = None
    best_t = None
    for wall in walls:
        t = _wall_hit(wall, o, d, margin)
        if t is not None and (best_t is None or t < best_t):
            best, best_t = wall, t
    return best


# ---------------------------------------------------------------------------
# Candidate transform from a measured-surface prior (geometry only; the
# caller applies the pixel-evidence gate)
# ---------------------------------------------------------------------------

def solve_placement(
    prior: str,
    splat_local: np.ndarray,
    world_rotation_xyzw,
    view_ray: dict,
    planes: RoomPlanes,
) -> dict | None:
    """Propose a world transform for a single-view object from its measured-
    surface prior. Returns a dict {position, rotation_xyzw, scale, method,
    position_source, constraints_applied} or None when the prior can't apply
    (no matching surface, or a degenerate solve). Never raises.

    prior: "floor" | "wall" (from prior_class).
    splat_local: (N, 3) local splat vertices (already loaded by the caller).
    world_rotation_xyzw: the object's layout-derived world rotation (fixed;
        floor keeps it, wall may refine it toward the measured wall normal).
    view_ray: the observation's {origin, direction, angular_extent_rad}.
    planes: the measured room.
    """
    o = np.asarray(view_ray["origin"], dtype=np.float64)
    d = np.asarray(view_ray["direction"], dtype=np.float64)
    ang = float(view_ray.get("angular_extent_rad", 0.0))
    if ang <= 0.0 or np.linalg.norm(d) < 1e-9:
        return None
    R_world = quat_to_rotmat(tuple(world_rotation_xyzw))

    if prior == "floor":
        floor_y = planes.floor_y
        if floor_y is None:
            return None
        try:
            s, t = solve_floor_contact(splat_local, R_world, o, d, ang, floor_y)
        except (DegenerateGeometryError, ValueError):
            return None
        if not _floor_hit_in_bounds(planes.floor, o, d, floor_y):
            return None
        return {
            "position": [float(c) for c in t],
            "rotation_xyzw": [float(c) for c in world_rotation_xyzw],
            "scale": float(s),
            "method": "single_view_floor_contact",
            "position_source": "single_view_floor_contact",
            "constraints_applied": ["floor_contact"],
        }

    if prior == "wall":
        wall = _nearest_wall(planes.walls, o, d / np.linalg.norm(d), _WALL_HIT_MARGIN_M)
        if wall is None:
            return None
        try:
            s, t, R_aligned, aligned = solve_wall_contact(
                splat_local, R_world, o, d, ang, wall.origin, wall.normal
            )
        except (DegenerateGeometryError, ValueError):
            return None
        constraints = ["wall_contact"]
        if aligned:
            constraints.append("wall_normal")
        return {
            "position": [float(c) for c in t],
            "rotation_xyzw": [float(c) for c in rotmat_to_quat(R_aligned)],
            "scale": float(s),
            "method": "single_view_wall_contact",
            "position_source": "single_view_wall_contact",
            "constraints_applied": constraints,
        }

    return None


def _floor_hit_in_bounds(floor, o: np.ndarray, d: np.ndarray, floor_y: float) -> bool:
    """The mask-centroid ray must actually cross the detected floor
    rectangle (padded) — an object whose ray leaves the room through a wall
    gap isn't standing on THIS floor. A parallel/upward ray fails the depth
    solve upstream, so here we only reject in-plane misses."""
    dn = np.linalg.norm(d)
    if dn < 1e-9:
        return False
    d = d / dn
    if abs(d[1]) < 1e-9:
        return True  # can't test XZ crossing; the depth solve already gated
    t = (floor_y - float(o[1])) / d[1]
    if t <= 0.0:
        return True  # gated upstream
    hit = o + t * d
    rel = hit - floor.origin
    u = float(np.dot(rel, floor.axis_u))
    v = float(np.dot(rel, floor.axis_v))
    m = _FLOOR_HIT_MARGIN_M
    return -m <= u <= floor.width_m + m and -m <= v <= floor.height_m + m
