"""Integration tests for the core ingest pipeline (_run_ingest).

Requests enter through POST /ingest/eventarc (the only ingest entry point;
the legacy direct /ingest route was removed) via the _post_bundle_event
helper. Tests are structured around the validation checks in validation.py,
plus happy paths and dispatch integration:
  - valid ARKIT_ONLY bundle → 200 + {scene_id, status: "queued"}
  - valid LIDAR_ARKIT bundle with depth → 200 + {scene_id, status: "queued"}
  - dispatch happy path — Scene created in repo, task enqueued with correct shape
  - dispatch failure mode — dispatcher raises → 500, Scene marked failed
  - unsupported schema_version → 200 + failed_invalid Scene
  - proto bundle_id ≠ URI-derived bundle_id → 200 + failed_invalid Scene
    (including case-differing and empty proto bundle_id)
  - missing device_id → 200 + failed_invalid Scene ("unknown" sentinel)
  - non-unit quaternion → 200 + failed_invalid Scene
  - depth frame on ARKIT_ONLY tier → 200 + failed_invalid Scene
  - absolute gs:// path → 200 + failed_invalid Scene
  - malformed proto bytes → 400 bundle_parse_failed

Bundle builders take a bundle_id that must match the bundle_id in the URI
the test posts (the validate_bundle cross-check rejects any divergence —
the pre-crosscheck fixtures here used to carry a random UUID against a
"test" URI, exactly the silent mismatch the check now catches).

The GCS fetch (_fetch_bundle_bytes) is patched out in every test.
Bundles are built in-memory using thegoodguest_schemas directly — no file I/O,
no network, no GCS credentials required.

Run from repo root:
  pytest services/api-internal/tests/ -v
"""
from __future__ import annotations

import time
import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock

from thegoodguest_schemas import (
    ARKIT_ONLY,
    LIDAR_ARKIT,
    LIDAR_ROOMPLAN,
    SCHEMA_VERSION,
    CaptureBundle,
)

import ingest_server as server  # the service module  # noqa: E402
from repository import InMemorySceneRepository  # noqa: E402
from dispatcher import InMemoryTaskDispatcher  # noqa: E402
from scene import SceneStatus  # noqa: E402
from validation import validate_bundle  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client() -> TestClient:
    """A TestClient for the ingester app. Module-scoped: the app is stateless
    so one client per test module is fine."""
    return TestClient(server.app)


def _post_bundle_event(client: TestClient, bundle_uri: str):
    """POST the Eventarc finalize event for a gs://bucket/path bundle URI.

    /ingest/eventarc is the only ingest entry point (the legacy direct
    /ingest route was removed); tests reach _run_ingest through it.
    """
    bucket, name = bundle_uri[5:].split("/", 1)
    return client.post("/ingest/eventarc", json={"bucket": bucket, "name": name})


# ---------------------------------------------------------------------------
# Bundle builders
# ---------------------------------------------------------------------------

def _make_bundle(
    *,
    schema_version: str = SCHEMA_VERSION,
    bundle_id: str = "test",
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

    bundle_id defaults to "test" — matching the captures/test/bundle.pb URIs
    this module posts — so the default bundle passes the bundle_id
    cross-check. Tests posting a different URI must pass the matching id.
    """
    if tier is None:
        tier = LIDAR_ARKIT if add_depth else ARKIT_ONLY

    b = CaptureBundle()
    b.schema_version = schema_version
    b.bundle_id = bundle_id
    b.user_id = "test-user"
    b.device.device_id = str(uuid.uuid4())
    b.device.hardware_id = "test-device"
    b.device.has_lidar = tier in (LIDAR_ARKIT,)
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
    """Well-formed ARKIT_ONLY bundle → 200 with {scene_id, status: queued}."""
    bundle_bytes = _make_bundle(frame_count=3)
    with patch.object(server, "_fetch_bundle_bytes", return_value=bundle_bytes), \
         patch.object(server, "_blob_exists", return_value=True), \
         patch.object(server, "_validate_image_blobs", return_value=[]), \
         patch.object(server, "_scene_repo", InMemorySceneRepository()), \
         patch.object(server, "_task_dispatcher", InMemoryTaskDispatcher()):
        resp = _post_bundle_event(client, "gs://test-bucket/captures/test/bundle.pb")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body["scene_id"], str) and body["scene_id"]
    assert body["status"] == "queued"


def test_valid_lidar_bundle_returns_200(client: TestClient) -> None:
    """Well-formed LIDAR_ARKIT bundle with depth on every frame → 200."""
    bundle_bytes = _make_bundle(frame_count=2, add_depth=True)
    with patch.object(server, "_fetch_bundle_bytes", return_value=bundle_bytes), \
         patch.object(server, "_blob_exists", return_value=True), \
         patch.object(server, "_validate_image_blobs", return_value=[]), \
         patch.object(server, "_scene_repo", InMemorySceneRepository()), \
         patch.object(server, "_task_dispatcher", InMemoryTaskDispatcher()):
        resp = _post_bundle_event(client, "gs://test-bucket/captures/test/bundle.pb")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body["scene_id"], str) and body["scene_id"]
    assert body["status"] == "queued"


# ---------------------------------------------------------------------------
# Dispatch integration
# ---------------------------------------------------------------------------

_BUNDLE_URI = "gs://test-bucket/captures/test/bundle.pb"


def test_dispatch_happy_path_scene_and_task_created(client: TestClient) -> None:
    """On a valid bundle: Scene is created with status=queued and exactly one
    task is enqueued with task_name==scene_id and the correct payload shape."""
    bundle_bytes = _make_bundle(frame_count=2)
    repo = InMemorySceneRepository()
    dispatcher = InMemoryTaskDispatcher()

    with patch.object(server, "_fetch_bundle_bytes", return_value=bundle_bytes), \
         patch.object(server, "_blob_exists", return_value=True), \
         patch.object(server, "_validate_image_blobs", return_value=[]), \
         patch.object(server, "_scene_repo", repo), \
         patch.object(server, "_task_dispatcher", dispatcher):
        resp = _post_bundle_event(client, _BUNDLE_URI)

    assert resp.status_code == 200
    body = resp.json()
    scene_id = body["scene_id"]
    assert isinstance(scene_id, str) and scene_id
    assert body["status"] == "queued"

    # Scene was persisted.
    scene = repo.get(scene_id)
    assert scene.status == SceneStatus.QUEUED
    assert scene.bundle_uri == _BUNDLE_URI

    # Exactly one task was enqueued.
    assert len(dispatcher.tasks) == 1
    task = dispatcher.tasks[0]

    # task_name == scene_id — Cloud Tasks dedup contract.
    assert task["task_name"] == scene_id

    # Payload carries the two fields perception-obj needs.
    assert task["payload"]["scene_id"] == scene_id
    assert task["payload"]["bundle_uri"] == _BUNDLE_URI

    # target_url is set (defaults to http://localhost:8081/process in tests).
    assert task["target_url"]


def test_dispatch_failure_returns_500_and_marks_scene_failed(client: TestClient) -> None:
    """If the dispatcher raises, /ingest returns 500 and the Scene is marked
    failed — no orphaned queued records."""
    bundle_bytes = _make_bundle(frame_count=2)
    repo = InMemorySceneRepository()

    failing_dispatcher = MagicMock(spec=InMemoryTaskDispatcher)
    failing_dispatcher.enqueue.side_effect = RuntimeError("cloud tasks unavailable")

    with patch.object(server, "_fetch_bundle_bytes", return_value=bundle_bytes), \
         patch.object(server, "_blob_exists", return_value=True), \
         patch.object(server, "_validate_image_blobs", return_value=[]), \
         patch.object(server, "_scene_repo", repo), \
         patch.object(server, "_task_dispatcher", failing_dispatcher):
        resp = _post_bundle_event(client, _BUNDLE_URI)

    assert resp.status_code == 500
    body = resp.json()
    assert body["error"] == "dispatch_failed"
    assert "cloud tasks unavailable" in body["detail"]

    # The Scene was created but then marked failed — no orphaned queued records.
    scenes = list(repo._store.values())  # type: ignore[attr-defined]
    assert len(scenes) == 1
    assert scenes[0].status == SceneStatus.FAILED


# ---------------------------------------------------------------------------
# Validation failures
# ---------------------------------------------------------------------------

def test_unsupported_schema_version_creates_failed_invalid_scene(client: TestClient) -> None:
    """Bundle with an unrecognized schema_version → 200 + failed_invalid Scene.

    HTTP 200 (not 400) prevents Pub/Sub retry storms on the Eventarc path.
    A Scene in failed_invalid is created so the iOS client can observe the
    rejection via GET /scenes/by-bundle/{bundle_id} polling (the iOS path
    never calls /ingest directly; it uploads to GCS and polls).
    """
    from thegoodguest_api_core.upload_session_repo import InMemoryUploadSessionRepository
    bundle_bytes = _make_bundle(schema_version="99.0.0")
    repo = InMemorySceneRepository()
    with (
        patch.object(server, "_fetch_bundle_bytes", return_value=bundle_bytes),
        patch.object(server, "_scene_repo", repo),
        patch.object(server, "_upload_session_repo", InMemoryUploadSessionRepository()),
    ):
        resp = _post_bundle_event(client, "gs://test-bucket/captures/test/bundle.pb")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "failed_invalid"
    assert body["error"] == "unsupported_schema_version"
    # Scene created and in terminal failed_invalid state.
    scenes = list(repo._store.values())
    assert len(scenes) == 1
    assert scenes[0].status == SceneStatus.FAILED_INVALID
    assert "unsupported_schema_version" in (scenes[0].last_error or "")


def test_old_version_1_0_0_creates_failed_invalid_scene(client: TestClient) -> None:
    """Bundles carrying schema_version='1.0.0' (pre-standardisation) → 200 + failed_invalid.

    Regression for decision 0031: '1.0.0' was the emitted value before standardising
    on '1'. The realistic failure mode is an old iOS build that hasn't updated.
    Confirms the realistic rejected value (not just the synthetic '99.0.0') creates
    a pollable failed_invalid Scene with a schema-rejection last_error.
    """
    from thegoodguest_api_core.upload_session_repo import InMemoryUploadSessionRepository
    bundle_bytes = _make_bundle(schema_version="1.0.0")
    repo = InMemorySceneRepository()
    with (
        patch.object(server, "_fetch_bundle_bytes", return_value=bundle_bytes),
        patch.object(server, "_scene_repo", repo),
        patch.object(server, "_upload_session_repo", InMemoryUploadSessionRepository()),
    ):
        resp = _post_bundle_event(client, "gs://test-bucket/captures/test/bundle.pb")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "failed_invalid"
    assert body["error"] == "unsupported_schema_version"
    scenes = list(repo._store.values())
    assert len(scenes) == 1
    assert scenes[0].status == SceneStatus.FAILED_INVALID
    assert "1.0.0" in (scenes[0].last_error or "")


def test_corrupt_quaternion_creates_failed_invalid_scene(client: TestClient) -> None:
    """Bundle with a non-unit quaternion → 200 + failed_invalid Scene.

    Sets quat = (1, 1, 0, 0), norm = sqrt(2) ≈ 1.414, which exceeds the
    1e-3 tolerance around 1.0. Like every contract-validation failure, this
    yields a pollable failed_invalid Scene and HTTP 200 (no Pub/Sub retry).
    """
    b = CaptureBundle()
    b.schema_version = SCHEMA_VERSION
    b.bundle_id = "test"  # matches the posted URI — passes the cross-check
    b.user_id = "test-user"
    b.device.device_id = str(uuid.uuid4())
    b.tier = ARKIT_ONLY
    b.started_at_device_us = 0
    b.ended_at_device_us = 1
    f = b.frames.add()
    f.frame_index = 0
    f.rgb_gcs_path = "frames/000000.jpg"
    f.camera_pose.quat_x = 1.0  # norm = sqrt(2) — deliberately non-unit
    f.camera_pose.quat_y = 1.0
    f.camera_pose.quat_z = 0.0
    f.camera_pose.quat_w = 0.0

    repo = InMemorySceneRepository()
    with (
        patch.object(server, "_fetch_bundle_bytes", return_value=b.SerializeToString()),
        patch.object(server, "_scene_repo", repo),
        patch.object(server, "_upload_session_repo", InMemoryUploadSessionRepository()),
    ):
        resp = _post_bundle_event(client, "gs://test-bucket/captures/test/bundle.pb")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "failed_invalid"
    assert body["error"] == "quaternion_norm_out_of_range"
    scenes = list(repo._store.values())
    assert len(scenes) == 1
    assert scenes[0].status == SceneStatus.FAILED_INVALID


def test_missing_device_id_creates_failed_invalid_scene(client: TestClient) -> None:
    """Bundle with an empty device.device_id → 200 + failed_invalid Scene.

    device_id is required (the iOS client persists a Keychain UUID); the
    hardware_id fallback was removed. The rejection Scene carries the
    "unknown" device_id sentinel so the client can still poll the outcome.
    """
    b = CaptureBundle()
    b.schema_version = SCHEMA_VERSION
    b.bundle_id = "test"  # matches the posted URI — passes the cross-check
    b.user_id = "test-user"
    b.device.hardware_id = "iPhone15,3"  # deliberately no device_id
    b.tier = ARKIT_ONLY
    b.started_at_device_us = 0
    b.ended_at_device_us = 1
    f = b.frames.add()
    f.frame_index = 0
    f.rgb_gcs_path = "frames/000000.jpg"
    f.camera_pose.quat_w = 1.0

    repo = InMemorySceneRepository()
    with (
        patch.object(server, "_fetch_bundle_bytes", return_value=b.SerializeToString()),
        patch.object(server, "_scene_repo", repo),
        patch.object(server, "_upload_session_repo", InMemoryUploadSessionRepository()),
    ):
        resp = _post_bundle_event(client, "gs://test-bucket/captures/test/bundle.pb")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "failed_invalid"
    assert body["error"] == "device_id_missing"
    scenes = list(repo._store.values())
    assert len(scenes) == 1
    assert scenes[0].status == SceneStatus.FAILED_INVALID
    assert scenes[0].device_id == "unknown"


def test_depth_on_arkit_only_tier_creates_failed_invalid_scene(client: TestClient) -> None:
    """Bundle with depth frames but ARKIT_ONLY tier → 200 + failed_invalid Scene.

    Uses _make_bundle with add_depth=True but forces tier=ARKIT_ONLY to
    trigger the tier-vs-depth consistency check. Returns 200 + Scene (not 400)
    for the same reason as schema rejection: iOS clients poll, not call /ingest.
    """
    from thegoodguest_api_core.upload_session_repo import InMemoryUploadSessionRepository
    bundle_bytes = _make_bundle(frame_count=1, add_depth=True, tier=ARKIT_ONLY)
    repo = InMemorySceneRepository()
    with (
        patch.object(server, "_fetch_bundle_bytes", return_value=bundle_bytes),
        patch.object(server, "_scene_repo", repo),
        patch.object(server, "_upload_session_repo", InMemoryUploadSessionRepository()),
    ):
        resp = _post_bundle_event(client, "gs://test-bucket/captures/test/bundle.pb")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "failed_invalid"
    assert body["error"] == "depth_requires_lidar_tier"
    scenes = list(repo._store.values())
    assert len(scenes) == 1
    assert scenes[0].status == SceneStatus.FAILED_INVALID
    assert "depth_requires_lidar_tier" in (scenes[0].last_error or "")


def test_malformed_proto_returns_400(client: TestClient) -> None:
    """Garbage bytes that cannot be parsed as a proto → 400 bundle_parse_failed."""
    with (
        patch.object(server, "_fetch_bundle_bytes", return_value=b"\xff\xff\xff\xff garbage"),
        patch.object(server, "_scene_repo", InMemorySceneRepository()),
    ):
        resp = _post_bundle_event(client, "gs://test-bucket/captures/test/bundle.pb")
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"] == "bundle_parse_failed"


def test_absolute_rgb_path_creates_failed_invalid_scene(client: TestClient) -> None:
    """Bundle with a full gs:// URI in rgb_gcs_path → 200 + failed_invalid Scene."""
    b = CaptureBundle()
    b.schema_version = SCHEMA_VERSION
    b.bundle_id = "test"  # matches the posted URI — passes the cross-check
    b.user_id = "test-user"
    b.device.device_id = str(uuid.uuid4())
    b.tier = ARKIT_ONLY
    b.started_at_device_us = 0
    b.ended_at_device_us = 1
    f = b.frames.add()
    f.frame_index = 0
    f.rgb_gcs_path = "gs://my-bucket/captures/abc/frames/000000.jpg"  # wrong
    f.camera_pose.quat_w = 1.0  # unit norm — passes the quat check

    repo = InMemorySceneRepository()
    with (
        patch.object(server, "_fetch_bundle_bytes", return_value=b.SerializeToString()),
        patch.object(server, "_scene_repo", repo),
        patch.object(server, "_upload_session_repo", InMemoryUploadSessionRepository()),
    ):
        resp = _post_bundle_event(client, "gs://test-bucket/captures/test/bundle.pb")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "failed_invalid"
    assert body["error"] == "absolute_gcs_path"
    scenes = list(repo._store.values())
    assert len(scenes) == 1
    assert scenes[0].status == SceneStatus.FAILED_INVALID


def test_absolute_roomplan_json_path_rejected() -> None:
    """room_plan.json_gcs_path joins check 6 (all GCS paths relative,
    decision 0077): an absolute URI fails validation; the relative form
    passes. Direct validate_bundle pin — the handler wiring is identical to
    every other absolute_gcs_path case."""
    b = CaptureBundle()
    b.schema_version = SCHEMA_VERSION
    b.user_id = "test-user"
    b.device.device_id = str(uuid.uuid4())
    b.tier = LIDAR_ROOMPLAN
    b.room_plan.json_gcs_path = "gs://my-bucket/captures/abc/roomplan/room.json"

    result = validate_bundle(b)
    assert result is not None
    code, detail = result
    assert code == "absolute_gcs_path"
    assert "json_gcs_path" in detail

    b.room_plan.json_gcs_path = "roomplan/room.json"
    assert validate_bundle(b) is None


# ---------------------------------------------------------------------------
# bundle_id cross-check (proto vs URI-derived)
# ---------------------------------------------------------------------------

class TestBundleIdCrosscheck:
    """Tests for validation check 2: bundle.bundle_id must equal the
    bundle_id derived from the upload URI.

    A mismatched bundle previously passed validation silently — the Scene
    keys on the URI-derived id while the proto claimed another, breaking
    every downstream join on bundle_id. Like every contract-validation
    failure, a mismatch yields a pollable failed_invalid Scene + HTTP 200
    (decision 0031's pattern), never a bare 400.
    """

    def test_mismatched_bundle_id_creates_failed_invalid_scene(
        self, client: TestClient
    ) -> None:
        """Proto bundle_id ≠ URI bundle_id → 200 + failed_invalid, no dispatch."""
        uri_id = str(uuid.uuid4())
        proto_id = str(uuid.uuid4())
        bundle_bytes = _make_bundle(frame_count=1, bundle_id=proto_id)
        repo = InMemorySceneRepository()
        dispatcher = InMemoryTaskDispatcher()
        mock_image_check = MagicMock(return_value=[])

        with (
            patch.object(server, "_fetch_bundle_bytes", return_value=bundle_bytes),
            patch.object(server, "_blob_exists", return_value=True),
            patch.object(server, "_validate_image_blobs", mock_image_check),
            patch.object(server, "_scene_repo", repo),
            patch.object(server, "_task_dispatcher", dispatcher),
            patch.object(server, "_upload_session_repo", InMemoryUploadSessionRepository()),
        ):
            resp = _post_bundle_event(
                client, f"gs://test-bucket/captures/{uri_id}/bundle.pb"
            )

        # 200 (not 400) so Pub/Sub acknowledges and does not retry.
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "failed_invalid"
        assert body["error"] == "bundle_id_mismatch"

        scenes = list(repo._store.values())
        assert len(scenes) == 1
        scene = scenes[0]
        assert scene.status == SceneStatus.FAILED_INVALID
        # The Scene keys on the URI-derived id — the id pollers actually use.
        assert scene.bundle_id == uri_id
        # last_error carries both ids so an operator can see which side is wrong.
        assert "bundle_id_mismatch" in (scene.last_error or "")
        assert proto_id in (scene.last_error or "")
        assert uri_id in (scene.last_error or "")
        # Terminal pre-GPU: nothing enqueued, image gate never reached.
        assert len(dispatcher.tasks) == 0
        mock_image_check.assert_not_called()

    def test_case_differing_bundle_id_is_rejected(self, client: TestClient) -> None:
        """A case-differing pair is a mismatch, not a match.

        Every downstream join on bundle_id (Firestore scenes.bundle_id
        queries, upload_sessions doc IDs, captures/{bundle_id}/ GCS paths)
        is byte-wise, so 'ABC…' vs 'abc…' breaks those joins exactly like a
        wholly different id. The comparison is deliberately case-sensitive;
        the iOS client lowercases bundle_id and builds the upload path from
        the same value, so only a non-conforming client can produce this.
        """
        uri_id = str(uuid.uuid4())  # canonical lowercase
        proto_id = uri_id.upper()   # same UUID text, wrong case
        bundle_bytes = _make_bundle(frame_count=1, bundle_id=proto_id)
        repo = InMemorySceneRepository()

        with (
            patch.object(server, "_fetch_bundle_bytes", return_value=bundle_bytes),
            patch.object(server, "_scene_repo", repo),
            patch.object(server, "_upload_session_repo", InMemoryUploadSessionRepository()),
        ):
            resp = _post_bundle_event(
                client, f"gs://test-bucket/captures/{uri_id}/bundle.pb"
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "failed_invalid"
        assert body["error"] == "bundle_id_mismatch"
        scenes = list(repo._store.values())
        assert len(scenes) == 1
        assert scenes[0].status == SceneStatus.FAILED_INVALID

    def test_empty_proto_bundle_id_is_rejected(self, client: TestClient) -> None:
        """An unset/empty proto bundle_id can never match the URI-derived id
        (the ingest URI regex guarantees non-empty) — previously an empty
        bundle_id passed validation silently."""
        bundle_bytes = _make_bundle(frame_count=1, bundle_id="")
        repo = InMemorySceneRepository()

        with (
            patch.object(server, "_fetch_bundle_bytes", return_value=bundle_bytes),
            patch.object(server, "_scene_repo", repo),
            patch.object(server, "_upload_session_repo", InMemoryUploadSessionRepository()),
        ):
            resp = _post_bundle_event(client, "gs://test-bucket/captures/test/bundle.pb")

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "failed_invalid"
        assert body["error"] == "bundle_id_mismatch"

    def test_matching_bundle_id_reaches_queued(self, client: TestClient) -> None:
        """Exact match — the conforming-client case — proceeds to QUEUED."""
        bid = str(uuid.uuid4())
        bundle_bytes = _make_bundle(frame_count=1, bundle_id=bid)
        repo = InMemorySceneRepository()
        dispatcher = InMemoryTaskDispatcher()

        with (
            patch.object(server, "_fetch_bundle_bytes", return_value=bundle_bytes),
            patch.object(server, "_blob_exists", return_value=True),
            patch.object(server, "_validate_image_blobs", return_value=[]),
            patch.object(server, "_scene_repo", repo),
            patch.object(server, "_task_dispatcher", dispatcher),
        ):
            resp = _post_bundle_event(
                client, f"gs://test-bucket/captures/{bid}/bundle.pb"
            )

        assert resp.status_code == 200
        assert resp.json()["status"] == "queued"
        assert len(dispatcher.tasks) == 1

    def test_no_expected_id_skips_crosscheck(self) -> None:
        """validate_bundle without expected_bundle_id skips check 2 only.

        Callers with no upload URI in hand (the api-core fixture self-tests)
        validate bundle content in isolation; any bundle_id passes there.
        With an expected id supplied, the same bundle matches or mismatches.
        """
        b = CaptureBundle()
        b.ParseFromString(_make_bundle(frame_count=1, bundle_id=str(uuid.uuid4())))
        assert validate_bundle(b) is None
        assert validate_bundle(b, expected_bundle_id=b.bundle_id) is None
        err = validate_bundle(b, expected_bundle_id="something-else")
        assert err is not None
        assert err[0] == "bundle_id_mismatch"

    def test_crosscheck_order_between_schema_and_device_id(self) -> None:
        """Check ordering: schema_version fires before the cross-check; the
        cross-check fires before device_id (a mis-identified bundle's content
        errors are noise — identity is reported first)."""
        b = CaptureBundle()
        b.schema_version = "99.0.0"  # bad schema AND mismatched id
        b.bundle_id = "proto-id"
        err = validate_bundle(b, expected_bundle_id="uri-id")
        assert err is not None
        assert err[0] == "unsupported_schema_version"

        b2 = CaptureBundle()
        b2.schema_version = SCHEMA_VERSION  # mismatched id AND missing device_id
        b2.bundle_id = "proto-id"
        err2 = validate_bundle(b2, expected_bundle_id="uri-id")
        assert err2 is not None
        assert err2[0] == "bundle_id_mismatch"


# ---------------------------------------------------------------------------
# Blob validation gate
# ---------------------------------------------------------------------------

class TestBlobValidationGate:
    """Tests for the ingest-side image-blob validation gate (step 5b).

    All GCS I/O is patched: _blob_exists returns True (blobs exist),
    _validate_image_blobs is controlled to return specific invalid-blob lists.
    Tests assert the HTTP response, the Scene status in the repo, and that
    no task is enqueued for FAILED_INVALID scenes.
    """

    _BUNDLE_URI = "gs://test-bucket/captures/bundle-abc/bundle.pb"

    def test_undersized_blobs_return_failed_invalid(self, client: TestClient) -> None:
        """_validate_image_blobs returning TOO_SMALL entries → 200 status=failed_invalid."""
        bundle_bytes = _make_bundle(frame_count=2, bundle_id="bundle-abc")
        repo = InMemorySceneRepository()
        dispatcher = InMemoryTaskDispatcher()

        invalid = [
            {"relative_path": "frames/000000.jpg", "reason": "too_small"},
            {"relative_path": "frames/000001.jpg", "reason": "too_small"},
        ]

        with patch.object(server, "_fetch_bundle_bytes", return_value=bundle_bytes), \
             patch.object(server, "_blob_exists", return_value=True), \
             patch.object(server, "_validate_image_blobs", return_value=invalid), \
             patch.object(server, "_scene_repo", repo), \
             patch.object(server, "_task_dispatcher", dispatcher), \
             patch.object(server, "_upload_session_repo", InMemoryUploadSessionRepository()):
            resp = _post_bundle_event(client, self._BUNDLE_URI)

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "failed_invalid"
        assert len(body["invalid_blobs"]) == 2
        assert body["invalid_blobs"][0]["reason"] == "too_small"
        # No task enqueued — FAILED_INVALID is terminal.
        assert len(dispatcher.tasks) == 0
        # Scene persisted as FAILED_INVALID.
        scenes = list(repo._store.values())
        assert len(scenes) == 1
        assert scenes[0].status == SceneStatus.FAILED_INVALID
        assert scenes[0].invalid_blobs == invalid

    def test_bad_magic_blobs_return_failed_invalid(self, client: TestClient) -> None:
        """_validate_image_blobs returning BAD_MAGIC → 200 status=failed_invalid."""
        bundle_bytes = _make_bundle(frame_count=1, bundle_id="bundle-abc")
        repo = InMemorySceneRepository()
        dispatcher = InMemoryTaskDispatcher()

        invalid = [{"relative_path": "frames/000000.jpg", "reason": "bad_magic"}]

        with patch.object(server, "_fetch_bundle_bytes", return_value=bundle_bytes), \
             patch.object(server, "_blob_exists", return_value=True), \
             patch.object(server, "_validate_image_blobs", return_value=invalid), \
             patch.object(server, "_scene_repo", repo), \
             patch.object(server, "_task_dispatcher", dispatcher), \
             patch.object(server, "_upload_session_repo", InMemoryUploadSessionRepository()):
            resp = _post_bundle_event(client, self._BUNDLE_URI)

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "failed_invalid"
        assert body["invalid_blobs"][0]["reason"] == "bad_magic"
        assert len(dispatcher.tasks) == 0

    def test_valid_blobs_proceed_to_queued(self, client: TestClient) -> None:
        """_validate_image_blobs returning [] → scene reaches QUEUED and task enqueued."""
        bundle_bytes = _make_bundle(frame_count=2, bundle_id="bundle-abc")
        repo = InMemorySceneRepository()
        dispatcher = InMemoryTaskDispatcher()

        with patch.object(server, "_fetch_bundle_bytes", return_value=bundle_bytes), \
             patch.object(server, "_blob_exists", return_value=True), \
             patch.object(server, "_validate_image_blobs", return_value=[]), \
             patch.object(server, "_scene_repo", repo), \
             patch.object(server, "_task_dispatcher", dispatcher):
            resp = _post_bundle_event(client, self._BUNDLE_URI)

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "queued"
        assert len(dispatcher.tasks) == 1

    def test_failed_invalid_scene_has_invalid_blobs_field(self, client: TestClient) -> None:
        """Scene.invalid_blobs carries the structured list from _validate_image_blobs."""
        bundle_bytes = _make_bundle(frame_count=1, bundle_id="bundle-abc")
        repo = InMemorySceneRepository()

        invalid = [{"relative_path": "frames/000000.jpg", "reason": "unrecognized_format"}]

        with patch.object(server, "_fetch_bundle_bytes", return_value=bundle_bytes), \
             patch.object(server, "_blob_exists", return_value=True), \
             patch.object(server, "_validate_image_blobs", return_value=invalid), \
             patch.object(server, "_scene_repo", repo), \
             patch.object(server, "_task_dispatcher", InMemoryTaskDispatcher()), \
             patch.object(server, "_upload_session_repo", InMemoryUploadSessionRepository()):
            _post_bundle_event(client, self._BUNDLE_URI)

        scenes = list(repo._store.values())
        assert len(scenes) == 1
        scene = scenes[0]
        assert scene.status == SceneStatus.FAILED_INVALID
        assert scene.invalid_blobs == invalid


# Import needed for TestBlobValidationGate
from thegoodguest_api_core.upload_session_repo import InMemoryUploadSessionRepository  # noqa: E402
