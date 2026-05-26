"""Tests for roomstudio_api_core.test_fixtures.capture_bundle.

Pins the invariants of build_capture_bundle — the blob set, the proto
structure, and the validation contract — so that smoke-tool changes
and future callers can rely on a stable fixture.

Run from repo root:
    python3 -m pytest packages/api-core/tests/test_capture_bundle_fixture.py
"""
from __future__ import annotations

import sys
from pathlib import Path

_repo_root = Path(__file__).resolve().parents[3]
for _pkg in ("packages/api-core", "packages/schemas"):
    _p = str(_repo_root / _pkg)
    if _p not in sys.path:
        sys.path.insert(0, _p)

from roomstudio_api_core.test_fixtures.capture_bundle import (
    TestBundleArtifacts,
    build_capture_bundle,
    TIER_ARKIT_ONLY,
    TIER_LIDAR_ARKIT,
    TIER_LIDAR_ROOMPLAN,
)

# Import the ingester's validation to check fixture-generated bundles pass.
_ingest_dir = str(_repo_root / "services" / "api-internal")
if _ingest_dir not in sys.path:
    sys.path.insert(0, _ingest_dir)

from validation import validate_bundle  # noqa: E402

import pytest


# ---------------------------------------------------------------------------
# TestBundleArtifacts structure
# ---------------------------------------------------------------------------

class TestArtifactsStructure:
    def test_returns_testbundleartifacts(self):
        arts = build_capture_bundle(tier=TIER_ARKIT_ONLY, frame_count=1)
        assert isinstance(arts, TestBundleArtifacts)

    def test_bundle_id_is_uuidv4(self):
        import uuid
        arts = build_capture_bundle(tier=TIER_ARKIT_ONLY, frame_count=1)
        val = uuid.UUID(arts.bundle_id, version=4)
        assert str(val) == arts.bundle_id

    def test_explicit_bundle_id_is_preserved(self):
        bid = "12345678-1234-4234-8234-123456789abc"
        arts = build_capture_bundle(tier=TIER_ARKIT_ONLY, frame_count=1, bundle_id=bid)
        assert arts.bundle_id == bid

    def test_blobs_contains_bundle_pb(self):
        arts = build_capture_bundle(tier=TIER_ARKIT_ONLY, frame_count=1)
        assert "bundle.pb" in arts.blobs

    def test_blob_values_are_nonempty_bytes(self):
        arts = build_capture_bundle(tier=TIER_LIDAR_ROOMPLAN, frame_count=2)
        for path, blob_bytes in arts.blobs.items():
            assert isinstance(blob_bytes, bytes), f"{path} is not bytes"
            assert len(blob_bytes) > 0, f"{path} is empty"


# ---------------------------------------------------------------------------
# Blob set per tier
# ---------------------------------------------------------------------------

class TestArtikitOnlyBlobs:
    def test_has_rgb_blobs_only(self):
        arts = build_capture_bundle(tier=TIER_ARKIT_ONLY, frame_count=3)
        paths = set(arts.blobs) - {"bundle.pb"}
        assert paths == {"frames/000000.jpg", "frames/000001.jpg", "frames/000002.jpg"}

    def test_no_depth_blobs(self):
        arts = build_capture_bundle(tier=TIER_ARKIT_ONLY, frame_count=2)
        assert not any("depth" in p for p in arts.blobs)

    def test_no_usdz_blob(self):
        arts = build_capture_bundle(tier=TIER_ARKIT_ONLY, frame_count=2)
        assert "roomplan/room.usdz" not in arts.blobs


class TestLidarArkitBlobs:
    def test_has_rgb_and_depth(self):
        arts = build_capture_bundle(tier=TIER_LIDAR_ARKIT, frame_count=2)
        assert "frames/000000.jpg" in arts.blobs
        assert "depth/000000.f32" in arts.blobs

    def test_has_confidence_by_default(self):
        arts = build_capture_bundle(tier=TIER_LIDAR_ARKIT, frame_count=2)
        assert "confidence/000000.png" in arts.blobs

    def test_no_confidence_when_disabled(self):
        arts = build_capture_bundle(
            tier=TIER_LIDAR_ARKIT, frame_count=2, include_confidence=False
        )
        assert not any("confidence" in p for p in arts.blobs)

    def test_no_usdz_blob(self):
        arts = build_capture_bundle(tier=TIER_LIDAR_ARKIT, frame_count=2)
        assert "roomplan/room.usdz" not in arts.blobs


class TestLidarRoomplanBlobs:
    def test_has_all_four_kinds(self):
        arts = build_capture_bundle(tier=TIER_LIDAR_ROOMPLAN, frame_count=1)
        assert "frames/000000.jpg" in arts.blobs
        assert "depth/000000.f32" in arts.blobs
        assert "confidence/000000.png" in arts.blobs
        assert "roomplan/room.usdz" in arts.blobs

    def test_no_usdz_when_roomplan_disabled(self):
        arts = build_capture_bundle(
            tier=TIER_LIDAR_ROOMPLAN, frame_count=1, include_roomplan=False
        )
        assert "roomplan/room.usdz" not in arts.blobs

    def test_frame_count_scales_all_per_frame_blobs(self):
        arts = build_capture_bundle(tier=TIER_LIDAR_ROOMPLAN, frame_count=4)
        rgb_paths = [p for p in arts.blobs if p.startswith("frames/")]
        depth_paths = [p for p in arts.blobs if p.startswith("depth/")]
        conf_paths = [p for p in arts.blobs if p.startswith("confidence/")]
        assert len(rgb_paths) == 4
        assert len(depth_paths) == 4
        assert len(conf_paths) == 4


# ---------------------------------------------------------------------------
# Proto validity — bundle.pb deserializes and passes ingester validation
# ---------------------------------------------------------------------------

class TestBundlePbValidity:
    def test_bundle_pb_deserializes(self):
        from roomstudio_schemas import CaptureBundle
        arts = build_capture_bundle(tier=TIER_LIDAR_ROOMPLAN, frame_count=2)
        b = CaptureBundle()
        b.ParseFromString(arts.blobs["bundle.pb"])
        assert b.bundle_id == arts.bundle_id

    def test_arkit_only_passes_validation(self):
        from roomstudio_schemas import CaptureBundle
        arts = build_capture_bundle(tier=TIER_ARKIT_ONLY, frame_count=2)
        b = CaptureBundle()
        b.ParseFromString(arts.blobs["bundle.pb"])
        assert validate_bundle(b) is None

    def test_lidar_arkit_passes_validation(self):
        from roomstudio_schemas import CaptureBundle
        arts = build_capture_bundle(tier=TIER_LIDAR_ARKIT, frame_count=2)
        b = CaptureBundle()
        b.ParseFromString(arts.blobs["bundle.pb"])
        assert validate_bundle(b) is None

    def test_lidar_roomplan_passes_validation(self):
        from roomstudio_schemas import CaptureBundle
        arts = build_capture_bundle(tier=TIER_LIDAR_ROOMPLAN, frame_count=2)
        b = CaptureBundle()
        b.ParseFromString(arts.blobs["bundle.pb"])
        assert validate_bundle(b) is None

    def test_all_bundle_paths_are_in_blobs(self):
        """Every path referenced in the proto must have a corresponding blob entry."""
        from roomstudio_schemas import CaptureBundle
        arts = build_capture_bundle(tier=TIER_LIDAR_ROOMPLAN, frame_count=2)
        b = CaptureBundle()
        b.ParseFromString(arts.blobs["bundle.pb"])

        referenced: list[str] = []
        for frame in b.frames:
            if frame.rgb_gcs_path:
                referenced.append(frame.rgb_gcs_path)
            if frame.HasField("depth"):
                if frame.depth.depth_gcs_path:
                    referenced.append(frame.depth.depth_gcs_path)
                if frame.depth.HasField("confidence_gcs_path"):
                    referenced.append(frame.depth.confidence_gcs_path)
        if b.HasField("room_plan") and b.room_plan.usdz_gcs_path:
            referenced.append(b.room_plan.usdz_gcs_path)

        for path in referenced:
            assert path in arts.blobs, f"Proto references {path!r} but it is not in blobs"

    def test_hardware_id_fallback(self):
        from roomstudio_schemas import CaptureBundle
        arts = build_capture_bundle(
            tier=TIER_ARKIT_ONLY, frame_count=1,
            device_id="hw-id-123",
            use_hardware_id_fallback=True,
        )
        b = CaptureBundle()
        b.ParseFromString(arts.blobs["bundle.pb"])
        assert b.device.hardware_id == "hw-id-123"
        assert b.device.device_id == ""

    def test_user_id_round_trips(self):
        from roomstudio_schemas import CaptureBundle
        arts = build_capture_bundle(
            tier=TIER_ARKIT_ONLY, frame_count=1, user_id="firebase-uid-xyz"
        )
        b = CaptureBundle()
        b.ParseFromString(arts.blobs["bundle.pb"])
        assert b.user_id == "firebase-uid-xyz"
