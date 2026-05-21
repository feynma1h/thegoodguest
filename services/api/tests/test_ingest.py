"""Integration tests for POST /ingest.

Tests are structured around the four validation checks in validation.py,
plus a happy path for each supported tier:
  - valid ARKIT_ONLY bundle → 200 + correct summary
  - valid LIDAR_ARKIT bundle with depth → 200 + correct summary
  - unsupported schema_version → 400 unsupported_schema_version
  - non-unit quaternion → 400 quaternion_norm_out_of_range
  - depth frame on ARKIT_ONLY tier → 400 depth_requires_lidar_tier
  - absolute gs:// path → 400 absolute_gcs_path

The GCS fetch (_fetch_bundle_bytes) is patched out in every test.
Bundles are built in-memory using roomstudio_schemas directly — no file I/O,
no network, no GCS credentials required.

Run from repo root:
  pytest services/api/tests/ -v

Or from services/api/:
  pytest tests/ -v
"""
from __future__ import annotations

import sys
import time
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

# Make services/api/ and packages/schemas importable regardless of where
# pytest is invoked from. Mirrors the sys.path approach used in the schema
# tests (packages/schemas/tests/test_capture_bundle.py).
_api_dir = Path(__file__).resolve().parents[1]
_schemas_dir = _api_dir.parents[1] / "packages/schemas"
for _p in (_api_dir, _schemas_dir):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from roomstudio_schemas import (  # noqa: E402
    ARKIT_ONLY,
    LIDAR_ARKIT,
    SCHEMA_VERSION,
    CaptureBundle,
)

import server  # the service module  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client() -> TestClient:
    """A TestClient for the ingester app. Module-scoped: the app is stateless
    so one client per test module is fine."""
    return TestClient(server.app)


# ---------------------------------------------------------------------------
# Bundle builders
# ---------------------------------------------------------------------------

def _make_bundle(
    *,
    schema_version: str = SCHEMA_VERSION,
    tier=None,
    frame_count: int = 3,
    add_depth: bool = False,
) -> bytes:
    """Build a minimal CaptureBundle that passes all validation checks and
    return its serialized bytes.

    All poses use the identity quaternion (0, 0, 0, 1) — unit norm, valid.
    All GCS paths are relative. Depth is optionally added to every frame.
    The tier defaults to LIDAR_ARKIT when add_depth=True, ARKIT_ONLY otherwise,
    so the default bundle always passes tier-vs-depth consistency. Callers can
    override tier to deliberately create an invalid bundle.
    """
    if tier is None:
        tier = LIDAR_ARKIT if add_depth else ARKIT_ONLY

    b = CaptureBundle()
    b.schema_version = schema_version
    b.bundle_id = str(uuid.uuid4())
    b.user_id = "test-user"
    b.device.hardware_id = "test-device"
    b.device.has_lidar = tier in (LIDAR_ARKIT,)
    b.tier = tier
    now_us = int(time.time() * 1_000_000)
    b.started_at_us = now_us
    b.ended_at_us = now_us + frame_count * 500_000

    for i in range(frame_count):
        f = b.frames.add()
        f.frame_index = i
        f.timestamp_us = now_us + i * 500_000
        f.rgb_gcs_path = f"frames/{i:06d}.jpg"
        # Identity rotation: camera at (i*0.1, 0, 0) looking along -Z.
        f.camera_pose.pos_x = i * 0.1
        f.camera_pose.pos_y = 0.0
        f.camera_pose.pos_z = 0.0
        f.camera_pose.quat_x = 0.0
        f.camera_pose.quat_y = 0.0
        f.camera_pose.quat_z = 0.0
        f.camera_pose.quat_w = 1.0
        f.intrinsics.fx = 800.0
        f.intrinsics.fy = 800.0
        f.intrinsics.cx = 512.0
        f.intrinsics.cy = 384.0
        f.intrinsics.width = 1024
        f.intrinsics.height = 768
        f.gravity.x = 0.0
        f.gravity.y = -1.0
        f.gravity.z = 0.0
        if add_depth:
            f.depth.depth_gcs_path = f"depth/{i:06d}.f32"
            f.depth.width = 256
            f.depth.height = 192
            f.depth.intrinsics.fx = 200.0
            f.depth.intrinsics.fy = 200.0
            f.depth.intrinsics.cx = 128.0
            f.depth.intrinsics.cy = 96.0
            f.depth.intrinsics.width = 256
            f.depth.intrinsics.height = 192

    return b.SerializeToString()


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------

def test_valid_arkit_bundle_returns_200(client: TestClient) -> None:
    """Well-formed ARKIT_ONLY bundle → 200 with correct summary fields."""
    bundle_bytes = _make_bundle(frame_count=3)
    with patch.object(server, "_fetch_bundle_bytes", return_value=bundle_bytes):
        resp = client.post(
            "/ingest",
            json={"bundle_gcs_uri": "gs://test-bucket/captures/test/bundle.pb"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["schema_version"] == SCHEMA_VERSION
    assert body["tier"] == "ARKIT_ONLY"
    assert body["tier_value"] == 1  # CaptureTier.ARKIT_ONLY — pinned per enum stability test
    assert body["frame_count"] == 3
    assert body["depth_frame_count"] == 0
    assert body["has_room_plan"] is False
    assert body["user_id"] == "test-user"


def test_valid_lidar_bundle_returns_200(client: TestClient) -> None:
    """Well-formed LIDAR_ARKIT bundle with depth on every frame → 200."""
    bundle_bytes = _make_bundle(frame_count=2, add_depth=True)
    with patch.object(server, "_fetch_bundle_bytes", return_value=bundle_bytes):
        resp = client.post(
            "/ingest",
            json={"bundle_gcs_uri": "gs://test-bucket/captures/test/bundle.pb"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["tier"] == "LIDAR_ARKIT"
    assert body["depth_frame_count"] == 2


# ---------------------------------------------------------------------------
# Validation failures
# ---------------------------------------------------------------------------

def test_unsupported_schema_version_returns_400(client: TestClient) -> None:
    """Bundle with an unrecognized schema_version → 400 unsupported_schema_version."""
    bundle_bytes = _make_bundle(schema_version="99.0.0")
    with patch.object(server, "_fetch_bundle_bytes", return_value=bundle_bytes):
        resp = client.post(
            "/ingest",
            json={"bundle_gcs_uri": "gs://test-bucket/captures/test/bundle.pb"},
        )
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"] == "unsupported_schema_version"
    assert "99.0.0" in body["detail"]


def test_corrupt_quaternion_returns_400(client: TestClient) -> None:
    """Bundle with a non-unit quaternion → 400 quaternion_norm_out_of_range.

    Sets quat = (1, 1, 0, 0), norm = sqrt(2) ≈ 1.414, which exceeds the
    1e-3 tolerance around 1.0.
    """
    b = CaptureBundle()
    b.schema_version = SCHEMA_VERSION
    b.bundle_id = str(uuid.uuid4())
    b.user_id = "test-user"
    b.tier = ARKIT_ONLY
    b.started_at_us = 0
    b.ended_at_us = 1
    f = b.frames.add()
    f.frame_index = 0
    f.rgb_gcs_path = "frames/000000.jpg"
    f.camera_pose.quat_x = 1.0  # norm = sqrt(2) — deliberately non-unit
    f.camera_pose.quat_y = 1.0
    f.camera_pose.quat_z = 0.0
    f.camera_pose.quat_w = 0.0

    with patch.object(server, "_fetch_bundle_bytes", return_value=b.SerializeToString()):
        resp = client.post(
            "/ingest",
            json={"bundle_gcs_uri": "gs://test-bucket/captures/test/bundle.pb"},
        )
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"] == "quaternion_norm_out_of_range"
    assert "frame 0" in body["detail"]


def test_depth_on_arkit_only_tier_returns_400(client: TestClient) -> None:
    """Bundle with depth frames but ARKIT_ONLY tier → 400 depth_requires_lidar_tier.

    Uses _make_bundle with add_depth=True but forces tier=ARKIT_ONLY to
    trigger the tier-vs-depth consistency check.
    """
    bundle_bytes = _make_bundle(frame_count=1, add_depth=True, tier=ARKIT_ONLY)
    with patch.object(server, "_fetch_bundle_bytes", return_value=bundle_bytes):
        resp = client.post(
            "/ingest",
            json={"bundle_gcs_uri": "gs://test-bucket/captures/test/bundle.pb"},
        )
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"] == "depth_requires_lidar_tier"
    assert "ARKIT_ONLY" in body["detail"]


def test_malformed_proto_returns_400(client: TestClient) -> None:
    """Garbage bytes that cannot be parsed as a proto → 400 bundle_parse_failed."""
    with patch.object(
        server, "_fetch_bundle_bytes", return_value=b"\xff\xff\xff\xff garbage"
    ):
        resp = client.post(
            "/ingest",
            json={"bundle_gcs_uri": "gs://test-bucket/captures/test/bundle.pb"},
        )
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"] == "bundle_parse_failed"


def test_absolute_rgb_path_returns_400(client: TestClient) -> None:
    """Bundle with a full gs:// URI in rgb_gcs_path → 400 absolute_gcs_path."""
    b = CaptureBundle()
    b.schema_version = SCHEMA_VERSION
    b.bundle_id = str(uuid.uuid4())
    b.user_id = "test-user"
    b.tier = ARKIT_ONLY
    b.started_at_us = 0
    b.ended_at_us = 1
    f = b.frames.add()
    f.frame_index = 0
    f.rgb_gcs_path = "gs://my-bucket/captures/abc/frames/000000.jpg"  # wrong
    f.camera_pose.quat_w = 1.0  # unit norm — passes the quat check

    with patch.object(server, "_fetch_bundle_bytes", return_value=b.SerializeToString()):
        resp = client.post(
            "/ingest",
            json={"bundle_gcs_uri": "gs://test-bucket/captures/test/bundle.pb"},
        )
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"] == "absolute_gcs_path"
    assert "rgb_gcs_path" in body["detail"]
