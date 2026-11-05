"""The scene-finish app: health never starts Chrome, /render maps results and failures."""

import base64
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from finish_server import create_app
from render_client import Renderer

FAKE = str(Path(__file__).resolve().parent / "fake_driver.py")
FRAME = {"id": 5, "pos": [0, 1, 0], "quat": [0, 0, 0, 1], "fy": 1000, "h": 1440, "w": 1920}


@pytest.fixture(autouse=True)
def _state(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_STATE", str(tmp_path / "attempts"))


def client(started: list):
    def factory():
        started.append(1)
        return Renderer(command=[sys.executable, FAKE], timeout_s=20)

    return TestClient(create_app(factory))


def test_health_does_not_start_the_renderer():
    started: list = []
    with client(started) as c:
        assert c.get("/health").json() == {"status": "ok"}
    assert started == []


def test_render_returns_base64_pngs():
    started: list = []
    with client(started) as c:
        r = c.post("/render", json={"shell": {"mode": "ok"}, "frames": [FRAME], "width": 400})
    assert r.status_code == 200
    body = r.json()
    assert set(body["images"]) == {"frame_5", "ids_5", "mask_5"}
    assert base64.b64decode(body["images"]["frame_5"]).startswith(b"\x89PNG")
    assert started == [1]


def test_render_failure_is_a_502_with_the_reason():
    with client([]) as c:
        r = c.post("/render", json={"shell": {"mode": "error_always"}, "frames": [FRAME]})
    assert r.status_code == 502
    assert "never settled" in r.json()["detail"]


@pytest.mark.parametrize(
    "body",
    [
        {"shell": {}, "frames": []},
        {"shell": {}, "frames": [{**FRAME, "pos": [0, 1]}]},
        {"shell": {}, "frames": [FRAME], "width": 5000},
        {"frames": [FRAME]},
    ],
)
def test_bad_requests_are_422(body):
    with client([]) as c:
        assert c.post("/render", json=body).status_code == 422
