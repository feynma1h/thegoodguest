"""The furniture loop, the merge, the routes, with a fake client and the stub renderer."""
import json
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import scenes
from claude_layer import constants as C
from claude_layer import publish
from claude_layer.client import ClaudeCaller, ClaudeUnusable, FakeClient
from claude_layer.enqueue import TaskList
from claude_layer.piece_loop import JobContext, piece_path, run_piece
from claude_layer.render import StubRenderer
from claude_layer.scene_port import LocalScenePort
from claude_layer.spend import SpendLedger
from claude_layer.wiring import Deps, register
from claude_layer.workspace import Workspace


@pytest.fixture
def scene(tmp_path):
    src = scenes.build(tmp_path / "src")
    return LocalScenePort("scene-x", src, tmp_path / "out")


def ctx_for(port, script, ceiling=12.0, assume_no_people=True, deadline_in=1e6):
    fake = FakeClient(script)
    ws = Workspace(port, assume_no_people=assume_no_people)
    caller = ClaudeCaller(fake, SpendLedger(port, "piece-box_0", ceiling), port.scene_id)
    return JobContext(port, ws, caller, StubRenderer(), "sha1", time.time() + deadline_in), fake


def start(port, now=None):
    return publish.start_job(port, now if now is not None else time.time(), ["box_0"])


def test_a_good_spec_passes_edits_stop_when_claude_says_done_and_pixels_are_deleted(scene):
    start(scene)
    ctx, fake = ctx_for(scene, [scenes.spec_answer(), {"done": True, "reason": "matches"}])
    root = ctx.ws.root
    res = run_piece(ctx, "box_0")
    ctx.ws.close()
    assert res["status"] == "passed" and res["stop"] == "model says done" and res["calls"] == 2
    assert [s["stage"] for s in fake.shapes] == ["spec", "critique"]
    assert all(s["photos"] <= C.PHOTO_CROPS_PER_REQUEST and s["max_photo_side"] <= C.PHOTO_CROP_MAX_SIDE_PX for s in fake.shapes)
    assert fake.shapes[1]["renders"] == fake.shapes[1]["photos"] > 0
    cached = scene.read_json(piece_path("box_0"))
    assert cached["status"] == "passed" and cached["spec"]["parts"] and not root.exists()
    blob = json.dumps(cached)
    assert "base64" not in blob and "PNG" not in blob


def test_a_finished_piece_is_not_paid_for_twice(scene):
    start(scene)
    ctx, fake = ctx_for(scene, [scenes.spec_answer(), {"done": True, "reason": "ok"}])
    run_piece(ctx, "box_0")
    ctx.ws.close()
    ctx2, fake2 = ctx_for(scene, [])
    assert run_piece(ctx2, "box_0")["status"] == "passed" and fake2.shapes == []
    ctx2.ws.close()


def test_a_retried_task_resumes_from_the_checkpoint_without_a_new_write(scene):
    start(scene)
    ctx, fake = ctx_for(scene, [scenes.spec_answer(), ClaudeUnusable("network")])
    res = run_piece(ctx, "box_0")  # the critique call dies: the first spec is kept
    ctx.ws.close()
    assert res["status"] == "passed" and res["stop"].startswith("claude:")
    cp = scene.read_json(piece_path("box_0"))
    cp["status"] = "running"  # as if the task had been killed before it finished
    scene.write_json(piece_path("box_0"), cp)
    ctx2, fake2 = ctx_for(scene, [{"done": True, "reason": "ok"}])
    res2 = run_piece(ctx2, "box_0")
    ctx2.ws.close()
    assert res2["status"] == "passed" and [s["stage"] for s in fake2.shapes] == ["critique"]


def test_no_person_mask_means_no_evidence_no_claude_call_and_a_failed_piece(scene):
    start(scene)
    ctx, fake = ctx_for(scene, [scenes.spec_answer()], assume_no_people=False)
    res = run_piece(ctx, "box_0")
    ctx.ws.close()
    assert res["status"] == "failed" and "people masked" in res["reason"] and fake.shapes == []


def test_invalid_specs_twice_fail_the_piece(scene):
    start(scene)
    too_big = scenes.spec_answer(size=(2.5, 1.0, 1.0))
    ctx, fake = ctx_for(scene, [too_big, too_big])
    res = run_piece(ctx, "box_0")
    ctx.ws.close()
    assert res["status"] == "failed" and "no valid model" in res["reason"] and len(fake.shapes) == 2


def test_spend_ceiling_before_the_first_call_fails_the_piece_and_after_a_good_spec_keeps_it(scene, monkeypatch):
    monkeypatch.setattr(C, "FURNITURE_MODEL", "claude-opus-5-5")  # the 0.2 ceiling below is sized for Opus prices
    start(scene)
    ctx, fake = ctx_for(scene, [scenes.spec_answer()], ceiling=0.0001)
    res = run_piece(ctx, "box_0")
    ctx.ws.close()
    assert res["status"] == "failed" and "spend ceiling" in res["reason"] and fake.shapes == []
    scene2 = LocalScenePort("scene-x", scene.source, scene.out.parent / "out2")
    start(scene2)
    ctx, fake = ctx_for(scene2, lambda r: scenes.spec_answer(), ceiling=0.2)  # room for the write, not the critique
    res = run_piece(ctx, "box_0")
    ctx.ws.close()
    assert res["status"] == "passed" and res["stop"] == "spend ceiling" and len(fake.shapes) == 1


def test_an_edit_that_makes_the_silhouette_worse_is_rejected_and_the_best_spec_kept(scene):
    start(scene)
    tiny = scenes.spec_answer(size=(0.3, 0.3, 0.3))
    ctx, fake = ctx_for(scene, [scenes.spec_answer(), {"done": False, "reason": "smaller", "spec": tiny},
                                {"done": False, "reason": "again", "spec": tiny}])
    res = run_piece(ctx, "box_0")
    ctx.ws.close()
    assert res["status"] == "passed" and res["accepted"] == 0 and res["stop"] == "two edits rejected in a row"
    assert res["spec"]["parts"][0]["size"][0] == 1.0


def test_merge_waits_then_publishes_both_files_together_and_failed_pieces_show_nothing(tmp_path):
    src = scenes.build(tmp_path / "src", boxes=[scenes.BOX, {**scenes.BOX, "id": "box_1", "center": [1.2, 0.5, 1.2]}])
    port = LocalScenePort("scene-x", src, tmp_path / "out")
    publish.start_job(port, 1000.0, ["box_0", "box_1"])
    assert publish.merge(port, 1100.0, code_sha="s")["waiting"] == ["box_0", "box_1", "finish"]
    ctx, _ = ctx_for(port, [scenes.spec_answer(), {"done": True, "reason": "ok"}])
    run_piece(ctx, "box_0")
    ctx.ws.close()
    port.write_json(publish.FINISH_RESULT, {"status": "done", "finish": {"finish_version": 2}, "generated_by": {"renderer": "stub"}})
    port.write_json(piece_path("box_1"), {"status": "failed", "reason": "x", "piece": "box_1"})
    assert not (port.out / "furniture.json").exists()
    out = publish.merge(port, 1200.0, code_sha="s")
    assert out["published"] and out["wrote"] == ["furniture.json", "finish.json"]
    fur = port.read_json("furniture.json")
    assert [o["key"] for o in fur["objects"]] == ["box_0"] and fur["furniture_version"] == 1
    assert port.read_json("finish.json")["finish_version"] == 2
    assert publish.merge(port, 1300.0, code_sha="s") == {"published": True, "noop": True}


def test_deadline_publishes_what_passed_and_marks_the_rest(tmp_path):
    src = scenes.build(tmp_path / "src")
    port = LocalScenePort("scene-x", src, tmp_path / "out")
    publish.start_job(port, 0.0, ["box_0"])
    out = publish.merge(port, C.JOB_DEADLINE_S + 1, code_sha="s")
    assert out["published"] and out["summary"]["deadline_hit"] and out["summary"]["pieces"]["box_0"]["stop"] == "deadline"
    assert port.read_json("furniture.json")["objects"] == [] and port.read_json("finish.json") is None


def test_redrive_replaces_only_the_named_piece_from_cached_specs_without_pixels(tmp_path):
    from claude_layer.redrive import redrive

    src = scenes.build(tmp_path / "src", boxes=[scenes.BOX, {**scenes.BOX, "id": "box_1", "center": [1.2, 0.5, 1.2]}])
    port = LocalScenePort("scene-x", src, tmp_path / "out")
    publish.start_job(port, 0.0, ["box_0", "box_1"])
    for i, c in enumerate(("#8a6a4a", "#336699")):
        spec = {**scenes.spec_answer(colour=c)}
        from claude_layer.schemas import spec_from_answer
        s = spec_from_answer(spec, f"box_{i}", [1, 1, 1])
        port.write_json(piece_path(f"box_{i}"), {"status": "passed", "spec": s, "piece": f"box_{i}"})
    port.write_json(publish.FINISH_RESULT, {"status": "unavailable"})
    publish.merge(port, 1.0, code_sha="a")
    first = {o["key"]: o for o in port.read_json("furniture.json")["objects"]}
    cached = port.read_json(piece_path("box_1"))
    cached["spec"]["materials"]["wood"]["color"] = "#ff0000"
    port.write_json(piece_path("box_1"), cached)
    redrive(port, {"box_1"}, "b")
    after = {o["key"]: o for o in port.read_json("furniture.json")["objects"]}
    assert after["box_0"] == first["box_0"] and after["box_1"]["spec"]["materials"]["wood"]["color"] == "#ff0000"
    with pytest.raises(SystemExit):
        redrive(port, {"nope"}, "b")


def app_for(port, script, tasks=None, **kw):
    tasks = tasks if tasks is not None else TaskList()
    deps = Deps(port_for=lambda sid, uri: port, client=FakeClient(script), renderer=StubRenderer(), enqueuer=tasks,
                code_sha="sha1", assume_no_people=True, **kw)
    app = FastAPI()
    register(app, deps)
    return TestClient(app), tasks, deps


def test_routes_run_the_whole_chain_and_publish_once(scene, monkeypatch):
    monkeypatch.setattr("claude_layer.finish_pass._render_calibrate", lambda ctx, finish, ids: {})
    http, tasks, deps = app_for(scene, lambda r: {"evidence": []} if r.stage == "finish" else
                                (scenes.spec_answer() if r.stage == "spec" else {"done": True, "reason": "ok"}))
    r = http.post("/finish", json={"scene_id": "scene-x", "bundle_uri": "x"})
    assert r.status_code == 200 and r.json()["pieces"] == ["box_0"]
    assert scene.read_json("finish.json") is None and scene.read_json("furniture.json") is None  # nothing yet
    deadline = [t for t in tasks.tasks if t["path"] == "/furniture-merge"][0]
    assert deadline["delay_s"] >= C.JOB_DEADLINE_S - 5
    piece = [t for t in tasks.tasks if t["path"] == "/furniture-piece"][0]
    assert http.post(piece["path"], json=piece["payload"]).json()["status"] == "passed"
    merge = [t for t in tasks.tasks if t["path"] == "/furniture-merge" and t["delay_s"] == 0][0]
    assert http.post(merge["path"], json=merge["payload"]).json()["wrote"] == ["furniture.json", "finish.json"]
    assert [o["key"] for o in scene.read_json("furniture.json")["objects"]] == ["box_0"]
    assert http.post(piece["path"], json=piece["payload"]).json() == {"status": "already published"}


def test_routes_degrade_without_poisoning_the_queue(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "shell.json").write_text(json.dumps({"status": "unavailable", "reason": "capture_expired"}))
    port = LocalScenePort("s", src, tmp_path / "out")
    http, tasks, _ = app_for(port, [])
    assert http.post("/finish", json={"scene_id": "s", "bundle_uri": "x"}).json() == {"status": "unavailable"}
    assert tasks.tasks == []
    (src / "shell.json").write_text(json.dumps(scenes.shell()))
    assert http.post("/finish", json={"scene_id": "s", "bundle_uri": "x"}).status_code == 503  # no boxes.json yet: retry
    assert http.post("/furniture-piece", json={"scene_id": "s", "bundle_uri": "x", "box_id": "zzz"}).status_code == 422


def test_routes_check_authorization_first(scene):
    from fastapi import HTTPException

    def deny(request, path):
        raise HTTPException(401)

    http, tasks, _ = app_for(scene, [], authorize=deny)
    for path, body in (("/finish", {"scene_id": "s", "bundle_uri": "x"}), ("/furniture-merge", {"scene_id": "s"}),
                       ("/furniture-piece", {"scene_id": "s", "bundle_uri": "x", "box_id": "b"})):
        assert http.post(path, json=body).status_code == 401
