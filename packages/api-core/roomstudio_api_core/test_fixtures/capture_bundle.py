"""Synthetic CaptureBundle factory for end-to-end and integration tests.

Produces a TestBundleArtifacts with:
  - A valid serialized CaptureBundle proto (bundle.pb)
  - All referenced blob bytes, keyed by their relative GCS paths

No real photos, no LiDAR hardware. Uses minimal synthetic bytes for blob
content — the ingester checks blob existence, not content. The proto
fields that the ingester validates (schema_version, quaternion norms,
tier-vs-depth consistency, relative GCS paths) are all valid.

Consumed by: tools/upload_test_bundle.py
             (future) service-level integration test suites
"""
from __future__ import annotations

import struct
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# roomstudio_schemas lives at packages/schemas; add to sys.path if not already present.
_repo_root = Path(__file__).resolve().parents[4]
_schemas_dir = str(_repo_root / "packages" / "schemas")
if _schemas_dir not in sys.path:
    sys.path.insert(0, _schemas_dir)

from roomstudio_schemas import (  # noqa: E402
    ARKIT_ONLY,
    LIDAR_ARKIT,
    LIDAR_ROOMPLAN,
    PLANE_HORIZONTAL,
    PLANE_VERTICAL,
    CaptureBundle,
    SCHEMA_VERSION,
)


# ---------------------------------------------------------------------------
# Minimal synthetic blob bytes — content is irrelevant to the ingester.
# ---------------------------------------------------------------------------

# RGB: starts with JFIF magic so it's recognisable as JPEG-like in logs.
_RGB_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9"

# Depth: 16 float32 values for a 4×4 depth map (all 0.5 m).
_DEPTH_BYTES = struct.pack("16f", *([0.5] * 16))

# Confidence: 16 bytes, all 0xFF (max confidence).
_CONFIDENCE_BYTES = b"\xff" * 16

# USDZ: starts with PK (ZIP magic) so it's recognisable.
_USDZ_BYTES = b"PK\x05\x06" + b"\x00" * 18


@dataclass
class TestBundleArtifacts:
    """All artifacts produced by build_capture_bundle.

    blobs: relative_path → bytes, including "bundle.pb".
    The smoke tool iterates blobs (sorted, bundle.pb last) to derive the
    upload_session manifest and to sequence PUT uploads.
    """

    bundle_id: str
    blobs: dict[str, bytes] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Tier constants
# ---------------------------------------------------------------------------

TIER_ARKIT_ONLY = "arkit-only"
TIER_LIDAR_ARKIT = "lidar-arkit"
TIER_LIDAR_ROOMPLAN = "lidar-roomplan"

_TIER_PROTO_VALUE = {
    TIER_ARKIT_ONLY: ARKIT_ONLY,
    TIER_LIDAR_ARKIT: LIDAR_ARKIT,
    TIER_LIDAR_ROOMPLAN: LIDAR_ROOMPLAN,
}


# ---------------------------------------------------------------------------
# Public factory
# ---------------------------------------------------------------------------

def build_capture_bundle(
    *,
    tier: str = TIER_LIDAR_ROOMPLAN,
    frame_count: int = 3,
    bundle_id: Optional[str] = None,
    device_id: str = "test-device-uuid",
    user_id: str = "test-user",
    include_depth: bool = True,
    include_confidence: bool = True,
    include_roomplan: bool = True,
    use_hardware_id_fallback: bool = False,
    plane_anchor_count: int = 0,
) -> TestBundleArtifacts:
    """Build a synthetic CaptureBundle and return all blob bytes.

    Args:
        tier: "arkit-only", "lidar-arkit", or "lidar-roomplan".
        frame_count: number of frames (>= 1).
        bundle_id: use this UUID as the bundle_id; fresh UUIDv4 if None.
        device_id: value for bundle.device.device_id (ignored if
            use_hardware_id_fallback is True).
        user_id: value for bundle.user_id; stored on the Scene for ownership
            checks in GET /scenes/by-bundle.
        include_depth: include depth blobs (only meaningful for lidar tiers).
        include_confidence: include confidence blobs (only meaningful for
            lidar tiers).
        include_roomplan: include USDZ blob (only meaningful for
            lidar-roomplan tier).
        use_hardware_id_fallback: leave device_id empty; set hardware_id
            instead. Tests the FALLBACK_HARDWARE_ID ingester path.
        plane_anchor_count: number of PlaneAnchor entries to add (decision
            0066). 0 (default) mirrors pre-plane clients — the shell's
            "unavailable" degrade path. When > 0, the first anchor is a
            floor-classified horizontal plane and the rest are vertical
            walls, all with valid unit-norm poses.
    """
    if tier not in _TIER_PROTO_VALUE:
        raise ValueError(f"unknown tier {tier!r}; expected one of {list(_TIER_PROTO_VALUE)}")
    if frame_count < 1:
        raise ValueError("frame_count must be >= 1")

    bid = bundle_id or str(uuid.uuid4())
    blobs: dict[str, bytes] = {}

    bundle = CaptureBundle()
    bundle.schema_version = SCHEMA_VERSION
    bundle.bundle_id = bid
    bundle.user_id = user_id
    bundle.tier = _TIER_PROTO_VALUE[tier]

    if use_hardware_id_fallback:
        bundle.device.hardware_id = device_id
        bundle.device.has_lidar = tier != TIER_ARKIT_ONLY
    else:
        bundle.device.device_id = device_id
        bundle.device.has_lidar = tier != TIER_ARKIT_ONLY

    bundle.device.os_version = "test/1.0"
    bundle.device.app_version = "test-fixture"

    now_us = int(time.monotonic_ns() // 1_000)
    bundle.started_at_device_us = now_us
    bundle.started_at_wall_us = int(time.time_ns() // 1_000)

    has_lidar = tier != TIER_ARKIT_ONLY
    add_depth = has_lidar and include_depth
    add_confidence = add_depth and include_confidence
    add_usdz = (tier == TIER_LIDAR_ROOMPLAN) and include_roomplan

    for i in range(frame_count):
        rgb_path = f"frames/{i:06d}.jpg"
        blobs[rgb_path] = _RGB_BYTES

        f = bundle.frames.add()
        f.frame_index = i
        f.timestamp_us = now_us + i * 500_000
        f.rgb_gcs_path = rgb_path

        # Identity quaternion — unit norm, valid for all validation checks.
        f.camera_pose.pos_x = 0.0
        f.camera_pose.pos_y = 0.0
        f.camera_pose.pos_z = float(i)
        f.camera_pose.quat_x = 0.0
        f.camera_pose.quat_y = 0.0
        f.camera_pose.quat_z = 0.0
        f.camera_pose.quat_w = 1.0

        # Gravity in camera frame: world gravity (0,-1,0) in identity pose == (0,-1,0).
        f.gravity.x = 0.0
        f.gravity.y = -1.0
        f.gravity.z = 0.0

        f.intrinsics.fx = 1000.0
        f.intrinsics.fy = 1000.0
        f.intrinsics.cx = 2.0
        f.intrinsics.cy = 2.0
        f.intrinsics.width = 4
        f.intrinsics.height = 4

        if add_depth:
            depth_path = f"depth/{i:06d}.f32"
            blobs[depth_path] = _DEPTH_BYTES
            f.depth.depth_gcs_path = depth_path

            if add_confidence:
                conf_path = f"confidence/{i:06d}.png"
                blobs[conf_path] = _CONFIDENCE_BYTES
                f.depth.confidence_gcs_path = conf_path

    bundle.ended_at_device_us = now_us + frame_count * 500_000

    if add_usdz:
        usdz_path = "roomplan/room.usdz"
        blobs[usdz_path] = _USDZ_BYTES
        bundle.room_plan.usdz_gcs_path = usdz_path

    for j in range(plane_anchor_count):
        a = bundle.plane_anchors.add()
        if j == 0:
            # Floor: anchor +Y (plane normal) already world +Y — identity.
            a.pose.pos_y = -1.4
            a.pose.quat_w = 1.0
            a.alignment = PLANE_HORIZONTAL
            a.classification = "floor"
        else:
            # Wall: +90° about X points anchor +Y (the normal) at world +Z.
            a.pose.pos_x = float(j)
            a.pose.pos_z = -2.0
            a.pose.quat_x = 0.7071067811865476
            a.pose.quat_w = 0.7071067811865476
            a.alignment = PLANE_VERTICAL
            a.classification = "wall"
        a.extent_width = 2.0
        a.extent_height = 2.0

    blobs["bundle.pb"] = bundle.SerializeToString()
    return TestBundleArtifacts(bundle_id=bid, blobs=blobs)
