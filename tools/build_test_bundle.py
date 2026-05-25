"""Build a synthetic CaptureBundle from `test_data/photos/` for backend
integration testing, WITHOUT needing the iOS app yet.

What's real and what's faked here:
  - RGB frames: real (the existing HEIC photos, converted to JPEG).
  - Camera poses: FAKED. We synthesize a plausible "walking around the
    room" trajectory: poses arranged on an arc around the scene origin,
    all looking inward and roughly level. The backend can consume these
    as if they came from ARKit; downstream perception will treat them as
    ARKit's gravity-aligned world frame.
  - Intrinsics: FAKED. iPhone main camera at 1024px max edge → fx=fy ~
    matching the photo's longest dimension. Good enough for shape; not
    metrically calibrated.
  - Gravity: FAKED. Hard-coded as "down is -Y in world" projected into
    each camera's local frame using the synthetic pose.
  - Depth: NOT included. Tier is ARKIT_ONLY for this test (the existing
    test photos have no LiDAR depth attached).
  - RoomPlan: NOT included.

Output:
  outputs/test_bundle/bundle.pb        — serialized CaptureBundle
  outputs/test_bundle/frames/NNN.jpg   — one JPEG per input photo
  outputs/test_bundle/manifest.txt     — human-readable summary

Run from the repo root:

    python tools/build_test_bundle.py

This is the input format the perception orchestrator will eventually
consume; building it by hand here lets us shake out the bundle-ingestion
code path before any iOS work.
"""
from __future__ import annotations

import io
import math
import sys
import time
import uuid
from pathlib import Path

import numpy as np
from PIL import Image

try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:
    pass

# Make the schemas package importable without installing it. In production
# this is `pip install -e packages/schemas`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "packages/schemas"))
from roomstudio_schemas import (  # noqa: E402
    ARKIT_ONLY,
    CaptureBundle,
    SCHEMA_VERSION,
)
from roomstudio_schemas.pose_math import (  # noqa: E402
    conjugate_quat,
    rotate_vec_by_quat,
    rotmat_to_quat,
)


PHOTOS_DIR = Path("test_data/photos")
OUT_DIR = Path("outputs/test_bundle")
MAX_EDGE_PX = 1024


def load_as_jpeg(path: Path) -> tuple[bytes, int, int]:
    """Return (jpeg bytes, width, height) downscaled to MAX_EDGE_PX longest edge."""
    img = Image.open(path).convert("RGB")
    w, h = img.size
    scale = MAX_EDGE_PX / max(w, h)
    if scale < 1.0:
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return buf.getvalue(), img.size[0], img.size[1]


def synthesize_pose(
    i: int, n: int
) -> tuple[np.ndarray, tuple[float, float, float, float]]:
    """A pose on a horizontal arc looking inward. Returns
    (position, quat_xyzw) in ARKit conventions (+Y up, camera looks down
    -Z in local frame).

    The rotation is computed internally as a 3x3 basis (right, up, -forward)
    and converted to a unit quaternion before return — matching what the
    iOS client will do when ARKit hands it `simd_float4x4` and it calls
    `simd_quatf(matrix)`. The bundle never carries the matrix; it carries
    only the quaternion.

    The arc spans 120 degrees, radius 2.5 m, camera height 1.4 m. With n=9
    that gives ~15-degree steps — coarser than a real ARKit capture but enough
    to exercise the contract.
    """
    # Spread across a 120-degree arc, centered at angle 0.
    angle_deg = -60.0 + 120.0 * (i / max(n - 1, 1))
    a = math.radians(angle_deg)
    radius = 2.5
    height = 1.4
    cam_x = radius * math.sin(a)
    cam_y = height
    cam_z = radius * math.cos(a)
    pos = np.array([cam_x, cam_y, cam_z], dtype=np.float64)

    # Look toward (0, height, 0). ARKit camera looks down its own -Z, so the
    # camera's -Z in world is (target - pos) normalized.
    target = np.array([0.0, height, 0.0])
    forward = target - pos
    forward = forward / (np.linalg.norm(forward) + 1e-12)
    world_up = np.array([0.0, 1.0, 0.0])
    right = np.cross(forward, world_up)
    right = right / (np.linalg.norm(right) + 1e-12)
    up = np.cross(right, forward)

    # Camera basis in world: +X_cam = right, +Y_cam = up, +Z_cam = -forward.
    R = np.column_stack([right, up, -forward])  # 3x3, world_from_camera rotation
    quat = rotmat_to_quat(R)
    return pos, quat


def gravity_in_camera_frame(
    quat_xyzw: tuple[float, float, float, float],
) -> tuple[float, float, float]:
    """World gravity is (0, -1, 0). Express it in camera-local coordinates.

    The pose quaternion rotates camera-local vectors INTO world coordinates,
    so the inverse rotation (the conjugate, for unit quaternions) takes
    world vectors into camera-local.

    This is the path the iOS app follows: it has the quaternion from
    ARKit and never materializes the rotation matrix.
    """
    return rotate_vec_by_quat((0.0, -1.0, 0.0), conjugate_quat(quat_xyzw))


def main() -> None:
    if not PHOTOS_DIR.exists():
        print(f"ERROR: {PHOTOS_DIR} not found. Run from repo root.")
        sys.exit(1)
    photos = sorted(
        p for p in PHOTOS_DIR.iterdir()
        if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".heic", ".heif")
    )
    if not photos:
        print(f"ERROR: no photos in {PHOTOS_DIR}")
        sys.exit(1)
    n = len(photos)

    (OUT_DIR / "frames").mkdir(parents=True, exist_ok=True)

    bundle = CaptureBundle()
    bundle.schema_version = SCHEMA_VERSION
    bundle.bundle_id = str(uuid.uuid4())
    bundle.user_id = "synthetic:test_data_room1"
    bundle.device.hardware_id = "synthetic"
    bundle.device.os_version = "n/a"
    bundle.device.app_version = "build_test_bundle.py"
    bundle.device.has_lidar = False
    bundle.tier = ARKIT_ONLY
    now_device_us = int(time.monotonic_ns() // 1_000)
    now_wall_us = int(time.time_ns() // 1_000)
    bundle.started_at_device_us = now_device_us
    bundle.started_at_wall_us = now_wall_us

    print(f"Building bundle from {n} photos in {PHOTOS_DIR}/")
    print(f"  bundle_id: {bundle.bundle_id}")

    # All frames share intrinsics in this synthesis: photos were downscaled
    # to the same longest edge.
    sample_jpeg, w, h = load_as_jpeg(photos[0])
    fx = fy = float(max(w, h))   # ~unity focal length in pixel units; not metric
    cx = w / 2.0
    cy = h / 2.0
    print(f"  frame size: {w}x{h}, fx=fy={fx:.1f}, cx={cx:.1f}, cy={cy:.1f}")

    for i, p in enumerate(photos):
        if i == 0:
            jpeg_bytes = sample_jpeg
            fw, fh = w, h
        else:
            jpeg_bytes, fw, fh = load_as_jpeg(p)

        rel_path = f"frames/{i:06d}.jpg"
        (OUT_DIR / rel_path).write_bytes(jpeg_bytes)

        pos, quat = synthesize_pose(i, n)
        gx, gy, gz = gravity_in_camera_frame(quat)

        f = bundle.frames.add()
        f.frame_index = i
        # 500 ms between frames in the synthetic timeline.
        f.timestamp_us = now_device_us + i * 500_000
        f.rgb_gcs_path = rel_path
        f.camera_pose.pos_x = float(pos[0])
        f.camera_pose.pos_y = float(pos[1])
        f.camera_pose.pos_z = float(pos[2])
        f.camera_pose.quat_x = quat[0]
        f.camera_pose.quat_y = quat[1]
        f.camera_pose.quat_z = quat[2]
        f.camera_pose.quat_w = quat[3]
        f.intrinsics.fx = fx
        f.intrinsics.fy = fy
        f.intrinsics.cx = cx
        f.intrinsics.cy = cy
        f.intrinsics.width = fw
        f.intrinsics.height = fh
        f.gravity.x = gx
        f.gravity.y = gy
        f.gravity.z = gz

    bundle.ended_at_device_us = now_device_us + n * 500_000

    wire = bundle.SerializeToString()
    (OUT_DIR / "bundle.pb").write_bytes(wire)

    summary = [
        f"schema_version: {bundle.schema_version}",
        f"bundle_id:      {bundle.bundle_id}",
        f"user_id:        {bundle.user_id}",
        f"tier:           ARKIT_ONLY",
        f"frames:         {len(bundle.frames)}",
        f"frame size:     {w}x{h}",
        f"intrinsics:     fx={fx:.1f} fy={fy:.1f} cx={cx:.1f} cy={cy:.1f}",
        f"bundle.pb:      {len(wire)} bytes",
    ]
    (OUT_DIR / "manifest.txt").write_text("\n".join(summary) + "\n")

    print("Done.")
    for line in summary:
        print(f"  {line}")
    print(f"  out:            {OUT_DIR}/")


if __name__ == "__main__":
    main()
