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

IMPORTANT: server.py must be loaded by file path to avoid the
services/api/server.py collision in sys.modules — see the same pattern and
comment in test_server_registry.py.

Run from repo root:
  pytest services/perception-obj/tests/test_server_routes.py -v
"""
from __future__ import annotations

import io
import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

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
# Helpers
# ---------------------------------------------------------------------------

def _fake_jpeg(size: tuple[int, int] = (8, 8)) -> bytes:
    """Return minimal valid JPEG bytes. Small enough to be fast in tests."""
    buf = io.BytesIO()
    Image.new("RGB", size).save(buf, format="JPEG")
    return buf.getvalue()


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


# ---------------------------------------------------------------------------
# POST /segment
# ---------------------------------------------------------------------------

class TestSegmentRoute:
    def test_valid_upload_invokes_sam3_segment(self):
        """/segment parses a multipart image upload and calls sam3.segment()."""
        mock_model = MagicMock()
        mock_model.segment.return_value = []

        with patch.object(server, "get_sam3", return_value=mock_model):
            resp = client.post(
                "/segment",
                files={"image": ("test.jpg", _fake_jpeg(), "image/jpeg")},
                data={"prompt": "chair,table"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert "objects" in body
        assert "image_size" in body
        mock_model.segment.assert_called_once()
        _, call_prompt = mock_model.segment.call_args[0]
        assert call_prompt == "chair,table"

    def test_uses_default_prompt_when_omitted(self):
        """/segment uses DEFAULT_OBJECT_PROMPT when no prompt form field is sent."""
        mock_model = MagicMock()
        mock_model.segment.return_value = []

        with patch.object(server, "get_sam3", return_value=mock_model):
            resp = client.post(
                "/segment",
                files={"image": ("test.jpg", _fake_jpeg(), "image/jpeg")},
            )

        assert resp.status_code == 200
        _, call_prompt = mock_model.segment.call_args[0]
        assert call_prompt == server.DEFAULT_OBJECT_PROMPT

    def test_missing_image_is_422(self):
        """/segment returns 422 when the image file field is absent."""
        resp = client.post("/segment", data={"prompt": "chair"})
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /segment-raw
# ---------------------------------------------------------------------------

class TestSegmentRawRoute:
    def test_valid_upload_returns_zip(self):
        """/segment-raw parses the upload and returns a zip stream."""
        mock_model = MagicMock()
        mock_model.segment.return_value = []

        with patch.object(server, "get_sam3", return_value=mock_model):
            resp = client.post(
                "/segment-raw",
                files={"image": ("test.jpg", _fake_jpeg(), "image/jpeg")},
            )

        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/zip")
        mock_model.segment.assert_called_once()

    def test_missing_image_is_422(self):
        resp = client.post("/segment-raw")
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /objects
# ---------------------------------------------------------------------------

class TestObjectsRoute:
    def test_valid_upload_invokes_sam3_returns_manifest(self):
        """/objects parses the upload, calls sam3.segment(), and returns a manifest."""
        mock_sam3 = MagicMock()
        mock_sam3.segment.return_value = []  # no objects → skips SAM 3D entirely

        with (
            patch.object(server, "get_sam3", return_value=mock_sam3),
            # Disable GCS: no cache hit, and mock the masks upload.
            patch.object(server, "_gcs_get_bytes", return_value=None),
            patch.object(server, "_gcs_upload", return_value="gs://fake/masks.npz"),
        ):
            resp = client.post(
                "/objects",
                files={"image": ("test.jpg", _fake_jpeg(), "image/jpeg")},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert "objects" in body
        assert "photo_sha256" in body
        assert body["objects"] == []
        mock_sam3.segment.assert_called_once()

    def test_cache_hit_returns_early_without_model(self):
        """/objects returns the cached manifest immediately when GCS cache hits."""
        cached = b'{"photo_sha256":"abc","objects":[],"image_size":[8,8],"cached":true}'

        with patch.object(server, "_gcs_get_bytes", return_value=cached):
            resp = client.post(
                "/objects",
                files={"image": ("test.jpg", _fake_jpeg(), "image/jpeg")},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["cached"] is True

    def test_missing_image_is_422(self):
        resp = client.post("/objects")
        assert resp.status_code == 422
