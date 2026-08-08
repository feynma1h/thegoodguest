"""Tests for POST /captures/{bundle_id}/upload_session.

Covers:
  - Valid request returns [{relative_path, session_uri}] for each manifest entry
  - JWT is verified; invalid token → 401
  - bundle_id must be UUIDv4; non-UUID → 400 invalid_bundle_id
  - Manifest path validation: empty, leading slash, gs://, .. traversal → 400
  - Semantic manifest validation (gaps c + F3): missing/zero/oversized
    expected_size_bytes, unknown directory/extension, nesting, duplicates,
    and the exactly-one-bundle.pb rule → 400 invalid_manifest
  - Empty manifest → 400 manifest_empty
  - Idempotency: repeated call with same manifest paths returns stored URIs
  - New manifest (different paths) replaces stored URIs
  - 403 when JWT uid does not match the stored user_id for the bundle_id
    (atomic claim inside the repository, gap a)
  - 429 rate_limited with resets_at + Retry-After at the per-UID daily mint
    quota (gap b); idempotent replays never consume quota
  - fcm_token stored and retrievable from the upload session record

NullTokenVerifier is used for all tests (accepts "test-uid:<uid>" tokens).
The GCS URI minter is injected through public_server's `_mint_uri_fn` seam —
no google-cloud-storage, and no cloud credentials of any kind. That last part
is a property this file is REQUIRED to hold and now pins explicitly
(TestUploadSessionNeedsNoCredentials): these tests must pass on a machine that
has never run `gcloud auth application-default login`.

Run from repo root:
  pytest services/api-public/tests/test_upload_session.py -v
"""
from __future__ import annotations

import threading
import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import public_server as server
from auth import NullTokenVerifier  # noqa: E402
from roomstudio_api_core.upload_session_repo import InMemoryUploadSessionRepository  # noqa: E402


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
        # The endpoint's mint seam. Patching
        # roomstudio_api_core.upload_session_repo.gcs_mint_resumable_uri here
        # did NOT work and was the CI defect: public_server binds the function
        # by from-import at module load, so rebinding the api-core module
        # attribute leaves the handler's own global pointing at the real
        # minter, which resolves ADC and 500s wherever there are no ambient
        # credentials. Patch the seam the handler actually reads.
        patch.object(server, "_mint_uri_fn", _fake_mint),
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
        manifest = [
            {"relative_path": "frames/000000.jpg", "expected_size_bytes": 100},
            {"relative_path": "bundle.pb", "expected_size_bytes": 64},
        ]
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
        manifest_a = [
            {"relative_path": "frames/000000.jpg", "expected_size_bytes": 512},
            {"relative_path": "bundle.pb", "expected_size_bytes": 128},
        ]
        manifest_b = [
            {"relative_path": "frames/000001.jpg", "expected_size_bytes": 512},
            {"relative_path": "bundle.pb", "expected_size_bytes": 128},
        ]
        repo = InMemoryUploadSessionRepository()

        resp1, _ = _post_upload_session(client, bundle_id, manifest_a, upload_repo=repo)
        resp2, _ = _post_upload_session(client, bundle_id, manifest_b, upload_repo=repo)
        assert resp1.status_code == 200
        assert resp2.status_code == 200
        paths1 = {e["relative_path"] for e in resp1.json()}
        paths2 = {e["relative_path"] for e in resp2.json()}
        assert paths1 == {"frames/000000.jpg", "bundle.pb"}
        assert paths2 == {"frames/000001.jpg", "bundle.pb"}


# ---------------------------------------------------------------------------
# Semantic manifest validation (gaps c + F3)
# ---------------------------------------------------------------------------

class TestUploadSessionSemanticValidation:
    def _post(self, client: TestClient, manifest: list[dict]):
        with (
            patch.object(server, "_token_verifier", NullTokenVerifier()),
            patch.object(server, "_upload_session_repo", InMemoryUploadSessionRepository()),
            # Most tests here assert a 400 and never reach the minter, but the
            # valid-manifest case does — and without this seam it resolved ADC
            # and 500'd on any uncredentialed machine.
            patch.object(server, "_mint_uri_fn", _fake_mint),
        ):
            return client.post(
                f"/captures/{_make_bundle_id()}/upload_session",
                json={"manifest": manifest},
                headers={"Authorization": _auth_header()},
            )

    def test_missing_expected_size_returns_400(self, client: TestClient) -> None:
        resp = self._post(client, [{"relative_path": "bundle.pb"}])
        assert resp.status_code == 400
        body = resp.json()
        assert body["error"] == "invalid_manifest"
        assert "expected_size_bytes" in body["detail"]

    def test_zero_expected_size_returns_400(self, client: TestClient) -> None:
        resp = self._post(
            client, [{"relative_path": "bundle.pb", "expected_size_bytes": 0}]
        )
        assert resp.status_code == 400
        assert resp.json()["error"] == "invalid_manifest"

    def test_non_integer_expected_size_returns_400(self, client: TestClient) -> None:
        resp = self._post(
            client, [{"relative_path": "bundle.pb", "expected_size_bytes": "big"}]
        )
        assert resp.status_code == 400
        assert resp.json()["error"] == "invalid_manifest"

    def test_unknown_directory_returns_400(self, client: TestClient) -> None:
        resp = self._post(client, [
            {"relative_path": "exfil/data.jpg", "expected_size_bytes": 100},
            {"relative_path": "bundle.pb", "expected_size_bytes": 64},
        ])
        assert resp.status_code == 400
        assert "exfil" in resp.json()["detail"]

    def test_unknown_extension_returns_400(self, client: TestClient) -> None:
        resp = self._post(client, [
            {"relative_path": "frames/000000.exe", "expected_size_bytes": 100},
            {"relative_path": "bundle.pb", "expected_size_bytes": 64},
        ])
        assert resp.status_code == 400
        assert resp.json()["error"] == "invalid_manifest"

    def test_nested_path_returns_400(self, client: TestClient) -> None:
        resp = self._post(client, [
            {"relative_path": "frames/deep/000000.jpg", "expected_size_bytes": 100},
            {"relative_path": "bundle.pb", "expected_size_bytes": 64},
        ])
        assert resp.status_code == 400
        assert resp.json()["error"] == "invalid_manifest"

    def test_duplicate_path_returns_400(self, client: TestClient) -> None:
        resp = self._post(client, [
            {"relative_path": "frames/000000.jpg", "expected_size_bytes": 100},
            {"relative_path": "frames/000000.jpg", "expected_size_bytes": 100},
            {"relative_path": "bundle.pb", "expected_size_bytes": 64},
        ])
        assert resp.status_code == 400
        assert "duplicate" in resp.json()["detail"]

    def test_manifest_without_bundle_pb_returns_400(self, client: TestClient) -> None:
        resp = self._post(
            client, [{"relative_path": "frames/000000.jpg", "expected_size_bytes": 100}]
        )
        assert resp.status_code == 400
        assert "bundle.pb" in resp.json()["detail"]

    def test_full_real_shape_manifest_accepted(self, client: TestClient) -> None:
        # The exact path shapes every deployed client emits (iOS
        # ManifestBuilder + the api-core fixture builder) must all pass.
        manifest = [
            {"relative_path": "frames/000000.jpg", "expected_size_bytes": 350_000},
            {"relative_path": "depth/000000.f32", "expected_size_bytes": 196_608},
            {"relative_path": "confidence/000000.png", "expected_size_bytes": 12_288},
            {"relative_path": "roomplan/room.json", "expected_size_bytes": 81_900},
            {"relative_path": "roomplan/room.usdz", "expected_size_bytes": 4_200_000},
            {"relative_path": "bundle.pb", "expected_size_bytes": 517_000},
        ]
        resp = self._post(client, manifest)
        assert resp.status_code == 200
        assert len(resp.json()) == len(manifest)


# ---------------------------------------------------------------------------
# Per-UID rate limit (gap b)
# ---------------------------------------------------------------------------

class TestUploadSessionRateLimit:
    def test_over_quota_returns_429_with_resets_at(
        self, client: TestClient, monkeypatch
    ) -> None:
        monkeypatch.setattr(server, "UPLOAD_DAILY_MINTS", 2)
        repo = InMemoryUploadSessionRepository()
        manifest = [{"relative_path": "bundle.pb", "expected_size_bytes": 64}]

        for _ in range(2):
            resp, _ = _post_upload_session(
                client, _make_bundle_id(), manifest, uid="user-q", upload_repo=repo
            )
            assert resp.status_code == 200

        resp, _ = _post_upload_session(
            client, _make_bundle_id(), manifest, uid="user-q", upload_repo=repo
        )
        assert resp.status_code == 429
        body = resp.json()
        assert body["error"] == "rate_limited"
        assert "resets_at" in body
        assert int(resp.headers["Retry-After"]) >= 1

    def test_replay_does_not_consume_quota(
        self, client: TestClient, monkeypatch
    ) -> None:
        # One mint at quota 1, then unlimited replays of the same manifest —
        # the timed-out-POST retry path must never be rate-limited.
        monkeypatch.setattr(server, "UPLOAD_DAILY_MINTS", 1)
        repo = InMemoryUploadSessionRepository()
        bundle_id = _make_bundle_id()
        manifest = [{"relative_path": "bundle.pb", "expected_size_bytes": 64}]

        first, _ = _post_upload_session(
            client, bundle_id, manifest, uid="user-r", upload_repo=repo
        )
        assert first.status_code == 200
        for _ in range(3):
            replay, _ = _post_upload_session(
                client, bundle_id, manifest, uid="user-r", upload_repo=repo
            )
            assert replay.status_code == 200
            assert replay.json() == first.json()

    def test_quota_is_per_uid(self, client: TestClient, monkeypatch) -> None:
        monkeypatch.setattr(server, "UPLOAD_DAILY_MINTS", 1)
        repo = InMemoryUploadSessionRepository()
        manifest = [{"relative_path": "bundle.pb", "expected_size_bytes": 64}]

        resp_a, _ = _post_upload_session(
            client, _make_bundle_id(), manifest, uid="user-a", upload_repo=repo
        )
        resp_b, _ = _post_upload_session(
            client, _make_bundle_id(), manifest, uid="user-b", upload_repo=repo
        )
        assert resp_a.status_code == 200
        assert resp_b.status_code == 200


class TestUploadSessionCaptureCeiling:
    """The GPU-cost ceiling (decision 0098). Distinct from the mint quota
    above: that one bounds API calls, this bounds reconstruction runs."""

    def test_over_ceiling_returns_429_capture_limit_reached(
        self, client: TestClient, monkeypatch
    ) -> None:
        monkeypatch.setattr(server, "UPLOAD_DAILY_CAPTURES", 2)
        monkeypatch.setattr(server, "UPLOAD_DAILY_MINTS", 50)
        repo = InMemoryUploadSessionRepository()
        manifest = [{"relative_path": "bundle.pb", "expected_size_bytes": 64}]

        for _ in range(2):
            resp, _ = _post_upload_session(
                client, _make_bundle_id(), manifest, uid="user-c", upload_repo=repo
            )
            assert resp.status_code == 200

        resp, _ = _post_upload_session(
            client, _make_bundle_id(), manifest, uid="user-c", upload_repo=repo
        )
        assert resp.status_code == 429
        body = resp.json()
        # A distinct code from rate_limited — the client should say a
        # different thing, and the operator should see a different signal.
        assert body["error"] == "capture_limit_reached"
        assert "resets_at" in body
        assert int(resp.headers["Retry-After"]) >= 1

    def test_re_minting_an_existing_capture_is_not_a_new_capture(
        self, client: TestClient, monkeypatch
    ) -> None:
        monkeypatch.setattr(server, "UPLOAD_DAILY_CAPTURES", 1)
        monkeypatch.setattr(server, "UPLOAD_DAILY_MINTS", 50)
        repo = InMemoryUploadSessionRepository()
        bundle_id = _make_bundle_id()

        first, _ = _post_upload_session(
            client, bundle_id,
            [{"relative_path": "bundle.pb", "expected_size_bytes": 64}],
            uid="user-d", upload_repo=repo,
        )
        assert first.status_code == 200

        # 0049 re-mint: same bundle, grown path set. No new GPU is committed,
        # so it must not spend the account's one capture.
        again, _ = _post_upload_session(
            client, bundle_id,
            [
                {"relative_path": "bundle.pb", "expected_size_bytes": 64},
                {"relative_path": "frames/000000.jpg", "expected_size_bytes": 999},
            ],
            uid="user-d", upload_repo=repo,
        )
        assert again.status_code == 200


# ---------------------------------------------------------------------------
# Hermeticity — the endpoint must not need cloud credentials to be tested
# ---------------------------------------------------------------------------

class TestUploadSessionNeedsNoCredentials:
    """These tests are the CI defect's regression pins.

    The first CI run this repo ever executed failed 12 tests in this file with
    `DefaultCredentialsError` -> 500. They had been green on the operator's
    machine for months because `gcloud auth application-default login` leaves
    ambient ADC lying around: the suite was silently testing against a real
    credential resolution path and nobody could tell.

    The fix is the `_mint_uri_fn` seam in public_server. These two tests pin
    both halves of it, and they are deliberately a matched pair — each one
    alone can be satisfied by a change that breaks the other.
    """

    def test_handler_succeeds_with_no_ambient_credentials(
        self, client: TestClient
    ) -> None:
        """A machine with NO credentials at all must still get 200.

        Simulates the CI runner directly rather than trusting the seam by
        inspection: google.auth.default is made to raise exactly what an
        uncredentialed environment raises. Before the seam this asserted
        500 == 200, which is the CI failure verbatim.
        """
        import google.auth
        from google.auth.exceptions import DefaultCredentialsError
        from roomstudio_api_core import upload_session_repo as usr

        def _no_credentials_anywhere(scopes=None):
            raise DefaultCredentialsError("no ADC (simulated CI runner)")

        bundle_id = _make_bundle_id()
        manifest = [{"relative_path": "bundle.pb", "expected_size_bytes": 128}]

        with (
            patch.object(google.auth, "default", _no_credentials_anywhere),
            # Drop any AuthorizedSession a previous test cached on this
            # thread, so the credential path is genuinely reached.
            patch.object(usr, "_mint_thread_local", threading.local()),
        ):
            resp, _ = _post_upload_session(client, bundle_id, manifest)

        assert resp.status_code == 200
        assert resp.json()[0]["relative_path"] == "bundle.pb"

    def test_seam_defaults_to_the_real_minter(self) -> None:
        """Unpatched, the seam MUST vend the production minter.

        The pin that stops the previous test from being satisfied the wrong
        way. Defaulting `_mint_uri_fn` to a fake would turn CI green and ship
        an api-public that hands clients fabricated session URIs — every
        upload would fail in the field while the suite stayed green.
        """
        assert server._mint_uri_fn is None, "production default must be unset"
        assert server._get_mint_uri_fn() is server.gcs_mint_resumable_uri
