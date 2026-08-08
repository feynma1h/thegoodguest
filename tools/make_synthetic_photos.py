"""Render the synthetic room photographs that `tools/build_test_bundle.py`
consumes, replacing the nine real HEICs that used to live in
`test_data/photos/`.

WHY THESE EXIST: the originals were nine photographs of a real bedroom,
committed in the repo's first commit and carried in every tree since. They
also carried GPS EXIF pinning a precise home location. That is not something
to hand to a git remote, so they were purged from history (decision 0101) and
these took their place.

WHY THEY ARE BETTER THAN WHAT THEY REPLACE, not merely safer: the originals
were photographs of one room paired with a completely unrelated synthetic
camera trajectory — `build_test_bundle.synthesize_pose` invents an arc and the
photos knew nothing about it, so the bundle's images and poses described
different worlds. These views are RENDERED FROM THOSE EXACT POSES, through the
exact intrinsics the bundle records (`fx = fy = max(w, h)`, principal point at
centre, no resize because the render is already at MAX_EDGE_PX). The fixture is
now internally consistent: frame i really is what a camera at pose i would see.

WHAT THIS IS NOT: a perception-quality fixture. Flat-shaded boxes with no real
texture will not exercise SAM 3, and they are not meant to. The tool they feed
is a contract smoke test — does a bundle assemble, serialize, upload, and
survive ingest validation — and for that the images need to be decodable,
plausibly sized, and distinct from one another. Real-room regression fixtures
live in `outputs/real-capture-*/`, gitignored and never committed.

Deterministic: same inputs, byte-identical outputs, so regenerating never
produces a spurious diff.

Run from the repo root:

    python tools/make_synthetic_photos.py

Writes nine JPEGs into `test_data/photos/`. They are committed, so this only
needs running if you want to change the scene.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_test_bundle import synthesize_pose  # noqa: E402  (pose source of truth)

OUT_DIR = Path("test_data/photos")
N_VIEWS = 9
# Match build_test_bundle's MAX_EDGE_PX so no resize happens and the recorded
# intrinsics describe this render exactly.
WIDTH, HEIGHT = 1024, 768
FX = FY = float(max(WIDTH, HEIGHT))
CX, CY = WIDTH / 2.0, HEIGHT / 2.0

# A room large enough that the radius-2.5 m camera arc stays inside it.
ROOM_X, ROOM_Z, ROOM_Y = 3.5, 3.5, 2.5
LIGHT = np.array([0.35, 0.85, 0.4])
LIGHT = LIGHT / np.linalg.norm(LIGHT)


def _quad(pts: list[tuple[float, float, float]], color: tuple[int, int, int]):
    return {"pts": np.array(pts, dtype=float), "color": color}


def _box(cx: float, cy: float, cz: float, sx: float, sy: float, sz: float, color):
    """Axis-aligned box as six quads; cy is the CENTRE height."""
    x0, x1 = cx - sx / 2, cx + sx / 2
    y0, y1 = cy - sy / 2, cy + sy / 2
    z0, z1 = cz - sz / 2, cz + sz / 2
    return [
        _quad([(x0, y1, z0), (x1, y1, z0), (x1, y1, z1), (x0, y1, z1)], color),  # top
        _quad([(x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)], color),  # bottom
        _quad([(x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)], color),  # +Z
        _quad([(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0)], color),  # -Z
        _quad([(x0, y0, z0), (x0, y0, z1), (x0, y1, z1), (x0, y1, z0)], color),  # -X
        _quad([(x1, y0, z0), (x1, y0, z1), (x1, y1, z1), (x1, y1, z0)], color),  # +X
    ]


def build_scene() -> list[dict]:
    """A plain bedroom: shell, then furniture the arc can actually see."""
    faces: list[dict] = []
    # Shell. Only the far walls matter for a camera looking inward.
    faces.append(_quad(
        [(-ROOM_X, 0, -ROOM_Z), (ROOM_X, 0, -ROOM_Z), (ROOM_X, 0, ROOM_Z), (-ROOM_X, 0, ROOM_Z)],
        (150, 140, 126)))  # floor
    faces.append(_quad(
        [(-ROOM_X, ROOM_Y, -ROOM_Z), (ROOM_X, ROOM_Y, -ROOM_Z),
         (ROOM_X, ROOM_Y, ROOM_Z), (-ROOM_X, ROOM_Y, ROOM_Z)], (238, 236, 231)))  # ceiling
    for x in (-ROOM_X, ROOM_X):
        faces.append(_quad(
            [(x, 0, -ROOM_Z), (x, 0, ROOM_Z), (x, ROOM_Y, ROOM_Z), (x, ROOM_Y, -ROOM_Z)],
            (206, 201, 190)))
    for z in (-ROOM_Z, ROOM_Z):
        faces.append(_quad(
            [(-ROOM_X, 0, z), (ROOM_X, 0, z), (ROOM_X, ROOM_Y, z), (-ROOM_X, ROOM_Y, z)],
            (214, 209, 198)))

    # Furniture, all behind the origin so the -60..+60 degree arc sees it.
    faces += _box(-1.2, 0.28, -1.6, 2.0, 0.55, 1.5, (128, 106, 92))    # bed
    faces += _box(-1.2, 0.62, -2.2, 1.9, 0.15, 0.35, (196, 190, 178))  # pillow row
    faces += _box(2.4, 1.05, -2.2, 0.65, 2.1, 1.3, (108, 92, 78))      # wardrobe
    faces += _box(1.0, 0.36, -0.6, 1.1, 0.72, 0.65, (146, 122, 96))    # table
    faces += _box(1.0, 0.86, -0.6, 0.18, 0.28, 0.18, (222, 198, 140))  # lamp on table
    faces += _box(-2.6, 0.45, 0.4, 0.7, 0.9, 0.7, (120, 118, 124))     # chair-ish block

    # Flat details: a rug on the floor and artwork on the far wall. Lifted a
    # hair off their surfaces so painter's-algorithm ties never flicker.
    faces.append(_quad([(-0.4, 0.004, -0.9), (2.2, 0.004, -0.9),
                        (2.2, 0.004, 1.1), (-0.4, 0.004, 1.1)], (166, 128, 112)))
    faces.append(_quad([(-0.6, 1.35, -ROOM_Z + 0.004), (0.7, 1.35, -ROOM_Z + 0.004),
                        (0.7, 2.05, -ROOM_Z + 0.004), (-0.6, 2.05, -ROOM_Z + 0.004)],
                       (92, 104, 116)))
    return faces


def face_normal(pts: np.ndarray) -> np.ndarray:
    n = np.cross(pts[1] - pts[0], pts[2] - pts[0])
    norm = np.linalg.norm(n)
    return n / norm if norm > 1e-9 else np.array([0.0, 1.0, 0.0])


def render(view: int, pos: np.ndarray, quat: tuple[float, float, float, float]) -> Image.Image:
    """Project and rasterize the scene from one camera pose.

    Pose semantics are the bundle's: `quat` rotates camera-local vectors into
    world, so world->camera is its inverse, and the camera looks down its own
    -Z (capture_bundle.proto's Pose docstring).
    """
    x, y, z, w = quat
    # Rotation matrix (world_from_camera) from the unit quaternion.
    r_wc = np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])
    r_cw = r_wc.T  # world -> camera

    img = Image.new("RGB", (WIDTH, HEIGHT), (176, 172, 164))
    draw = ImageDraw.Draw(img)

    drawable = []
    for face in build_scene():
        cam = (face["pts"] - pos) @ r_cw.T
        depth = -cam[:, 2]  # camera looks down -Z
        if np.any(depth <= 0.05):
            continue  # any corner behind or at the camera: skip (no clipping)
        u = CX + FX * cam[:, 0] / depth
        v = CY - FY * cam[:, 1] / depth
        # Backface + Lambert shading in world space.
        n = face_normal(face["pts"])
        if np.dot(n, pos - face["pts"].mean(axis=0)) < 0:
            n = -n
        shade = 0.55 + 0.45 * max(0.0, float(np.dot(n, LIGHT)))
        color = tuple(int(min(255, c * shade)) for c in face["color"])
        drawable.append((float(depth.mean()), list(zip(u, v, strict=True)), color))

    for _, poly, color in sorted(drawable, key=lambda t: -t[0]):  # painter's algorithm
        draw.polygon(poly, fill=color)

    # Deterministic sensor-ish grain, so the frames are not flat colour fields.
    rng = np.random.default_rng(1000 + view)
    arr = np.asarray(img).astype(np.int16)
    arr += rng.integers(-6, 7, arr.shape, dtype=np.int16)
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for i in range(N_VIEWS):
        pos, quat = synthesize_pose(i, N_VIEWS)
        img = render(i, pos, quat)
        out = OUT_DIR / f"room_{i:02d}.jpg"
        img.save(out, "JPEG", quality=88, optimize=True)
        angle = -60.0 + 120.0 * (i / max(N_VIEWS - 1, 1))
        print(f"  {out}  {img.size[0]}x{img.size[1]}  "
              f"arc {angle:+.1f}deg  cam=({pos[0]:+.2f},{pos[1]:.2f},{pos[2]:+.2f})")
    print(f"\n{N_VIEWS} synthetic views written to {OUT_DIR}/")
    print("Consumed by: python tools/build_test_bundle.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
