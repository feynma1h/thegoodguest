"""POST /still: the room's still picture, end to end against the fake driver,
an in-memory bucket and an in-memory scenes collection (no cloud, no Chrome)."""

import io
import json
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from finish_server import create_app
from PIL import Image
from render_client import STILL_HEIGHT_PX, STILL_WIDTH_PX, RenderError, Renderer
from routes_still import StillDeps
from still_ports import STILL_DAY, STILL_NIGHT, InMemoryStillMarker, InMemoryStillStore
from task_auth import OidcAuthorizer, authorizer_from_env, no_check

FAKE = str(Path(__file__).resolve().parent / "fake_driver.py")
SID = "e64fab6a-f48e-427a-bcc9-f72208c6357d"
SHELL = {"mode": "ok", "status": "ready", "walls": [], "floor": {}}


@pytest.fixture(autouse=True)
def _state(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_STATE", str(tmp_path / "attempts"))


def jobs_run(tmp_path) -> int:
    p = tmp_path / "attempts"
    return int(p.read_text()) if p.exists() else 0


def doc(d: dict) -> bytes:
    return json.dumps(d).encode()


def scene_files(**docs) -> dict:
    return {(SID, f"{name}.json"): doc(d) for name, d in docs.items()}


class Rig:
    def __init__(self, blobs=None, scenes=None, authorize=no_check, delete_on_mark=False):
        self.store = InMemoryStillStore(blobs)
        self.marker = InMemoryStillMarker({SID: {"status": "ready"}} if scenes is None else scenes,
                                          delete_on_mark=delete_on_mark)
        deps = StillDeps(store=self.store, marker=self.marker, authorize=authorize)
        self.app = create_app(lambda: Renderer(command=[sys.executable, FAKE], timeout_s=20), lambda: deps)

    def post(self, body=None, headers=None):
        with TestClient(self.app) as c:
            return c.post("/still", json=body if body is not None else {"scene_id": SID}, headers=headers or {})


def image(data: bytes) -> Image.Image:
    im = Image.open(io.BytesIO(data))
    im.load()
    return im


def test_a_bare_shell_gets_a_day_still_and_no_night():
    rig = Rig(scene_files(shell=SHELL))
    r = rig.post()
    assert r.status_code == 200
    assert r.json() == {"status": "done", "night": False, "finished": False}
    day = image(rig.store.blobs[(SID, STILL_DAY)])
    assert (day.format, day.size) == ("JPEG", (STILL_WIDTH_PX, STILL_HEIGHT_PX))
    assert rig.store.content_types[(SID, STILL_DAY)] == "image/jpeg"
    assert (SID, STILL_NIGHT) not in rig.store.blobs
    assert rig.marker.scenes[SID]["still"]["night"] is False
    assert rig.marker.scenes[SID]["status"] == "ready"  # nothing else on the scene moved


def test_a_room_with_twins_gets_day_and_night():
    rig = Rig(scene_files(shell=SHELL, finish={"finish_version": 2}, furniture={"objects": [{"key": "bed"}]}))
    r = rig.post()
    assert r.json() == {"status": "done", "night": True, "finished": True}
    night = image(rig.store.blobs[(SID, STILL_NIGHT)])
    assert (night.format, night.size) == ("JPEG", (1600, 1200))
    assert rig.marker.scenes[SID]["still"]["night"] is True


def test_a_redraw_without_twins_removes_the_old_night_still():
    rig = Rig({**scene_files(shell=SHELL), (SID, STILL_NIGHT): b"old night"})
    assert rig.post().json()["night"] is False
    assert (SID, STILL_NIGHT) not in rig.store.blobs


def test_an_unreadable_finish_is_drawn_without_as_on_the_website():
    blobs = {**scene_files(shell=SHELL, furniture={"objects": []}), (SID, "finish.json"): b"{not json"}
    r = Rig(blobs).post()
    assert r.json() == {"status": "done", "night": False, "finished": False}


@pytest.mark.parametrize(
    "blobs,scenes,reason",
    [
        (scene_files(shell=SHELL), {}, "no_scene"),
        ({}, None, "no_shell"),
        (scene_files(shell={**SHELL, "status": "unavailable"}), None, "shell_unavailable"),
        ({(SID, "shell.json"): b"<html>"}, None, "shell_unreadable"),
    ],
)
def test_nothing_to_draw_drains_without_starting_chrome(tmp_path, blobs, scenes, reason):
    rig = Rig(blobs, scenes)
    r = rig.post()
    assert (r.status_code, r.json()) == (200, {"status": "skipped", "reason": reason})
    assert jobs_run(tmp_path) == 0
    assert (SID, STILL_DAY) not in rig.store.blobs


def test_a_failed_render_asks_the_queue_to_retry_and_writes_nothing():
    rig = Rig(scene_files(shell={**SHELL, "mode": "error_always"}))
    r = rig.post()
    assert r.status_code == 503
    assert "never settled" in r.json()["reason"]
    assert (SID, STILL_DAY) not in rig.store.blobs
    assert "still" not in rig.marker.scenes[SID]


def test_a_room_deleted_while_it_was_drawn_loses_its_pictures():
    rig = Rig(scene_files(shell=SHELL, finish={"f": 1}, furniture={"objects": []}), delete_on_mark=True)
    r = rig.post()
    assert r.json() == {"status": "skipped", "reason": "no_scene"}
    assert (SID, STILL_DAY) not in rig.store.blobs
    assert (SID, STILL_NIGHT) not in rig.store.blobs


def test_the_task_check_runs_before_anything_is_read(tmp_path):
    def refuse(request, path):
        assert path == "/still"
        raise HTTPException(status_code=401, detail="no")

    rig = Rig(scene_files(shell=SHELL), authorize=refuse)
    assert rig.post().status_code == 401
    assert jobs_run(tmp_path) == 0 and "still" not in rig.marker.scenes[SID]


@pytest.mark.parametrize("scene_id", ["../other", "a/b", "", "x" * 65])
def test_a_scene_id_that_is_not_one_is_refused(scene_id):
    assert Rig(scene_files(shell=SHELL)).post({"scene_id": scene_id}).status_code == 422


# -- the renderer's still job ------------------------------------------------


def make() -> Renderer:
    return Renderer(command=[sys.executable, FAKE], timeout_s=20)


def test_render_still_returns_jpegs_and_cleans_up(tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    r = make()
    try:
        out = r.render_still(shell=SHELL, finish={"f": 1}, furniture={"objects": []})
    finally:
        r.close()
    assert image(out.day).size == image(out.night).size == (1600, 1200)
    assert out.info["night"] is True and out.info["glRenderer"] == "fake"
    assert list(tmp_path.glob("scene-finish-still-*")) == []


@pytest.mark.parametrize("mode,match", [("wrong_size", "expected 1600x1200"), ("lose_night", "missing")])
def test_render_still_refuses_a_picture_it_did_not_ask_for(mode, match):
    r = make()
    try:
        with pytest.raises(RenderError, match=match):
            r.render_still(shell={**SHELL, "mode": mode}, finish={"f": 1}, furniture={"objects": []})
    finally:
        r.close()


# -- the task check ----------------------------------------------------------


class _Req:
    def __init__(self, auth=None):
        self.headers = {"Authorization": auth} if auth else {}


def test_the_token_must_be_for_this_route_and_from_the_invoker():
    seen = []

    def verify(token, audience):
        seen.append((token, audience))
        if token == "bad":
            raise ValueError("signature")
        return {"email": "tasks-invoker@x.iam.gserviceaccount.com" if token == "good" else "someone@else"}

    check = OidcAuthorizer("https://scene-finish.example/", "tasks-invoker@x.iam.gserviceaccount.com", verify)
    check(_Req("Bearer good"), "/still")
    assert seen == [("good", "https://scene-finish.example/still")]
    for auth in (None, "Basic good", "Bearer ", "Bearer bad", "Bearer other"):
        with pytest.raises(HTTPException) as e:
            check(_Req(auth), "/still")
        assert e.value.status_code == 401


def test_production_without_the_task_settings_refuses_to_run(monkeypatch):
    monkeypatch.delenv("RECEIVER_URL", raising=False)
    monkeypatch.delenv("CLOUD_TASKS_INVOKER_SA", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "production")
    with pytest.raises(RuntimeError):
        authorizer_from_env()
    monkeypatch.delenv("ENVIRONMENT")
    assert authorizer_from_env() is no_check
    monkeypatch.setenv("RECEIVER_URL", "https://s.example")
    monkeypatch.setenv("CLOUD_TASKS_INVOKER_SA", "inv@x")
    assert isinstance(authorizer_from_env(), OidcAuthorizer)
