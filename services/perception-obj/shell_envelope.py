"""Envelope-only degrade shell (decision 0077 tier ladder — the LIDAR_ARKIT
fallback, and roomplan-absent LIDAR_ROOMPLAN bundles).

The 0069 closure pass measured catastrophically on real LiDAR rooms
(decision 0075): any vertical anchor >= 0.3 m^2 became a "wall", closure
inflated furniture planes into full-height slabs (+2.48 m worst case), and
Sutherland-Hodgman floor clipping against those slabs shipped 12% / 38% of
the measured floor. The operator acceptance metric bans rendering planes
that don't exist in reality. This module replaces closure on LiDAR degrade
bundles with the adjudication's VALIDATED envelope derivation
(docs/briefs/lidar-first-rooms-adjudication.md §2a/§4, operator-confirmed
4.20 x 3.29 m against the real 247003de room): select the room's envelope
walls, intersect the four envelope planes, and render exactly that
rectangle — furniture-face planes are internal evidence, never geometry.

Selection rule (MEASURED on both preserved captures — a deliberate
amendment to the 0077 brief's literal "classification in {wall, door,
window} OR height-reach" clause, which over-admits on real data: ARKit
classifies some furniture faces "wall", and open door leaves / through-
opening detections carry door members; both hijack an extreme-offset pick.
Height-reach separates the populations perfectly on both rooms — envelope
walls top out within centimeters of the common top, furniture stops
1-2 m short):

    candidate  <=>  detected top >= common_top - SHELL_ENVELOPE_TOP_TOL_M
                    AND classification != "seat"

Candidates cluster into two near-perpendicular direction families; each
family's two extreme-offset planes are the envelope; adjacent pairs
intersect (room_planes.vertical_seam_xz) into the four floor corners.
Verified against the adjudication under BOTH the code-default and the
serving merge knobs (the selection is downstream of the merge and reads
only tops/normals/offsets): 247003de -> the adjudicated walls 02/05/09/12,
rectangle 13.8 m^2 with opposite sides agreeing to 3-7 cm; 13bae607 ->
01/03/06/08. Those achieved numbers are the regression pins
(tests/test_shell_envelope.py).

Honesty invariants:
  * No plane is invented: every envelope wall IS a merged measured wall,
    extended only along its own plane (to the seam corners, the floor, and
    the common top — the same joint vocabulary as 0069, now restricted to
    four walls that provably reach the ceiling line).
  * A non-candidate plane is never rendered, on any path.
  * If the envelope cannot close (fewer than two families of two), nothing
    is extended: candidates ship at DETECTED extents, the floor stays the
    measured coverage polygon, and `closed=False` is recorded.

Pure numpy over room_planes outputs; no GCS, no PIL, no proto imports.
Consumers: shell_receiver.py (the anchor_envelope method of shell.json v3),
tests/test_shell_envelope.py.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

import numpy as np
from room_planes import Opening, ShellPlaneGeom, vertical_seam_xz
from shell_geometry import ShellGeometry, _normalize_ccw_xz

# ---------------------------------------------------------------------------
# Tunables (env-overridable; calibrated on the two preserved LiDAR captures,
# the same posture as every SHELL_* knob)
# ---------------------------------------------------------------------------

# A wall is an envelope candidate when its detected top reaches within this
# of the common top. Measured margin on both rooms: envelope walls sit
# 0.00-0.08 m below the common top; the tallest furniture plane 0.98 m.
SHELL_ENVELOPE_TOP_TOL_M = float(os.environ.get("SHELL_ENVELOPE_TOP_TOL_M", "0.3"))

# Direction-family clustering tolerance (headings mod 180 degrees). The
# measured rooms' family spreads are <= 1.5 degrees; 15 keeps slightly
# unsquare rooms in one family without merging perpendicular families.
SHELL_ENVELOPE_FAMILY_TOL_DEG = float(
    os.environ.get("SHELL_ENVELOPE_FAMILY_TOL_DEG", "15")
)

# The two chosen families must differ by at least this much for the seam
# intersections to be well-conditioned (both rooms measure 87-90 degrees).
_MIN_FAMILY_ANGLE_DEG = 45.0

_UP = np.array([0.0, 1.0, 0.0])


# ---------------------------------------------------------------------------
# Output shapes
# ---------------------------------------------------------------------------

@dataclass
class EnvelopeWall:
    """One rendered envelope wall: the measured source (untouched) plus the
    rendered quad spanning corner-to-corner, floor-to-common-top."""

    wall_id: str  # rendered id ("wall_00"..); source keeps its own id
    source: ShellPlaneGeom  # the selected merged wall; corners_world = measured
    corners_world: np.ndarray  # (4, 3) rendered quad, interior-fronting winding
    normal: np.ndarray  # (3,) interior-pointing unit normal
    origin: np.ndarray  # (3,) == corners_world[0]
    axis_u: np.ndarray  # (3,) unit; corner0 -> corner1
    axis_v: np.ndarray  # (3,) unit; corner0 -> corner3 (== up)
    width_m: float
    height_m: float
    openings: list[Opening] = field(default_factory=list)  # RENDERED frame


@dataclass
class EnvelopeShell:
    """derive_envelope output. `closed` is True only when a full 4-plane
    envelope exists; walls then hold exactly 4 entries in floor-polygon
    walk order. When False, walls are the candidates at DETECTED extents
    and floor_corners is None (the caller falls back to the measured
    coverage polygon) — nothing extended, nothing invented."""

    walls: list[EnvelopeWall]
    floor_corners: np.ndarray | None  # (4, 3) at floor_y, CCW in XZ
    floor_y: float | None
    top_y: float | None
    closed: bool
    candidate_wall_ids: list[str]  # merged-wall ids that passed selection
    interior_wall_ids: list[str]  # merged-wall ids held back as evidence
    quality: dict = field(default_factory=dict)


def envelope_wall_geom(ew: EnvelopeWall) -> ShellPlaneGeom:
    """The rendered envelope wall as a ShellPlaneGeom, for shell_observation
    (the materials layer observes the geometry we ship)."""
    return ShellPlaneGeom(
        kind="wall",
        corners_world=ew.corners_world,
        normal=ew.normal,
        origin=ew.origin,
        axis_u=ew.axis_u,
        axis_v=ew.axis_v,
        width_m=ew.width_m,
        height_m=ew.height_m,
        classification=ew.source.classification,
        member_indices=list(ew.source.member_indices),
        wall_id=ew.wall_id,
        openings=list(ew.openings),
        area_m2=ew.source.area_m2,
    )


def envelope_floor_geom(envelope: EnvelopeShell, geometry) -> ShellPlaneGeom | None:
    """The floor plane the materials layer observes: the envelope rectangle
    when closed (select_floor's exact frame convention — u=+X, v=-Z, origin
    at (min_x, y, max_z) — so cross(axis_u, axis_v) == +Y), else the
    measured floor geom unchanged."""
    if envelope.floor_y is None:
        return None
    if not envelope.closed or envelope.floor_corners is None:
        return geometry.floor
    pts = envelope.floor_corners
    y = float(envelope.floor_y)
    min_x, max_x = float(pts[:, 0].min()), float(pts[:, 0].max())
    min_z, max_z = float(pts[:, 2].min()), float(pts[:, 2].max())
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
        classification=(
            geometry.floor.classification if geometry.floor is not None else "floor"
        ),
        member_indices=(
            list(geometry.floor.member_indices) if geometry.floor is not None else []
        ),
        area_m2=(geometry.floor.area_m2 if geometry.floor is not None else 0.0),
    )


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------

def _wall_top(w: ShellPlaneGeom) -> float:
    return float(w.corners_world[:, 1].max())


def select_envelope_candidates(
    walls: list[ShellPlaneGeom],
) -> tuple[list[ShellPlaneGeom], float | None]:
    """(candidates, common_top). The height-reach rule (module docstring):
    candidates reach the common top; `seat`-classified planes (measured:
    bed rails in both rooms) are excluded outright."""
    if not walls:
        return [], None
    common_top = max(_wall_top(w) for w in walls)
    candidates = [
        w for w in walls
        if _wall_top(w) >= common_top - SHELL_ENVELOPE_TOP_TOL_M
        and w.classification != "seat"
    ]
    return candidates, common_top


def _heading_deg(w: ShellPlaneGeom) -> float:
    return float(np.degrees(np.arctan2(w.normal[2], w.normal[0])) % 180.0)


def _heading_delta(a: float, b: float) -> float:
    d = abs(a - b) % 180.0
    return min(d, 180.0 - d)


def _cluster_families(candidates: list[ShellPlaneGeom]) -> list[dict]:
    """Greedy direction-family clustering (deterministic: input order, which
    merge_walls already sorts by heading/offset). Families sorted by total
    detected area, largest first."""
    families: list[dict] = []
    for w in candidates:
        h = _heading_deg(w)
        for fam in families:
            if _heading_delta(h, fam["heading"]) <= SHELL_ENVELOPE_FAMILY_TOL_DEG:
                fam["members"].append(w)
                break
        else:
            families.append({"heading": h, "members": [w]})
    families.sort(key=lambda f: -sum(w.area_m2 for w in f["members"]))
    return families


def _family_extremes(
    members: list[ShellPlaneGeom],
) -> tuple[ShellPlaneGeom, ShellPlaneGeom]:
    """The two extreme-offset planes along the family axis (the first
    member's normal — all members are near-parallel by construction).
    Ties break by list order (np.argmin/argmax first-hit)."""
    axis = members[0].normal
    offsets = [float(np.dot(axis, w.origin)) for w in members]
    return members[int(np.argmin(offsets))], members[int(np.argmax(offsets))]


# ---------------------------------------------------------------------------
# Derivation
# ---------------------------------------------------------------------------

def _detected_extent_wall(w: ShellPlaneGeom, wall_id: str) -> EnvelopeWall:
    """A candidate shipped at its DETECTED extent (the not-closed degrade):
    rendered quad == measured corners, openings in the measured frame
    (identical to the rendered frame here)."""
    return EnvelopeWall(
        wall_id=wall_id,
        source=w,
        corners_world=w.corners_world.copy(),
        normal=w.normal.copy(),
        origin=w.corners_world[0].copy(),
        axis_u=w.axis_u.copy(),
        axis_v=w.axis_v.copy(),
        width_m=w.width_m,
        height_m=w.height_m,
        openings=list(w.openings),
    )


def _map_openings(
    source: ShellPlaneGeom,
    rendered_origin: np.ndarray,
    rendered_axis_u: np.ndarray,
    floor_y: float,
    width_m: float,
    height_m: float,
) -> list[Opening]:
    """Re-express the source wall's measured opening rects in the rendered
    quad's frame (meters from the rendered origin). Corners are mapped
    through world space, so an axis_u flip between the measured and
    rendered frames is handled by construction."""
    out: list[Opening] = []
    for op in source.openings:
        us, vs = [], []
        for u, v in ((op.u0, op.v0), (op.u1, op.v1)):
            world = source.origin + u * source.axis_u + np.array([0.0, v, 0.0])
            us.append(float(np.dot(world - rendered_origin, rendered_axis_u)))
            vs.append(float(world[1] - floor_y))
        out.append(Opening(
            classification=op.classification,
            u0=max(0.0, min(us)),
            v0=max(0.0, min(vs)),
            u1=min(width_m, max(us)),
            v1=min(height_m, max(vs)),
        ))
    return out


def derive_envelope(geometry: ShellGeometry) -> EnvelopeShell | None:
    """Derive the envelope shell from a measured ShellGeometry
    (assemble_shell output). Returns None when there are no candidate walls
    at all AND no floor — the caller maps that to no_geometry_source."""
    walls = geometry.walls
    candidates, common_top = select_envelope_candidates(walls)
    candidate_ids = [w.wall_id or "" for w in candidates]
    interior_ids = [
        w.wall_id or "" for w in walls if (w.wall_id or "") not in candidate_ids
    ]

    if not candidates and geometry.floor is None:
        return None

    floor_y = (
        float(geometry.floor.origin[1]) if geometry.floor is not None
        else (min(float(w.corners_world[:, 1].min()) for w in candidates)
              if candidates else None)
    )

    quality = {
        "walls_detected": len(walls),
        "envelope_candidates": list(candidate_ids),
        "interior_wall_ids": list(interior_ids),
        "common_top_y": round(common_top, 4) if common_top is not None else None,
    }

    families = _cluster_families(candidates)
    fam_a = families[0] if families else None
    fam_b = None
    if fam_a is not None:
        for fam in families[1:]:
            if _heading_delta(fam["heading"], fam_a["heading"]) >= _MIN_FAMILY_ANGLE_DEG:
                fam_b = fam
                break

    closed = (
        fam_a is not None
        and fam_b is not None
        and len(fam_a["members"]) >= 2
        and len(fam_b["members"]) >= 2
        and floor_y is not None
        and common_top is not None
    )

    if not closed:
        # Nothing is extended: candidates at detected extents, measured floor.
        quality["envelope_closed"] = False
        return EnvelopeShell(
            walls=[
                _detected_extent_wall(w, f"wall_{i:02d}")
                for i, w in enumerate(candidates)
            ],
            floor_corners=None,
            floor_y=floor_y,
            top_y=common_top,
            closed=False,
            candidate_wall_ids=candidate_ids,
            interior_wall_ids=interior_ids,
            quality=quality,
        )

    a_lo, a_hi = _family_extremes(fam_a["members"])
    b_lo, b_hi = _family_extremes(fam_b["members"])

    # Floor-polygon walk order: each adjacent pair shares one envelope plane,
    # so consecutive corners bound one wall: c0c1 on b_lo, c1c2 on a_hi,
    # c2c3 on b_hi, c3c0 on a_lo.
    corner_pairs = [(a_lo, b_lo), (a_hi, b_lo), (a_hi, b_hi), (a_lo, b_hi)]
    corners_xz = []
    for wa, wb in corner_pairs:
        seam = vertical_seam_xz(wa.normal, wa.origin, wb.normal, wb.origin)
        if seam is None:
            # Near-parallel "perpendicular" families: ill-conditioned — treat
            # as not closed rather than emit a degenerate rectangle.
            quality["envelope_closed"] = False
            quality["seam_failed"] = True
            return EnvelopeShell(
                walls=[
                    _detected_extent_wall(w, f"wall_{i:02d}")
                    for i, w in enumerate(candidates)
                ],
                floor_corners=None,
                floor_y=floor_y,
                top_y=common_top,
                closed=False,
                candidate_wall_ids=candidate_ids,
                interior_wall_ids=interior_ids,
                quality=quality,
            )
        corners_xz.append(np.array([seam[0], floor_y, seam[2]]))
    floor_corners = _normalize_ccw_xz(np.stack(corners_xz))

    room_center = floor_corners.mean(axis=0)
    wall_sides = [
        (b_lo, corners_xz[0], corners_xz[1]),
        (a_hi, corners_xz[1], corners_xz[2]),
        (b_hi, corners_xz[2], corners_xz[3]),
        (a_lo, corners_xz[3], corners_xz[0]),
    ]

    env_walls: list[EnvelopeWall] = []
    for i, (src, ca, cb) in enumerate(wall_sides):
        n = src.normal.copy()
        anchor = 0.5 * (ca + cb)
        if float(np.dot(n, room_center - anchor)) < 0.0:
            n = -n
        # Winding contract (room_planes): cross(axis_u, up) == normal fronts
        # the interior. Order the two corners so that holds.
        lateral = cb - ca
        lateral[1] = 0.0
        norm = float(np.linalg.norm(lateral))
        if norm < 1e-9:
            continue  # degenerate side; skip rather than guess
        lateral /= norm
        if float(np.dot(np.cross(lateral, _UP), n)) < 0.0:
            ca, cb = cb, ca
            lateral = -lateral
        width = float(np.linalg.norm((cb - ca) * np.array([1.0, 0.0, 1.0])))
        height = float(common_top - floor_y)
        origin = np.array([ca[0], floor_y, ca[2]])
        corners = np.stack([
            origin,
            origin + width * lateral,
            origin + width * lateral + height * _UP,
            origin + height * _UP,
        ])
        env_walls.append(EnvelopeWall(
            wall_id=f"wall_{i:02d}",
            source=src,
            corners_world=corners,
            normal=n,
            origin=origin,
            axis_u=lateral,
            axis_v=_UP.copy(),
            width_m=width,
            height_m=height,
            openings=_map_openings(src, origin, lateral, floor_y, width, height),
        ))

    side_lengths = [
        float(np.linalg.norm(
            (floor_corners[(i + 1) % 4] - floor_corners[i]) * np.array([1.0, 0.0, 1.0])
        ))
        for i in range(4)
    ]
    x, z = floor_corners[:, 0], floor_corners[:, 2]
    area = 0.5 * abs(float(np.dot(x, np.roll(z, -1)) - np.dot(np.roll(x, -1), z)))
    quality.update({
        "envelope_closed": True,
        "envelope_side_lengths_m": [round(s, 3) for s in side_lengths],
        "envelope_area_m2": round(area, 2),
        "envelope_wall_sources": [w.source.wall_id for w in env_walls],
    })

    return EnvelopeShell(
        walls=env_walls,
        floor_corners=floor_corners,
        floor_y=floor_y,
        top_y=common_top,
        closed=True,
        candidate_wall_ids=candidate_ids,
        interior_wall_ids=interior_ids,
        quality=quality,
    )
