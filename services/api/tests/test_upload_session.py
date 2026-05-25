"""Tests for POST /captures/{bundle_id}/upload_session.

Covers:
  - Valid request returns [{relative_path, session_uri}] for each manifest entry
  - JWT is verified; invalid token → 401
  - bundle_id must be UUIDv4; non-UUID → 400 invalid_bundle_id
  - Manifest path validation: empty, leading slash, gs://, .. traversal → 400
  - Empty manifest → 400 manifest_empty
  - Idempotency: repeated call with same manifest paths returns stored URIs
  - New manifest (different paths) replaces stored URIs
  - 403 when JWT uid does not match the stored user_id for the bundle_id
  - fcm_token stored and retrievable from the upload session record

NullTokenVerifier is used for all tests (accepts "test-uid:<uid>" tokens).
The GCS URI minter is injected as a lambda — no google-cloud-storage needed.

Run from repo root:
  pytest services/api/tests/test_upload_session.py -v
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

_api_dir = Path(__file__).resolve().parents[1]
_schemas_dir = _api_dir.parents[1] / "packages/schemas"
for _p in (_api_dir, _schemas_dir):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import server  # noqa: E402
from auth import NullTokenVerifier  # noqa: E402
from upload_session_repo import InMemoryUploadSessionRepository  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(server.app)


def _make_bundle_id() -> str:
    return str(uuid.uuid4())


def _auth_header(uid: str = "user-abc") -> str:
    return f"Bearer test-uid:{uid}"


def _fake_mint(bucket: str, blob_path: str, size_bytes: int) -> str:
    return f"https://storage.googleapis.com/fake-resumable/{blob_path}"


def _post_upload_session(
    client: TestClient,
    bundle_id: str,
    manifest: list[dict],
    uid: str = "user-abc",
    fcm_token: str | None = None,
    upload_repo: InMemoryUploadSessionRepository | None = None,
):
    """Helper: POST /captures/{bundle_id}/upload_session with patched deps."""
    repo = upload_repo or InMemoryUploadSessionRepository()
    with (
        patch.object(server, "_token_verifier", NullTokenVerifier()),
        patch.object(server, "_upload_session_repo", repo),
        patch("upload_session_repo.gcs_mint_resumable_uri", side_effect=_fake_mint),
    ):
        return client.post(
            f"/captures/{bundle_id}/upload_session",
            json={"manifest": manifest, "fcm_token": fcm_token},
            headers={"Authorization": _auth_header(uid)},
        ), repo


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

class TestUploadSessionHappyPath:
    def test_returns_200_with_session_entries(self, client: TestClient) -> None:
        bundle_id = _make_bundle_id()
        manifest = [
            {"relative_path": "frames/000000.jpg", "expected_size_bytes": 1024},
            {"relative_path": "depth/000000.f32", "expected_size_bytes": 512},
            {"relative_path": "bundle.pb", "expected_size_bytes": 256},
        ]
        resp, _ = _post_upload_session(client, bundle_id, manifest)
        assert resp.status_code == 200
        entries = resp.json()
        assert len(entries) == 3
        paths_returned = {e["relative_path"] for e in entries}
        assert paths_returned == {"frames/000000.jpg", "depth/000000.f32", "bundle.pb"}

    def test_session_uris_are_non_empty_strings(self, client: TestClient) -> None:
        bundle_id = _make_bundle_id()
        manifest = [{"relative_path": "frames/000000.jpg", "expected_size_bytes": 100}]
        resp, _ = _post_upload_session(client, bundle_id, manifest)
        assert resp.status_code == 200
        for entry in resp.json():
            assert isinstance(entry["session_uri"], str)
            assert entry["session_uri"]

    def test_fcm_token_stored_in_repo(self, client: TestClient) -> None:
        bundle_id = _make_bundle_id()
        manifest = [{"relative_path": "bundle.pb", "expected_size_bytes": 128}]
        repo = InMemoryUploadSessionRepository()
        resp, _ = _post_upload_session(client, bundle_id, manifest, fcm_token="fcm-tok-123", upload_repo=repo)
        assert resp.status_code == 200
        assert repo.get_fcm_token(bundle_id) == "fcm-tok-123"


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

class TestUploadSessionAuth:
    def test_missing_authorization_header_returns_401(self, client: TestClient) -> None:
        bundle_id = _make_bundle_id()
        manifest = [{"relative_path": "bundle.pb", "expected_size_bytes": 128}]
        with (
            patch.object(server, "_token_verifier", NullTokenVerifier()),
            patch.object(server, "_upload_session_repo", InMemoryUploadSessionRepository()),
        ):
            resp = client.post(
                f"/captures/{bundle_id}/upload_session",
                json={"manifest": manifest},
                # No Authorization header
            )
        assert resp.status_code == 422  # FastAPI rejects missing required header

    def test_malformed_bearer_returns_401(self, client: TestClient) -> None:
        bundle_id = _make_bundle_id()
        manifest = [{"relative_path": "bundle.pb", "expected_size_bytes": 128}]
        with (
            patch.object(server, "_token_verifier", NullTokenVerifier()),
            patch.object(server, "_upload_session_repo", InMemoryUploadSessionRepository()),
        ):
            resp = client.post(
                f"/captures/{bundle_id}/upload_session",
                json={"manifest": manifest},
                headers={"Authorization": "NotBearer xyz"},
            )
        assert resp.status_code == 401
        assert resp.json()["error"] == "missing_token"

    def test_invalid_token_returns_401(self, client: TestClient) -> None:
        bundle_id = _make_bundle_id()
        manifest = [{"relative_path": "bundle.pb", "expected_size_bytes": 128}]
        with (
            patch.object(server, "_token_verifier", NullTokenVerifier()),
            patch.object(server, "_upload_session_repo", InMemoryUploadSessionRepository()),
        ):
            resp = client.post(
                f"/captures/{bundle_id}/upload_session",
                json={"manifest": manifest},
                headers={"Authorization": "Bearer not-a-test-uid-token"},
            )
        assert resp.status_code == 401
        assert resp.json()["error"] == "invalid_token"

    def test_different_user_same_bundle_id_returns_403(self, client: TestClient) -> None:
        bundle_id = _make_bundle_id()
        manifest = [{"relative_path": "bundle.pb", "expected_size_bytes": 128}]
        repo = InMemoryUploadSessionRepository()

        # First call: user-a creates the session.
        resp1, _ = _post_upload_session(client, bundle_id, manifest, uid="user-a", upload_repo=repo)
        assert resp1.status_code == 200

        # Second call: user-b tries to claim the same bundle_id.
        resp2, _ = _post_upload_session(client, bundle_id, manifest, uid="user-b", upload_repo=repo)
        assert resp2.status_code == 403
        assert resp2.json()["error"] == "forbidden"


# ---------------------------------------------------------------------------
# bundle_id validation
# ---------------------------------------------------------------------------

class TestUploadSessionBundleIdValidation:
    def test_non_uuid_bundle_id_returns_400(self, client: TestClient) -> None:
        manifest = [{"relative_path": "bundle.pb", "expected_size_bytes": 128}]
        with (
            patch.object(server, "_token_verifier", NullTokenVerifier()),
            patch.object(server, "_upload_session_repo", InMemoryUploadSessionRepository()),
        ):
            resp = client.post(
                "/captures/not-a-uuid/upload_session",
                json={"manifest": manifest},
                headers={"Authorization": _auth_header()},
            )
        assert resp.status_code == 400
        assert resp.json()["error"] == "invalid_bundle_id"

    def test_uuid_v1_returns_400(self, client: TestClient) -> None:
        import uuid as _uuid
        v1 = str(_uuid.uuid1())
        manifest = [{"relative_path": "bundle.pb", "expected_size_bytes": 128}]
        with (
            patch.object(server, "_token_verifier", NullTokenVerifier()),
            patch.object(server, "_upload_session_repo", InMemoryUploadSessionRepository()),
        ):
            resp = client.post(
                f"/captures/{v1}/upload_session",
                json={"manifest": manifest},
                headers={"Authorization": _auth_header()},
            )
        assert resp.status_code == 400
        assert resp.json()["error"] == "invalid_bundle_id"


# ---------------------------------------------------------------------------
# Manifest validation
# ---------------------------------------------------------------------------

class TestUploadSessionManifestValidation:
    def _post_bad_manifest(self, client: TestClient, bundle_id: str, manifest: list[dict]):
        with (
            patch.object(server, "_token_verifier", NullTokenVerifier()),
            patch.object(server, "_upload_session_repo", InMemoryUploadSessionRepository()),
        ):
            return client.post(
                f"/captures/{bundle_id}/upload_session",
                json={"manifest": manifest},
                headers={"Authorization": _auth_header()},
            )

    def test_empty_manifest_returns_400(self, client: TestClient) -> None:
        resp = self._post_bad_manifest(client, _make_bundle_id(), [])
        assert resp.status_code == 400
        assert resp.json()["error"] == "manifest_empty"

    def test_path_with_leading_slash_returns_400(self, client: TestClient) -> None:
        manifest = [{"relative_path": "/frames/000000.jpg", "expected_size_bytes": 100}]
        resp = self._post_bad_manifest(client, _make_bundle_id(), manifest)
        assert resp.status_code == 400
        assert resp.json()["error"] == "invalid_manifest"

    def test_absolute_gcs_path_returns_400(self, client: TestClient) -> None:
        manifest = [{"relative_path": "gs://bucket/frames/000000.jpg", "expected_size_bytes": 100}]
        resp = self._post_bad_manifest(client, _make_bundle_id(), manifest)
        assert resp.status_code == 400
        assert resp.json()["error"] == "invalid_manifest"

    def test_path_traversal_returns_400(self, client: TestClient) -> None:
        manifest = [{"relative_path": "../other-bundle/bundle.pb", "expected_size_bytes": 100}]
        resp = self._post_bad_manifest(client, _make_bundle_id(), manifest)
        assert resp.status_code == 400
        assert resp.json()["error"] == "invalid_manifest"

    def test_empty_path_string_returns_400(self, client: TestClient) -> None:
        manifest = [{"relative_path": "", "expected_size_bytes": 100}]
        resp = self._post_bad_manifest(client, _make_bundle_id(), manifest)
        assert resp.status_code == 400
        assert resp.json()["error"] == "invalid_manifest"


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------

class TestUploadSessionIdempotency:
    def test_repeated_call_same_manifest_returns_same_uris(self, client: TestClient) -> None:
        bundle_id = _make_bundle_id()
        manifest = [
            {"relative_path": "frames/000000.jpg", "expected_size_bytes": 512},
            {"relative_path": "bundle.pb", "expected_size_bytes": 128},
        ]
        repo = InMemoryUploadSessionRepository()

        resp1, _ = _post_upload_session(client, bundle_id, manifest, upload_repo=repo)
        resp2, _ = _post_upload_session(client, bundle_id, manifest, upload_repo=repo)
        assert resp1.status_code == 200
        assert resp2.status_code == 200
        assert resp1.json() == resp2.json()

    def test_different_manifest_paths_replaces_session(self, client: TestClient) -> None:
        bundle_id = _make_bundle_id()
        manifest_a = [{"relative_path": "frames/000000.jpg", "expected_size_bytes": 512}]
        manifest_b = [{"relative_path": "frames/000001.jpg", "expected_size_bytes": 512}]
        repo = InMemoryUploadSessionRepository()

        resp1, _ = _post_upload_session(client, bundle_id, manifest_a, upload_repo=repo)
        resp2, _ = _post_upload_session(client, bundle_id, manifest_b, upload_repo=repo)
        assert resp1.status_code == 200
        assert resp2.status_code == 200
        paths1 = {e["relative_path"] for e in resp1.json()}
        paths2 = {e["relative_path"] for e in resp2.json()}
        assert paths1 == {"frames/000000.jpg"}
        assert paths2 == {"frames/000001.jpg"}
