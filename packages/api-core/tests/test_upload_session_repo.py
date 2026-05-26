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

Run from repo root:
  pytest packages/api-core/tests/ -v
"""
from __future__ import annotations

import sys
from pathlib import Path

_api_core_dir = Path(__file__).resolve().parents[1]
if str(_api_core_dir) not in sys.path:
    sys.path.insert(0, str(_api_core_dir))

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
