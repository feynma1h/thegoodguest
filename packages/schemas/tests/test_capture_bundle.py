"""Schema invariants for the capture bundle. These tests pin down the
contract — if any of them break, downstream code on either the iOS or
the backend side will silently misinterpret data, so failures here are
load-bearing.

Run from repo root:

    pytest packages/schemas/tests/

Or just:

    python -m pytest packages/schemas/tests/test_capture_bundle.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make the schemas package importable without installing it.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from roomstudio_schemas import (
    ARKIT_ONLY,
    LIDAR_ARKIT,
    LIDAR_ROOMPLAN,
    SCHEMA_VERSION,
    CaptureBundle,
    CaptureTier,
)


def _minimal_bundle() -> CaptureBundle:
    b = CaptureBundle()
    b.schema_version = SCHEMA_VERSION
    b.bundle_id = "test-bundle"
    b.user_id = "test-user"
    b.tier = ARKIT_ONLY
    b.device.has_lidar = False
    return b


def test_schema_version_is_set():
    """SCHEMA_VERSION must be a non-empty string; checked because a missing
    version is the worst kind of bundle: silently misinterpreted."""
    assert isinstance(SCHEMA_VERSION, str) and SCHEMA_VERSION


def test_tier_enum_values_stable():
    """If the integer values of the tier enum ever change, every bundle in
    GCS becomes silently mislabeled. Pin them."""
    assert CaptureTier.Value("CAPTURE_TIER_UNSPECIFIED") == 0
    assert CaptureTier.Value("ARKIT_ONLY") == 1
    assert CaptureTier.Value("LIDAR_ARKIT") == 2
    assert CaptureTier.Value("LIDAR_ROOMPLAN") == 3


def test_empty_bundle_roundtrips():
    b = _minimal_bundle()
    wire = b.SerializeToString()
    b2 = CaptureBundle()
    b2.ParseFromString(wire)
    assert b2.schema_version == SCHEMA_VERSION
    assert b2.tier == ARKIT_ONLY
    assert len(b2.frames) == 0


def test_frame_optional_depth_absent_by_default():
    """Depth is optional. A freshly-added frame must not claim to have depth."""
    b = _minimal_bundle()
    f = b.frames.add()
    f.frame_index = 0
    f.rgb_gcs_path = "frames/000000.jpg"
    assert not f.HasField("depth")
    # Round-trip preserves absence.
    b2 = CaptureBundle()
    b2.ParseFromString(b.SerializeToString())
    assert not b2.frames[0].HasField("depth")


def test_room_plan_optional_absent_by_default():
    b = _minimal_bundle()
    assert not b.HasField("room_plan")
    b2 = CaptureBundle()
    b2.ParseFromString(b.SerializeToString())
    assert not b2.HasField("room_plan")


def test_pose_position_and_quaternion_roundtrip():
    """The Pose contract: pos (xyz) + unit quaternion (xyzw). Both must
    survive the wire bit-for-bit at float32 precision."""
    b = _minimal_bundle()
    f = b.frames.add()
    f.camera_pose.pos_x = 1.5
    f.camera_pose.pos_y = -2.25
    f.camera_pose.pos_z = 0.125
    # 90-degree rotation about +Y. Unit-norm: 0^2 + 0.7071^2 + 0^2 + 0.7071^2 = 1.0
    f.camera_pose.quat_x = 0.0
    f.camera_pose.quat_y = 0.7071067811865476
    f.camera_pose.quat_z = 0.0
    f.camera_pose.quat_w = 0.7071067811865476

    b2 = CaptureBundle()
    b2.ParseFromString(b.SerializeToString())
    p = b2.frames[0].camera_pose
    # float32 round-trip — exact equality is too tight, so use approximate.
    assert abs(p.pos_x - 1.5) < 1e-6
    assert abs(p.pos_y - (-2.25)) < 1e-6
    assert abs(p.pos_z - 0.125) < 1e-6
    assert abs(p.quat_x - 0.0) < 1e-6
    assert abs(p.quat_y - 0.7071067811865476) < 1e-6
    assert abs(p.quat_z - 0.0) < 1e-6
    assert abs(p.quat_w - 0.7071067811865476) < 1e-6


def test_pose_identity_defaults_are_zero_quat():
    """A freshly-created Pose has all fields zero. That means the default
    quaternion is (0,0,0,0), which is NOT a valid rotation. Writers MUST
    populate quat fields explicitly (typically (0,0,0,1) for identity).
    This test documents the gotcha so it can't surprise anyone later."""
    b = _minimal_bundle()
    f = b.frames.add()
    # No camera_pose assignments — every field defaults to 0.
    p = f.camera_pose
    assert (p.quat_x, p.quat_y, p.quat_z, p.quat_w) == (0.0, 0.0, 0.0, 0.0)
    # Quaternion identity rotation is (0,0,0,1), NOT all zeros. Callers
    # must set it; the proto cannot enforce non-default values.


def test_lidar_tier_with_depth():
    """A LiDAR-tier bundle must be able to attach depth to a frame and
    round-trip cleanly."""
    b = _minimal_bundle()
    b.tier = LIDAR_ARKIT
    b.device.has_lidar = True
    f = b.frames.add()
    f.frame_index = 0
    f.rgb_gcs_path = "frames/000000.jpg"
    f.depth.depth_gcs_path = "depth/000000.f32"
    f.depth.width = 256
    f.depth.height = 192
    f.depth.intrinsics.fx = 200.0
    f.depth.intrinsics.fy = 200.0
    f.depth.intrinsics.cx = 128.0
    f.depth.intrinsics.cy = 96.0
    f.depth.intrinsics.width = 256
    f.depth.intrinsics.height = 192

    b2 = CaptureBundle()
    b2.ParseFromString(b.SerializeToString())
    assert b2.tier == LIDAR_ARKIT
    assert b2.frames[0].HasField("depth")
    assert b2.frames[0].depth.depth_gcs_path == "depth/000000.f32"
    assert not b2.frames[0].depth.HasField("confidence_gcs_path")


def test_room_plan_with_summary():
    b = _minimal_bundle()
    b.tier = LIDAR_ROOMPLAN
    b.device.has_lidar = True
    b.room_plan.usdz_gcs_path = "roomplan/room.usdz"
    b.room_plan.roomplan_version = "iOS17.4-RoomPlan2"
    b.room_plan.summary.wall_count = 4
    b.room_plan.summary.door_count = 1
    b.room_plan.summary.window_count = 2
    o = b.room_plan.summary.objects.add()
    o.category = "sofa"
    o.extent_x, o.extent_y, o.extent_z = 2.0, 0.8, 0.9

    b2 = CaptureBundle()
    b2.ParseFromString(b.SerializeToString())
    assert b2.HasField("room_plan")
    assert b2.room_plan.summary.wall_count == 4
    assert b2.room_plan.summary.objects[0].category == "sofa"


def test_paths_are_relative_not_gs_uris():
    """rgb_gcs_path et al. are documented as paths WITHIN the bundle
    prefix, not full gs:// URIs. The schema can't enforce this, but
    callers should follow it. The orchestrator joins them to
    gs://{bucket}/captures/{bundle_id}/{path}."""
    b = _minimal_bundle()
    f = b.frames.add()
    f.rgb_gcs_path = "frames/000000.jpg"
    # This is the convention; if it ever starts with "gs://" that's a bug
    # in the writer, not the schema.
    assert not f.rgb_gcs_path.startswith("gs://")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
