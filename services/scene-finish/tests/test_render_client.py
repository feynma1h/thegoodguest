"""The Python renderer client, against a fake driver speaking the same protocol."""

import sys
from pathlib import Path

import pytest
from render_client import MAX_FRAMES, RenderError, Renderer

FAKE = str(Path(__file__).resolve().parent / "fake_driver.py")
FRAME = {"id": 5, "pos": [0, 1, 0], "quat": [0, 0, 0, 1], "fy": 1000, "h": 1440, "w": 1920}


@pytest.fixture(autouse=True)
def _state(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_STATE", str(tmp_path / "attempts"))


def make() -> Renderer:
    return Renderer(command=[sys.executable, FAKE], timeout_s=20)


def test_returns_the_three_passes_per_frame_and_cleans_up(tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    r = make()
    try:
        out = r.render(shell={"mode": "ok"}, frames=[FRAME, {**FRAME, "id": 9}], finish={"a": 1})
    finally:
        r.close()
    assert set(out.images) == {f"{k}_{i}" for k in ("frame", "ids", "mask") for i in (5, 9)}
    assert all(v.startswith(b"\x89PNG") for v in out.images.values())
    assert out.info["glRenderer"] == "fake"
    assert list(tmp_path.glob("scene-finish-render-*")) == []  # the documents are gone


def test_one_retry_in_a_fresh_driver_after_a_crash():
    r = make()
    try:
        out = r.render(shell={"mode": "crash_first"}, frames=[FRAME])
    finally:
        r.close()
    assert "frame_5" in out.images


def test_one_retry_after_a_reported_error():
    r = make()
    try:
        out = r.render(shell={"mode": "error_first"}, frames=[FRAME])
    finally:
        r.close()
    assert "ids_5" in out.images


def test_second_failure_raises_with_the_drivers_reason():
    r = make()
    try:
        with pytest.raises(RenderError, match="never settled"):
            r.render(shell={"mode": "error_always"}, frames=[FRAME])
    finally:
        r.close()


@pytest.mark.parametrize(
    "kwargs,match",
    [
        ({"frames": []}, "no frames"),
        ({"frames": [FRAME] * (MAX_FRAMES + 1)}, "more than"),
        ({"frames": [FRAME], "width": 10}, "width"),
    ],
)
def test_invalid_jobs_are_refused_before_any_driver_starts(kwargs, match):
    r = make()
    with pytest.raises(RenderError, match=match):
        r.render(shell={"mode": "ok"}, **kwargs)
    assert r._proc is None
