"""The guide's turn loop, with a scripted stand-in for Claude (no credits, no network).

The stand-in plays the part a live model would: it asks the room for changes,
offers what comes back, and then speaks. The tests check the plumbing around it:
that proposals reach the panel as cards, that a shown proposal arrives as a motion
plan and changes the room, that a refusal reaches the guide as a reason, that a
note changes the room's needs, and that a number from nowhere is flagged.
"""
import json

import pytest

from test_engine import _study
from thegoodguest_room_guide.gateway import JsonRequest, ModelNotAllowed, TurnRequest
from thegoodguest_room_guide.guide import TOOLS, foreign_numbers, run_turn
from thegoodguest_room_guide.harness import Session


def last_tool_result(req: TurnRequest) -> dict:
    content = req.messages[-1]["content"]
    return json.loads(content[-1]["content"])


class Script:
    """A stand-in model: a list of steps, each a function of the request."""

    def __init__(self, needs: dict, steps):
        self.needs = needs
        self.steps = list(steps)

    def __call__(self, req):
        if isinstance(req, JsonRequest):
            return self.needs
        step = self.steps.pop(0)
        return {"content": step(req), "stop_reason": "end_turn"}


def text(t):
    return lambda req: [{"type": "text", "text": t}]


def tool(name, args, i):
    return lambda req: [{"type": "tool_use", "id": f"t{i}", "name": name, "input": args(req) if callable(args) else args}]


@pytest.fixture
def study(tmp_path):
    builder, needs = _study()
    scene = tmp_path / "scene.json"
    scene.write_text(json.dumps(builder.scene()))
    return scene, needs


def session_with(study, tmp_path, steps):
    scene, needs = study
    return Session(scene, tmp_path / "work", mode="stub", stub=Script(needs, steps))


def run(s, words):
    events = []
    reply = run_turn(s, words, lambda kind, data: events.append((kind, data)))
    return reply, events


def test_the_tools_are_strict_and_closed():
    names = {t["name"] for t in TOOLS}
    assert names == {"look_for_changes", "move", "offer", "show", "put_back", "measure", "point_at", "note"}
    assert all(t["strict"] and t["input_schema"]["additionalProperties"] is False for t in TOOLS)


def test_a_suggestion_is_looked_for_then_offered_as_a_card(study, tmp_path):
    s = session_with(study, tmp_path, [
        tool("look_for_changes", {"goal": "light", "piece": "desk"}, 1),
        tool("offer", lambda req: {"proposal": last_tool_result(req)["proposals"][0]["id"]}, 2),
        text("Turned side-on to the window, the desk would take its daylight from the side. Want to see it?"),
    ])
    reply, events = run(s, "What would you change?")
    cards = [d for k, d in events if k == "card"]
    assert len(cards) == 1 and cards[0]["words"]
    assert reply.startswith("Turned side-on")
    assert not [k for k, _ in events if k == "play"], "an idea is offered, not played"
    assert events[-1][0] == "done" and events[-1][1]["flags"] == []


def test_showing_plays_a_checked_plan_and_changes_the_room(study, tmp_path):
    s = session_with(study, tmp_path, [
        tool("move", {"piece": "desk", "how": "wall", "target": "wall_-z"}, 1),
        tool("show", lambda req: {"proposal": last_tool_result(req)["proposal"]["id"]}, 2),
        text("Done: the desk is against the wall now."),
    ])
    reply, events = run(s, "Put the desk against the other wall.")
    plays = [d for k, d in events if k == "play"]
    assert len(plays) == 1
    plan = plays[0]["plan"]
    assert plan["plan_version"] == 1 and "desk" in plan["tracks"] and plan["checked"]["frames"] > 0
    assert "desk" in s.arrangement and len(s.history) == 2
    assert s.changes


def test_a_refusal_reaches_the_guide_as_a_reason(study, tmp_path):
    s = session_with(study, tmp_path, [
        tool("move", {"piece": "door", "how": "wall", "target": "wall_-z"}, 1),
        lambda req: [{"type": "text", "text": "I can't: " + last_tool_result(req)["refused"]}],
    ])
    reply, _ = run(s, "Move the door.")
    assert "stays where it is" in reply


def test_a_note_changes_the_rooms_needs(study, tmp_path):
    s = session_with(study, tmp_path, [
        tool("note", {"fact": "the door is never used, we go through the other room", "piece": "door",
                      "change": "relax", "need": "pass"}, 1),
        text("Noted."),
    ])
    assert s.needs.needs_of("door", "pass")
    run(s, "We never use that door.")
    assert not s.needs.needs_of("door", "pass")
    assert s.told == ["the door is never used, we go through the other room"]


def test_a_finding_named_by_its_piece_is_searched_for(study, tmp_path):
    """Asked to fix "desk", the room searches its daylight finding the way that finding is scored."""
    from thegoodguest_room_guide.guide import Turn
    s = session_with(study, tmp_path, [])
    t = Turn(s, lambda kind, data: None)
    assert "pref:task_light:desk" in [f.key for f in s.engine.current_findings]
    assert t._finding_key("desk") == "pref:task_light:desk"
    assert t.t_look_for_changes("fix", finding="desk")["proposals"]
    assert "no finding 'piano'" in t.t_look_for_changes("fix", finding="piano")["why"]


def test_after_a_card_the_guide_is_asked_for_the_problem_first(study, tmp_path):
    from thegoodguest_room_guide.guide import Turn
    s = session_with(study, tmp_path, [])
    t = Turn(s, lambda kind, data: None)
    props = t.t_look_for_changes("light", piece="desk")["proposals"]
    out = json.loads(t.call("offer", {"proposal": props[0]["id"]}))
    assert out["then"].startswith("now tell them what you found")
    assert "then" not in json.loads(t.call("move", {"piece": "door", "how": "wall", "target": "wall_-z"}))


def test_a_number_quoted_from_an_earlier_turn_is_not_flagged(study, tmp_path):
    heard = {}

    def quote(req):
        heard["gap"] = last_tool_result(req)["said"]
        return [{"type": "text", "text": f"It's {heard['gap']}."}]

    s = session_with(study, tmp_path, [
        tool("measure", {"a": "desk", "b": "door"}, 1), quote,
        lambda req: [{"type": "text", "text": f"As I said, {heard['gap']}."}],
    ])
    _, first = run(s, "How far is the door from the desk?")
    _, second = run(s, "Say that again?")
    assert any(ch.isdigit() for ch in heard["gap"]), heard
    assert first[-1][1]["flags"] == [] and second[-1][1]["flags"] == []


def test_a_number_from_nowhere_is_flagged():
    assert foreign_numbers("It has about 0.7 m in front.", ["there's about 0.7 m before the bed"]) == []
    assert foreign_numbers("It needs 1.2 m.", ["there's about 0.7 m before the bed"]) == ["1.2 m"]


def test_only_the_two_allowed_models(study, tmp_path):
    s = session_with(study, tmp_path, [text("hello")])
    s.model = "claude-haiku-5-5"
    with pytest.raises(ModelNotAllowed):
        run(s, "hi")
