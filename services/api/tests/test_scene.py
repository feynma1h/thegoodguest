"""Tests for the Scene model, state machine, and SceneRepository.

All tests use InMemorySceneRepository — no Firestore, no GCP credentials.
The FirestoreSceneRepository is not instantiated; its deferred import means
importing repository.py is safe even without google-cloud-firestore installed.

Tests are organized into four groups:
  1. Scene model        — construction, field validation, invariants
  2. State machine      — every allowed transition passes; every disallowed
                          transition raises InvalidTransitionError
  3. Repository contract — get/create/update_status semantics via the
                          in-memory fake (copy isolation, error cases, etc.)
  4. device_id resolution — resolve_device_id helper: provided path, fallback
                            path with warning log, both-empty rejection

Run from repo root:
  pytest services/api/tests/test_scene.py -v
"""
from __future__ import annotations

import logging
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

_api_dir = Path(__file__).resolve().parents[1]
_schemas_dir = _api_dir.parents[1] / "packages/schemas"
for _p in (_api_dir, _schemas_dir):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from scene import (
    DeviceIdSource,
    InvalidTransitionError,
    Scene,
    SceneStatus,
    allowed_transitions,
    new_scene,
    validate_transition,
)
from repository import InMemorySceneRepository, SceneNotFoundError
import server  # for resolve_device_id


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime.now(tz=timezone.utc)

def _scene(**kwargs) -> Scene:
    """Build a minimal valid Scene; callers override specific fields."""
    defaults = dict(
        scene_id="scene-001",
        device_id="device-uuid-abc",
        device_id_source=DeviceIdSource.PROVIDED,
        status=SceneStatus.QUEUED,
        bundle_uri="gs://test-bucket/captures/abc/bundle.pb",
        created_at=_NOW,
        updated_at=_NOW,
    )
    defaults.update(kwargs)
    return Scene(**defaults)


def _bundle_stub(*, device_id: str = "", hardware_id: str = "iPhone15,3"):
    """Minimal bundle-like object for testing resolve_device_id."""
    class DeviceStub:
        pass
    class BundleStub:
        pass
    d = DeviceStub()
    d.device_id = device_id
    d.hardware_id = hardware_id
    b = BundleStub()
    b.device = d
    return b


# ---------------------------------------------------------------------------
# 1. Scene model
# ---------------------------------------------------------------------------

class TestSceneModel:

    def test_new_scene_is_queued(self):
        s = new_scene(
            device_id="d",
            device_id_source=DeviceIdSource.PROVIDED,
            bundle_uri="gs://b/path/bundle.pb",
        )
        assert s.status == SceneStatus.QUEUED

    def test_new_scene_generates_uuid(self):
        s = new_scene(
            device_id="d",
            device_id_source=DeviceIdSource.PROVIDED,
            bundle_uri="gs://b/path/bundle.pb",
        )
        assert len(s.scene_id) == 36  # UUIDv4

    def test_new_scene_accepts_explicit_scene_id(self):
        s = new_scene(
            scene_id="my-id",
            device_id="d",
            device_id_source=DeviceIdSource.PROVIDED,
            bundle_uri="gs://b/path/bundle.pb",
        )
        assert s.scene_id == "my-id"

    def test_new_scene_timestamps_are_tz_aware(self):
        s = new_scene(
            device_id="d",
            device_id_source=DeviceIdSource.PROVIDED,
            bundle_uri="gs://b/path/bundle.pb",
        )
        assert s.created_at.tzinfo is not None
        assert s.updated_at.tzinfo is not None

    def test_defaults(self):
        s = new_scene(
            device_id="d",
            device_id_source=DeviceIdSource.PROVIDED,
            bundle_uri="gs://b/path/bundle.pb",
        )
        assert s.attempt_count == 0
        assert s.result_uri is None
        assert s.last_error is None

    def test_empty_scene_id_raises(self):
        with pytest.raises(ValueError, match="scene_id"):
            _scene(scene_id="")

    def test_empty_device_id_raises(self):
        with pytest.raises(ValueError, match="device_id"):
            _scene(device_id="")

    def test_relative_bundle_uri_raises(self):
        with pytest.raises(ValueError, match="bundle_uri"):
            _scene(bundle_uri="captures/abc/bundle.pb")

    def test_http_bundle_uri_raises(self):
        with pytest.raises(ValueError, match="bundle_uri"):
            _scene(bundle_uri="https://storage.googleapis.com/b/bundle.pb")

    def test_negative_attempt_count_raises(self):
        with pytest.raises(ValueError, match="attempt_count"):
            _scene(attempt_count=-1)

    def test_naive_created_at_raises(self):
        with pytest.raises(ValueError, match="timezone-aware"):
            _scene(created_at=datetime(2026, 1, 1))  # no tzinfo

    def test_naive_updated_at_raises(self):
        with pytest.raises(ValueError, match="timezone-aware"):
            _scene(updated_at=datetime(2026, 1, 1))  # no tzinfo

    def test_string_status_raises(self):
        with pytest.raises(ValueError, match="status"):
            _scene(status="queued")  # must be SceneStatus, not a raw string

    def test_string_device_id_source_raises(self):
        with pytest.raises(ValueError, match="device_id_source"):
            _scene(device_id_source="provided")  # must be DeviceIdSource enum

    def test_fallback_source_accepted(self):
        s = _scene(device_id_source=DeviceIdSource.FALLBACK_HARDWARE_ID)
        assert s.device_id_source == DeviceIdSource.FALLBACK_HARDWARE_ID


# ---------------------------------------------------------------------------
# 2. State machine
# ---------------------------------------------------------------------------

class TestStateMachine:

    # Allowed transitions
    def test_queued_to_processing(self):
        validate_transition(SceneStatus.QUEUED, SceneStatus.PROCESSING)

    def test_processing_to_ready(self):
        validate_transition(SceneStatus.PROCESSING, SceneStatus.READY)

    def test_processing_to_failed(self):
        validate_transition(SceneStatus.PROCESSING, SceneStatus.FAILED)

    def test_failed_to_queued_retry(self):
        validate_transition(SceneStatus.FAILED, SceneStatus.QUEUED)

    # Disallowed transitions — queued
    def test_queued_to_ready_raises(self):
        with pytest.raises(InvalidTransitionError):
            validate_transition(SceneStatus.QUEUED, SceneStatus.READY)

    def test_queued_to_failed_allowed(self):
        """QUEUED → FAILED is permitted for dispatch-time failures (task never
        enqueued). Distinct from the PROCESSING → FAILED path triggered by
        perception errors after the task was dispatched."""
        validate_transition(SceneStatus.QUEUED, SceneStatus.FAILED)  # must not raise

    def test_queued_to_queued_raises(self):
        with pytest.raises(InvalidTransitionError):
            validate_transition(SceneStatus.QUEUED, SceneStatus.QUEUED)

    # Disallowed transitions — processing
    def test_processing_to_queued_raises(self):
        with pytest.raises(InvalidTransitionError):
            validate_transition(SceneStatus.PROCESSING, SceneStatus.QUEUED)

    def test_processing_to_processing_raises(self):
        with pytest.raises(InvalidTransitionError):
            validate_transition(SceneStatus.PROCESSING, SceneStatus.PROCESSING)

    # Disallowed transitions — ready (terminal)
    def test_ready_is_terminal(self):
        for target in SceneStatus:
            with pytest.raises(InvalidTransitionError):
                validate_transition(SceneStatus.READY, target)

    # Disallowed transitions — failed
    def test_failed_to_processing_raises(self):
        with pytest.raises(InvalidTransitionError):
            validate_transition(SceneStatus.FAILED, SceneStatus.PROCESSING)

    def test_failed_to_ready_raises(self):
        with pytest.raises(InvalidTransitionError):
            validate_transition(SceneStatus.FAILED, SceneStatus.READY)

    def test_failed_to_failed_raises(self):
        with pytest.raises(InvalidTransitionError):
            validate_transition(SceneStatus.FAILED, SceneStatus.FAILED)

    # allowed_transitions helper
    def test_allowed_from_queued(self):
        assert allowed_transitions(SceneStatus.QUEUED) == frozenset({
            SceneStatus.PROCESSING,
            SceneStatus.FAILED,           # dispatch-time failure path
            SceneStatus.FAILED_INCOMPLETE, # existence-check failure (missing blobs)
        })

    def test_allowed_from_ready_is_empty(self):
        assert allowed_transitions(SceneStatus.READY) == frozenset()

    def test_error_message_names_current_and_target(self):
        with pytest.raises(InvalidTransitionError, match="queued.*ready"):
            validate_transition(SceneStatus.QUEUED, SceneStatus.READY)


# ---------------------------------------------------------------------------
# 3. Repository contract (InMemorySceneRepository)
# ---------------------------------------------------------------------------

class TestInMemoryRepository:

    @pytest.fixture
    def repo(self) -> InMemorySceneRepository:
        return InMemorySceneRepository()

    def test_create_and_get_roundtrip(self, repo):
        s = _scene()
        repo.create(s)
        fetched = repo.get(s.scene_id)
        assert fetched.scene_id == s.scene_id
        assert fetched.status == SceneStatus.QUEUED

    def test_get_missing_raises(self, repo):
        with pytest.raises(SceneNotFoundError):
            repo.get("does-not-exist")

    def test_create_duplicate_raises(self, repo):
        s = _scene()
        repo.create(s)
        with pytest.raises(ValueError, match="already exists"):
            repo.create(s)

    def test_create_returns_isolated_copy(self, repo):
        """Mutating the returned scene must not affect the stored scene."""
        s = _scene()
        returned = repo.create(s)
        returned.status = SceneStatus.PROCESSING
        assert repo.get(s.scene_id).status == SceneStatus.QUEUED

    def test_get_returns_isolated_copy(self, repo):
        """Mutating a fetched scene must not affect the stored scene."""
        s = _scene()
        repo.create(s)
        fetched = repo.get(s.scene_id)
        fetched.status = SceneStatus.FAILED
        assert repo.get(s.scene_id).status == SceneStatus.QUEUED

    def test_update_status_allowed_transition(self, repo):
        repo.create(_scene(status=SceneStatus.QUEUED))
        updated = repo.update_status("scene-001", SceneStatus.PROCESSING)
        assert updated.status == SceneStatus.PROCESSING

    def test_update_status_advances_updated_at(self, repo):
        before = datetime.now(tz=timezone.utc)
        repo.create(_scene(status=SceneStatus.QUEUED))
        updated = repo.update_status("scene-001", SceneStatus.PROCESSING)
        assert updated.updated_at >= before

    def test_update_status_sets_result_uri(self, repo):
        repo.create(_scene(status=SceneStatus.PROCESSING))
        updated = repo.update_status(
            "scene-001", SceneStatus.READY,
            result_uri="gs://bucket/splats/scene.ply",
        )
        assert updated.result_uri == "gs://bucket/splats/scene.ply"

    def test_update_status_sets_last_error(self, repo):
        repo.create(_scene(status=SceneStatus.PROCESSING))
        updated = repo.update_status(
            "scene-001", SceneStatus.FAILED,
            last_error="GPU OOM on frame 4",
        )
        assert updated.last_error == "GPU OOM on frame 4"

    def test_update_status_invalid_transition_raises(self, repo):
        repo.create(_scene(status=SceneStatus.QUEUED))
        with pytest.raises(InvalidTransitionError):
            repo.update_status("scene-001", SceneStatus.READY)

    def test_update_status_missing_scene_raises(self, repo):
        with pytest.raises(SceneNotFoundError):
            repo.update_status("ghost-id", SceneStatus.PROCESSING)

    def test_happy_path_queued_processing_ready(self, repo):
        repo.create(_scene(status=SceneStatus.QUEUED))
        repo.update_status("scene-001", SceneStatus.PROCESSING)
        final = repo.update_status(
            "scene-001", SceneStatus.READY,
            result_uri="gs://bucket/splats/scene.ply",
        )
        assert final.status == SceneStatus.READY
        assert final.result_uri == "gs://bucket/splats/scene.ply"

    def test_retry_path_failed_to_queued(self, repo):
        repo.create(_scene(status=SceneStatus.PROCESSING))
        repo.update_status("scene-001", SceneStatus.FAILED, last_error="timeout")
        retried = repo.update_status("scene-001", SceneStatus.QUEUED)
        assert retried.status == SceneStatus.QUEUED

    def test_device_id_source_preserved(self, repo):
        s = _scene(device_id_source=DeviceIdSource.FALLBACK_HARDWARE_ID)
        repo.create(s)
        assert repo.get(s.scene_id).device_id_source == DeviceIdSource.FALLBACK_HARDWARE_ID


# ---------------------------------------------------------------------------
# 4. device_id resolution
# ---------------------------------------------------------------------------

class TestResolveDeviceId:

    def test_provided_path_uses_device_id(self):
        bundle = _bundle_stub(device_id="stable-uuid-123", hardware_id="iPhone15,3")
        device_id, source = server.resolve_device_id(bundle, "gs://b/bundle.pb")
        assert device_id == "stable-uuid-123"
        assert source == DeviceIdSource.PROVIDED

    def test_provided_path_no_warning(self, caplog):
        bundle = _bundle_stub(device_id="stable-uuid-123", hardware_id="iPhone15,3")
        with caplog.at_level(logging.WARNING, logger="server"):
            server.resolve_device_id(bundle, "gs://b/bundle.pb")
        assert caplog.records == []

    def test_fallback_uses_hardware_id(self):
        bundle = _bundle_stub(device_id="", hardware_id="iPhone15,3")
        device_id, source = server.resolve_device_id(bundle, "gs://b/bundle.pb")
        assert device_id == "iPhone15,3"
        assert source == DeviceIdSource.FALLBACK_HARDWARE_ID

    def test_fallback_emits_warning(self, caplog):
        bundle = _bundle_stub(device_id="", hardware_id="iPhone15,3")
        with caplog.at_level(logging.WARNING, logger="server"):
            server.resolve_device_id(bundle, "gs://b/bundle.pb")
        assert len(caplog.records) == 1
        assert caplog.records[0].levelname == "WARNING"
        assert "iPhone15,3" in caplog.records[0].message
        assert "gs://b/bundle.pb" in caplog.records[0].message

    def test_fallback_warning_is_greppable(self, caplog):
        """Warning must contain hardware_id value and bundle URI for Cloud Logging."""
        bundle = _bundle_stub(device_id="", hardware_id="iPhone14,2")
        with caplog.at_level(logging.WARNING, logger="server"):
            server.resolve_device_id(bundle, "gs://prod-bucket/captures/xyz/bundle.pb")
        msg = caplog.records[0].message
        assert "iPhone14,2" in msg
        assert "gs://prod-bucket/captures/xyz/bundle.pb" in msg

    def test_both_empty_raises(self):
        bundle = _bundle_stub(device_id="", hardware_id="")
        with pytest.raises(ValueError, match="device_id.*hardware_id.*empty"):
            server.resolve_device_id(bundle, "gs://b/bundle.pb")

    def test_both_empty_raises_value_error_not_500(self):
        """Ensures the exception type is ValueError (maps to 400 in server.py)."""
        bundle = _bundle_stub(device_id="", hardware_id="")
        with pytest.raises(ValueError):
            server.resolve_device_id(bundle, "gs://b/bundle.pb")
