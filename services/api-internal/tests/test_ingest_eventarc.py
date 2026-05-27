"""Tests for POST /ingest/eventarc and the existence-check pass in _run_ingest.

Covers:
  Eventarc endpoint:
    - Valid GCS finalize event → dispatches ingest and returns 200
    - Missing 'bucket' or 'name' in event body → 400
    - object name that doesn't match captures/*/bundle.pb → 400
    - Idempotency: scene already QUEUED → 200, no re-enqueue
    - Idempotency: scene already PROCESSING → 200, no re-enqueue
    - Idempotency: scene FAILED_INCOMPLETE → re-runs ingest with existing scene_id

  Existence-check pass (tested through /ingest and /ingest/eventarc):
    - All blobs present → scene reaches QUEUED (proceeds normally)
    - One blob missing → status=failed_incomplete, missing_paths in response
    - Multiple blobs missing → all listed in missing_paths
    - No frames in bundle → no existence check needed (no paths to check)
    - FCM notifier called with correct token when upload incomplete
    - Scene transitions from QUEUED to FAILED_INCOMPLETE in repo on missing blob

NullFcmNotifier is used for all tests. _blob_exists and _fetch_bundle_bytes
are patched so no GCS credentials are needed.

Run from repo root:
  pytest services/api/tests/test_ingest_eventarc.py -v
"""
from __future__ import annotations

import sys
import time
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest
from fastapi.testclient import TestClient

_api_dir = Path(__file__).resolve().parents[1]
_repo_root = _api_dir.parents[1]
for _p in (
    str(_api_dir),
    str(_repo_root / "packages/schemas"),
    str(_repo_root / "packages/api-core"),
):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from roomstudio_schemas import ARKIT_ONLY, LIDAR_ARKIT, SCHEMA_VERSION, CaptureBundle  # noqa: E402

import server  # noqa: E402
from repository import InMemorySceneRepository  # noqa: E402
from dispatcher import InMemoryTaskDispatcher  # noqa: E402
from scene import SceneStatus  # noqa: E402
from fcm import NullFcmNotifier  # noqa: E402
from roomstudio_api_core.upload_session_repo import InMemoryUploadSessionRepository  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(server.app)


# ---------------------------------------------------------------------------
# Bundle builder
# ---------------------------------------------------------------------------

def _make_bundle(*, frame_count: int = 2, add_depth: bool = False) -> bytes:
    tier = LIDAR_ARKIT if add_depth else ARKIT_ONLY
    b = CaptureBundle()
    b.schema_version = SCHEMA_VERSION
    b.bundle_id = str(uuid.uuid4())
    b.user_id = "test-user"
    b.device.hardware_id = "test-device"
    b.tier = tier
    now_us = int(time.monotonic_ns() // 1_000)
    b.started_at_device_us = now_us
    b.ended_at_device_us = now_us + frame_count * 500_000
    b.started_at_wall_us = int(time.time_ns() // 1_000)
    for i in range(frame_count):
        f = b.frames.add()
        f.frame_index = i
        f.timestamp_us = now_us + i * 500_000
        f.rgb_gcs_path = f"frames/{i:06d}.jpg"
        f.camera_pose.quat_w = 1.0
        f.intrinsics.fx = 800.0
        f.intrinsics.fy = 800.0
        f.intrinsics.cx = 512.0
        f.intrinsics.cy = 384.0
        f.intrinsics.width = 1024
        f.intrinsics.height = 768
        f.gravity.y = -1.0
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


_BUCKET = "test-bucket"
_BUNDLE_ID = str(uuid.uuid4())
_BUNDLE_URI = f"gs://{_BUCKET}/captures/{_BUNDLE_ID}/bundle.pb"

_EVENTARC_BODY = {"bucket": _BUCKET, "name": f"captures/{_BUNDLE_ID}/bundle.pb"}


# ---------------------------------------------------------------------------
# Eventarc endpoint — routing and event parsing
# ---------------------------------------------------------------------------

class TestIngestEventarc:
    def test_valid_event_dispatches_ingest(self, client: TestClient) -> None:
        bundle_bytes = _make_bundle(frame_count=2)
        repo = InMemorySceneRepository()
        dispatcher = InMemoryTaskDispatcher()

        with (
            patch.object(server, "_fetch_bundle_bytes", return_value=bundle_bytes),
            patch.object(server, "_blob_exists", return_value=True),
            patch.object(server, "_scene_repo", repo),
            patch.object(server, "_task_dispatcher", dispatcher),
            patch.object(server, "_fcm_notifier", NullFcmNotifier()),
            patch.object(server, "_upload_session_repo", InMemoryUploadSessionRepository()),
        ):
            resp = client.post("/ingest/eventarc", json=_EVENTARC_BODY)

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "queued"
        assert len(dispatcher.tasks) == 1

    def test_missing_bucket_returns_400(self, client: TestClient) -> None:
        resp = client.post("/ingest/eventarc", json={"name": f"captures/{_BUNDLE_ID}/bundle.pb"})
        assert resp.status_code == 400
        assert resp.json()["error"] == "bad_event"

    def test_missing_name_returns_400(self, client: TestClient) -> None:
        resp = client.post("/ingest/eventarc", json={"bucket": _BUCKET})
        assert resp.status_code == 400
        assert resp.json()["error"] == "bad_event"

    def test_name_not_bundle_pb_returns_400(self, client: TestClient) -> None:
        resp = client.post(
            "/ingest/eventarc",
            json={"bucket": _BUCKET, "name": f"captures/{_BUNDLE_ID}/frames/000000.jpg"},
        )
        assert resp.status_code == 400
        assert resp.json()["error"] == "bad_event"

    def test_idempotency_already_queued_skips_reenqueue(self, client: TestClient) -> None:
        bundle_id = str(uuid.uuid4())
        bundle_uri = f"gs://{_BUCKET}/captures/{bundle_id}/bundle.pb"
        bundle_bytes = _make_bundle()
        repo = InMemorySceneRepository()
        dispatcher = InMemoryTaskDispatcher()

        event = {"bucket": _BUCKET, "name": f"captures/{bundle_id}/bundle.pb"}

        with (
            patch.object(server, "_fetch_bundle_bytes", return_value=bundle_bytes),
            patch.object(server, "_blob_exists", return_value=True),
            patch.object(server, "_scene_repo", repo),
            patch.object(server, "_task_dispatcher", dispatcher),
            patch.object(server, "_fcm_notifier", NullFcmNotifier()),
            patch.object(server, "_upload_session_repo", InMemoryUploadSessionRepository()),
        ):
            # First fire.
            resp1 = client.post("/ingest/eventarc", json=event)
            assert resp1.status_code == 200
            scene_id = resp1.json()["scene_id"]
            assert len(dispatcher.tasks) == 1

            # Second fire (idempotent).
            resp2 = client.post("/ingest/eventarc", json=event)
            assert resp2.status_code == 200
            assert resp2.json()["scene_id"] == scene_id
            # Still only one task — no second enqueue.
            assert len(dispatcher.tasks) == 1

    def test_idempotency_already_processing_skips_reenqueue(self, client: TestClient) -> None:
        bundle_id = str(uuid.uuid4())
        bundle_bytes = _make_bundle()
        repo = InMemorySceneRepository()
        dispatcher = InMemoryTaskDispatcher()
        event = {"bucket": _BUCKET, "name": f"captures/{bundle_id}/bundle.pb"}

        with (
            patch.object(server, "_fetch_bundle_bytes", return_value=bundle_bytes),
            patch.object(server, "_blob_exists", return_value=True),
            patch.object(server, "_scene_repo", repo),
            patch.object(server, "_task_dispatcher", dispatcher),
            patch.object(server, "_fcm_notifier", NullFcmNotifier()),
            patch.object(server, "_upload_session_repo", InMemoryUploadSessionRepository()),
        ):
            # First fire → QUEUED.
            resp1 = client.post("/ingest/eventarc", json=event)
            scene_id = resp1.json()["scene_id"]
            # Advance scene to PROCESSING.
            repo.update_status(scene_id, SceneStatus.PROCESSING)

            # Second fire → idempotent.
            resp2 = client.post("/ingest/eventarc", json=event)
            assert resp2.status_code == 200
            assert resp2.json()["status"] == "processing"
            assert len(dispatcher.tasks) == 1  # still just one task

    def test_failed_incomplete_retries_with_existing_scene(self, client: TestClient) -> None:
        bundle_id = str(uuid.uuid4())
        bundle_bytes = _make_bundle()
        repo = InMemorySceneRepository()
        dispatcher = InMemoryTaskDispatcher()
        event = {"bucket": _BUCKET, "name": f"captures/{bundle_id}/bundle.pb"}

        with (
            patch.object(server, "_fetch_bundle_bytes", return_value=bundle_bytes),
            patch.object(server, "_scene_repo", repo),
            patch.object(server, "_task_dispatcher", dispatcher),
            patch.object(server, "_fcm_notifier", NullFcmNotifier()),
            patch.object(server, "_upload_session_repo", InMemoryUploadSessionRepository()),
        ):
            # First fire: one blob missing → failed_incomplete.
            with patch.object(server, "_blob_exists", return_value=False):
                resp1 = client.post("/ingest/eventarc", json=event)
            assert resp1.status_code == 200
            assert resp1.json()["status"] == "failed_incomplete"
            # Find the scene created.
            scenes = list(repo._store.values())
            assert len(scenes) == 1
            scene_id = scenes[0].scene_id
            assert scenes[0].status == SceneStatus.FAILED_INCOMPLETE
            assert len(dispatcher.tasks) == 0

            # Second fire: all blobs now present → should re-use same scene_id.
            with patch.object(server, "_blob_exists", return_value=True):
                resp2 = client.post("/ingest/eventarc", json=event)
            assert resp2.status_code == 200
            assert resp2.json()["status"] == "queued"
            assert resp2.json()["scene_id"] == scene_id
            assert len(dispatcher.tasks) == 1
            # Scene transitioned correctly.
            assert repo.get(scene_id).status == SceneStatus.QUEUED


# ---------------------------------------------------------------------------
# Existence-check pass
# ---------------------------------------------------------------------------

class TestExistenceCheck:
    def test_all_blobs_present_proceeds_to_queued(self, client: TestClient) -> None:
        bundle_bytes = _make_bundle(frame_count=2)
        repo = InMemorySceneRepository()
        dispatcher = InMemoryTaskDispatcher()

        with (
            patch.object(server, "_fetch_bundle_bytes", return_value=bundle_bytes),
            patch.object(server, "_blob_exists", return_value=True),
            patch.object(server, "_scene_repo", repo),
            patch.object(server, "_task_dispatcher", dispatcher),
        ):
            resp = client.post("/ingest", json={"bundle_gcs_uri": _BUNDLE_URI})

        assert resp.status_code == 200
        assert resp.json()["status"] == "queued"

    def test_one_blob_missing_returns_failed_incomplete(self, client: TestClient) -> None:
        bundle_bytes = _make_bundle(frame_count=2)
        repo = InMemorySceneRepository()

        def _exists(bucket: str, blob_path: str) -> bool:
            return "frames/000000.jpg" not in blob_path

        with (
            patch.object(server, "_fetch_bundle_bytes", return_value=bundle_bytes),
            patch.object(server, "_blob_exists", side_effect=_exists),
            patch.object(server, "_scene_repo", repo),
            patch.object(server, "_task_dispatcher", InMemoryTaskDispatcher()),
            patch.object(server, "_fcm_notifier", NullFcmNotifier()),
            patch.object(server, "_upload_session_repo", InMemoryUploadSessionRepository()),
        ):
            resp = client.post("/ingest", json={"bundle_gcs_uri": _BUNDLE_URI})

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "failed_incomplete"
        assert "frames/000000.jpg" in body["missing_paths"]

    def test_multiple_blobs_missing_all_listed(self, client: TestClient) -> None:
        bundle_bytes = _make_bundle(frame_count=3)
        repo = InMemorySceneRepository()

        with (
            patch.object(server, "_fetch_bundle_bytes", return_value=bundle_bytes),
            patch.object(server, "_blob_exists", return_value=False),
            patch.object(server, "_scene_repo", repo),
            patch.object(server, "_task_dispatcher", InMemoryTaskDispatcher()),
            patch.object(server, "_fcm_notifier", NullFcmNotifier()),
            patch.object(server, "_upload_session_repo", InMemoryUploadSessionRepository()),
        ):
            resp = client.post("/ingest", json={"bundle_gcs_uri": _BUNDLE_URI})

        body = resp.json()
        assert body["status"] == "failed_incomplete"
        # All 3 rgb frames should be listed.
        assert len(body["missing_paths"]) == 3

    def test_scene_marked_failed_incomplete_in_repo(self, client: TestClient) -> None:
        bundle_bytes = _make_bundle(frame_count=2)
        repo = InMemorySceneRepository()

        with (
            patch.object(server, "_fetch_bundle_bytes", return_value=bundle_bytes),
            patch.object(server, "_blob_exists", return_value=False),
            patch.object(server, "_scene_repo", repo),
            patch.object(server, "_task_dispatcher", InMemoryTaskDispatcher()),
            patch.object(server, "_fcm_notifier", NullFcmNotifier()),
            patch.object(server, "_upload_session_repo", InMemoryUploadSessionRepository()),
        ):
            resp = client.post("/ingest", json={"bundle_gcs_uri": _BUNDLE_URI})

        assert resp.json()["status"] == "failed_incomplete"
        scenes = list(repo._store.values())
        assert len(scenes) == 1
        assert scenes[0].status == SceneStatus.FAILED_INCOMPLETE
        assert scenes[0].missing_paths

    def test_failed_incomplete_scene_has_user_id_from_upload_session(
        self, client: TestClient
    ) -> None:
        """Scene created on the failed-incomplete branch must carry user_id from the
        upload session, not be left as None (decision 0022)."""
        bundle_id = str(uuid.uuid4())
        bundle_uri = f"gs://{_BUCKET}/captures/{bundle_id}/bundle.pb"
        bundle_bytes = _make_bundle(frame_count=1)

        upload_repo = InMemoryUploadSessionRepository()
        upload_repo._store[bundle_id] = {
            "user_id": "uid-from-session-42",
            "fcm_token": None,
            "manifest": [],
            "session_entries": [],
            "created_at": None,
        }
        repo = InMemorySceneRepository()

        with (
            patch.object(server, "_fetch_bundle_bytes", return_value=bundle_bytes),
            patch.object(server, "_blob_exists", return_value=False),
            patch.object(server, "_scene_repo", repo),
            patch.object(server, "_task_dispatcher", InMemoryTaskDispatcher()),
            patch.object(server, "_fcm_notifier", NullFcmNotifier()),
            patch.object(server, "_upload_session_repo", upload_repo),
        ):
            resp = client.post("/ingest", json={"bundle_gcs_uri": bundle_uri})

        assert resp.json()["status"] == "failed_incomplete"
        scenes = list(repo._store.values())
        assert len(scenes) == 1
        assert scenes[0].user_id == "uid-from-session-42"

    def test_fcm_notifier_called_when_upload_incomplete(self, client: TestClient) -> None:
        bundle_id = str(uuid.uuid4())
        bundle_uri = f"gs://{_BUCKET}/captures/{bundle_id}/bundle.pb"
        bundle_bytes = _make_bundle(frame_count=1)
        upload_repo = InMemoryUploadSessionRepository()

        # Seed an FCM token for this bundle_id.
        def _fake_mint(bucket, blob_path, size):
            return f"https://fake/{blob_path}"

        upload_repo._store[bundle_id] = {
            "user_id": "u1",
            "fcm_token": "fcm-token-xyz",
            "manifest": [],
            "session_entries": [],
            "created_at": None,
        }

        mock_notifier = MagicMock(spec=NullFcmNotifier)

        with (
            patch.object(server, "_fetch_bundle_bytes", return_value=bundle_bytes),
            patch.object(server, "_blob_exists", return_value=False),
            patch.object(server, "_scene_repo", InMemorySceneRepository()),
            patch.object(server, "_task_dispatcher", InMemoryTaskDispatcher()),
            patch.object(server, "_fcm_notifier", mock_notifier),
            patch.object(server, "_upload_session_repo", upload_repo),
        ):
            resp = client.post("/ingest", json={"bundle_gcs_uri": bundle_uri})

        assert resp.json()["status"] == "failed_incomplete"
        mock_notifier.notify_upload_incomplete.assert_called_once()
        kwargs = mock_notifier.notify_upload_incomplete.call_args.kwargs
        assert kwargs["fcm_token"] == "fcm-token-xyz"
        assert kwargs["missing_paths"]

    def test_no_fcm_called_when_all_blobs_present(self, client: TestClient) -> None:
        bundle_bytes = _make_bundle(frame_count=1)
        mock_notifier = MagicMock(spec=NullFcmNotifier)

        with (
            patch.object(server, "_fetch_bundle_bytes", return_value=bundle_bytes),
            patch.object(server, "_blob_exists", return_value=True),
            patch.object(server, "_scene_repo", InMemorySceneRepository()),
            patch.object(server, "_task_dispatcher", InMemoryTaskDispatcher()),
            patch.object(server, "_fcm_notifier", mock_notifier),
            patch.object(server, "_upload_session_repo", InMemoryUploadSessionRepository()),
        ):
            resp = client.post("/ingest", json={"bundle_gcs_uri": _BUNDLE_URI})

        assert resp.json()["status"] == "queued"
        mock_notifier.notify_upload_incomplete.assert_not_called()

    def test_bundle_without_frames_skips_existence_check(self, client: TestClient) -> None:
        """A bundle with no frames has no blob paths to check; ingest proceeds."""
        b = CaptureBundle()
        b.schema_version = SCHEMA_VERSION
        b.bundle_id = str(uuid.uuid4())
        b.user_id = "u"
        b.device.hardware_id = "d"
        b.tier = ARKIT_ONLY
        b.started_at_device_us = 0
        b.ended_at_device_us = 1
        bundle_bytes = b.SerializeToString()

        repo = InMemorySceneRepository()
        exists_mock = MagicMock(return_value=True)

        with (
            patch.object(server, "_fetch_bundle_bytes", return_value=bundle_bytes),
            patch.object(server, "_blob_exists", exists_mock),
            patch.object(server, "_scene_repo", repo),
            patch.object(server, "_task_dispatcher", InMemoryTaskDispatcher()),
        ):
            resp = client.post("/ingest", json={"bundle_gcs_uri": _BUNDLE_URI})

        assert resp.status_code == 200
        assert resp.json()["status"] == "queued"
        exists_mock.assert_not_called()

    def test_depth_blobs_checked(self, client: TestClient) -> None:
        """Existence check covers depth_gcs_path, not just rgb_gcs_path."""
        bundle_bytes = _make_bundle(frame_count=1, add_depth=True)
        checked_paths: list[str] = []

        def _exists(bucket: str, blob_path: str) -> bool:
            checked_paths.append(blob_path)
            return True

        with (
            patch.object(server, "_fetch_bundle_bytes", return_value=bundle_bytes),
            patch.object(server, "_blob_exists", side_effect=_exists),
            patch.object(server, "_scene_repo", InMemorySceneRepository()),
            patch.object(server, "_task_dispatcher", InMemoryTaskDispatcher()),
        ):
            client.post("/ingest", json={"bundle_gcs_uri": _BUNDLE_URI})

        assert any("depth" in p for p in checked_paths), (
            f"Expected depth paths to be checked, got: {checked_paths}"
        )
