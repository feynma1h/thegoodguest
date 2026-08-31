"""Tests for POST /ingest/eventarc and the existence-check pass in _run_ingest.

Covers:
  Eventarc endpoint:
    - Valid GCS finalize event → dispatches ingest and returns 200
    - Schema-invalid bundle → 200 + failed_invalid Scene, no GPU dispatch
      (200 prevents Pub/Sub retry; Scene makes rejection pollable — see decision 0031)
    - Missing 'bucket' or 'name' in event body → 400
    - object name that doesn't match captures/*/bundle.pb → 200 eventarc_ignored
      (not 400 — the trigger is bucket-wide; non-bundle.pb events must be
      acknowledged so Pub/Sub does not retry; see decision 0023)
    - Idempotency: scene already QUEUED → 200, no re-enqueue
    - Idempotency: scene already PROCESSING → 200, no re-enqueue
    - Idempotency: scene FAILED_INCOMPLETE → re-runs ingest with existing scene_id
    - Idempotency: scene FAILED → re-runs ingest with existing scene_id (no duplicate)

  Existence-check pass (tested through /ingest/eventarc):
    - All blobs present → scene reaches QUEUED (proceeds normally)
    - One blob missing → status=failed_incomplete, missing_paths in response
    - Multiple blobs missing → all listed in missing_paths
    - No frames in bundle → no existence check needed (no paths to check)
    - FCM notifier called with correct token when upload incomplete
    - Scene transitions from QUEUED to FAILED_INCOMPLETE in repo on missing blob

NullFcmNotifier is used for all tests. _blob_exists and _fetch_bundle_bytes
are patched so no GCS credentials are needed.

Run from repo root:
  pytest services/api-internal/tests/test_ingest_eventarc.py -v
"""
from __future__ import annotations

import time
import uuid
from unittest.mock import MagicMock, patch, call

import pytest
from fastapi.testclient import TestClient

from thegoodguest_schemas import (
    ARKIT_ONLY,
    LIDAR_ARKIT,
    LIDAR_ROOMPLAN,
    SCHEMA_VERSION,
    CaptureBundle,
)

import ingest_server as server  # noqa: E402
from repository import InMemorySceneRepository  # noqa: E402
from dispatcher import InMemoryTaskDispatcher  # noqa: E402
from scene import SceneStatus  # noqa: E402
from fcm import NullFcmNotifier  # noqa: E402
from thegoodguest_api_core.upload_session_repo import InMemoryUploadSessionRepository  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(server.app)


def _post_bundle_event(client: TestClient, bundle_uri: str):
    """POST the Eventarc finalize event for a gs://bucket/path bundle URI.

    /ingest/eventarc is the only ingest entry point (the legacy direct
    /ingest route was removed); tests reach _run_ingest through it.
    """
    bucket, name = bundle_uri[5:].split("/", 1)
    return client.post("/ingest/eventarc", json={"bucket": bucket, "name": name})


# ---------------------------------------------------------------------------
# Bundle builder
# ---------------------------------------------------------------------------

_BUCKET = "test-bucket"
_BUNDLE_ID = str(uuid.uuid4())
_BUNDLE_URI = f"gs://{_BUCKET}/captures/{_BUNDLE_ID}/bundle.pb"

_EVENTARC_BODY = {"bucket": _BUCKET, "name": f"captures/{_BUNDLE_ID}/bundle.pb"}


def _make_bundle(
    *,
    bundle_id: str = _BUNDLE_ID,
    frame_count: int = 2,
    add_depth: bool = False,
    add_roomplan: bool = False,
) -> bytes:
    """bundle_id must match the id in the URI the test posts — the
    validate_bundle cross-check rejects any divergence. The default matches
    the module-level _BUNDLE_URI/_EVENTARC_BODY; tests minting their own
    per-test bundle_id must pass it here too.

    add_roomplan mints the LIDAR_ROOMPLAN shape the co-run ships: depth frames
    plus a RoomPlanModel declaring both roomplan blobs."""
    if add_roomplan:
        add_depth = True
    tier = LIDAR_ARKIT if add_depth else ARKIT_ONLY
    if add_roomplan:
        tier = LIDAR_ROOMPLAN
    b = CaptureBundle()
    b.schema_version = SCHEMA_VERSION
    b.bundle_id = bundle_id
    b.user_id = "test-user"
    b.device.device_id = str(uuid.uuid4())
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
    if add_roomplan:
        b.room_plan.json_gcs_path = "roomplan/room.json"
        b.room_plan.usdz_gcs_path = "roomplan/room.usdz"
        b.room_plan.roomplan_version = "test;CapturedRoom.v2;beautifyObjects"
    return b.SerializeToString()


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
            patch.object(server, "_validate_image_blobs", return_value=[]),
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

    def test_bad_schema_version_creates_failed_invalid_scene(self, client: TestClient) -> None:
        """Schema-invalid bundle via Eventarc → 200 + failed_invalid Scene, no GPU dispatch.

        This is the load-bearing test for the schema-rejection path:
          - HTTP 200 (not 400) so Pub/Sub acknowledges and does not retry.
            A non-2xx would cause a retry storm across every stale iOS client
            at a schema bump (see decision 0031).
          - failed_invalid Scene created so the iOS client can observe the
            rejection via GET /scenes/by-bundle/{bundle_id} polling.
          - last_error names the rejection kind (operator discriminator —
            both schema and image-decode share the failed_invalid bucket).
          - Image-decode check (_validate_image_blobs) is never reached;
            schema gate fires first.
        """
        bundle_id = str(uuid.uuid4())
        eventarc_body = {"bucket": _BUCKET, "name": f"captures/{bundle_id}/bundle.pb"}

        b = CaptureBundle()
        b.schema_version = "1.0.0"   # the old value, rejected post-0031
        b.bundle_id = bundle_id
        b.user_id = "test-user"
        b.device.device_id = str(uuid.uuid4())
        b.device.hardware_id = "test-device"
        b.tier = ARKIT_ONLY
        b.started_at_device_us = 0
        b.ended_at_device_us = 1
        bad_bundle_bytes = b.SerializeToString()

        repo = InMemorySceneRepository()
        mock_image_check = MagicMock(return_value=[])

        with (
            patch.object(server, "_fetch_bundle_bytes", return_value=bad_bundle_bytes),
            patch.object(server, "_validate_image_blobs", mock_image_check),
            patch.object(server, "_scene_repo", repo),
            patch.object(server, "_upload_session_repo", InMemoryUploadSessionRepository()),
            patch.object(server, "_fcm_notifier", NullFcmNotifier()),
        ):
            resp = client.post("/ingest/eventarc", json=eventarc_body)

        # Must be 200 — non-2xx triggers Pub/Sub redelivery.
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "failed_invalid"
        assert body["error"] == "unsupported_schema_version"

        # Scene must exist so the client can poll to a terminal state.
        scenes = list(repo._store.values())
        assert len(scenes) == 1
        scene = scenes[0]
        assert scene.status == SceneStatus.FAILED_INVALID
        assert scene.bundle_id == bundle_id
        # last_error names the rejection kind — operator discriminator.
        assert "unsupported_schema_version" in (scene.last_error or "")

        # Image-decode check must not have run — schema gate fires first.
        mock_image_check.assert_not_called()

    def test_missing_bucket_returns_400(self, client: TestClient) -> None:
        resp = client.post("/ingest/eventarc", json={"name": f"captures/{_BUNDLE_ID}/bundle.pb"})
        assert resp.status_code == 400
        assert resp.json()["error"] == "bad_event"

    def test_missing_name_returns_400(self, client: TestClient) -> None:
        resp = client.post("/ingest/eventarc", json={"bucket": _BUCKET})
        assert resp.status_code == 400
        assert resp.json()["error"] == "bad_event"

    def test_name_not_bundle_pb_returns_200_ignored(self, client: TestClient) -> None:
        """Non-bundle.pb finalize events must return 200 (not 400) so Pub/Sub
        acknowledges the message and does not enter the retry loop.
        The trigger is bucket-wide; pixel-blob events are expected traffic.
        See decision 0023."""
        resp = client.post(
            "/ingest/eventarc",
            json={"bucket": _BUCKET, "name": f"captures/{_BUNDLE_ID}/frames/000000.jpg"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["event"] == "eventarc_ignored"
        assert body["reason"] == "not_bundle_pb"
        assert "frames/000000.jpg" in body["object_name"]

    def test_idempotency_already_queued_skips_reenqueue(self, client: TestClient) -> None:
        bundle_id = str(uuid.uuid4())
        bundle_uri = f"gs://{_BUCKET}/captures/{bundle_id}/bundle.pb"
        bundle_bytes = _make_bundle(bundle_id=bundle_id)
        repo = InMemorySceneRepository()
        dispatcher = InMemoryTaskDispatcher()

        event = {"bucket": _BUCKET, "name": f"captures/{bundle_id}/bundle.pb"}

        with (
            patch.object(server, "_fetch_bundle_bytes", return_value=bundle_bytes),
            patch.object(server, "_blob_exists", return_value=True),
            patch.object(server, "_validate_image_blobs", return_value=[]),
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
        bundle_bytes = _make_bundle(bundle_id=bundle_id)
        repo = InMemorySceneRepository()
        dispatcher = InMemoryTaskDispatcher()
        event = {"bucket": _BUCKET, "name": f"captures/{bundle_id}/bundle.pb"}

        with (
            patch.object(server, "_fetch_bundle_bytes", return_value=bundle_bytes),
            patch.object(server, "_blob_exists", return_value=True),
            patch.object(server, "_validate_image_blobs", return_value=[]),
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

    def test_idempotency_failed_invalid_skips_reenqueue(self, client: TestClient) -> None:
        """FAILED_INVALID is terminal — a second Eventarc event for the same
        bundle_id must return 200 immediately without re-running ingest.

        Unlike FAILED_INCOMPLETE (missing blobs that a re-upload can supply),
        FAILED_INVALID means the bytes were present but non-decodable. There
        is nothing a second finalize event can do to fix that."""
        bundle_id = str(uuid.uuid4())
        bundle_bytes = _make_bundle(bundle_id=bundle_id)
        repo = InMemorySceneRepository()
        dispatcher = InMemoryTaskDispatcher()
        event = {"bucket": _BUCKET, "name": f"captures/{bundle_id}/bundle.pb"}

        invalid = [{"relative_path": "frames/000000.jpg", "reason": "too_small"}]

        with (
            patch.object(server, "_fetch_bundle_bytes", return_value=bundle_bytes),
            patch.object(server, "_blob_exists", return_value=True),
            patch.object(server, "_validate_image_blobs", return_value=invalid),
            patch.object(server, "_scene_repo", repo),
            patch.object(server, "_task_dispatcher", dispatcher),
            patch.object(server, "_fcm_notifier", NullFcmNotifier()),
            patch.object(server, "_upload_session_repo", InMemoryUploadSessionRepository()),
        ):
            # First fire → FAILED_INVALID.
            resp1 = client.post("/ingest/eventarc", json=event)
            assert resp1.status_code == 200
            assert resp1.json()["status"] == "failed_invalid"
            scenes = list(repo._store.values())
            scene_id = scenes[0].scene_id
            assert len(dispatcher.tasks) == 0

            # Second fire → idempotent skip (FAILED_INVALID is terminal).
            resp2 = client.post("/ingest/eventarc", json=event)
            assert resp2.status_code == 200
            assert resp2.json()["status"] == "failed_invalid"
            assert resp2.json()["scene_id"] == scene_id
            # No additional scenes created, no tasks enqueued.
            assert len(list(repo._store.values())) == 1
            assert len(dispatcher.tasks) == 0

    def test_failed_incomplete_retries_with_existing_scene(self, client: TestClient) -> None:
        bundle_id = str(uuid.uuid4())
        bundle_bytes = _make_bundle(bundle_id=bundle_id)
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
            with (
                patch.object(server, "_blob_exists", return_value=True),
                patch.object(server, "_validate_image_blobs", return_value=[]),
            ):
                resp2 = client.post("/ingest/eventarc", json=event)
            assert resp2.status_code == 200
            assert resp2.json()["status"] == "queued"
            assert resp2.json()["scene_id"] == scene_id
            assert len(dispatcher.tasks) == 1
            # Scene transitioned correctly.
            assert repo.get(scene_id).status == SceneStatus.QUEUED

    def test_failed_retries_with_existing_scene_no_duplicate(self, client: TestClient) -> None:
        """Redelivery for a FAILED scene retries with the SAME scene_id.

        FAILED at ingest means dispatch failed and we returned 500, so Pub/Sub
        redelivers — the redelivery must reuse the existing Scene (FAILED →
        QUEUED) rather than falling through to a fresh ingest and creating a
        duplicate Scene per retry."""
        bundle_id = str(uuid.uuid4())
        bundle_bytes = _make_bundle(bundle_id=bundle_id)
        repo = InMemorySceneRepository()
        event = {"bucket": _BUCKET, "name": f"captures/{bundle_id}/bundle.pb"}

        failing_dispatcher = MagicMock(spec=InMemoryTaskDispatcher)
        failing_dispatcher.enqueue.side_effect = RuntimeError("cloud tasks unavailable")
        working_dispatcher = InMemoryTaskDispatcher()

        with (
            patch.object(server, "_fetch_bundle_bytes", return_value=bundle_bytes),
            patch.object(server, "_blob_exists", return_value=True),
            patch.object(server, "_validate_image_blobs", return_value=[]),
            patch.object(server, "_scene_repo", repo),
            patch.object(server, "_fcm_notifier", NullFcmNotifier()),
            patch.object(server, "_upload_session_repo", InMemoryUploadSessionRepository()),
        ):
            # First fire: dispatch fails → 500, scene FAILED.
            with patch.object(server, "_task_dispatcher", failing_dispatcher):
                resp1 = client.post("/ingest/eventarc", json=event)
            assert resp1.status_code == 500
            scenes = list(repo._store.values())
            assert len(scenes) == 1
            scene_id = scenes[0].scene_id
            assert scenes[0].status == SceneStatus.FAILED

            # Redelivery: dispatch now works → same scene retried, no duplicate.
            with patch.object(server, "_task_dispatcher", working_dispatcher):
                resp2 = client.post("/ingest/eventarc", json=event)
            assert resp2.status_code == 200
            assert resp2.json()["status"] == "queued"
            assert resp2.json()["scene_id"] == scene_id
            assert len(list(repo._store.values())) == 1  # no duplicate Scene
            assert len(working_dispatcher.tasks) == 1
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
            patch.object(server, "_validate_image_blobs", return_value=[]),
            patch.object(server, "_scene_repo", repo),
            patch.object(server, "_task_dispatcher", dispatcher),
        ):
            resp = _post_bundle_event(client, _BUNDLE_URI)

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
            resp = _post_bundle_event(client, _BUNDLE_URI)

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
            resp = _post_bundle_event(client, _BUNDLE_URI)

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
            resp = _post_bundle_event(client, _BUNDLE_URI)

        assert resp.json()["status"] == "failed_incomplete"
        scenes = list(repo._store.values())
        assert len(scenes) == 1
        assert scenes[0].status == SceneStatus.FAILED_INCOMPLETE
        assert scenes[0].missing_paths

    def test_roomplan_bundle_needs_its_room_json(self, client: TestClient) -> None:
        """Decision 0105: every declared blob must have arrived. The client
        sets LIDAR_ROOMPLAN only when room.json actually shipped, so a
        ROOMPLAN bundle without it is a lost upload — held here for a
        re-upload, not dispatched onto the GPU to render the LiDAR-ARKit
        shell the user did not scan for."""
        bundle_bytes = _make_bundle(frame_count=2, add_roomplan=True)
        repo = InMemorySceneRepository()
        dispatcher = InMemoryTaskDispatcher()

        def _exists(bucket: str, blob_path: str) -> bool:
            return not blob_path.endswith("roomplan/room.json")

        with (
            patch.object(server, "_fetch_bundle_bytes", return_value=bundle_bytes),
            patch.object(server, "_blob_exists", side_effect=_exists),
            patch.object(server, "_validate_image_blobs", return_value=[]),
            patch.object(server, "_scene_repo", repo),
            patch.object(server, "_task_dispatcher", dispatcher),
            patch.object(server, "_fcm_notifier", NullFcmNotifier()),
            patch.object(server, "_upload_session_repo", InMemoryUploadSessionRepository()),
        ):
            resp = _post_bundle_event(client, _BUNDLE_URI)

        body = resp.json()
        assert body["status"] == "failed_incomplete"
        assert body["missing_paths"] == ["roomplan/room.json"]
        # Never reaches the GPU: a degraded run burns ~1,500 GPU-seconds
        # (decision 0098) to produce a shell the capture did not ask for.
        assert dispatcher.tasks == []

    def test_roomplan_bundle_dispatches_when_room_json_arrived(
        self, client: TestClient
    ) -> None:
        """The other half of the same rule: present means proceed."""
        bundle_bytes = _make_bundle(frame_count=2, add_roomplan=True)
        repo = InMemorySceneRepository()
        dispatcher = InMemoryTaskDispatcher()

        with (
            patch.object(server, "_fetch_bundle_bytes", return_value=bundle_bytes),
            patch.object(server, "_blob_exists", return_value=True),
            patch.object(server, "_validate_image_blobs", return_value=[]),
            patch.object(server, "_scene_repo", repo),
            patch.object(server, "_task_dispatcher", dispatcher),
            patch.object(server, "_fcm_notifier", NullFcmNotifier()),
            patch.object(server, "_upload_session_repo", InMemoryUploadSessionRepository()),
        ):
            resp = _post_bundle_event(client, _BUNDLE_URI)

        assert resp.json()["status"] == "queued"

    def test_roomplan_usdz_stays_required(self, client: TestClient) -> None:
        """The usdz half needs no special case. It is declared, so the rule
        covers it — which is the point of stating a rule instead of listing
        fields. If a future decision stops uploading it, it stops being
        declared and drops out of the check on its own."""
        bundle_bytes = _make_bundle(frame_count=2, add_roomplan=True)

        def _exists(bucket: str, blob_path: str) -> bool:
            return not blob_path.endswith("roomplan/room.usdz")

        with (
            patch.object(server, "_fetch_bundle_bytes", return_value=bundle_bytes),
            patch.object(server, "_blob_exists", side_effect=_exists),
            patch.object(server, "_validate_image_blobs", return_value=[]),
            patch.object(server, "_scene_repo", InMemorySceneRepository()),
            patch.object(server, "_task_dispatcher", InMemoryTaskDispatcher()),
            patch.object(server, "_fcm_notifier", NullFcmNotifier()),
            patch.object(server, "_upload_session_repo", InMemoryUploadSessionRepository()),
        ):
            resp = _post_bundle_event(client, _BUNDLE_URI)

        assert resp.json()["missing_paths"] == ["roomplan/room.usdz"]

    def test_non_roomplan_bundles_are_unaffected(self, client: TestClient) -> None:
        """The degrade lock. A bundle with no room_plan message collects
        exactly the paths it collected before decision 0105 — the rule only
        ever adds what a bundle itself declares."""
        for kwargs in ({}, {"add_depth": True}):
            bundle = CaptureBundle()
            bundle.ParseFromString(_make_bundle(frame_count=3, **kwargs))
            assert not bundle.HasField("room_plan")
            paths = server._collect_bundle_blob_paths(bundle)
            expected = [f"frames/{i:06d}.jpg" for i in range(3)]
            if kwargs.get("add_depth"):
                expected = [
                    p
                    for i in range(3)
                    for p in (f"frames/{i:06d}.jpg", f"depth/{i:06d}.f32")
                ]
            assert paths == expected

    def test_failed_incomplete_scene_has_user_id_from_upload_session(
        self, client: TestClient
    ) -> None:
        """Scene created on the failed-incomplete branch must carry user_id from the
        upload session, not be left as None (decision 0022)."""
        bundle_id = str(uuid.uuid4())
        bundle_uri = f"gs://{_BUCKET}/captures/{bundle_id}/bundle.pb"
        bundle_bytes = _make_bundle(bundle_id=bundle_id, frame_count=1)

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
            resp = _post_bundle_event(client, bundle_uri)

        assert resp.json()["status"] == "failed_incomplete"
        scenes = list(repo._store.values())
        assert len(scenes) == 1
        assert scenes[0].user_id == "uid-from-session-42"

    def test_queued_scene_carries_fcm_token_from_upload_session(
        self, client: TestClient
    ) -> None:
        """A happy-path Scene must capture fcm_token from the upload session so
        perception-obj can notify the device on terminal transitions
        (ClaimResult.fcm_token → notify_ready/notify_failed)."""
        bundle_id = str(uuid.uuid4())
        bundle_uri = f"gs://{_BUCKET}/captures/{bundle_id}/bundle.pb"
        bundle_bytes = _make_bundle(bundle_id=bundle_id, frame_count=1)

        upload_repo = InMemoryUploadSessionRepository()
        upload_repo._store[bundle_id] = {
            "user_id": "uid-from-session-42",
            "fcm_token": "fcm-reg-token-abc",
            "manifest": [],
            "session_entries": [],
            "created_at": None,
        }
        repo = InMemorySceneRepository()

        with (
            patch.object(server, "_fetch_bundle_bytes", return_value=bundle_bytes),
            patch.object(server, "_blob_exists", return_value=True),
            patch.object(server, "_validate_image_blobs", return_value=[]),
            patch.object(server, "_scene_repo", repo),
            patch.object(server, "_task_dispatcher", InMemoryTaskDispatcher()),
            patch.object(server, "_fcm_notifier", NullFcmNotifier()),
            patch.object(server, "_upload_session_repo", upload_repo),
        ):
            resp = _post_bundle_event(client, bundle_uri)

        assert resp.json()["status"] == "queued"
        scenes = list(repo._store.values())
        assert len(scenes) == 1
        assert scenes[0].status == SceneStatus.QUEUED
        assert scenes[0].fcm_token == "fcm-reg-token-abc"

    def test_fcm_notifier_called_when_upload_incomplete(self, client: TestClient) -> None:
        bundle_id = str(uuid.uuid4())
        bundle_uri = f"gs://{_BUCKET}/captures/{bundle_id}/bundle.pb"
        bundle_bytes = _make_bundle(bundle_id=bundle_id, frame_count=1)
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
            resp = _post_bundle_event(client, bundle_uri)

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
            patch.object(server, "_validate_image_blobs", return_value=[]),
            patch.object(server, "_scene_repo", InMemorySceneRepository()),
            patch.object(server, "_task_dispatcher", InMemoryTaskDispatcher()),
            patch.object(server, "_fcm_notifier", mock_notifier),
            patch.object(server, "_upload_session_repo", InMemoryUploadSessionRepository()),
        ):
            resp = _post_bundle_event(client, _BUNDLE_URI)

        assert resp.json()["status"] == "queued"
        mock_notifier.notify_upload_incomplete.assert_not_called()

    def test_bundle_without_frames_skips_existence_check(self, client: TestClient) -> None:
        """A bundle with no frames has no blob paths to check; ingest proceeds."""
        b = CaptureBundle()
        b.schema_version = SCHEMA_VERSION
        b.bundle_id = _BUNDLE_ID  # matches _BUNDLE_URI — passes the cross-check
        b.user_id = "u"
        b.device.device_id = str(uuid.uuid4())
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
            patch.object(server, "_validate_image_blobs", return_value=[]),
            patch.object(server, "_scene_repo", repo),
            patch.object(server, "_task_dispatcher", InMemoryTaskDispatcher()),
        ):
            resp = _post_bundle_event(client, _BUNDLE_URI)

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
            patch.object(server, "_validate_image_blobs", return_value=[]),
            patch.object(server, "_scene_repo", InMemorySceneRepository()),
            patch.object(server, "_task_dispatcher", InMemoryTaskDispatcher()),
        ):
            _post_bundle_event(client, _BUNDLE_URI)

        assert any("depth" in p for p in checked_paths), (
            f"Expected depth paths to be checked, got: {checked_paths}"
        )
