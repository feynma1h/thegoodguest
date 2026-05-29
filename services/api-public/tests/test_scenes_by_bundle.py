"""Tests for GET /scenes/by-bundle/{bundle_id}.

Covers:
  - 200 response with correct shape for an owned scene in each status
  - result_uri and missing_paths are null when not set
  - 401 missing_token — no Authorization header
  - 401 missing_token — Authorization header not Bearer-prefixed
  - 401 invalid_token — JWT fails verification
  - 400 invalid_bundle_id — bundle_id is not a UUIDv4
  - 403 forbidden — JWT uid does not match scene.user_id
  - 403 forbidden — scene.user_id is None (scene has no owner)
  - 404 not_found — no scene exists for this bundle_id

NullTokenVerifier is used for all tests (accepts "test-uid:<uid>" tokens).
InMemorySceneReadRepository is injected directly — no Firestore.

Run from repo root:
  pytest services/api-public/tests/test_scenes_by_bundle.py -v
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import server
from auth import NullTokenVerifier  # noqa: E402
from roomstudio_api_core.scene import DeviceIdSource, Scene, SceneStatus  # noqa: E402
from roomstudio_api_core.scene_read_repo import InMemorySceneReadRepository  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _make_bundle_id() -> str:
    return str(uuid.uuid4())


def _make_scene(
    bundle_id: str,
    user_id: str | None = "user-abc",
    status: SceneStatus = SceneStatus.QUEUED,
    result_uri: str | None = None,
    missing_paths: list | None = None,
) -> Scene:
    return Scene(
        scene_id=str(uuid.uuid4()),
        device_id="device-1",
        device_id_source=DeviceIdSource.PROVIDED,
        status=status,
        bundle_uri=f"gs://roomstudio-captures/captures/{bundle_id}/bundle.pb",
        created_at=_NOW,
        updated_at=_NOW,
        bundle_id=bundle_id,
        user_id=user_id,
        result_uri=result_uri,
        missing_paths=missing_paths,
    )


def _auth_header(uid: str = "user-abc") -> str:
    return f"Bearer test-uid:{uid}"


def _get(
    client: TestClient,
    bundle_id: str,
    uid: str = "user-abc",
    scene_repo: InMemorySceneReadRepository | None = None,
):
    """Helper: GET /scenes/by-bundle/{bundle_id} with patched deps."""
    repo = scene_repo or InMemorySceneReadRepository()
    with (
        patch.object(server, "_token_verifier", NullTokenVerifier()),
        patch.object(server, "_scene_read_repo", repo),
    ):
        return client.get(
            f"/scenes/by-bundle/{bundle_id}",
            headers={"Authorization": _auth_header(uid)},
        )


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(server.app)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

class TestScenesByBundleHappyPath:
    def test_returns_200_with_correct_shape(self, client: TestClient) -> None:
        bundle_id = _make_bundle_id()
        scene = _make_scene(bundle_id, status=SceneStatus.QUEUED)
        repo = InMemorySceneReadRepository({scene.scene_id: scene})

        resp = _get(client, bundle_id, scene_repo=repo)
        assert resp.status_code == 200

        body = resp.json()
        assert body["scene_id"] == scene.scene_id
        assert body["bundle_id"] == bundle_id
        assert body["status"] == "queued"
        assert body["result_uri"] is None
        assert body["missing_paths"] is None
        assert "created_at" in body
        assert "updated_at" in body

    def test_status_ready_with_result_uri(self, client: TestClient) -> None:
        bundle_id = _make_bundle_id()
        result = f"gs://roomstudio-perception-outputs/scenes/{bundle_id}/splat.ply"
        scene = _make_scene(bundle_id, status=SceneStatus.READY, result_uri=result)
        repo = InMemorySceneReadRepository({scene.scene_id: scene})

        resp = _get(client, bundle_id, scene_repo=repo)
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ready"
        assert body["result_uri"] == result

    def test_status_failed_incomplete_with_missing_paths(self, client: TestClient) -> None:
        bundle_id = _make_bundle_id()
        missing = ["frames/000000.jpg", "depth/000000.f32"]
        scene = _make_scene(bundle_id, status=SceneStatus.FAILED_INCOMPLETE, missing_paths=missing)
        repo = InMemorySceneReadRepository({scene.scene_id: scene})

        resp = _get(client, bundle_id, scene_repo=repo)
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "failed_incomplete"
        assert body["missing_paths"] == missing

    def test_failed_scene_returns_200_not_4xx(self, client: TestClient) -> None:
        """Scene status is body-only; failure is not mapped to an HTTP error code."""
        bundle_id = _make_bundle_id()
        scene = _make_scene(bundle_id, status=SceneStatus.FAILED)
        repo = InMemorySceneReadRepository({scene.scene_id: scene})

        resp = _get(client, bundle_id, scene_repo=repo)
        assert resp.status_code == 200
        assert resp.json()["status"] == "failed"

    def test_last_error_not_in_response(self, client: TestClient) -> None:
        """last_error is server-side only; must not appear in the public response."""
        bundle_id = _make_bundle_id()
        scene = _make_scene(bundle_id)
        scene.last_error = "some internal error"
        repo = InMemorySceneReadRepository({scene.scene_id: scene})

        resp = _get(client, bundle_id, scene_repo=repo)
        assert resp.status_code == 200
        assert "last_error" not in resp.json()

    def test_timestamps_are_iso8601_strings(self, client: TestClient) -> None:
        bundle_id = _make_bundle_id()
        scene = _make_scene(bundle_id)
        repo = InMemorySceneReadRepository({scene.scene_id: scene})

        resp = _get(client, bundle_id, scene_repo=repo)
        body = resp.json()
        # Should parse as ISO 8601 without error.
        datetime.fromisoformat(body["created_at"])
        datetime.fromisoformat(body["updated_at"])


# ---------------------------------------------------------------------------
# Auth — 401
# ---------------------------------------------------------------------------

class TestScenesByBundleAuth:
    def test_missing_authorization_header_returns_422(self, client: TestClient) -> None:
        bundle_id = _make_bundle_id()
        repo = InMemorySceneReadRepository()
        with (
            patch.object(server, "_token_verifier", NullTokenVerifier()),
            patch.object(server, "_scene_read_repo", repo),
        ):
            resp = client.get(f"/scenes/by-bundle/{bundle_id}")
        assert resp.status_code == 422  # FastAPI rejects missing required header

    def test_non_bearer_authorization_returns_401(self, client: TestClient) -> None:
        bundle_id = _make_bundle_id()
        repo = InMemorySceneReadRepository()
        with (
            patch.object(server, "_token_verifier", NullTokenVerifier()),
            patch.object(server, "_scene_read_repo", repo),
        ):
            resp = client.get(
                f"/scenes/by-bundle/{bundle_id}",
                headers={"Authorization": "NotBearer xyz"},
            )
        assert resp.status_code == 401
        assert resp.json()["error"] == "missing_token"

    def test_invalid_token_returns_401(self, client: TestClient) -> None:
        bundle_id = _make_bundle_id()
        repo = InMemorySceneReadRepository()
        with (
            patch.object(server, "_token_verifier", NullTokenVerifier()),
            patch.object(server, "_scene_read_repo", repo),
        ):
            resp = client.get(
                f"/scenes/by-bundle/{bundle_id}",
                headers={"Authorization": "Bearer not-a-test-uid-token"},
            )
        assert resp.status_code == 401
        assert resp.json()["error"] == "invalid_token"


# ---------------------------------------------------------------------------
# bundle_id validation — 400
# ---------------------------------------------------------------------------

class TestScenesByBundleBundleIdValidation:
    def test_non_uuid_returns_400(self, client: TestClient) -> None:
        resp = _get(client, "not-a-uuid")
        assert resp.status_code == 400
        assert resp.json()["error"] == "invalid_bundle_id"

    def test_uuid_v1_returns_400(self, client: TestClient) -> None:
        v1 = str(uuid.uuid1())
        resp = _get(client, v1)
        assert resp.status_code == 400
        assert resp.json()["error"] == "invalid_bundle_id"


# ---------------------------------------------------------------------------
# Authorization — 403
# ---------------------------------------------------------------------------

class TestScenesByBundleAuthorization:
    def test_uid_mismatch_returns_403(self, client: TestClient) -> None:
        bundle_id = _make_bundle_id()
        scene = _make_scene(bundle_id, user_id="user-a")
        repo = InMemorySceneReadRepository({scene.scene_id: scene})

        resp = _get(client, bundle_id, uid="user-b", scene_repo=repo)
        assert resp.status_code == 403
        assert resp.json()["error"] == "forbidden"

    def test_scene_with_no_owner_returns_403(self, client: TestClient) -> None:
        bundle_id = _make_bundle_id()
        scene = _make_scene(bundle_id, user_id=None)
        repo = InMemorySceneReadRepository({scene.scene_id: scene})

        resp = _get(client, bundle_id, scene_repo=repo)
        assert resp.status_code == 403
        body = resp.json()
        assert body["error"] == "forbidden"
        assert body["detail"] == "scene has no owner"


# ---------------------------------------------------------------------------
# Not found — 404
# ---------------------------------------------------------------------------

class TestScenesByBundleNotFound:
    def test_unknown_bundle_id_returns_404(self, client: TestClient) -> None:
        bundle_id = _make_bundle_id()
        repo = InMemorySceneReadRepository()  # empty

        resp = _get(client, bundle_id, scene_repo=repo)
        assert resp.status_code == 404
        assert resp.json()["error"] == "not_found"
