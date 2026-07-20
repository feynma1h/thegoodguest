#!/usr/bin/env python3
"""Generate synthetic 3DGS PLY fixtures + a manifest for the web viewer.

Writes primitive-shaped Gaussian-splat clouds (sofa, table, lamp, plant)
to web/public/dev-fixtures/ (gitignored), each origin-centered with its
longest extent normalized to ~1.0 — the same local-frame convention SAM 3D
objects arrive in — plus a manifest.json in the GET /scenes/{id}/assets
response shape (manifest v2 + asset_urls) with world transforms placing
them as a small room. The web viewer's no-source fallback autoloads this
manifest, so the assembled-room render path is testable end-to-end with no
backend, no GPU pipeline, and no real room data.

PLY layout is the standard INRIA 3DGS vertex schema (binary little-endian
float32): x y z, nx ny nz (zeros), f_dc_0..2 (SH DC color), f_rest_0..44
(zeros, SH degree 3), opacity (pre-sigmoid logit), scale_0..2 (log sigma),
rot_0..3 (quaternion, w-first, identity).

Run from repo root:
    python tools/make_synthetic_splat.py

Consumers: web/ dev workflow (see web/README.md); web viewer's
/dev-fixtures/manifest.json autoload; drag-drop testing of any splat
renderer.
"""
from __future__ import annotations

import json
import math
import struct
from pathlib import Path

import numpy as np

OUT_DIR = Path(__file__).resolve().parents[1] / "web" / "public" / "dev-fixtures"

SH_C0 = 0.28209479177387814  # SH degree-0 basis constant
N_F_REST = 45  # SH degree 3: (16-1) coefficients x 3 channels


def write_gaussian_ply(path: Path, xyz: np.ndarray, rgb: np.ndarray,
                       sigma: float = 0.012) -> None:
    """Write an INRIA-layout 3DGS binary PLY.

    xyz: (N, 3) positions; rgb: (N, 3) colors in [0, 1]; sigma: gaussian
    radius in local units (log-encoded per the format).
    """
    n = xyz.shape[0]
    props = (
        ["x", "y", "z", "nx", "ny", "nz", "f_dc_0", "f_dc_1", "f_dc_2"]
        + [f"f_rest_{i}" for i in range(N_F_REST)]
        + ["opacity", "scale_0", "scale_1", "scale_2", "rot_0", "rot_1", "rot_2", "rot_3"]
    )
    header = "\n".join(
        ["ply", "format binary_little_endian 1.0", f"element vertex {n}"]
        + [f"property float {p}" for p in props]
        + ["end_header", ""]
    ).encode("ascii")

    rec = np.zeros((n, len(props)), dtype="<f4")
    rec[:, 0:3] = xyz
    rec[:, 6:9] = (rgb - 0.5) / SH_C0  # DC term encodes color
    off = 9 + N_F_REST
    rec[:, off] = math.log(0.95 / (1 - 0.95))  # opacity logit(0.95)
    rec[:, off + 1: off + 4] = math.log(sigma)
    rec[:, off + 4] = 1.0  # rot quaternion identity, w-first
    path.write_bytes(header + rec.tobytes())


def _center_and_normalize(xyz: np.ndarray) -> np.ndarray:
    """Origin-center and scale so the longest extent is 1.0 — the SAM 3D
    local-frame convention the viewer's transforms assume."""
    xyz = xyz - xyz.mean(axis=0)
    extent = (xyz.max(axis=0) - xyz.min(axis=0)).max()
    return xyz / extent


def _box(rng, n, cx, cy, cz, sx, sy, sz):
    pts = (rng.random((n, 3)) - 0.5) * np.array([sx, sy, sz])
    return pts + np.array([cx, cy, cz])


def _sphere(rng, n, cx, cy, cz, r):
    v = rng.normal(size=(n, 3))
    v /= np.linalg.norm(v, axis=1, keepdims=True)
    return v * (r * rng.random((n, 1)) ** (1 / 3)) + np.array([cx, cy, cz])


def _cylinder(rng, n, cx, cy, cz, r, h):
    ang = rng.random(n) * 2 * np.pi
    rad = r * np.sqrt(rng.random(n))
    y = (rng.random(n) - 0.5) * h
    return np.column_stack([cx + rad * np.cos(ang), cy + y, cz + rad * np.sin(ang)])


def _tint(rng, base, n, jitter=0.06):
    return np.clip(np.array(base) + rng.normal(size=(n, 3)) * jitter, 0.02, 0.98)


def make_sofa(rng):
    seat = _box(rng, 9000, 0, 0.12, 0, 1.0, 0.22, 0.48)
    back = _box(rng, 6000, 0, 0.38, -0.19, 1.0, 0.34, 0.12)
    arm_l = _box(rng, 2000, -0.46, 0.28, 0.02, 0.10, 0.28, 0.42)
    arm_r = _box(rng, 2000, 0.46, 0.28, 0.02, 0.10, 0.28, 0.42)
    xyz = np.vstack([seat, back, arm_l, arm_r])
    rgb = _tint(rng, [0.28, 0.34, 0.52], xyz.shape[0])  # slate blue
    return xyz, rgb


def make_table(rng):
    top = _box(rng, 8000, 0, 0.42, 0, 1.0, 0.05, 0.62)
    legs = [
        _cylinder(rng, 1200, sx * 0.44, 0.20, sz * 0.26, 0.035, 0.40)
        for sx in (-1, 1)
        for sz in (-1, 1)
    ]
    xyz = np.vstack([top] + legs)
    rgb = _tint(rng, [0.45, 0.31, 0.19], xyz.shape[0])  # walnut
    return xyz, rgb


def make_lamp(rng):
    shade = _sphere(rng, 6000, 0, 0.38, 0, 0.26)
    stem = _cylinder(rng, 2500, 0, -0.02, 0, 0.025, 0.62)
    base = _cylinder(rng, 1800, 0, -0.36, 0, 0.16, 0.04)
    xyz = np.vstack([shade, stem, base])
    rgb = np.vstack([
        _tint(rng, [0.95, 0.85, 0.55], 6000, 0.04),   # warm glowing shade
        _tint(rng, [0.20, 0.20, 0.22], 2500 + 1800),  # dark metal
    ])
    return xyz, rgb


def make_plant(rng):
    foliage = np.vstack([
        _sphere(rng, 2500, dx, 0.30 + dy, dz, 0.20)
        for dx, dy, dz in [(0, 0.1, 0), (-0.15, 0, 0.1), (0.15, 0, -0.05), (0, -0.05, 0.16)]
    ])
    pot = _cylinder(rng, 2500, 0, -0.32, 0, 0.18, 0.26)
    xyz = np.vstack([foliage, pot])
    rgb = np.vstack([
        _tint(rng, [0.22, 0.48, 0.24], foliage.shape[0]),  # leafy green
        _tint(rng, [0.62, 0.36, 0.24], 2500),              # terracotta
    ])
    return xyz, rgb


SCENE_ID = "11111111-1111-4111-8111-111111111111"  # matches the mock fixture
GS_PREFIX = f"gs://mock-outputs/scenes/{SCENE_ID}/splats"

# World transforms (ARKit frame: +Y up, meters) forming a small living-room
# corner. Kept in sync with web/src/lib/api/mock.ts's READY_ASSETS.
OBJECTS = [
    ("sofa", "depth_fit", True, {"position": [0, 0.35, -1.6],
                                  "rotation_xyzw": [0, 0, 0, 1], "scale": 1.4}),
    ("table", "depth_fit", True, {"position": [0.1, 0.25, -0.4],
                                   "rotation_xyzw": [0, 0.3826834, 0, 0.9238795],
                                   "scale": 0.9}),
    ("lamp", "layout_triangulated", True, {"position": [-1.2, 0.8, -1.2],
                                            "rotation_xyzw": [0, 0, 0, 1], "scale": 0.5}),
    ("plant", None, False, None),  # unplaced: exercises the "not shown" UI
]


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(7)
    makers = {"sofa": make_sofa, "table": make_table, "lamp": make_lamp,
              "plant": make_plant}

    manifest_objects = []
    asset_urls = {}
    for i, (name, method, placed, transform) in enumerate(OBJECTS):
        xyz, rgb = makers[name](rng)
        xyz = _center_and_normalize(xyz)
        path = OUT_DIR / f"{name}.ply"
        write_gaussian_ply(path, xyz, rgb)
        gs_uri = f"{GS_PREFIX}/{name}.ply"
        entry = {
            "object_id": f"obj_{i:03d}",
            "label": name,
            "placed": placed,
            "method": method,
            "splat_gcs_uri": gs_uri,
            "world_transform": transform,
        }
        if not placed:
            entry["reason"] = "insufficient_observations"
        manifest_objects.append(entry)
        if placed:
            asset_urls[gs_uri] = f"/dev-fixtures/{name}.ply"
        print(f"  {path.name}: {xyz.shape[0]} gaussians, {path.stat().st_size / 1e6:.1f} MB")

    assets = {
        "scene_id": SCENE_ID,
        "manifest": {
            "scene_id": SCENE_ID,
            "manifest_version": 2,
            "objects": manifest_objects,
            "frames": [],
        },
        "asset_urls": asset_urls,
        "expires_at": "2099-01-01T00:00:00+00:00",
    }
    (OUT_DIR / "manifest.json").write_text(json.dumps(assets, indent=2))
    print(f"  manifest.json → {OUT_DIR}")


if __name__ == "__main__":
    main()
