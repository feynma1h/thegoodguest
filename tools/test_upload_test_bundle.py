"""Unit tests for tools/upload_test_bundle.py.

Tests the cross-flag validation logic (validate_config) and UID cache loading.
These tests do not require a deployed stack, Firebase credentials, or GCS access.

Run from repo root:
    python3 -m pytest tools/test_upload_test_bundle.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Add repo root packages to sys.path so the tool can import its deps.
_repo_root = Path(__file__).resolve().parents[1]
for _pkg in ("packages/schemas", "packages/api-core"):
    _p = str(_repo_root / _pkg)
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Import the modules under test.
_tools_dir = str(_repo_root / "tools")
if _tools_dir not in sys.path:
    sys.path.insert(0, _tools_dir)

from upload_test_bundle import (  # noqa: E402
    Config,
    Misconfig,
    validate_config,
    _validate_uid_cache,
    TIER_ARKIT_ONLY,
    TIER_LIDAR_ARKIT,
    TIER_LIDAR_ROOMPLAN,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_namespace(**overrides):
    """Return an argparse.Namespace with all required fields set to valid values."""
    import argparse
    defaults = dict(
        mode="happy-path",
        public_url="http://localhost:8080",
        internal_url="http://localhost:8081",
        firebase_api_key="test-api-key",
        firebase_project_id="test-project",
        gcs_bucket="test-bucket",
        tier=TIER_LIDAR_ROOMPLAN,
        frame_count=3,
        drop_blob_kind=None,
        timeout=120.0,
        poll_interval=2.0,
        reuse_uid=None,
        save_uid=None,
        cleanup=False,
        verbose=False,
        json=False,
        use_hardware_id_fallback=False,
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _make_cfg(**overrides) -> Config:
    return Config(_make_namespace(**overrides))


# ---------------------------------------------------------------------------
# Missing required flags → exit 2
# ---------------------------------------------------------------------------

class TestRequiredFlags:
    def test_missing_public_url_raises_misconfig(self):
        with pytest.raises(Misconfig, match="public-url"):
            validate_config(_make_cfg(public_url=""))

    def test_missing_internal_url_raises_misconfig(self):
        with pytest.raises(Misconfig, match="internal-url"):
            validate_config(_make_cfg(internal_url=""))

    def test_missing_firebase_api_key_raises_misconfig(self):
        with pytest.raises(Misconfig, match="firebase-api-key"):
            validate_config(_make_cfg(firebase_api_key=""))

    def test_missing_firebase_project_id_raises_misconfig(self):
        with pytest.raises(Misconfig, match="firebase-project-id"):
            validate_config(_make_cfg(firebase_project_id=""))

    def test_missing_gcs_bucket_raises_misconfig(self):
        with pytest.raises(Misconfig, match="gcs-bucket"):
            validate_config(_make_cfg(gcs_bucket=""))

    def test_all_required_flags_set_passes(self):
        validate_config(_make_cfg())  # should not raise


# ---------------------------------------------------------------------------
# frame_count < 1 → exit 2
# ---------------------------------------------------------------------------

class TestFrameCount:
    def test_frame_count_zero_raises_misconfig(self):
        with pytest.raises(Misconfig, match="frame-count"):
            validate_config(_make_cfg(frame_count=0))

    def test_frame_count_negative_raises_misconfig(self):
        with pytest.raises(Misconfig, match="frame-count"):
            validate_config(_make_cfg(frame_count=-1))

    def test_frame_count_one_passes(self):
        validate_config(_make_cfg(frame_count=1))


# ---------------------------------------------------------------------------
# skip-blob without --drop-blob-kind → exit 2
# ---------------------------------------------------------------------------

class TestSkipBlobRequiresDrop:
    def test_skip_blob_without_drop_kind_raises_misconfig(self):
        with pytest.raises(Misconfig, match="drop-blob-kind"):
            validate_config(_make_cfg(mode="skip-blob", drop_blob_kind=None))

    def test_skip_blob_with_depth_lidar_arkit_passes(self):
        validate_config(
            _make_cfg(mode="skip-blob", tier=TIER_LIDAR_ARKIT, drop_blob_kind="depth")
        )

    def test_skip_blob_with_rgb_arkit_only_passes(self):
        validate_config(
            _make_cfg(mode="skip-blob", tier=TIER_ARKIT_ONLY, drop_blob_kind="rgb")
        )


# ---------------------------------------------------------------------------
# --drop-blob-kind incompatible with --tier → exit 2
# ---------------------------------------------------------------------------

class TestDropBlobKindTierCompatibility:
    def test_depth_with_arkit_only_raises_misconfig(self):
        with pytest.raises(Misconfig, match="arkit-only"):
            validate_config(
                _make_cfg(mode="skip-blob", tier=TIER_ARKIT_ONLY, drop_blob_kind="depth")
            )

    def test_confidence_with_arkit_only_raises_misconfig(self):
        with pytest.raises(Misconfig, match="arkit-only"):
            validate_config(
                _make_cfg(mode="skip-blob", tier=TIER_ARKIT_ONLY, drop_blob_kind="confidence")
            )

    def test_usdz_with_arkit_only_raises_misconfig(self):
        with pytest.raises(Misconfig, match="lidar-roomplan"):
            validate_config(
                _make_cfg(mode="skip-blob", tier=TIER_ARKIT_ONLY, drop_blob_kind="usdz")
            )

    def test_usdz_with_lidar_arkit_raises_misconfig(self):
        with pytest.raises(Misconfig, match="lidar-roomplan"):
            validate_config(
                _make_cfg(mode="skip-blob", tier=TIER_LIDAR_ARKIT, drop_blob_kind="usdz")
            )

    def test_usdz_with_lidar_roomplan_passes(self):
        validate_config(
            _make_cfg(mode="skip-blob", tier=TIER_LIDAR_ROOMPLAN, drop_blob_kind="usdz")
        )

    def test_depth_with_lidar_arkit_passes(self):
        validate_config(
            _make_cfg(mode="skip-blob", tier=TIER_LIDAR_ARKIT, drop_blob_kind="depth")
        )

    def test_depth_with_lidar_roomplan_passes(self):
        validate_config(
            _make_cfg(mode="skip-blob", tier=TIER_LIDAR_ROOMPLAN, drop_blob_kind="depth")
        )

    def test_drop_blob_kind_outside_skip_blob_mode_passes(self):
        # --drop-blob-kind is ignored for non-skip-blob modes
        validate_config(
            _make_cfg(mode="happy-path", tier=TIER_ARKIT_ONLY, drop_blob_kind="depth")
        )


# ---------------------------------------------------------------------------
# --reuse-uid cache file validation → exit 2
# ---------------------------------------------------------------------------

class TestReuseUidCache:
    def test_missing_file_raises_misconfig(self, tmp_path):
        missing = str(tmp_path / "does_not_exist.json")
        with pytest.raises(Misconfig, match="not found"):
            _validate_uid_cache(missing)

    def test_non_json_file_raises_misconfig(self, tmp_path):
        bad = tmp_path / "uid.json"
        bad.write_text("this is not json")
        with pytest.raises(Misconfig, match="malformed"):
            _validate_uid_cache(str(bad))

    def test_missing_refresh_token_key_raises_misconfig(self, tmp_path):
        bad = tmp_path / "uid.json"
        bad.write_text(json.dumps({"local_id": "uid-123"}))
        with pytest.raises(Misconfig, match="malformed"):
            _validate_uid_cache(str(bad))

    def test_missing_local_id_key_raises_misconfig(self, tmp_path):
        bad = tmp_path / "uid.json"
        bad.write_text(json.dumps({"refresh_token": "tok-abc"}))
        with pytest.raises(Misconfig, match="malformed"):
            _validate_uid_cache(str(bad))

    def test_empty_refresh_token_raises_misconfig(self, tmp_path):
        bad = tmp_path / "uid.json"
        bad.write_text(json.dumps({"local_id": "uid-123", "refresh_token": ""}))
        with pytest.raises(Misconfig, match="malformed"):
            _validate_uid_cache(str(bad))

    def test_valid_cache_file_passes(self, tmp_path):
        good = tmp_path / "uid.json"
        good.write_text(json.dumps({"local_id": "uid-123", "refresh_token": "tok-abc"}))
        _validate_uid_cache(str(good))  # should not raise

    def test_reuse_uid_in_validate_config_passes_valid_file(self, tmp_path):
        good = tmp_path / "uid.json"
        good.write_text(json.dumps({"local_id": "uid-123", "refresh_token": "tok-abc"}))
        validate_config(_make_cfg(reuse_uid=str(good)))
