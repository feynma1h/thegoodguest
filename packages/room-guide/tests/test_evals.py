"""The eval's own checks, all free: each planted problem can be found, and the
runner and the judge work end to end with stand-ins for Claude."""
import json

import pytest

from evals.compare import comparison
from evals.judge import combine, judge
from evals.rooms import all_rooms, matches
from evals.run import MORE, NOTHING, SHOW, key_findings, problems, run
from thegoodguest_room_guide.gateway import JsonRequest
from thegoodguest_room_guide.laws import check
from thegoodguest_room_guide.model import room_from_scene
from thegoodguest_room_guide.needs import parse_needs

ROOMS = all_rooms()
BY_NAME = {r.name: r for r in ROOMS}


@pytest.mark.parametrize("r", ROOMS, ids=lambda r: r.name)
def test_the_answer_key_finds_the_planted_problem_and_nothing_worse(r):
    fs = problems(key_findings(r))
    keys = [f.key for f in fs]
    for e in r.expect:
        assert matches(e, keys), f"{r.name}: nothing matching {e} in {keys}"
    unplanted = [f.key for f in fs if f.severity >= 3 and not set(f.pieces) & set(r.planted)]
    assert unplanted == [], f"{r.name} has a problem nobody planted: {unplanted}"


@pytest.mark.parametrize("r", ROOMS, ids=lambda r: r.name)
def test_the_rooms_as_built_break_no_law(r):
    room = room_from_scene(r.scene())
    assert check(room, {}, fixed=parse_needs(room, r.key).fixed_ids()) == []


def test_the_rooms_are_named_once():
    assert len(BY_NAME) == len(ROOMS) >= 12
    assert sum(not r.expect for r in ROOMS) == 2, "two rooms with nothing planted keep the eval honest"


def _says(r, line):
    """A stand-in model: the room's answer key for the rules pass, and one line for every turn."""
    def answer(req):
        if isinstance(req, JsonRequest):
            return r.key
        return {"content": [{"type": "text", "text": line}], "stop_reason": "end_turn"}
    return answer


def test_the_runner_records_what_was_found_said_and_spent(tmp_path):
    r = BY_NAME["heater_close"]
    summary = run("claude-sonnet-5-5", tmp_path, [r.name], jobs=1, mode="stub",
                  stub=_says(r, "Move the heater away from the sofa."))
    res = json.loads((tmp_path / "claude-sonnet-5-5" / r.name / "result.json").read_text())
    assert res["found"] == {e: True for e in r.expect}
    assert res["rules"]["origin"] == "rules pass"
    assert [t["person"] for t in res["turns"]] == [None, NOTHING, MORE], "nothing offered, so no 'Show me'"
    assert res["billed_usd"] == 0 and res["priced_usd"] > 0
    assert summary["planted_found"] == summary["planted"] == 1 and summary["missing"] == []
    again = run("claude-sonnet-5-5", tmp_path, [r.name], jobs=1, mode="replay")
    assert again["planted_found"] == 1, "a finished room is read back, not rerun"
    assert SHOW == "Show me."


def test_a_room_wins_only_when_both_readings_agree():
    score = {"found": 2, "truthful": 2, "useful": 2, "voice": 2, "notes": ""}
    always_a = {"a": score, "b": score, "better": "A", "why": "first"}
    v = combine("room", "m1", "m2", always_a, always_a)
    assert v["winner"] == "tie" and v["readings"] == ["m1", "m2"], "a judge that always picks A decides nothing"
    v = combine("room", "m1", "m2", always_a, {**always_a, "better": "B"})
    assert v["winner"] == "m1"


def test_the_judge_reads_both_conversations_both_ways(tmp_path):
    r = BY_NAME["heater_close"]
    run("claude-opus-5-5", tmp_path, [r.name], jobs=1, mode="stub", stub=_says(r, "Move the heater away from the sofa."))
    run("claude-sonnet-5-5", tmp_path, [r.name], jobs=1, mode="stub", stub=_says(r, "This room works as it is."))
    seen = []

    def judge_stub(req):
        seen.append(req.text)
        a = req.text.split("CONVERSATION A")[1].split("CONVERSATION B")[0]
        score = {"found": 2, "truthful": 2, "useful": 2, "voice": 2, "notes": ""}
        return {"a": score, "b": score, "better": "A" if "heater" in a else "B", "why": "it found the heater"}

    doc = judge(tmp_path / "claude-opus-5-5", tmp_path / "claude-sonnet-5-5", tmp_path / "judge",
                mode="stub", stub=judge_stub, jobs=1)
    assert doc["wins"] == {"claude-opus-5-5": 1, "claude-sonnet-5-5": 0} and doc["split"] == 0
    assert len(seen) == 2 and "The planted problem: An electric heater" in seen[0]
    assert "The sofa is about 0.2 m in front of the oil-filled heater." in seen[0]

    table = comparison(tmp_path, "claude-opus-5-5", "claude-sonnet-5-5", ["judge"])
    assert "| heater_close | yes | yes | no | no | Opus 5.5 |" in table
    assert (tmp_path / "comparison.md").read_text() == table
