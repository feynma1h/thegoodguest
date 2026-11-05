"""Gate arithmetic, answer schemas, the finish pass, alerts."""
import time

import pytest

import scenes
from claude_layer import constants as C
from claude_layer import finish_pass, gates, observe, schemas
from claude_layer.client import ClaudeCaller, ClaudeRefused, FakeClient
from claude_layer.piece_loop import JobContext
from claude_layer.render import StubRenderer
from claude_layer.scene_port import LocalScenePort
from claude_layer.spend import SpendLedger
from claude_layer.workspace import Workspace


def S(dl=2.0, dab=2.0, gap=0.1, share=0.8):
    return gates.PieceScore(dl, dab, gap, share, 3)


def test_edit_accept_rule_has_a_tolerance_on_each_number():
    best = S()
    assert gates.edit_accepted(S(dl=2.9), best) and not gates.edit_accepted(S(dl=3.1), best)
    assert gates.edit_accepted(S(dab=2.9), best) and not gates.edit_accepted(S(dab=3.1), best)
    assert gates.edit_accepted(S(gap=0.11), best) and not gates.edit_accepted(S(gap=0.13), best)


def test_loop_stops_on_cap_two_rejections_or_two_small_gains():
    st = gates.LoopState()
    st.after_edit(False, 0)
    assert st.stop_reason() is None
    st.after_edit(False, 0)
    assert st.stop_reason() == "two edits rejected in a row"
    st = gates.LoopState()
    st.after_edit(True, 0.1)
    st.after_edit(True, 0.2)
    assert st.stop_reason() == "no further gain"
    st = gates.LoopState()
    for _ in range(C.MAX_EDITS):
        st.after_edit(True, 2.0)
    assert st.stop_reason() == "edit cap"


def test_first_render_must_overlap_the_box():
    assert gates.usable_first_render(None)
    assert gates.usable_first_render(S(gap=0.5)).startswith("placement uncertain")
    assert gates.usable_first_render(S(gap=0.2)) is None


def summ(**regions):
    return {k: {"delta_lab": [v, 0, 0], "frames": 3, "photo_std_L": 4.0, "render_std_L": 4.0} for k, v in regions.items()}


def test_finish_gate_needs_a_real_gain_and_no_region_much_worse():
    base = summ(paint=5.0, floor=3.0)
    assert gates.finish_gate(base, summ(paint=4.0, floor=3.0))[0]
    assert not gates.finish_gate(base, summ(paint=4.8, floor=3.0))[0]  # 0.2 L is noise
    assert not gates.finish_gate(base, summ(paint=1.0, floor=4.5))[0]  # a region worsened by 1.5
    assert not gates.finish_gate(base, summ(tile=1.0))[0]  # nothing measurable in both


def test_wainscot_claim_must_sit_near_the_atlas_edge_and_not_be_worse_than_the_measurement():
    assert gates.wainscot_edge_ok(1.30, 1.29, None)[0]
    assert not gates.wainscot_edge_ok(1.45, 1.29, None)[0]
    assert not gates.wainscot_edge_ok(1.30, None, None)[0]
    assert not gates.wainscot_edge_ok(1.33, 1.29, 1.29)[0]


def test_calibration_step_is_clamped():
    assert gates.clamp_calibration_step([9.0, 6.0, 0.0]) == [4.0, 3.0, 0.0]
    assert gates.clamp_calibration_step([-1.0, 1.0, 1.0]) == [-1.0, 1.0, 1.0]


def test_spec_answer_round_trips_and_guards_hold():
    good = scenes.spec_answer()
    spec = schemas.validate_spec_answer("b", [1, 1, 1], set())(good)
    assert spec["key"] == spec["object"] == "b" and spec["box_dims"] == [1, 1, 1] and "wood" in spec["materials"]
    for bad in (scenes.spec_answer(size=(1.5, 1, 1)),  # outside the box by 50%
                {**good, "parts": [{**good["parts"][0], "at": [0, -0.5, 0]}]},  # below the floor
                {**good, "parts": [{**good["parts"][0], "kind": "teapot"}]},
                {**good, "parts": [{**good["parts"][0], "mat": "nope"}]},
                {**good, "place": {"rule": "on", "target": "ghost"}},
                {**good, "materials": [{"name": "wood", "color": "#8a6a4a", "tex": {"kind": "marble"}}]}):
        with pytest.raises(ValueError):
            schemas.validate_spec_answer("b", [1, 1, 1], {"other"})(bad)
    on = {**good, "place": {"rule": "on", "target": "other"}}
    assert schemas.validate_spec_answer("b", [1, 1, 1], {"other"})(on)["place"]["target"] == "other"


def test_critique_answers_are_done_or_a_full_valid_edit():
    v = schemas.validate_critique_answer("b", [1, 1, 1], set())
    assert v({"done": True, "reason": "ok"}) == ("done", "ok")
    assert v({"done": False, "reason": "r", "spec": scenes.spec_answer()})[0] == "edit"
    with pytest.raises(ValueError):
        v({"done": False, "reason": "r"})


def test_hints_are_checked_section_by_section_and_stamped_review():
    ok, bad = schemas.hints_from_answer({
        "baseboard": {"present": True, "height_m": 0.1},
        "wainscot": {"height_m": 9.0},  # out of range
        "floor": {"slab_u_m": 0.6, "slab_v_m": 0.6},
        "door": {"casing": "frame", "panels": [[0.1, 0.1, 0.9, 0.5]]},
        "window": {"glass_hex": "blue"},
        "evidence": []})
    assert set(ok) == {"baseboard", "floor", "openings"} and ok["baseboard"]["source"] == "review"
    assert set(ok["openings"]) == {"door"} and set(bad) == {"wainscot", "openings.window"}


@pytest.fixture
def scene(tmp_path):
    return LocalScenePort("scene-x", scenes.build(tmp_path / "src"), tmp_path / "out")


def finish_ctx(port, script):
    ws = Workspace(port, assume_no_people=True)
    fake = FakeClient(script)
    ctx = JobContext(port, ws, ClaudeCaller(fake, SpendLedger(port, "finish"), "scene-x"), StubRenderer(), "sha1", time.time() + 1e6)
    return ctx, fake


def test_finish_pass_keeps_a_hint_only_when_its_render_improves_and_records_the_rest(scene, monkeypatch):
    calls = []

    def fake_render(ctx, finish, ids):
        calls.append(sorted((finish.get("hints") or {})))
        return summ(paint=2.0, floor=3.0) if "baseboard" in (finish.get("hints") or {}) else summ(paint=5.0, floor=3.0)

    monkeypatch.setattr(finish_pass, "_render_calibrate", fake_render)
    ctx, fake = finish_ctx(scene, [{"baseboard": {"present": True}, "floor": {"slab_u_m": 0.6, "slab_v_m": 0.6},
                                    "evidence": [{"claim": "baseboard", "seen": "a strip"}]}])
    res = finish_pass.run_finish(ctx)
    ctx.ws.close()
    assert res["status"] == "done" and fake.shapes[0]["atlases"] >= 1 and fake.shapes[0]["photos"] == 0
    assert "baseboard" in res["finish"]["hints"] and "floor" not in res["finish"]["hints"]
    assert res["finish"]["rejected"]["floor"].startswith("residual:")
    assert res["finish"]["hints"]["baseboard"]["source"] == "review"
    assert res["finish"]["residual"]["after_l"] <= res["finish"]["residual"]["before_l"]


def test_finish_without_claude_is_the_measured_finish_and_says_why(scene, monkeypatch):
    monkeypatch.setattr(finish_pass, "_render_calibrate", lambda ctx, finish, ids: summ(paint=1.0))
    ctx, fake = finish_ctx(scene, [ClaudeRefused("no")])
    res = finish_pass.run_finish(ctx)
    ctx.ws.close()
    assert res["status"] == "done" and not res["finish"].get("hints") and "all" in res["finish"]["rejected"]


def test_finish_with_no_frames_is_unavailable_not_an_error(tmp_path):
    src = scenes.build(tmp_path / "src", n_frames=0)
    port = LocalScenePort("scene-x", src, tmp_path / "out")
    ctx, _ = finish_ctx(port, [])
    assert finish_pass.run_finish(ctx)["status"] == "unavailable"
    ctx.ws.close()


def test_alerts_fire_on_the_designed_conditions():
    ok = {"pieces": {"a": {"status": "passed"}, "b": {"status": "passed"}}, "spend_usd": 1, "spend_ceiling_usd": 12, "time_to_look_s": 600}
    assert observe.alerts(ok) == []
    bad = {"pieces": {"a": {"status": "failed"}, "b": {"status": "passed"}}, "spend_usd": 12, "spend_ceiling_usd": 12,
           "time_to_look_s": 4000, "deadline_hit": True}
    assert {a["alert"] for a in observe.alerts(bad)} == {"failed_piece_rate", "spend_ceiling_reached", "slow_time_to_look", "deadline_hit"}
