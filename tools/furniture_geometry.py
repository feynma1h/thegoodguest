"""Geometry shared by the furniture twin tools: where a part of a twin is in
space, and whether two of them overlap.

A twin is a list of parts in the piece's own frame: origin at the centre of
its footprint ON THE FLOOR, +y up. Rotations follow three.js ('XYZ' Euler in
degrees, about the part's own origin `at`); the twin's yaw turns that frame
about +y, with local +z going to (sin yaw, 0, cos yaw) in the world.
"""
from __future__ import annotations

import itertools
import math

import numpy as np


def euler_xyz(deg) -> np.ndarray:
    """three.js 'XYZ' Euler (degrees) -> rotation matrix R = Rx @ Ry @ Rz."""
    ax, ay, az = (math.radians(a) for a in deg)
    cx, sx, cy, sy, cz, sz = math.cos(ax), math.sin(ax), math.cos(ay), math.sin(ay), math.cos(az), math.sin(az)
    rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    return rx @ ry @ rz


def yaw_matrix(yaw: float) -> np.ndarray:
    c, s = math.cos(yaw), math.sin(yaw)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])


def part_extent(part: dict) -> tuple[np.ndarray, np.ndarray]:
    """Rough axis-aligned (min, max) of a part in the piece frame, ignoring
    rotation (good enough for a sanity bound)."""
    at = np.array(part.get("at", [0, 0, 0]), float)
    k = part["kind"]
    if k == "box":
        h = np.array(part["size"], float) / 2
    elif k == "cyl":
        r = max(part["r"], part.get("rTop", part["r"]))
        h = np.array([r, part["h"] / 2, r])
    elif k == "sphere":
        h = np.array(part["r"] if isinstance(part["r"], list) else [part["r"]] * 3, float)
    elif k == "lathe":
        r = max(p[0] for p in part["profile"])
        ys = [p[1] for p in part["profile"]]
        return at + np.array([-r, min(ys), -r]), at + np.array([r, max(ys), r])
    elif k == "tube":
        pts = np.array(part["path"], float)
        return at + pts.min(0) - part["r"], at + pts.max(0) + part["r"]
    elif k == "extrude":
        pts = np.array(part["outline"], float)
        d = part["depth"] / 2
        return at + np.array([pts[:, 0].min(), pts[:, 1].min(), -d]), at + np.array([pts[:, 0].max(), pts[:, 1].max(), d])
    elif k == "books":
        h = np.array([part["w"] / 2, part["hmax"] / 2, part["depth"] / 2])
        return at - np.array([h[0], 0, h[2]]), at + np.array([h[0], part["hmax"], h[2]])
    elif k == "drape":
        h = np.array([part["w"] / 2, part["h"] / 2, part["amp"]])
    else:
        h = np.zeros(3)
    if part.get("rot") and any(abs(a) > 1e-6 for a in part["rot"]):
        h = np.full(3, float(np.max(h)))  # rotated: bound by the longest half-extent
    return at - h, at + h


def part_obb(part: dict, origin: np.ndarray, yaw: float):
    """(centre, 3x3 axes as columns, half extents) of a part in world space."""
    lo, hi = part_extent({**part, "rot": None})  # local AABB ignoring rotation
    c_local, half = (lo + hi) / 2, np.maximum((hi - lo) / 2, 1e-4)
    r_part = euler_xyz(part["rot"]) if part.get("rot") else np.eye(3)
    at = np.array(part.get("at", [0, 0, 0]), float)
    # rotation is about the part's own origin (`at`); the extent's centre may be offset from it
    c = at + r_part @ (c_local - at)
    ry = yaw_matrix(yaw)
    return origin + ry @ c, ry @ r_part, half


def obb_penetration(a, b) -> tuple[float, np.ndarray]:
    """(depth, axis) of the shallowest way out of an overlap between two
    oriented boxes, over the 15 separating axes. depth <= 0 means separated.
    `axis` is a unit vector pointing from a towards b."""
    ca, ra, ha = a
    cb, rb, hb = b
    t = cb - ca
    axes = [ra[:, i] for i in range(3)] + [rb[:, i] for i in range(3)]
    axes += [np.cross(ra[:, i], rb[:, j]) for i in range(3) for j in range(3)]
    best, best_axis = math.inf, np.array([0.0, 1.0, 0.0])
    for ax in axes:
        n = np.linalg.norm(ax)
        if n < 1e-9:
            continue
        ax = ax / n
        pa = float(np.sum(np.abs(ra.T @ ax) * ha))
        pb = float(np.sum(np.abs(rb.T @ ax) * hb))
        d = float(t @ ax)
        depth = pa + pb - abs(d)
        if depth < best:
            best, best_axis = depth, ax if d >= 0 else -ax
        if best <= 0:
            return best, best_axis
    return best, best_axis


def obb_overlap(a, b) -> float:
    """Minimum penetration depth (<= 0 means separated)."""
    return obb_penetration(a, b)[0]


def corners(obb) -> np.ndarray:
    c, r, h = obb
    return np.array([c + r @ (h * np.array(s)) for s in itertools.product((-1, 1), repeat=3)])


def polygon_sign(poly: np.ndarray) -> int:
    n = len(poly)
    area = sum(poly[i][0] * poly[(i + 1) % n][1] - poly[(i + 1) % n][0] * poly[i][1] for i in range(n))
    return 1 if area > 0 else -1


def point_outside_polygon(p, poly) -> float:
    """Distance (>0) by which p (x, z) lies outside the convex polygon, else 0."""
    return worst_edge(p, poly)[0]


def worst_edge(p, poly) -> tuple[float, np.ndarray]:
    """(distance outside, unit inward normal) of the edge p is furthest outside of."""
    n = len(poly)
    sign = polygon_sign(poly)
    worst, normal = 0.0, np.zeros(2)
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        e = b - a
        e = e / (np.linalg.norm(e) + 1e-12)
        d = sign * (e[0] * (p[1] - a[1]) - e[1] * (p[0] - a[0]))  # > 0 inside
        if -d > worst:
            worst, normal = -d, np.array([-e[1], e[0]]) * sign
    return worst, normal
