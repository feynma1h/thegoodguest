"""Tests for roomstudio_api_core.test_fixtures.capture_bundle.

Pins the invariants of build_capture_bundle — the blob set, the proto
structure, and the validation contract — so that smoke-tool changes
and future callers can rely on a stable fixture.

Run from repo root:
    python3 -m pytest packages/api-core/tests/test_capture_bundle_fixture.py
"""
from __future__ import annotations

from roomstudio_api_core.test_fixtures.capture_bundle import (
    TestBundleArtifacts,
    build_capture_bundle,
    TIER_ARKIT_ONLY,
    TIER_LIDAR_ARKIT,
    TIER_LIDAR_ROOMPLAN,
)
from validation import validate_bundle

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
    def test_has_all_blob_kinds(self):
        arts = build_capture_bundle(tier=TIER_LIDAR_ROOMPLAN, frame_count=1)
        assert "frames/000000.jpg" in arts.blobs
        assert "depth/000000.f32" in arts.blobs
        assert "confidence/000000.png" in arts.blobs
        assert "roomplan/room.usdz" in arts.blobs
        assert "roomplan/room.json" in arts.blobs

    def test_no_roomplan_blobs_when_roomplan_disabled(self):
        arts = build_capture_bundle(
            tier=TIER_LIDAR_ROOMPLAN, frame_count=1, include_roomplan=False
        )
        assert "roomplan/room.usdz" not in arts.blobs
        assert "roomplan/room.json" not in arts.blobs

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
        if b.HasField("room_plan"):
            if b.room_plan.usdz_gcs_path:
                referenced.append(b.room_plan.usdz_gcs_path)
            if b.room_plan.json_gcs_path:
                referenced.append(b.room_plan.json_gcs_path)

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


# ---------------------------------------------------------------------------
# Plane anchors (decision 0066)
# ---------------------------------------------------------------------------

class TestPlaneAnchors:
    def test_default_has_no_plane_anchors(self):
        """The default mirrors pre-plane clients — the shell's honest
        'unavailable' degrade path starts from an empty list."""
        from roomstudio_schemas import CaptureBundle
        arts = build_capture_bundle(tier=TIER_ARKIT_ONLY, frame_count=1)
        b = CaptureBundle()
        b.ParseFromString(arts.blobs["bundle.pb"])
        assert len(b.plane_anchors) == 0

    def test_plane_anchors_are_valid_and_pass_validation(self):
        """A plane-carrying bundle: first anchor floor/horizontal, rest
        wall/vertical, all unit-norm poses — and the ingest validator
        accepts it unchanged (the additive-field contract, exercised
        through the real validate_bundle)."""
        import math

        from roomstudio_schemas import (
            PLANE_HORIZONTAL,
            PLANE_VERTICAL,
            CaptureBundle,
        )

        arts = build_capture_bundle(
            tier=TIER_ARKIT_ONLY, frame_count=1, plane_anchor_count=3
        )
        b = CaptureBundle()
        b.ParseFromString(arts.blobs["bundle.pb"])
        assert len(b.plane_anchors) == 3
        assert b.plane_anchors[0].alignment == PLANE_HORIZONTAL
        assert b.plane_anchors[0].classification == "floor"
        for a in b.plane_anchors[1:]:
            assert a.alignment == PLANE_VERTICAL
            assert a.classification == "wall"
        for a in b.plane_anchors:
            norm = math.sqrt(
                a.pose.quat_x**2 + a.pose.quat_y**2 + a.pose.quat_z**2 + a.pose.quat_w**2
            )
            assert abs(norm - 1.0) < 1e-3
            assert a.extent_width > 0 and a.extent_height > 0
        assert validate_bundle(b) is None


# ---------------------------------------------------------------------------
# RoomPlanModel (decision 0077)
# ---------------------------------------------------------------------------

class TestRoomPlanModel:
    def test_roomplan_bundle_carries_json_and_passes_validation(self):
        """A RoomPlan-carrying bundle: json_gcs_path (the geometry source of
        truth), usdz_gcs_path, and a non-empty roomplan_version — and the
        ingest validator accepts it unchanged (the additive-field contract,
        exercised through the real validate_bundle; the 0066 plane_anchors
        precedent)."""
        import json

        from roomstudio_schemas import CaptureBundle

        arts = build_capture_bundle(tier=TIER_LIDAR_ROOMPLAN, frame_count=1)
        b = CaptureBundle()
        b.ParseFromString(arts.blobs["bundle.pb"])
        assert b.HasField("room_plan")
        assert b.room_plan.json_gcs_path == "roomplan/room.json"
        assert b.room_plan.usdz_gcs_path == "roomplan/room.usdz"
        assert b.room_plan.roomplan_version
        # The JSON blob is structurally a CapturedRoom Codable document.
        doc = json.loads(arts.blobs["roomplan/room.json"])
        assert doc["version"] == 2
        for key in ("walls", "floors", "objects", "doors", "windows", "openings"):
            assert key in doc
        assert validate_bundle(b) is None

    def test_non_roomplan_tiers_have_no_room_plan(self):
        """Absence is clean on the other tiers: no room_plan field, and the
        bundle still validates — the degrade contract starts from HasField
        being False, never from a half-populated message."""
        from roomstudio_schemas import CaptureBundle

        for tier in (TIER_ARKIT_ONLY, TIER_LIDAR_ARKIT):
            arts = build_capture_bundle(tier=tier, frame_count=1)
            b = CaptureBundle()
            b.ParseFromString(arts.blobs["bundle.pb"])
            assert not b.HasField("room_plan")
            assert validate_bundle(b) is None
