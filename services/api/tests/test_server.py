"""Tests for server-level concerns: health endpoint and startup validation.

Covers:
  - GET /health returns 200 {"status": "ok"} unconditionally.
  - _check_production_env() is a no-op when ENVIRONMENT is unset.
  - _check_production_env() is a no-op when ENVIRONMENT != "production".
  - _check_production_env() passes when ENVIRONMENT=production and all vars set.
  - _check_production_env() raises RuntimeError listing each missing var when
    ENVIRONMENT=production and one or more required vars are absent.

The startup validation function is tested directly rather than through
TestClient+lifespan so tests don't require controlling process-level env vars
or spinning up/tearing down the full app per case.

Run from repo root:
  pytest services/api/tests/test_server.py -v
"""
from __future__ import annotations

import sys
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
# _check_production_env — unit tests (no ENVIRONMENT set)
# ---------------------------------------------------------------------------

class TestCheckProductionEnv:
    def test_no_env_var_is_noop(self) -> None:
        """ENVIRONMENT unset → no error regardless of other vars."""
        with patch.dict("os.environ", {}, clear=False):
            # Remove ENVIRONMENT if somehow present; leave everything else alone.
            env_without = {k: v for k, v in __import__("os").environ.items()
                           if k != "ENVIRONMENT"}
            with patch.dict("os.environ", env_without, clear=True):
                _check_production_env()  # must not raise

    def test_environment_not_production_is_noop(self) -> None:
        """ENVIRONMENT=staging (or any non-"production" value) → no error."""
        with patch.dict("os.environ", {"ENVIRONMENT": "staging"}, clear=False):
            _check_production_env()  # must not raise

    def test_production_all_vars_set_passes(self) -> None:
        """ENVIRONMENT=production with all required vars set → no error."""
        full_env = {"ENVIRONMENT": "production"}
        full_env.update({v: "some-value" for v in _PRODUCTION_REQUIRED_VARS})
        with patch.dict("os.environ", full_env, clear=False):
            _check_production_env()  # must not raise

    def test_production_missing_var_raises(self) -> None:
        """ENVIRONMENT=production with one missing var → RuntimeError."""
        full_env = {"ENVIRONMENT": "production"}
        full_env.update({v: "some-value" for v in _PRODUCTION_REQUIRED_VARS})
        # Remove one required var.
        missing_var = "FIRESTORE_PROJECT"
        full_env.pop(missing_var)
        # Also clear it from os.environ if present via clear=True in patch.dict.
        with patch.dict("os.environ", full_env, clear=True):
            with pytest.raises(RuntimeError) as exc_info:
                _check_production_env()
        assert missing_var in str(exc_info.value)

    def test_production_multiple_missing_vars_all_listed(self) -> None:
        """RuntimeError message lists all missing vars, not just the first."""
        with patch.dict("os.environ", {"ENVIRONMENT": "production"}, clear=True):
            with pytest.raises(RuntimeError) as exc_info:
                _check_production_env()
        msg = str(exc_info.value)
        for var in _PRODUCTION_REQUIRED_VARS:
            assert var in msg, f"Expected {var!r} in error message"

    def test_production_empty_string_treated_as_missing(self) -> None:
        """An env var set to '' is treated the same as absent."""
        env = {"ENVIRONMENT": "production"}
        env.update({v: "some-value" for v in _PRODUCTION_REQUIRED_VARS})
        env["CLOUD_TASKS_QUEUE"] = ""  # explicitly empty
        with patch.dict("os.environ", env, clear=True):
            with pytest.raises(RuntimeError) as exc_info:
                _check_production_env()
        assert "CLOUD_TASKS_QUEUE" in str(exc_info.value)
