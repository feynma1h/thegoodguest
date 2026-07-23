"""Room-shell geometry: measured-plane assembly + envelope closure
(decisions 0066 geometry source / 0069 closure).

assemble_shell turns the bundle's PlaneAnchor set into a measured floor +
wall set via room_planes (THE anchor-interpretation module — floor
selection, coplanar wall merge live there). close_shell then joins the
envelope: detected wall extents extend to the measured floor-plane
intersection, to wall-wall seam lines with adjacent DETECTED walls
(gated), and to a common observed top height; the floor polygon extends
outward to wall contact lines and is bounded by them. Joints, never
loops: no plane is ever invented — every extension is the intersection
of two measurements, open sides stay open, and a bundle whose anchors
yield nothing usable returns an empty shell (the caller writes status
"unavailable").

Honesty invariants (pinned by tests):
  - closure never adds a plane, and never mutates ShellPlaneGeom's
    DETECTED geometry (corners_world et al. are what facts may read);
  - every rendered edge carries provenance (observed / extended_to_* /
    bounded_by_wall) with the extension distance;
  - the fragment filter only ever REMOVES planes (unclassified verticals
    with no joint participation), it cannot conjure structure.

Closure vocabulary: a wall's rendered quad is its measured lateral/height
span widened per-edge; edges are named bottom (y_min) / top (y_max) /
left (lat_min) / right (lat_max) as seen from the room interior (front
face). The floor's rendered polygon is the largest member's boundary
polygon with vertices snapped OUTWARD onto nearby wall contact lines and
clamped to stay inside all wall lines (the v1 bake's bounding rule).
Closure moves vertices; it does not insert new ones.

Pure numpy; no GCS, no PIL, no model imports. Consumers:
shell_receiver.py (the /shell stage), tests/test_shell_geometry.py.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import numpy as np
from room_planes import (
    _HORIZONTAL,
    _VERTICAL,
    ShellPlaneGeom,
    merge_walls,
    parse_anchors,
    select_floor,
    vertical_seam_xz,
)

# ---------------------------------------------------------------------------
# Closure tunables (env-overridable). Defaults are one-capture-calibrated
# against f3d70236's recorded anchors (the V1 probe, 0069 brief) — the same
# posture as the SHELL_WALL_* merge knobs.
# ---------------------------------------------------------------------------

# A wall whose detected bottom sits higher above the floor than this stays
# unextended (never extrude a high floating fragment into a full wall).
SHELL_FLOOR_DROP_MAX_M = float(os.environ.get("SHELL_FLOOR_DROP_MAX_M", "2.0"))

# Wall-wall seams: admitted when the seam line lies beyond NEITHER wall's
# detected lateral extent by more than this. The 0069 brief's a-priori
# default was 1.5; V1 calibration on f3d70236 lowered it — at 1.5 a
# floating curtain-plane fragment seams the main wall across a fabricated
# 1.45 m run, while every real corner on that capture closes at <= 0.3.
SHELL_JOIN_MAX_GAP_M = float(os.environ.get("SHELL_JOIN_MAX_GAP_M", "0.5"))

# Bring structural walls up to the max detected top height ("1" / "0").
SHELL_COMMON_TOP_ENABLED = (
    os.environ.get("SHELL_COMMON_TOP_ENABLED", "1") not in ("0", "false", "False")
)

# A vertical plane at or above this DETECTED area is structural regardless
# of classification; below it, unclassified planes need joint
# participation to survive the fragment filter.
SHELL_STRUCTURAL_MIN_AREA_M2 = float(
    os.environ.get("SHELL_STRUCTURAL_MIN_AREA_M2", "1.0")
)

# "Floor contact" for filter participation: the wall's detected bottom is
# already within this of the floor plane (NOT the drop gate — a wall may
# be extended 2 m down yet only counts as touching when it starts here).
SHELL_FLOOR_CONTACT_TOL_M = float(
    os.environ.get("SHELL_FLOOR_CONTACT_TOL_M", "0.15")
)

# Below this angle between wall normals a seam line is ill-conditioned
# and never made (near-parallel walls don't corner).
_SEAM_MIN_ANGLE_DEG = 30.0

# Small epsilon: extensions below this are "already there" (observed).
_EPS_M = 1e-6

# Floor vertices may be clamped inward up to this beyond a wall line
# before the bounding rule moves them (v1 bake parity).
_FLOOR_BOUND_TOL_M = 0.02


# ---------------------------------------------------------------------------
# Output shapes
# ---------------------------------------------------------------------------

@dataclass
class EdgeState:
    """Provenance for one rendered wall edge."""

    state: str  # "observed" | "extended_to_floor" | "extended_to_common_height" | "extended_to_wall:<id>"
    extension_m: float = 0.0


@dataclass
class ClosedWall:
    """One surviving wall after closure: the measured geometry (untouched)
    plus the rendered quad and per-edge provenance."""

    geom: ShellPlaneGeom  # measured; corners_world is the measured_quad
    rendered_corners: np.ndarray  # (4, 3), same winding as measured
    edges: dict[str, EdgeState]  # keys: bottom / top / left / right


@dataclass
class ShellClosure:
    """close_shell output. Walls here are the SURVIVORS of the fragment
    filter; dropped ids are recorded, never silently gone."""

    walls: list[ClosedWall]
    floor_polygon_measured: np.ndarray | None  # (N, 3) at y_floor
    floor_polygon_rendered: np.ndarray | None  # (N, 3) post-closure
    floor_edge_states: list[str]  # per rendered segment i: v[i] -> v[i+1]
    dropped_wall_ids: list[str]
    quality: dict


@dataclass
class ShellGeometry:
    """assemble_shell output: the measured shell, plus the raw floor member
    polygons (world frame) whose union defines the floor's detected shape."""

    floor: ShellPlaneGeom | None
    walls: list[ShellPlaneGeom]
    # World-frame polygons ((N, 3) arrays) of the merged floor's member
    # anchors — boundary polygons when the client sent them, extent
    # rectangles otherwise.
    floor_member_polygons: list[np.ndarray]
    quality: dict


# ---------------------------------------------------------------------------
# Assembly (measurement only — no closure)
# ---------------------------------------------------------------------------

def assemble_shell(plane_anchors) -> ShellGeometry:
    """Assemble the measured shell from a bundle's plane_anchors (repeated
    PlaneAnchor). Empty/unusable input yields floor=None, walls=[] — the
    caller maps that to status "unavailable"; nothing is invented here."""
    parsed = parse_anchors(plane_anchors)

    floor, floor_polygons = select_floor(parsed)
    walls = merge_walls(parsed)

    quality = {
        "planes_in_bundle": len(parsed),
        "horizontal_anchors": sum(1 for a in parsed if a.alignment == _HORIZONTAL),
        "vertical_anchors": sum(1 for a in parsed if a.alignment == _VERTICAL),
        "floor_member_count": len(floor.member_indices) if floor else 0,
        "wall_count": len(walls),
    }
    return ShellGeometry(
        floor=floor,
        walls=walls,
        floor_member_polygons=floor_polygons,
        quality=quality,
    )


# ---------------------------------------------------------------------------
# Closure internals
# ---------------------------------------------------------------------------

def _lat_span(w: ShellPlaneGeom) -> tuple[float, float]:
    """Wall's detected lateral span in its own frame: s=0 at corner0."""
    return 0.0, w.width_m


def _seam_s(w: ShellPlaneGeom, seam_xz: np.ndarray) -> float:
    """Lateral coordinate of a vertical seam line in wall w's frame."""
    d = seam_xz - np.array([w.origin[0], 0.0, w.origin[2]])
    return float(d @ w.axis_u)


def _seam_gap(w: ShellPlaneGeom, s_seam: float) -> float:
    """Signed distance of the seam beyond w's detected extent: 0 inside,
    negative beyond the left (lat_min) edge, positive beyond the right."""
    lo, hi = _lat_span(w)
    if s_seam < lo:
        return s_seam - lo
    if s_seam > hi:
        return s_seam - hi
    return 0.0


def _admitted_seams(
    walls: list[ShellPlaneGeom],
) -> list[tuple[int, int, np.ndarray, float, float]]:
    """All admitted seams (i, j, seam_xz, gap_i, gap_j) among the measured
    walls: angle >= _SEAM_MIN_ANGLE_DEG and the seam beyond neither
    detected extent by more than SHELL_JOIN_MAX_GAP_M."""
    seams = []
    for i in range(len(walls)):
        for j in range(i + 1, len(walls)):
            a, b = walls[i], walls[j]
            seam = vertical_seam_xz(
                a.normal, a.origin, b.normal, b.origin,
                min_angle_deg=_SEAM_MIN_ANGLE_DEG,
            )
            if seam is None:
                continue
            ga = _seam_gap(a, _seam_s(a, seam))
            gb = _seam_gap(b, _seam_s(b, seam))
            if abs(ga) <= SHELL_JOIN_MAX_GAP_M and abs(gb) <= SHELL_JOIN_MAX_GAP_M:
                seams.append((i, j, seam, ga, gb))
    return seams


def _is_structural(w: ShellPlaneGeom) -> bool:
    """Structural: ARKit-classified surface, carries openings (door/window
    anchors are classified structure), or large detected area."""
    return (
        bool(w.classification)
        or len(w.openings) > 0
        or w.area_m2 >= SHELL_STRUCTURAL_MIN_AREA_M2
    )


def _floor_contact(w: ShellPlaneGeom, floor_y: float | None) -> bool:
    if floor_y is None:
        return False
    y_min = float(w.corners_world[:, 1].min())
    return (y_min - floor_y) <= SHELL_FLOOR_CONTACT_TOL_M


def _polygon_signed_area_xz(poly: np.ndarray) -> float:
    x, z = poly[:, 0], poly[:, 2]
    return 0.5 * float(np.sum(x * np.roll(z, -1) - np.roll(x, -1) * z))


def _normalize_ccw_xz(poly: np.ndarray) -> np.ndarray:
    """Normalize vertex order so the shoelace area over (x, z) is
    positive — one pinned winding for every emitted floor polygon."""
    if _polygon_signed_area_xz(poly) < 0:
        return poly[::-1].copy()
    return poly


# ---------------------------------------------------------------------------
# Closure
# ---------------------------------------------------------------------------

def close_shell(geometry: ShellGeometry) -> ShellClosure:
    """The envelope-closure pass (0069): filter fragments, extend surviving
    walls to the floor / seams / common top, snap the floor polygon to wall
    contact lines. Never mutates `geometry` — measured stays measured."""
    walls = geometry.walls
    floor = geometry.floor
    floor_y = float(floor.origin[1]) if floor is not None else None

    # ---- seams on MEASURED extents (used for both filter + extension) ----
    seams = _admitted_seams(walls)
    seam_partners: dict[int, list[tuple[int, np.ndarray]]] = {
        i: [] for i in range(len(walls))
    }
    for i, j, seam, _, _ in seams:
        seam_partners[i].append((j, seam))
        seam_partners[j].append((i, seam))

    # ---- fragment filter --------------------------------------------------
    def _participates(idx: int) -> bool:
        if _floor_contact(walls[idx], floor_y):
            return True
        return any(_is_structural(walls[p]) for p, _ in seam_partners[idx])

    keep = [
        i for i, w in enumerate(walls)
        if _is_structural(w) or _participates(i)
    ]
    dropped_ids = [
        walls[i].wall_id or f"wall_{i:02d}"
        for i in range(len(walls))
        if i not in keep
    ]
    kept_set = set(keep)

    # ---- per-wall closure (survivors only) --------------------------------
    closed: dict[int, ClosedWall] = {}
    stats = {
        "fragments_dropped": len(dropped_ids),
        "wall_floor_joints": 0,
        "wall_wall_seams": 0,
        "walls_raised_to_common_top": 0,
        "floor_vertices_snapped": 0,
    }

    for i in keep:
        w = walls[i]
        y_min = float(w.corners_world[:, 1].min())
        y_max = float(w.corners_world[:, 1].max())
        s_lo, s_hi = _lat_span(w)
        edges = {
            "bottom": EdgeState("observed"),
            "top": EdgeState("observed"),
            "left": EdgeState("observed"),
            "right": EdgeState("observed"),
        }

        # Wall -> floor.
        if floor_y is not None:
            drop = y_min - floor_y
            if _EPS_M < drop <= SHELL_FLOOR_DROP_MAX_M:
                edges["bottom"] = EdgeState("extended_to_floor", drop)
                y_min = floor_y
                stats["wall_floor_joints"] += 1

        # Wall -> wall seams: extend each lateral edge to the NEAREST
        # admitted seam beyond it (survivor partners only); never past it.
        left_cand: tuple[float, int] | None = None  # (s_seam, partner)
        right_cand: tuple[float, int] | None = None
        for p, seam in seam_partners[i]:
            if p not in kept_set:
                continue
            s_seam = _seam_s(w, seam)
            gap = _seam_gap(w, s_seam)
            if -SHELL_JOIN_MAX_GAP_M <= gap < -_EPS_M:
                if left_cand is None or s_seam > left_cand[0]:
                    left_cand = (s_seam, p)
            elif _EPS_M < gap <= SHELL_JOIN_MAX_GAP_M:
                if right_cand is None or s_seam < right_cand[0]:
                    right_cand = (s_seam, p)
        if left_cand is not None:
            partner_id = walls[left_cand[1]].wall_id
            edges["left"] = EdgeState(
                f"extended_to_wall:{partner_id}", s_lo - left_cand[0]
            )
            s_lo = left_cand[0]
            stats["wall_wall_seams"] += 1
        if right_cand is not None:
            partner_id = walls[right_cand[1]].wall_id
            edges["right"] = EdgeState(
                f"extended_to_wall:{partner_id}", right_cand[0] - s_hi
            )
            s_hi = right_cand[0]
            stats["wall_wall_seams"] += 1

        closed[i] = ClosedWall(
            geom=w,
            rendered_corners=np.stack([
                w.origin + s_lo * w.axis_u + (y_min - w.origin[1]) * w.axis_v,
                w.origin + s_hi * w.axis_u + (y_min - w.origin[1]) * w.axis_v,
                w.origin + s_hi * w.axis_u + (y_max - w.origin[1]) * w.axis_v,
                w.origin + s_lo * w.axis_u + (y_max - w.origin[1]) * w.axis_v,
            ]),
            edges=edges,
        )

    # ---- common top (structural survivors, measured heights) --------------
    if SHELL_COMMON_TOP_ENABLED:
        structural_kept = [i for i in keep if _is_structural(walls[i])]
        if structural_kept:
            common_top = max(
                float(walls[i].corners_world[:, 1].max()) for i in structural_kept
            )
            for i in structural_kept:
                cw = closed[i]
                y_max = float(cw.geom.corners_world[:, 1].max())
                raise_by = common_top - y_max
                if raise_by > _EPS_M:
                    cw.edges["top"] = EdgeState(
                        "extended_to_common_height", raise_by
                    )
                    up = cw.geom.axis_v
                    cw.rendered_corners[2] += raise_by * up
                    cw.rendered_corners[3] += raise_by * up
                    stats["walls_raised_to_common_top"] += 1

    # ---- floor closure -----------------------------------------------------
    floor_measured: np.ndarray | None = None
    floor_rendered: np.ndarray | None = None
    floor_edge_states: list[str] = []
    if floor is not None and geometry.floor_member_polygons:
        # Base = largest-area member polygon (the real captures' floor is a
        # single ARKit-merged anchor; multi-member unions can land when a
        # capture demands them — the extra members still count in quality).
        base = max(
            geometry.floor_member_polygons,
            key=lambda p: abs(_polygon_signed_area_xz(p)),
        )
        floor_measured = _normalize_ccw_xz(np.asarray(base, dtype=np.float64))
        rendered = floor_measured.copy()

        # Wall contact lines (survivors only): (normal_xz, point_xz, wall,
        # rendered lateral span for the outward-snap reach check).
        lines = []
        for i in keep:
            cw = closed[i]
            n = cw.geom.normal
            p0 = cw.geom.origin
            s = (cw.rendered_corners - cw.geom.origin) @ cw.geom.axis_u
            lines.append((n, p0, cw.geom, float(s.min()), float(s.max())))

        # Pass 1 — outward snap: each vertex moves onto the nearest wall
        # line within the join gate whose lateral span (rendered, +gate
        # margin) covers it. Small, gate-bounded moves; no new vertices.
        outward: list[bool] = [False] * len(rendered)
        for vi in range(len(rendered)):
            v = rendered[vi]
            best: tuple[float, int] | None = None  # (interior distance, line idx)
            for li, (n, p0, geom_w, s_min, s_max) in enumerate(lines):
                d = float((v - p0) @ n)
                if not (0.0 <= d <= SHELL_JOIN_MAX_GAP_M):
                    continue
                s_v = float((v - geom_w.origin) @ geom_w.axis_u)
                if not (s_min - SHELL_JOIN_MAX_GAP_M <= s_v <= s_max + SHELL_JOIN_MAX_GAP_M):
                    continue
                if best is None or d < best[0]:
                    best = (d, li)
            if best is not None and best[0] > _EPS_M:
                n, p0, _, _, _ = lines[best[1]]
                rendered[vi] = v - best[0] * np.array([n[0], 0.0, n[2]])
                outward[vi] = True
                stats["floor_vertices_snapped"] += 1

        # Pass 2 — bounding (the v1 bake's rule, done right): clip the
        # polygon against each surviving wall's interior half-plane
        # (Sutherland–Hodgman). Exact area, intersection vertices inserted
        # ON the wall line — a vertex far past a line is cut off, never
        # dragged perpendicular (which could fold the polygon).
        for n, p0, _, _, _ in lines:
            m = len(rendered)
            if m == 0:
                break
            clipped_pts: list[np.ndarray] = []
            clipped_out: list[bool] = []
            d_all = (rendered - p0) @ n
            for a in range(m):
                b = (a + 1) % m
                da, db = float(d_all[a]), float(d_all[b])
                a_in = da >= -_FLOOR_BOUND_TOL_M
                b_in = db >= -_FLOOR_BOUND_TOL_M
                if a_in:
                    clipped_pts.append(rendered[a])
                    clipped_out.append(outward[a])
                if a_in != b_in:
                    t = da / (da - db)  # crossing point on the wall line
                    clipped_pts.append(
                        rendered[a] + t * (rendered[b] - rendered[a])
                    )
                    clipped_out.append(False)
            if len(clipped_pts) >= 3:
                rendered = np.asarray(clipped_pts)
                outward = clipped_out
            # else: the clip would degenerate the floor — a wall line
            # cutting essentially everything is a calibration anomaly;
            # keep the unclipped polygon rather than emit no floor.

        # Per-segment provenance, decided GEOMETRICALLY: a segment lies on
        # wall w's contact line iff both endpoints do (robust to clip
        # bookkeeping); extended when either endpoint was snapped outward,
        # bounded otherwise. Everything else is (a truncation of) a
        # detected boundary edge: observed.
        floor_rendered = rendered
        n_v = len(rendered)
        for si in range(n_v):
            va, vb = rendered[si], rendered[(si + 1) % n_v]
            state = "observed"
            for n, p0, geom_w, _, _ in lines:
                if (
                    abs(float((va - p0) @ n)) <= 1e-6
                    and abs(float((vb - p0) @ n)) <= 1e-6
                ):
                    if outward[si] or outward[(si + 1) % n_v]:
                        state = f"extended_to_wall:{geom_w.wall_id}"
                    else:
                        state = f"bounded_by_wall:{geom_w.wall_id}"
                    break
            floor_edge_states.append(state)

    quality = dict(stats)
    return ShellClosure(
        walls=[closed[i] for i in keep],
        floor_polygon_measured=floor_measured,
        floor_polygon_rendered=floor_rendered,
        floor_edge_states=floor_edge_states,
        dropped_wall_ids=dropped_ids,
        quality=quality,
    )
