"""Geometry kernel for the room guide: yaw-only boxes, the floor polygon, a floor grid.

Everything here is in the room frame: +Y up, metres, right-handed. Every solid in
a room is a union of yaw-only boxes (an oriented rectangle on the floor with a
vertical extent), so that is the only shape any rule tests. Rotation follows
three.js, which the diorama viewer uses: a yaw turns local +Z, a piece's front,
to (sin yaw, cos yaw) in (x, z), and local +X to (cos yaw, -sin yaw).

The floor grid answers the questions that need space rather than shapes: how
far each spot is from the nearest obstacle, whether two places connect, and how
wide the widest way between them is.

Read by: model.py, laws.py, needs.py, analyzer.py, engine.py, motion.py.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

Vec2 = tuple[float, float]


@dataclass(frozen=True)
class Box:
    """A yaw-only box in the room frame.

    (x, z) is the centre of its footprint; hx and hz are its half extents along
    its own across (local +X) and front (local +Z) axes; y0 and y1 are its
    bottom and top.
    """

    x: float
    z: float
    hx: float
    hz: float
    yaw: float
    y0: float
    y1: float

    @property
    def across(self) -> Vec2:
        return (math.cos(self.yaw), -math.sin(self.yaw))

    @property
    def front(self) -> Vec2:
        return (math.sin(self.yaw), math.cos(self.yaw))

    def corners(self) -> np.ndarray:
        """The footprint's four corners, (4, 2), in order round the box."""
        c = np.array([self.x, self.z])
        a = np.array(self.across) * self.hx
        f = np.array(self.front) * self.hz
        return np.array([c + a + f, c - a + f, c - a - f, c + a - f])

    def to_local(self, pts: np.ndarray) -> np.ndarray:
        """(n, 2) room points to (n, 2) coordinates along (across, front)."""
        rel = np.asarray(pts, dtype=float) - np.array([self.x, self.z])
        ax, az = self.across
        fx, fz = self.front
        return np.stack([rel[:, 0] * ax + rel[:, 1] * az, rel[:, 0] * fx + rel[:, 1] * fz], axis=1)

    def grown(self, by: float) -> "Box":
        """The same box with its footprint grown by `by` on every side."""
        return Box(self.x, self.z, self.hx + by, self.hz + by, self.yaw, self.y0, self.y1)


def _half_projection(b: Box, n: np.ndarray) -> float:
    ax, az = b.across
    fx, fz = b.front
    return b.hx * abs(ax * n[0] + az * n[1]) + b.hz * abs(fx * n[0] + fz * n[1])


def footprint_penetration(a: Box, b: Box) -> float:
    """How deep two footprints interpenetrate, by the separating-axis test.

    Positive: they overlap, and this is the overlap along the axis where it is
    smallest. Zero or negative: they do not overlap.
    """
    d = np.array([b.x - a.x, b.z - a.z])
    best = math.inf
    for axis in (a.across, a.front, b.across, b.front):
        n = np.array(axis)
        best = min(best, _half_projection(a, n) + _half_projection(b, n) - abs(float(d @ n)))
    return best


def vertical_overlap(a: Box, b: Box) -> float:
    """How far two boxes' height ranges overlap; zero or negative when they don't."""
    return min(a.y1, b.y1) - max(a.y0, b.y0)


def penetration(a: Box, b: Box) -> float:
    """Depth of 3D overlap: the smaller of the footprint and height overlaps.

    Positive only when the two boxes share volume.
    """
    return min(footprint_penetration(a, b), vertical_overlap(a, b))


def footprint_distance(b: Box, pts: np.ndarray) -> np.ndarray:
    """Distance from each (n, 2) point to the box's footprint; 0 inside it."""
    loc = b.to_local(pts)
    du = np.maximum(np.abs(loc[:, 0]) - b.hx, 0.0)
    dv = np.maximum(np.abs(loc[:, 1]) - b.hz, 0.0)
    return np.hypot(du, dv)


def footprint_gap(a: Box, b: Box) -> float:
    """Shortest distance between two footprints; 0 when they touch or overlap.

    Exact: between two disjoint convex shapes the closest pair always includes
    a corner of one of them.
    """
    if footprint_penetration(a, b) > 0:
        return 0.0
    return float(min(footprint_distance(b, a.corners()).min(), footprint_distance(a, b.corners()).min()))


# ---------------------------------------------------------------- polygons

def point_in_polygon(pts: np.ndarray, poly: np.ndarray) -> np.ndarray:
    """Which of the (n, 2) points lie inside the polygon (even-odd rule)."""
    pts = np.asarray(pts, dtype=float)
    x, z = pts[:, 0], pts[:, 1]
    inside = np.zeros(len(pts), dtype=bool)
    n = len(poly)
    for i in range(n):
        x1, z1 = poly[i]
        x2, z2 = poly[(i + 1) % n]
        crosses = (z1 > z) != (z2 > z)
        with np.errstate(divide="ignore", invalid="ignore"):
            xi = x1 + (z - z1) * (x2 - x1) / (z2 - z1)
        inside ^= crosses & (x < xi)
    return inside


def segment_distance(pts: np.ndarray, a: Vec2, b: Vec2) -> np.ndarray:
    """Distance from each (n, 2) point to the segment a-b."""
    pts = np.asarray(pts, dtype=float)
    a = np.asarray(a, dtype=float)
    ab = np.asarray(b, dtype=float) - a
    denom = float(ab @ ab)
    t = np.zeros(len(pts)) if denom == 0 else np.clip((pts - a) @ ab / denom, 0.0, 1.0)
    closest = a + t[:, None] * ab
    return np.hypot(pts[:, 0] - closest[:, 0], pts[:, 1] - closest[:, 1])


def polygon_edge_distance(pts: np.ndarray, poly: np.ndarray) -> np.ndarray:
    """Distance from each (n, 2) point to the polygon's nearest edge."""
    n = len(poly)
    d = np.full(len(pts), np.inf)
    for i in range(n):
        d = np.minimum(d, segment_distance(pts, poly[i], poly[(i + 1) % n]))
    return d


def box_inside_polygon(b: Box, poly: np.ndarray, tol: float = 0.01) -> bool:
    """Whether a footprint lies inside the floor polygon, allowing `tol` of noise.

    Checks the corners and, for a polygon with reflex corners, that no polygon
    corner pokes into the box.
    """
    corners = b.corners()
    inside = point_in_polygon(corners, poly)
    if not np.all(inside | (polygon_edge_distance(corners, poly) <= tol)):
        return False
    loc = b.to_local(np.asarray(poly, dtype=float))
    poking = (np.abs(loc[:, 0]) < b.hx - tol) & (np.abs(loc[:, 1]) < b.hz - tol)
    return not bool(np.any(poking))


# ---------------------------------------------------------------- the floor grid

@dataclass(frozen=True)
class FloorGrid:
    """Square cells over the floor polygon's bounding rectangle.

    `points` holds every cell centre, row by row (z rows, x columns); `inside`
    says which centres lie on the floor.
    """

    cell: float
    x0: float
    z0: float
    nx: int
    nz: int
    points: np.ndarray
    inside: np.ndarray

    @classmethod
    def over(cls, poly: np.ndarray, cell: float = 0.05) -> "FloorGrid":
        poly = np.asarray(poly, dtype=float)
        x0, z0 = poly.min(axis=0)
        x1, z1 = poly.max(axis=0)
        nx = max(1, int(math.ceil((x1 - x0) / cell)))
        nz = max(1, int(math.ceil((z1 - z0) / cell)))
        xs = x0 + (np.arange(nx) + 0.5) * cell
        zs = z0 + (np.arange(nz) + 0.5) * cell
        gx, gz = np.meshgrid(xs, zs)
        pts = np.stack([gx.ravel(), gz.ravel()], axis=1)
        return cls(cell, float(x0), float(z0), nx, nz, pts, point_in_polygon(pts, poly))

    @property
    def shape(self) -> tuple[int, int]:
        return (self.nz, self.nx)

    def in_box(self, b: Box, grow: float = 0.0) -> np.ndarray:
        """Cells whose centres fall in the footprint grown by `grow`."""
        loc = b.to_local(self.points)
        return (np.abs(loc[:, 0]) <= b.hx + grow) & (np.abs(loc[:, 1]) <= b.hz + grow)


def clearance(grid: FloorGrid, blockers: list[Box], poly: np.ndarray) -> np.ndarray:
    """For each cell: distance to the nearest wall or blocking footprint (0 off the floor)."""
    d = polygon_edge_distance(grid.points, np.asarray(poly, dtype=float))
    for b in blockers:
        d = np.minimum(d, footprint_distance(b, grid.points))
    return np.where(grid.inside, d, 0.0)


def flood(seeds: np.ndarray, passable: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    """Cells reachable from `seeds` through `passable` cells, four-connected."""
    ok = passable.reshape(shape)
    reached = seeds.reshape(shape) & ok
    while True:
        grow = reached.copy()
        grow[1:, :] |= reached[:-1, :]
        grow[:-1, :] |= reached[1:, :]
        grow[:, 1:] |= reached[:, :-1]
        grow[:, :-1] |= reached[:, 1:]
        grow &= ok
        if np.array_equal(grow, reached):
            return reached.ravel()
        reached = grow


def widest_path(clear: np.ndarray, sources: np.ndarray, targets: np.ndarray,
                shape: tuple[int, int], *, top: float = 3.0, tol: float = 0.01) -> float:
    """Width of the widest way from any source cell to any target cell.

    The largest w such that the cells at least w/2 from every obstacle connect a
    source to a target. 0 when nothing connects them even at zero width.
    """
    def connects(w: float) -> bool:
        walk = clear >= w / 2
        return bool(np.any(flood(sources & walk, walk, shape) & targets))

    if not connects(1e-6):
        return 0.0
    lo, hi = 0.0, top
    if connects(hi):
        return hi
    while hi - lo > tol:
        mid = (lo + hi) / 2
        if connects(mid):
            lo = mid
        else:
            hi = mid
    return lo


def largest_open_rectangle(free: np.ndarray, shape: tuple[int, int]) -> int:
    """Cells in the largest axis-aligned rectangle of free cells (histogram method)."""
    grid = free.reshape(shape)
    heights = np.zeros(shape[1], dtype=int)
    best = 0
    for row in grid:
        heights = np.where(row, heights + 1, 0)
        stack: list[int] = []
        for i in range(len(heights) + 1):
            h = int(heights[i]) if i < len(heights) else 0
            while stack and int(heights[stack[-1]]) >= h:
                top = stack.pop()
                width = i if not stack else i - stack[-1] - 1
                best = max(best, int(heights[top]) * width)
            stack.append(i)
    return best
