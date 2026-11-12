"""Compares two models' conversations room by room, blind and both ways round.

    GUIDE_LIVE=1 python -m evals.judge <out>/claude-opus-5-5 <out>/claude-sonnet-5-5 --out <out>/judge-opus

Run it from packages/room-guide, after run.py has run both models.

The judge reads three things for each room:
  - the room's measured facts: what the answer key lets the analyzer find;
  - the planted problem;
  - the two conversations as the person saw them (words, cards, moves),
    labelled A and B.
It scores each conversation 0 to 2 on four things and picks the better one, or
a tie. Each room is asked twice, once with each model as A. A model wins a room
only when both readings pick it; otherwise the room is a tie. That cancels the
judge's lean toward one position.

The judge goes through the gateway like everything else, so it is priced,
cached and pinned to the 0360 pair. A judge that is also one of the models
being judged may favour its own voice; `--judge-model` lets the other one judge
too.

Read by: a developer comparing models or prompts; tests/test_evals.py.
"""
from __future__ import annotations

import argparse
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from evals.rooms import all_rooms
from evals.run import key_findings, ledger_totals, problems
from thegoodguest_room_guide.analyzer import room_line
from thegoodguest_room_guide.gateway import ALLOWED_MODELS, Gateway, JsonRequest
from thegoodguest_room_guide.model import room_from_scene

JUDGE_VERSION = "judge/1"
CRITERIA = ("found", "truthful", "useful", "voice")

JUDGE_SYSTEM = """\
You judge a home-design guide. A person has scanned a room. The guide talks
with them about it. It can offer a change as a card, and it can show a change
by moving the furniture on screen. You will read the room's measured facts and
two conversations, A and B, between the same person and two versions of the
guide. Score each conversation, then say which is better for the person.

Score each conversation 0, 1 or 2 on:
- found: did the guide bring up the room's real problem (given below)?
  2 it named it clearly and early; 1 it touched on it, or got to it late;
  0 it missed it. In a room with no planted problem: 2 it said plainly what
  works and invented nothing; 0 it invented a problem.
- truthful: does everything it said match the measured facts and the room?
  2 nothing wrong; 1 a slip that wouldn't mislead; 0 a wrong or invented claim
  (a piece, a number, a problem that isn't there, a benefit a move doesn't bring).
- useful: would the person act on what it offered? 2 a change that fixes the
  real problem, or an honest "nothing better" where nothing is better; 1 a
  change that helps less than it could; 0 a change that makes things worse, or
  nothing where something was plainly possible.
- voice: does it sound like a warm, expert designer talking to them?
  2 short, plain and specific; 1 correct but wordy, stiff or vague;
  0 jargon, lecturing or filler.

Judge only what the person saw: the words, the cards and the moves. Don't
reward length. Then pick the better conversation for the person, or "tie" when
they are about equal, and say why in one or two sentences."""

_SCORE = {"type": "object", "additionalProperties": False, "required": [*CRITERIA, "notes"],
          "properties": {**{c: {"type": "integer", "enum": [0, 1, 2]} for c in CRITERIA},
                         "notes": {"type": "string"}}}
SCHEMA = {"type": "object", "additionalProperties": False, "required": ["a", "b", "better", "why"],
          "properties": {"a": _SCORE, "b": _SCORE, "better": {"type": "string", "enum": ["A", "B", "tie"]},
                         "why": {"type": "string"}}}


def conversation(result: dict) -> str:
    """A conversation as the person saw it."""
    lines = []
    for t in result["turns"]:
        if t["person"]:
            lines.append(f"Person: {t['person']}")
        lines.append(f"Guide: {t['said'].strip() or '(said nothing)'}")
        for c in t["cards"]:
            lines.append(f"  [card offered: {' '.join(c['words'])}]")
        for p in t["played"]:
            lines.append(f"  [on screen, moved: {', '.join(p['pieces'])}]")
    return "\n".join(lines)


def facts(r) -> str:
    room = room_from_scene(r.scene())
    pieces = [f"- {p.name}" + (f": {p.description}" if p.description else "")
              for p in room.pieces.values() if p.support != "wall" or p.opening is None]
    measured = [f"- {f.text}" for f in problems(key_findings(r))] or ["- Nothing measured is wrong."]
    return "\n".join([room_line(room), "", "In the room:", *pieces, "",
                      "What the measurements say is wrong:", *measured, "",
                      f"The planted problem: {r.problem}"])


def judge_request(r, first: dict, second: dict, model: str) -> JsonRequest:
    text = "\n".join(["THE ROOM", facts(r), "", "CONVERSATION A", conversation(first), "",
                      "CONVERSATION B", conversation(second), "", "Score A and B, then pick the better one."])
    return JsonRequest(stage="judge", prompt_version=JUDGE_VERSION, system=JUDGE_SYSTEM, text=text,
                       schema=SCHEMA, model=model, effort="medium")


def combine(name: str, m1: str, m2: str, v1: dict, v2: dict) -> dict:
    """Two readings of one room (m1 as A, then m2 as A) as one verdict."""
    pick1 = {"A": m1, "B": m2}.get(v1["better"], "tie")
    pick2 = {"A": m2, "B": m1}.get(v2["better"], "tie")
    scores = {m1: {c: (v1["a"][c] + v2["b"][c]) / 2 for c in CRITERIA},
              m2: {c: (v1["b"][c] + v2["a"][c]) / 2 for c in CRITERIA}}
    return {"room": name, "winner": pick1 if pick1 == pick2 else "tie", "readings": [pick1, pick2],
            "scores": scores, "why": [v1["why"], v2["why"]],
            "notes": {m1: [v1["a"]["notes"], v2["b"]["notes"]], m2: [v1["b"]["notes"], v2["a"]["notes"]]}}


def judge(dir1: Path, dir2: Path, out: Path, model: str = "claude-opus-5-5", mode: str | None = None,
          stub=None, jobs: int = 4) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    gw = Gateway(out / "llm", mode=mode, stub=stub, budget_usd=5.0)
    m1, m2 = dir1.name, dir2.name
    pairs = []
    for r in all_rooms():
        a, b = dir1 / r.name / "result.json", dir2 / r.name / "result.json"
        if a.exists() and b.exists():
            pairs.append((r, json.loads(a.read_text()), json.loads(b.read_text())))

    def one(item):
        r, x, y = item
        v1 = gw.ask_json(judge_request(r, x, y, model))
        v2 = gw.ask_json(judge_request(r, y, x, model))
        return combine(r.name, m1, m2, v1, v2)

    with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        rooms = list(pool.map(one, pairs))
    total = {m: {c: round(sum(v["scores"][m][c] for v in rooms), 1) for c in CRITERIA} for m in (m1, m2)}
    doc = {"judge": model, "models": [m1, m2], "rooms": rooms,
           "wins": {m: sum(v["winner"] == m for v in rooms) for m in (m1, m2)},
           "ties": sum(v["winner"] == "tie" for v in rooms),
           "split": sum(v["readings"][0] != v["readings"][1] for v in rooms),
           "totals": total, "out_of": 2 * len(rooms),
           "spend": ledger_totals(out / "llm" / "ledger.jsonl")}
    (out / "judge.json").write_text(json.dumps(doc, indent=1))
    return doc


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("first", type=Path, help="one model's run folder, <out>/<model>")
    ap.add_argument("second", type=Path, help="the other model's run folder")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--judge-model", default="claude-opus-5-5", choices=ALLOWED_MODELS)
    ap.add_argument("--jobs", type=int, default=4)
    a = ap.parse_args(argv)
    mode = "auto" if os.environ.get("GUIDE_LIVE") == "1" else "replay"
    doc = judge(a.first, a.second, a.out, a.judge_model, mode=mode, jobs=a.jobs)
    print(json.dumps({k: doc[k] for k in ("judge", "wins", "ties", "split", "totals", "out_of")}, indent=1))


if __name__ == "__main__":
    main()
