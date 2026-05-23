"""Tests for the lazy model registry and health endpoints in server.py.

Verifies:
  - /health always returns 200 without touching the model registry.
  - /ready reports the correct per-model status in each registry state.
  - get_sam3() / get_sam3d() trigger deferred model import + construction.
  - Cached failure: a failed load raises HTTPException on every subsequent call.

Strategy: import server once at module level (after stubbing torch and the
model packages). Between tests, reset only the registry module globals so we
get a clean slate without paying the cost — or fragility — of full module
reimports across an already-collected test suite.

IMPORTANT: services/api/server.py also exists. When the full test suite runs,
the api tests execute first, caching services/api/server.py as
sys.modules["server"]. We must import by file path (not by name) to
unconditionally get the perception-obj server.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Stub heavy deps before importing the perception-obj server.
# test_process_receiver.py also stubs torch at module level via setdefault(),
# but we use an explicit assignment so our cuda.is_available stub wins.
# ---------------------------------------------------------------------------
_torch_stub = MagicMock()
_torch_stub.cuda.is_available.return_value = False
sys.modules["torch"] = _torch_stub
sys.modules.setdefault("models", MagicMock())
sys.modules.setdefault("models.sam3", MagicMock())
sys.modules.setdefault("models.sam3d", MagicMock())

# Load by absolute path so we always get services/perception-obj/server.py,
# regardless of which server.py pytest may have cached as sys.modules["server"]
# from an earlier test collection pass (e.g. services/api/server.py).
_PERC_SERVER_PATH = Path(__file__).resolve().parents[1] / "server.py"
_spec = importlib.util.spec_from_file_location("perc_server", _PERC_SERVER_PATH)
server = importlib.util.module_from_spec(_spec)
sys.modules["perc_server"] = server
_spec.loader.exec_module(server)


# ---------------------------------------------------------------------------
# Per-test registry reset
# ---------------------------------------------------------------------------

def _reset_registry() -> None:
    """Zero out all server-level registry state between tests."""
    server._sam3 = None
    server._sam3d = None
    server._sam3_error = None
    server._sam3d_error = None
    server._sam3_loading = False
    server._sam3d_loading = False
    # Re-initialise the locks so tests with injected failures don't leave
    # them in an unexpected state (threading.Lock() is always unlocked initially).
    import threading
    server._sam3_lock = threading.Lock()
    server._sam3d_lock = threading.Lock()


@pytest.fixture(autouse=True)
def clean_registry():
    """Auto-use fixture: reset registry globals before every test."""
    _reset_registry()
    # Also reset the model stubs so side_effect / return_value from one test
    # don't bleed into the next.
    sys.modules["models.sam3"] = MagicMock()
    sys.modules["models.sam3d"] = MagicMock()
    yield
    _reset_registry()


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------

from fastapi.testclient import TestClient  # noqa: E402

client = TestClient(server.app)


class TestHealthz:
    def test_always_200(self):
        """/health returns 200 with no model interaction regardless of state."""
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_200_when_models_not_loaded(self):
        """/health is 200 even before any model has been touched."""
        assert server._sam3 is None
        assert server._sam3d is None
        assert client.get("/health").status_code == 200


# ---------------------------------------------------------------------------
# /ready
# ---------------------------------------------------------------------------

class TestReadyz:
    def test_not_loaded_state(self):
        """/ready reports not_loaded for both models before any /process call."""
        resp = client.get("/ready")
        assert resp.status_code == 503
        body = resp.json()
        assert body["sam3"] == "not_loaded"
        assert body["sam3d"] == "not_loaded"

    def test_loaded_state(self):
        """/ready reports loaded for both models after registry is populated."""
        server._sam3 = MagicMock()
        server._sam3d = MagicMock()
        resp = client.get("/ready")
        assert resp.status_code == 200
        body = resp.json()
        assert body["sam3"] == "loaded"
        assert body["sam3d"] == "loaded"

    def test_failed_state(self):
        """/ready reports failed when an error is recorded."""
        server._sam3_error = "RuntimeError: CUDA not available"
        resp = client.get("/ready")
        assert resp.status_code == 500
        body = resp.json()
        assert body["sam3"] == "failed"
        assert body["sam3_error"] == "RuntimeError: CUDA not available"

    def test_loading_state(self):
        """/ready reports loading when the loading flag is set."""
        server._sam3_loading = True
        resp = client.get("/ready")
        assert resp.status_code == 503
        assert resp.json()["sam3"] == "loading"

    def test_partial_loaded(self):
        """/ready is 503 when sam3 is loaded but sam3d is not yet."""
        server._sam3 = MagicMock()
        # sam3d still None
        resp = client.get("/ready")
        assert resp.status_code == 503
        body = resp.json()
        assert body["sam3"] == "loaded"
        assert body["sam3d"] == "not_loaded"


# ---------------------------------------------------------------------------
# get_sam3 / get_sam3d accessors
# ---------------------------------------------------------------------------

class TestAccessors:
    def test_get_sam3_constructs_on_first_call(self):
        """get_sam3() imports models.sam3 and constructs SAM3Model on first call."""
        fake_instance = MagicMock()
        sys.modules["models.sam3"].SAM3Model.return_value = fake_instance

        result = server.get_sam3()
        assert result is fake_instance
        assert server._sam3 is fake_instance

    def test_get_sam3_cached(self):
        """get_sam3() returns the same instance on subsequent calls."""
        fake_instance = MagicMock()
        sys.modules["models.sam3"].SAM3Model.return_value = fake_instance

        first = server.get_sam3()
        second = server.get_sam3()
        assert first is second
        # SAM3Model should only have been constructed once.
        sys.modules["models.sam3"].SAM3Model.assert_called_once()

    def test_get_sam3_failure_cached(self):
        """get_sam3() caches failure: raises HTTPException on every call after
        the first failed load."""
        from fastapi import HTTPException
        sys.modules["models.sam3"].SAM3Model.side_effect = RuntimeError("boom")

        with pytest.raises(HTTPException) as exc_info:
            server.get_sam3()
        assert exc_info.value.status_code == 500
        assert server._sam3_error is not None

        # Second call — error is cached, should raise immediately without
        # trying to construct again.
        with pytest.raises(HTTPException):
            server.get_sam3()

    def test_get_sam3d_constructs_on_first_call(self):
        """get_sam3d() imports models.sam3d and constructs SAM3DModel on first call."""
        fake_instance = MagicMock()
        sys.modules["models.sam3d"].SAM3DModel.return_value = fake_instance

        result = server.get_sam3d()
        assert result is fake_instance
        assert server._sam3d is fake_instance
