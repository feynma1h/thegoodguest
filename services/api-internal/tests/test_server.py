"""Tests for api-internal server-level concerns: health endpoint and startup validation.

Covers:
  - GET /health returns 200 {"status": "ok"} unconditionally.
  - _check_production_env() is a no-op when ENVIRONMENT is unset.
  - _check_production_env() is a no-op when ENVIRONMENT != "production".
  - _check_production_env() passes when ENVIRONMENT=production and all vars set.
  - _check_production_env() raises RuntimeError listing each missing var when
    ENVIRONMENT=production and one or more required vars are absent.

api-internal required vars: FIRESTORE_PROJECT, CLOUD_TASKS_*, PERCEPTION_OBJ_PROCESS_URL.
GCS_CAPTURES_BUCKET is NOT required (bucket is extracted from the GCS URI at runtime).

Run from repo root:
  pytest services/api-internal/tests/test_server.py -v
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import server
from server import _check_production_env, _PRODUCTION_REQUIRED_VARS  # noqa: E402


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(server.app)


# ---------------------------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------------------------

class TestHealth:
    def test_health_returns_200(self, client: TestClient) -> None:
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_health_body(self, client: TestClient) -> None:
        resp = client.get("/health")
        assert resp.json() == {"status": "ok"}

    def test_health_content_type_json(self, client: TestClient) -> None:
        resp = client.get("/health")
        assert "application/json" in resp.headers["content-type"]


# ---------------------------------------------------------------------------
# _check_production_env — unit tests
# ---------------------------------------------------------------------------

class TestCheckProductionEnv:
    def test_no_env_var_is_noop(self) -> None:
        env_without = {k: v for k, v in __import__("os").environ.items()
                       if k != "ENVIRONMENT"}
        with patch.dict("os.environ", env_without, clear=True):
            _check_production_env()  # must not raise

    def test_environment_not_production_is_noop(self) -> None:
        with patch.dict("os.environ", {"ENVIRONMENT": "staging"}, clear=False):
            _check_production_env()  # must not raise

    def test_production_all_vars_set_passes(self) -> None:
        full_env = {"ENVIRONMENT": "production"}
        full_env.update({v: "some-value" for v in _PRODUCTION_REQUIRED_VARS})
        with patch.dict("os.environ", full_env, clear=False):
            _check_production_env()  # must not raise

    def test_production_missing_var_raises(self) -> None:
        full_env = {"ENVIRONMENT": "production"}
        full_env.update({v: "some-value" for v in _PRODUCTION_REQUIRED_VARS})
        missing_var = "FIRESTORE_PROJECT"
        full_env.pop(missing_var)
        with patch.dict("os.environ", full_env, clear=True):
            with pytest.raises(RuntimeError) as exc_info:
                _check_production_env()
        assert missing_var in str(exc_info.value)

    def test_production_multiple_missing_vars_all_listed(self) -> None:
        with patch.dict("os.environ", {"ENVIRONMENT": "production"}, clear=True):
            with pytest.raises(RuntimeError) as exc_info:
                _check_production_env()
        msg = str(exc_info.value)
        for var in _PRODUCTION_REQUIRED_VARS:
            assert var in msg, f"Expected {var!r} in error message"

    def test_production_empty_string_treated_as_missing(self) -> None:
        env = {"ENVIRONMENT": "production"}
        env.update({v: "some-value" for v in _PRODUCTION_REQUIRED_VARS})
        env["CLOUD_TASKS_QUEUE"] = ""
        with patch.dict("os.environ", env, clear=True):
            with pytest.raises(RuntimeError) as exc_info:
                _check_production_env()
        assert "CLOUD_TASKS_QUEUE" in str(exc_info.value)

    def test_gcs_captures_bucket_not_required(self) -> None:
        """GCS_CAPTURES_BUCKET must NOT be in api-internal's required vars.

        The ingest path extracts the bucket from the GCS URI; the env var is
        unused on this service. Startup validation should not gate on it.
        """
        assert "GCS_CAPTURES_BUCKET" not in _PRODUCTION_REQUIRED_VARS

    def test_required_vars_are_internal_only(self) -> None:
        """api-internal must require Cloud Tasks and perception vars."""
        required = set(_PRODUCTION_REQUIRED_VARS)
        assert "CLOUD_TASKS_PROJECT" in required
        assert "CLOUD_TASKS_LOCATION" in required
        assert "CLOUD_TASKS_QUEUE" in required
        assert "PERCEPTION_OBJ_PROCESS_URL" in required
