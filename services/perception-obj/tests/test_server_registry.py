"""Tests for the lazy model registry, health endpoints, and route registration.

Verifies:
  - /health always returns 200 without touching the model registry.
  - /ready reports the correct per-model status in each registry state.
  - get_sam3() / get_sam3d() trigger deferred model import + construction.
  - Cached failure: a failed load raises HTTPException on every subsequent call.
  - POST /process body is parsed as a ProcessRequest model, not a query param.

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
from unittest.mock import MagicMock, patch

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


# ---------------------------------------------------------------------------
# POST /process — route registration (TestClient level)
# ---------------------------------------------------------------------------

class TestProcessRoute:
    """TestClient-level tests for POST /process.

    These test FastAPI route registration — specifically that ProcessRequest is
    resolved as a request body model, not a query parameter. Tests that call
    handle_process() directly do not catch this class of bug (see the 422
    incident in docs/decisions/0010 and the fix in fix(perception-obj) commit).
    """

    def test_valid_body_reaches_handler(self):
        """A valid JSON body must reach handle_process as a ProcessRequest.

        Asserts the positive contract: FastAPI parses {scene_id, bundle_uri} as
        a body model and passes a fully-populated ProcessRequest to the handler.
        """
        from process_receiver import ProcessRequest

        captured: dict = {}

        async def _fake_handle(request, req, **kwargs):
            captured["req"] = req
            from fastapi.responses import JSONResponse
            return JSONResponse({"status": "mocked"})

        with (
            patch("process_receiver.handle_process", _fake_handle),
            patch.object(server, "get_sam3", return_value=MagicMock()),
            patch.object(server, "get_sam3d", return_value=MagicMock()),
            patch.object(server, "_get_oidc_verifier", return_value=None),
            patch.object(server, "_get_receiver_repo", return_value=MagicMock()),
            patch.object(server, "_get_fcm_notifier", return_value=MagicMock()),
        ):
            resp = client.post(
                "/process",
                json={"scene_id": "abc-123", "bundle_uri": "gs://b/bundle.pb"},
            )

        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        req = captured.get("req")
        assert req is not None, "handle_process was not called — body may not have been parsed"
        assert isinstance(req, ProcessRequest), f"Expected ProcessRequest, got {type(req)}"
        assert req.scene_id == "abc-123"
        assert req.bundle_uri == "gs://b/bundle.pb"

    def test_missing_body_is_body_error_not_query_error(self):
        """Regression guard: missing body must produce loc=['body',...], not
        loc=['query','req']. The broken pre-fix behavior was the latter — caused
        by ProcessRequest being imported after the route registration so FastAPI
        couldn't resolve the annotation and fell back to treating req as a query
        parameter."""
        resp = client.post("/process")
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        locs = [d["loc"] for d in detail]
        assert all(loc[0] == "body" for loc in locs), (
            f"Query-param validation error indicates annotation not resolved: {locs}"
        )


# ---------------------------------------------------------------------------
# POST /shell — route registration (TestClient level; decision 0066)
# ---------------------------------------------------------------------------

class TestShellRoute:
    """Same 0010 rule as TestProcessRoute, for the shell stage — plus the
    0066 hard constraint that /shell never triggers a model load."""

    def test_valid_body_reaches_handler_without_model_load(self):
        from shell_receiver import ShellRequest

        captured: dict = {}

        async def _fake_handle(request, req, **kwargs):
            captured["req"] = req
            from fastapi.responses import JSONResponse
            return JSONResponse({"status": "mocked"})

        def _model_access_forbidden(*a, **k):
            raise AssertionError("/shell must never touch the SAM accessors")

        with (
            patch("shell_receiver.handle_shell", _fake_handle),
            patch.object(server, "get_sam3", _model_access_forbidden),
            patch.object(server, "get_sam3d", _model_access_forbidden),
            patch.object(server, "_get_shell_oidc_verifier", return_value=None),
        ):
            resp = client.post(
                "/shell",
                json={"scene_id": "abc-123", "bundle_uri": "gs://b/bundle.pb"},
            )

        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        req = captured.get("req")
        assert req is not None, "handle_shell was not called — body may not have been parsed"
        assert isinstance(req, ShellRequest), f"Expected ShellRequest, got {type(req)}"
        assert req.scene_id == "abc-123"
        assert req.bundle_uri == "gs://b/bundle.pb"

    def test_missing_body_is_body_error_not_query_error(self):
        resp = client.post("/shell")
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        locs = [d["loc"] for d in detail]
        assert all(loc[0] == "body" for loc in locs), (
            f"Query-param validation error indicates annotation not resolved: {locs}"
        )

    def test_shell_oidc_audience_is_shell_path(self):
        """The /shell verifier's audience must be RECEIVER_URL + '/shell' —
        a /process token must not replay against this endpoint."""
        import process_receiver

        with patch.object(process_receiver, "CLOUD_TASKS_INVOKER_SA", "sa@x.iam"):
            server._shell_oidc_verifier = None
            verifier = server._get_shell_oidc_verifier()
            server._shell_oidc_verifier = None  # don't leak into other tests
        assert verifier is not None
        assert verifier._audience.endswith("/shell")
