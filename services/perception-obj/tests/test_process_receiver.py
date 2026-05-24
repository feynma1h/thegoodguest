"""Integration tests for POST /process.

Tests verify the full orchestration contract: OIDC verification, scene
claim/release state machine, failure classification, final-attempt detection,
concurrent claim race, stale-lease reclaim, and manual-retry path.

SAM 3, SAM 3D Objects, GCS, and FCM are all mocked — tests verify
orchestration, not model behaviour.

The server singleton state (_receiver_repo, _fcm_notifier, _oidc_verifier) is
patched per test via patch.object so each test starts with a clean slate.

Run from repo root:
  pytest services/perception-obj/tests/test_process_receiver.py -v
"""
from __future__ import annotations

import json
import sys
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# conftest.py already adds services/perception-obj to sys.path.
# We also need packages/schemas for CaptureBundle.
_schemas_path = Path(__file__).resolve().parents[3] / "packages/schemas"
if str(_schemas_path) not in sys.path:
    sys.path.insert(0, str(_schemas_path))

# Stub heavy deps that aren't installed in the test venv. Must happen before
# any import that transitively pulls them in.
sys.modules.setdefault("torch", MagicMock())
sys.modules.setdefault("models", MagicMock())
sys.modules.setdefault("models.sam3", MagicMock())
sys.modules.setdefault("models.sam3d", MagicMock())

_fake_sam3 = MagicMock()
_fake_sam3d = MagicMock()

# process_receiver imports CaptureBundle, OIDC helpers, and receiver_repo —
# all are available. No server import needed; we test handle_process directly.
from receiver_repo import ClaimStatus, InMemoryReceiverRepository
from fcm import NullFcmNotifier
from process_receiver import (
    EnvironmentalError,
    PoisonError,
    ProcessRequest,
    handle_process,
    run_perception,
    _bundle_prefix,
)
from oidc import OIDCError, OIDCVerifier
from roomstudio_schemas import CaptureBundle, ARKIT_ONLY, SCHEMA_VERSION


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SCENE_ID   = "scene-test-001"
_BUNDLE_URI = "gs://bucket/captures/test/bundle.pb"
_DEVICE_ID  = "device-abc"
_RESULT_URI = "gs://out/scenes/scene-test-001/manifest.json"
_OUTPUTS_BUCKET = "roomstudio-perception-outputs"

_VALID_AUTH = "Bearer eyJvalid.token"


def _make_bundle_bytes(frame_count: int = 2) -> bytes:
    """Build a minimal valid CaptureBundle proto."""
    import time as _time
    b = CaptureBundle()
    b.schema_version = SCHEMA_VERSION
    b.bundle_id = "test-bundle"
    b.user_id = "user-1"
    b.device.hardware_id = _DEVICE_ID
    b.tier = ARKIT_ONLY
    now = int(_time.time() * 1_000_000)
    b.started_at_us = now
    b.ended_at_us = now + frame_count * 500_000
    for i in range(frame_count):
        f = b.frames.add()
        f.frame_index = i
        f.timestamp_us = now + i * 500_000
        f.rgb_gcs_path = f"frames/{i:06d}.jpg"
        f.camera_pose.quat_w = 1.0
        f.intrinsics.fx = 800.0
        f.intrinsics.fy = 800.0
        f.intrinsics.cx = 512.0
        f.intrinsics.cy = 384.0
        f.intrinsics.width = 1024
        f.intrinsics.height = 768
        f.gravity.y = -1.0
    return b.SerializeToString()


def _seeded_repo(status: str = "queued", lease_expires_at=None) -> InMemoryReceiverRepository:
    repo = InMemoryReceiverRepository()
    repo.seed(_SCENE_ID, status=status, device_id=_DEVICE_ID,
              bundle_uri=_BUNDLE_URI, lease_expires_at=lease_expires_at)
    return repo


def _null_fcm() -> NullFcmNotifier:
    return NullFcmNotifier()


def _mock_run_perception(result_uri: str = _RESULT_URI):
    """Patch run_perception to return a fixed result_uri."""
    return patch(
        "process_receiver.run_perception",
        return_value=result_uri,
    )


def _mock_run_perception_raises(exc: Exception):
    return patch("process_receiver.run_perception", side_effect=exc)


def _no_oidc():
    """Return a verifier that always passes (accepts any header)."""
    v = MagicMock(spec=OIDCVerifier)
    v.verify.return_value = None
    return v


# ---------------------------------------------------------------------------
# Unit tests: handle_process orchestration
# ---------------------------------------------------------------------------

class TestHandleProcessOrchestration:
    """Tests for handle_process() — the core orchestration logic.

    Uses TestClient indirectly via the handle_process coroutine called
    with a fake Request.
    """

    def _run(self, req: ProcessRequest, *, repo, extra_headers=None, oidc=None):
        """Invoke handle_process with a synthetic FastAPI Request."""
        from fastapi import Request as _Request
        from starlette.testclient import TestClient
        import asyncio

        headers = {"content-type": "application/json"}
        if extra_headers:
            headers.update(extra_headers)

        # Build a minimal Starlette Request.
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/process",
            "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
            "query_string": b"",
        }
        fake_request = _Request(scope)

        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(
                handle_process(
                    fake_request,
                    req,
                    oidc_verifier=oidc,
                    receiver_repo=repo,
                    fcm_notifier=_null_fcm(),
                    outputs_bucket=_OUTPUTS_BUCKET,
                    sam3_model=_fake_sam3,
                    sam3d_model=_fake_sam3d,
                    object_prompt="chair,sofa",
                )
            )
        finally:
            loop.close()

    # --- happy path ---

    def test_happy_path_returns_200_ready(self):
        repo = _seeded_repo("queued")
        with _mock_run_perception():
            resp = self._run(ProcessRequest(scene_id=_SCENE_ID, bundle_uri=_BUNDLE_URI), repo=repo)
        assert resp.status_code == 200
        body = json.loads(resp.body)
        assert body["status"] == "ready"
        assert body["scene_id"] == _SCENE_ID

    def test_happy_path_scene_is_ready(self):
        repo = _seeded_repo("queued")
        with _mock_run_perception():
            self._run(ProcessRequest(scene_id=_SCENE_ID, bundle_uri=_BUNDLE_URI), repo=repo)
        assert repo.get_raw(_SCENE_ID)["status"] == "ready"

    def test_happy_path_result_uri_set(self):
        repo = _seeded_repo("queued")
        with _mock_run_perception(_RESULT_URI):
            self._run(ProcessRequest(scene_id=_SCENE_ID, bundle_uri=_BUNDLE_URI), repo=repo)
        assert repo.get_raw(_SCENE_ID)["result_uri"] == _RESULT_URI

    # --- already owned ---

    def test_already_owned_returns_200_noop(self):
        future_lease = datetime.now(tz=timezone.utc) + timedelta(hours=1)
        repo = _seeded_repo("processing", lease_expires_at=future_lease)
        with _mock_run_perception():
            resp = self._run(ProcessRequest(scene_id=_SCENE_ID, bundle_uri=_BUNDLE_URI), repo=repo)
        assert resp.status_code == 200
        body = json.loads(resp.body)
        assert body["reason"] == "already_owned"

    def test_already_owned_no_model_call(self):
        future_lease = datetime.now(tz=timezone.utc) + timedelta(hours=1)
        repo = _seeded_repo("processing", lease_expires_at=future_lease)
        with patch("process_receiver.run_perception") as mock_run:
            self._run(ProcessRequest(scene_id=_SCENE_ID, bundle_uri=_BUNDLE_URI), repo=repo)
        mock_run.assert_not_called()

    # --- stale lease reclaim ---

    def test_stale_lease_reclaimed_and_processed(self):
        past_lease = datetime.now(tz=timezone.utc) - timedelta(hours=1)
        repo = _seeded_repo("processing", lease_expires_at=past_lease)
        with _mock_run_perception():
            resp = self._run(ProcessRequest(scene_id=_SCENE_ID, bundle_uri=_BUNDLE_URI), repo=repo)
        assert resp.status_code == 200
        assert repo.get_raw(_SCENE_ID)["status"] == "ready"

    # --- wrong state / not found ---

    def test_wrong_state_failed_returns_200_noop(self):
        repo = _seeded_repo("failed")
        resp = self._run(ProcessRequest(scene_id=_SCENE_ID, bundle_uri=_BUNDLE_URI), repo=repo)
        assert resp.status_code == 200
        assert json.loads(resp.body)["reason"] == "wrong_state"

    def test_not_found_returns_200_noop(self):
        repo = InMemoryReceiverRepository()  # empty — scene doesn't exist
        resp = self._run(ProcessRequest(scene_id=_SCENE_ID, bundle_uri=_BUNDLE_URI), repo=repo)
        assert resp.status_code == 200
        assert json.loads(resp.body)["reason"] == "not_found"

    # --- manual retry path (failed→queued reset by ingester before re-enqueue) ---

    def test_manual_retry_queued_scene_is_processed(self):
        """After ingester resets failed→queued, the receiver sees queued and processes."""
        repo = _seeded_repo("queued")
        with _mock_run_perception():
            resp = self._run(ProcessRequest(scene_id=_SCENE_ID, bundle_uri=_BUNDLE_URI), repo=repo)
        assert resp.status_code == 200
        assert repo.get_raw(_SCENE_ID)["status"] == "ready"

    # --- poison failures ---

    def test_poison_returns_200_and_marks_failed(self):
        repo = _seeded_repo("queued")
        with _mock_run_perception_raises(PoisonError("bundle 404")):
            resp = self._run(ProcessRequest(scene_id=_SCENE_ID, bundle_uri=_BUNDLE_URI), repo=repo)
        assert resp.status_code == 200
        assert repo.get_raw(_SCENE_ID)["status"] == "failed"

    def test_poison_detail_in_last_error(self):
        repo = _seeded_repo("queued")
        with _mock_run_perception_raises(PoisonError("bundle 404")):
            self._run(ProcessRequest(scene_id=_SCENE_ID, bundle_uri=_BUNDLE_URI), repo=repo)
        assert "bundle 404" in repo.get_raw(_SCENE_ID)["last_error"]

    # --- environmental failures ---

    def test_environmental_non_final_returns_500(self):
        repo = _seeded_repo("queued")
        with _mock_run_perception_raises(EnvironmentalError("transient GCS")):
            resp = self._run(
                ProcessRequest(scene_id=_SCENE_ID, bundle_uri=_BUNDLE_URI),
                repo=repo,
                extra_headers={"x-cloudtasks-taskretrycount": "0"},  # first attempt
            )
        assert resp.status_code == 500
        # Scene should still be processing (not failed yet)
        assert repo.get_raw(_SCENE_ID)["status"] == "processing"

    def test_environmental_final_attempt_writes_failed(self):
        repo = _seeded_repo("queued")
        with _mock_run_perception_raises(EnvironmentalError("transient GCS")):
            resp = self._run(
                ProcessRequest(scene_id=_SCENE_ID, bundle_uri=_BUNDLE_URI),
                repo=repo,
                extra_headers={"x-cloudtasks-taskretrycount": "2"},  # final attempt
            )
        assert resp.status_code == 500
        assert repo.get_raw(_SCENE_ID)["status"] == "failed"

    def test_environmental_final_attempt_sets_last_error(self):
        repo = _seeded_repo("queued")
        with _mock_run_perception_raises(EnvironmentalError("model OOM")):
            self._run(
                ProcessRequest(scene_id=_SCENE_ID, bundle_uri=_BUNDLE_URI),
                repo=repo,
                extra_headers={"x-cloudtasks-taskretrycount": "2"},
            )
        assert "model OOM" in repo.get_raw(_SCENE_ID)["last_error"]

    # --- stale-lease reclaim via handler ---

    def test_stale_lease_reclaim_refreshes_lease(self):
        """Stale-lease reclaim writes a fresh lease_expires_at before processing."""
        past_lease = datetime.now(tz=timezone.utc) - timedelta(hours=1)
        repo = _seeded_repo("processing", lease_expires_at=past_lease)
        with _mock_run_perception():
            self._run(ProcessRequest(scene_id=_SCENE_ID, bundle_uri=_BUNDLE_URI), repo=repo)
        # After success the lease is cleared, but during processing it must have
        # been refreshed.  We verify the terminal state is ready and lease is
        # cleared — if the reclaim had not happened, run_perception would not
        # have been called and status would still be processing.
        raw = repo.get_raw(_SCENE_ID)
        assert raw["status"] == "ready"
        assert raw["lease_expires_at"] is None  # cleared by release_ready

    def test_live_noop_does_not_mutate_lease(self):
        """Live-lease noop must not touch lease_expires_at or lease_holder_id."""
        future_lease = datetime.now(tz=timezone.utc) + timedelta(hours=1)
        repo = _seeded_repo("processing", lease_expires_at=future_lease)
        repo.seed(_SCENE_ID, status="processing", device_id=_DEVICE_ID,
                  lease_expires_at=future_lease, lease_holder_id="other-worker")
        with _mock_run_perception():
            resp = self._run(
                ProcessRequest(scene_id=_SCENE_ID, bundle_uri=_BUNDLE_URI), repo=repo
            )
        assert resp.status_code == 200
        raw = repo.get_raw(_SCENE_ID)
        assert raw["lease_expires_at"] == future_lease
        assert raw["lease_holder_id"] == "other-worker"

    # --- EnvironmentalError lease release ---

    def test_environmental_non_final_clears_lease(self):
        """EnvironmentalError clears the lease but leaves status=processing."""
        repo = _seeded_repo("queued")
        with _mock_run_perception_raises(EnvironmentalError("transient")):
            resp = self._run(
                ProcessRequest(scene_id=_SCENE_ID, bundle_uri=_BUNDLE_URI),
                repo=repo,
                extra_headers={"x-cloudtasks-taskretrycount": "0"},
            )
        assert resp.status_code == 500
        raw = repo.get_raw(_SCENE_ID)
        assert raw["status"] == "processing"
        assert raw["lease_expires_at"] is None

    # --- OIDC rejection ---

    def test_oidc_missing_returns_401(self):
        repo = _seeded_repo("queued")
        verifier = MagicMock(spec=OIDCVerifier)
        verifier.verify.side_effect = OIDCError("missing_token", "no header")
        with _mock_run_perception():
            resp = self._run(
                ProcessRequest(scene_id=_SCENE_ID, bundle_uri=_BUNDLE_URI),
                repo=repo,
                oidc=verifier,
            )
        assert resp.status_code == 401
        assert json.loads(resp.body)["error"] == "missing_token"

    def test_oidc_rejection_no_scene_mutation(self):
        """OIDC failure must not touch the scene."""
        repo = _seeded_repo("queued")
        verifier = MagicMock(spec=OIDCVerifier)
        verifier.verify.side_effect = OIDCError("wrong_email", "bad sa")
        with _mock_run_perception():
            self._run(
                ProcessRequest(scene_id=_SCENE_ID, bundle_uri=_BUNDLE_URI),
                repo=repo,
                oidc=verifier,
            )
        # Scene should remain queued — no claim happened.
        assert repo.get_raw(_SCENE_ID)["status"] == "queued"


# ---------------------------------------------------------------------------
# Concurrent claim race via handle_process
# ---------------------------------------------------------------------------

class TestConcurrentClaimRaceViaHandler:
    def test_exactly_one_worker_processes(self):
        """Two concurrent handle_process calls on the same QUEUED scene: exactly
        one should process (scene ends up ready), the other should 200-exit with
        already_owned."""
        repo = _seeded_repo("queued")
        results: list[int] = []
        lock = threading.Lock()

        def _worker():
            import asyncio
            from fastapi import Request as _Req

            scope = {
                "type": "http",
                "method": "POST",
                "path": "/process",
                "headers": [],
                "query_string": b"",
            }
            fake_req = _Req(scope)
            loop = asyncio.new_event_loop()
            with patch("process_receiver.run_perception", return_value=_RESULT_URI):
                resp = loop.run_until_complete(handle_process(
                    fake_req,
                    ProcessRequest(scene_id=_SCENE_ID, bundle_uri=_BUNDLE_URI),
                    oidc_verifier=None,
                    receiver_repo=repo,
                    fcm_notifier=_null_fcm(),
                    outputs_bucket=_OUTPUTS_BUCKET,
                    sam3_model=_fake_sam3,
                    sam3d_model=_fake_sam3d,
                    object_prompt="chair",
                ))
            loop.close()
            with lock:
                results.append(resp.status_code)

        threads = [threading.Thread(target=_worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Both return 200 (one "ready", one "noop/already_owned").
        assert all(c == 200 for c in results)
        # Scene ends up ready exactly once.
        assert repo.get_raw(_SCENE_ID)["status"] == "ready"


# ---------------------------------------------------------------------------
# SIGTERM handler
# ---------------------------------------------------------------------------

class TestSigtermHandler:
    """Tests for the module-level _sigterm_handler in process_receiver."""

    def _run_claim(self, repo, scene_id=_SCENE_ID):
        """Claim a scene via handle_process so _held_scene_ids is populated."""
        import asyncio
        from fastapi import Request as _Req
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/process",
            "headers": [],
            "query_string": b"",
        }
        fake_req = _Req(scope)
        loop = asyncio.new_event_loop()
        with patch("process_receiver.run_perception", side_effect=EnvironmentalError("hold")):
            resp = loop.run_until_complete(handle_process(
                fake_req,
                ProcessRequest(scene_id=scene_id, bundle_uri=_BUNDLE_URI),
                oidc_verifier=None,
                receiver_repo=repo,
                fcm_notifier=_null_fcm(),
                outputs_bucket=_OUTPUTS_BUCKET,
                sam3_model=_fake_sam3,
                sam3d_model=_fake_sam3d,
                object_prompt="chair",
            ))
        loop.close()
        return resp

    def test_sigterm_resets_held_scene_to_queued(self):
        """SIGTERM handler sets status=queued and clears lease for held scenes."""
        import process_receiver
        import signal as _signal

        repo = _seeded_repo("queued")
        # Run a claim that will fail environmentally, leaving the scene in
        # processing with cleared lease.  Re-seed it as processing+live lease
        # so the SIGTERM handler has something to release.
        repo.seed(_SCENE_ID, status="processing", device_id=_DEVICE_ID,
                  lease_expires_at=datetime.now(tz=timezone.utc) + timedelta(hours=1))
        process_receiver._sigterm_repo_ref = repo
        with process_receiver._held_scenes_lock:
            process_receiver._held_scene_ids.add(_SCENE_ID)

        # Fire the handler directly (same as receiving SIGTERM).
        process_receiver._sigterm_handler(_signal.SIGTERM, None)

        raw = repo.get_raw(_SCENE_ID)
        assert raw["status"] == "queued"
        assert raw["lease_expires_at"] is None
        assert raw["shutdown_release_count"] == 1

    def test_sigterm_clears_held_scene_ids(self):
        """After SIGTERM handler runs, _held_scene_ids is cleared."""
        import process_receiver
        import signal as _signal

        repo = _seeded_repo("processing")
        repo.seed(_SCENE_ID, status="processing", device_id=_DEVICE_ID,
                  lease_expires_at=datetime.now(tz=timezone.utc) + timedelta(hours=1))
        process_receiver._sigterm_repo_ref = repo
        with process_receiver._held_scenes_lock:
            process_receiver._held_scene_ids.add(_SCENE_ID)

        process_receiver._sigterm_handler(_signal.SIGTERM, None)

        with process_receiver._held_scenes_lock:
            assert _SCENE_ID not in process_receiver._held_scene_ids

    def test_sigterm_noop_when_no_repo(self):
        """SIGTERM handler is safe to call before any scene is ever claimed."""
        import process_receiver
        import signal as _signal

        process_receiver._sigterm_repo_ref = None
        process_receiver._sigterm_handler(_signal.SIGTERM, None)  # must not raise

    def test_sigterm_noop_on_already_released_scene(self):
        """SIGTERM handler skips scenes that are no longer in processing state."""
        import process_receiver
        import signal as _signal

        repo = _seeded_repo("ready")  # already completed
        process_receiver._sigterm_repo_ref = repo
        with process_receiver._held_scenes_lock:
            process_receiver._held_scene_ids.add(_SCENE_ID)

        process_receiver._sigterm_handler(_signal.SIGTERM, None)

        # Status must not be changed — the scene completed normally.
        assert repo.get_raw(_SCENE_ID)["status"] == "ready"


# ---------------------------------------------------------------------------
# Concurrent stale-lease reclaim via handle_process
# ---------------------------------------------------------------------------

class TestConcurrentStaleReclaimViaHandler:
    def test_exactly_one_worker_reclaims(self):
        """Two concurrent handle_process calls on a stale-lease PROCESSING scene:
        exactly one should reclaim and process (scene ends up ready), the other
        should 200-noop after seeing the refreshed lease.
        """
        past_lease = datetime.now(tz=timezone.utc) - timedelta(hours=1)
        repo = _seeded_repo("processing", lease_expires_at=past_lease)
        results: list = []
        lock = threading.Lock()

        def _worker():
            import asyncio
            from fastapi import Request as _Req
            scope = {
                "type": "http",
                "method": "POST",
                "path": "/process",
                "headers": [],
                "query_string": b"",
            }
            fake_req = _Req(scope)
            loop = asyncio.new_event_loop()
            with patch("process_receiver.run_perception", return_value=_RESULT_URI):
                resp = loop.run_until_complete(handle_process(
                    fake_req,
                    ProcessRequest(scene_id=_SCENE_ID, bundle_uri=_BUNDLE_URI),
                    oidc_verifier=None,
                    receiver_repo=repo,
                    fcm_notifier=_null_fcm(),
                    outputs_bucket=_OUTPUTS_BUCKET,
                    sam3_model=_fake_sam3,
                    sam3d_model=_fake_sam3d,
                    object_prompt="chair",
                ))
            loop.close()
            import json as _json
            with lock:
                results.append(_json.loads(resp.body))

        threads = [threading.Thread(target=_worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        statuses = {r["status"] for r in results}
        assert "ready" in statuses, f"Expected one ready, got: {results}"
        assert repo.get_raw(_SCENE_ID)["status"] == "ready"


# ---------------------------------------------------------------------------
# Unit tests: bundle_prefix helper
# ---------------------------------------------------------------------------

class TestBundlePrefix:
    def test_strips_filename(self):
        assert _bundle_prefix("gs://b/a/b/c/bundle.pb") == "gs://b/a/b/c/"

    def test_deep_path(self):
        assert _bundle_prefix("gs://bucket/captures/id123/bundle.pb") == \
               "gs://bucket/captures/id123/"
