"""TestClient-level route coverage for all perception-obj endpoints.

Verifies that every route: (a) is reachable via the FastAPI app, (b) parses
its request parameters correctly, and (c) invokes the handler. Tests here are
intentionally shallow — they do not verify model output or business logic.
That lives in test_process_receiver.py and the model unit tests.

The pattern: stub out heavy dependencies (model accessors, GCS) and confirm
the route wires up correctly. Even a 200 with mocked output proves the route
is registered and the request was parsed.

Why TestClient tests alongside handler tests:
  Handler-level tests (test_process_receiver.py) call the handler function
  directly — they never exercise FastAPI route registration. A mistyped
  annotation or an import placed in the wrong order silently misroutes
  requests. The 422 incident on POST /process (docs/decisions/0010) was
  caused by exactly this: the annotation resolved to a query parameter
  instead of a body model, all handler tests passed, production broke.

IMPORTANT: server.py is loaded by file path, not module name, so no other
server.py cached as sys.modules["server"] can shadow it — see the same
pattern and the full rationale in test_server_registry.py.

Run from repo root:
  pytest services/perception-obj/tests/test_server_routes.py -v
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Stub heavy deps before loading the server.
# test_server_registry.py does the same; both stubs are compatible — the
# setdefault calls here are no-ops when registry tests run first.
# ---------------------------------------------------------------------------
_torch_stub = sys.modules.get("torch") or MagicMock()
_torch_stub.cuda.is_available.return_value = False
sys.modules.setdefault("torch", _torch_stub)
sys.modules.setdefault("models", MagicMock())
sys.modules.setdefault("models.sam3", MagicMock())
sys.modules.setdefault("models.sam3d", MagicMock())

# Use the already-loaded perc_server if registry tests ran first; otherwise
# load it fresh. Either way, `server` is the perception-obj server module.
if "perc_server" in sys.modules:
    server = sys.modules["perc_server"]
else:
    _PERC_SERVER_PATH = Path(__file__).resolve().parents[1] / "server.py"
    _spec = importlib.util.spec_from_file_location("perc_server", _PERC_SERVER_PATH)
    server = importlib.util.module_from_spec(_spec)
    sys.modules["perc_server"] = server
    _spec.loader.exec_module(server)

from fastapi.testclient import TestClient  # noqa: E402

client = TestClient(server.app)


# ---------------------------------------------------------------------------
# GET /
# ---------------------------------------------------------------------------

class TestRoot:
    def test_returns_200_with_model_list(self):
        resp = client.get("/")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert "models" in body
        assert isinstance(body["models"], list)

