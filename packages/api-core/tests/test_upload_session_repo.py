"""Unit tests for roomstudio_api_core.upload_session_repo.

Tests the module directly — no FastAPI, no HTTP, no GCS credentials.

Covers:
  validate_manifest_path:
    - valid relative paths → None
    - empty path → error string
    - leading slash → error string
    - gs:// prefix → error string
    - .. traversal → error string

  InMemoryUploadSessionRepository:
    - get_user_id: None for unknown bundle_id, stored uid after create_or_get
    - create_or_get: mints URIs, returns entries
    - create_or_get idempotency: same manifest paths → same entries
    - create_or_get replacement: different paths → new entries
    - get_fcm_token: None for unknown, stored token after create_or_get
    - parallel minting: manifest order preserved, real overlap, first error
      aborts without storing, UPLOAD_SESSION_MINT_CONCURRENCY=1 serial path

Run from repo root:
  pytest packages/api-core/tests/ -v
"""
from __future__ import annotations

import threading
import time

import pytest

from roomstudio_api_core.upload_session_repo import (
    InMemoryUploadSessionRepository,
    validate_manifest_path,
)


# ---------------------------------------------------------------------------
# validate_manifest_path
# ---------------------------------------------------------------------------

class TestValidateManifestPath:
    def test_valid_simple_path(self) -> None:
        assert validate_manifest_path("bundle.pb") is None

    def test_valid_nested_path(self) -> None:
        assert validate_manifest_path("frames/000000.jpg") is None

    def test_valid_deeply_nested(self) -> None:
        assert validate_manifest_path("depth/raw/000000.f32") is None

    def test_empty_path_returns_error(self) -> None:
        err = validate_manifest_path("")
        assert err is not None
        assert "empty" in err

    def test_leading_slash_returns_error(self) -> None:
        err = validate_manifest_path("/frames/000000.jpg")
        assert err is not None
        assert "relative" in err

    def test_gcs_prefix_returns_error(self) -> None:
        err = validate_manifest_path("gs://bucket/frames/000000.jpg")
        assert err is not None
        assert "relative" in err

    def test_dotdot_traversal_returns_error(self) -> None:
        err = validate_manifest_path("../other/bundle.pb")
        assert err is not None
        assert ".." in err

    def test_dotdot_in_middle_returns_error(self) -> None:
        err = validate_manifest_path("frames/../../../etc/passwd")
        assert err is not None

    def test_single_dot_is_valid(self) -> None:
        # A single dot is not a traversal — just an unusual path segment.
        assert validate_manifest_path("./frames/000000.jpg") is None


# ---------------------------------------------------------------------------
# InMemoryUploadSessionRepository
# ---------------------------------------------------------------------------

def _fake_mint(bucket: str, blob_path: str, size_bytes: int) -> str:
    return f"https://fake/{blob_path}"


class TestInMemoryUploadSessionRepository:
    def test_get_user_id_unknown_returns_none(self) -> None:
        repo = InMemoryUploadSessionRepository()
        assert repo.get_user_id("unknown-bundle-id") is None

    def test_create_or_get_returns_entries(self) -> None:
        repo = InMemoryUploadSessionRepository()
        manifest = [
            {"relative_path": "frames/000000.jpg", "expected_size_bytes": 512},
            {"relative_path": "bundle.pb", "expected_size_bytes": 128},
        ]
        entries = repo.create_or_get(
            "bundle-1", "user-a", manifest, None,
            mint_uri_fn=_fake_mint, bucket="test-bucket",
        )
        assert len(entries) == 2
        paths = {e["relative_path"] for e in entries}
        assert paths == {"frames/000000.jpg", "bundle.pb"}
        for e in entries:
            assert e["session_uri"].startswith("https://fake/")

    def test_get_user_id_after_create(self) -> None:
        repo = InMemoryUploadSessionRepository()
        manifest = [{"relative_path": "bundle.pb", "expected_size_bytes": 128}]
        repo.create_or_get("b1", "user-abc", manifest, None, mint_uri_fn=_fake_mint, bucket="b")
        assert repo.get_user_id("b1") == "user-abc"

    def test_idempotency_same_paths_returns_same_entries(self) -> None:
        repo = InMemoryUploadSessionRepository()
        manifest = [{"relative_path": "bundle.pb", "expected_size_bytes": 128}]
        e1 = repo.create_or_get("b1", "user-a", manifest, None, mint_uri_fn=_fake_mint, bucket="bkt")
        e2 = repo.create_or_get("b1", "user-a", manifest, None, mint_uri_fn=_fake_mint, bucket="bkt")
        assert e1 == e2

    def test_different_paths_replaces_entries(self) -> None:
        repo = InMemoryUploadSessionRepository()
        m1 = [{"relative_path": "a.jpg", "expected_size_bytes": 100}]
        m2 = [{"relative_path": "b.jpg", "expected_size_bytes": 100}]
        e1 = repo.create_or_get("b1", "u", m1, None, mint_uri_fn=_fake_mint, bucket="bkt")
        e2 = repo.create_or_get("b1", "u", m2, None, mint_uri_fn=_fake_mint, bucket="bkt")
        assert {x["relative_path"] for x in e1} == {"a.jpg"}
        assert {x["relative_path"] for x in e2} == {"b.jpg"}

    def test_get_fcm_token_unknown_returns_none(self) -> None:
        repo = InMemoryUploadSessionRepository()
        assert repo.get_fcm_token("unknown") is None

    def test_get_fcm_token_stored(self) -> None:
        repo = InMemoryUploadSessionRepository()
        manifest = [{"relative_path": "bundle.pb", "expected_size_bytes": 128}]
        repo.create_or_get("b1", "u", manifest, "fcm-tok-xyz", mint_uri_fn=_fake_mint, bucket="bkt")
        assert repo.get_fcm_token("b1") == "fcm-tok-xyz"

    def test_get_fcm_token_none_when_not_provided(self) -> None:
        repo = InMemoryUploadSessionRepository()
        manifest = [{"relative_path": "bundle.pb", "expected_size_bytes": 128}]
        repo.create_or_get("b1", "u", manifest, None, mint_uri_fn=_fake_mint, bucket="bkt")
        assert repo.get_fcm_token("b1") is None

    def test_uri_includes_bundle_id_and_path(self) -> None:
        repo = InMemoryUploadSessionRepository()
        manifest = [{"relative_path": "frames/000000.jpg", "expected_size_bytes": 0}]
        entries = repo.create_or_get(
            "my-bundle-id", "u", manifest, None,
            mint_uri_fn=_fake_mint, bucket="bkt",
        )
        assert "my-bundle-id" in entries[0]["session_uri"]
        assert "frames/000000.jpg" in entries[0]["session_uri"]


# ---------------------------------------------------------------------------
# Parallel minting (invariants of create_or_get, through the public interface)
# ---------------------------------------------------------------------------

def _sized_manifest(n: int) -> list[dict]:
    return [
        {"relative_path": f"frames/{i:06d}.jpg", "expected_size_bytes": i}
        for i in range(n)
    ]


class TestParallelMinting:
    """Minting runs on a bounded pool since the 878-path serial mint took ~80 s
    in production (2026-07-26) and blew the client's 60 s timeout. These pin
    the contract, not the pool: order, real overlap, abort-without-store, and
    the serial fallback all must survive any reimplementation.
    """

    def test_entries_preserve_manifest_order(self) -> None:
        # Per-path jitter makes later entries finish earlier; the returned
        # list must still be in manifest order with each URI matching its own
        # path.
        def jittered_mint(bucket: str, blob_path: str, size_bytes: int) -> str:
            time.sleep((hash(blob_path) % 5) / 1000)
            return f"https://fake/{blob_path}"

        repo = InMemoryUploadSessionRepository()
        manifest = _sized_manifest(64)
        entries = repo.create_or_get(
            "b1", "u", manifest, None, mint_uri_fn=jittered_mint, bucket="bkt",
        )
        assert [e["relative_path"] for e in entries] == [
            m["relative_path"] for m in manifest
        ]
        for e in entries:
            assert e["session_uri"].endswith(f"captures/b1/{e['relative_path']}")

    def test_minting_actually_overlaps(self) -> None:
        lock = threading.Lock()
        in_flight = 0
        max_in_flight = 0

        def counting_mint(bucket: str, blob_path: str, size_bytes: int) -> str:
            nonlocal in_flight, max_in_flight
            with lock:
                in_flight += 1
                max_in_flight = max(max_in_flight, in_flight)
            time.sleep(0.02)
            with lock:
                in_flight -= 1
            return f"https://fake/{blob_path}"

        repo = InMemoryUploadSessionRepository()
        repo.create_or_get(
            "b1", "u", _sized_manifest(8), None,
            mint_uri_fn=counting_mint, bucket="bkt",
        )
        assert max_in_flight > 1

    def test_first_error_aborts_and_stores_nothing(self) -> None:
        def failing_mint(bucket: str, blob_path: str, size_bytes: int) -> str:
            if blob_path.endswith("000003.jpg"):
                raise RuntimeError("mint boom")
            return f"https://fake/{blob_path}"

        repo = InMemoryUploadSessionRepository()
        with pytest.raises(RuntimeError, match="mint boom"):
            repo.create_or_get(
                "b1", "u", _sized_manifest(16), None,
                mint_uri_fn=failing_mint, bucket="bkt",
            )
        # A failed mint must not leave a partial record: the retry must take
        # the mint-everything path, not the idempotent short-circuit.
        assert repo.get_user_id("b1") is None

    def test_concurrency_one_is_serial_and_correct(self, monkeypatch) -> None:
        monkeypatch.setenv("UPLOAD_SESSION_MINT_CONCURRENCY", "1")
        lock = threading.Lock()
        in_flight = 0
        max_in_flight = 0

        def counting_mint(bucket: str, blob_path: str, size_bytes: int) -> str:
            nonlocal in_flight, max_in_flight
            with lock:
                in_flight += 1
                max_in_flight = max(max_in_flight, in_flight)
            time.sleep(0.005)
            with lock:
                in_flight -= 1
            return f"https://fake/{blob_path}"

        repo = InMemoryUploadSessionRepository()
        manifest = _sized_manifest(6)
        entries = repo.create_or_get(
            "b1", "u", manifest, None, mint_uri_fn=counting_mint, bucket="bkt",
        )
        assert max_in_flight == 1
        assert [e["relative_path"] for e in entries] == [
            m["relative_path"] for m in manifest
        ]

    def test_empty_manifest_returns_empty_list(self) -> None:
        repo = InMemoryUploadSessionRepository()
        entries = repo.create_or_get(
            "b1", "u", [], None, mint_uri_fn=_fake_mint, bucket="bkt",
        )
        assert entries == []


# ---------------------------------------------------------------------------
# gcs_mint_resumable_uri session caching
# ---------------------------------------------------------------------------

class TestMintSessionCache:
    """The production minter reuses one AuthorizedSession per thread.

    Pins the RP-8 fix: per-call google.auth.default() + AuthorizedSession
    construction OOM-killed the 512 MiB api-public instance on a 2,170-path
    manifest at mint concurrency 64. Credentials resolution and session
    construction must happen at most once per thread, not once per path.
    """

    def _patch_auth(self, monkeypatch):
        import google.auth
        import google.auth.transport.requests as gatr

        counts = {"default": 0, "session": 0}

        class _FakeResponse:
            headers = {"Location": "https://fake-session-uri"}

            @staticmethod
            def raise_for_status() -> None:
                return None

        class _FakeSession:
            def __init__(self, credentials) -> None:
                counts["session"] += 1

            def post(self, url, headers=None, json=None):
                return _FakeResponse()

        def _fake_default(scopes=None):
            counts["default"] += 1
            return object(), "proj"

        monkeypatch.setattr(google.auth, "default", _fake_default)
        monkeypatch.setattr(gatr, "AuthorizedSession", _FakeSession)
        return counts

    def test_same_thread_constructs_one_session(self, monkeypatch) -> None:
        from roomstudio_api_core import upload_session_repo as usr

        counts = self._patch_auth(monkeypatch)
        monkeypatch.setattr(usr, "_mint_thread_local", threading.local())

        for i in range(5):
            uri = usr.gcs_mint_resumable_uri("bkt", f"captures/b/{i}.jpg", 10)
            assert uri == "https://fake-session-uri"
        assert counts["default"] == 1
        assert counts["session"] == 1

    def test_distinct_threads_get_distinct_sessions(self, monkeypatch) -> None:
        from roomstudio_api_core import upload_session_repo as usr

        counts = self._patch_auth(monkeypatch)
        monkeypatch.setattr(usr, "_mint_thread_local", threading.local())

        def _mint_two() -> None:
            usr.gcs_mint_resumable_uri("bkt", "captures/b/a.jpg", 10)
            usr.gcs_mint_resumable_uri("bkt", "captures/b/b.jpg", 10)

        threads = [threading.Thread(target=_mint_two) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        # One construction per thread — not per call (6 calls total).
        assert counts["session"] == 3
