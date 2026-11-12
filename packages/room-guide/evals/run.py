"""Runs the eval on one model: the rules pass and three turns in every room.

    GUIDE_LIVE=1 python -m evals.run --model claude-sonnet-5-5 --out ../../outputs/guide-evals/run-1

Run it from packages/room-guide. Without GUIDE_LIVE=1 only cached answers are
used: a room whose answers aren't cached runs on laws only and says so.

Each room gets `<out>/<model>/<room>/` holding the scene, the gateway's cache and
ledger, and `result.json`:
  - the needs the model wrote, and what they let the analyzer find;
  - whether the planted problem was among those findings;
  - each turn's words, tool calls, cards, plays and flags;
  - what it cost and how long it took.
A room that already has a result.json is skipped, so a stopped run picks up
where it left off. Rerunning a finished room from its cache is free.

The person says the same things to every model:
  1. nothing: the opening;
  2. "Show me." if a change was offered, else "Is there really nothing you'd change?";
  3. "What else would you change?"

Read by: a developer measuring a prompt or model change; judge.py; tests/test_evals.py.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from evals.rooms import ROOMS, EvalRoom, all_rooms, matches
from thegoodguest_room_guide.analyzer import findings
from thegoodguest_room_guide.assess import assess
from thegoodguest_room_guide.gateway import ALLOWED_MODELS, BudgetExceeded
from thegoodguest_room_guide.guide import run_turn
from thegoodguest_room_guide.harness import Session
from thegoodguest_room_guide.model import room_from_scene
from thegoodguest_room_guide.needs import parse_needs
from thegoodguest_room_guide.prompts import OPENING
from thegoodguest_room_guide.rules_pass import needs_to_json

SHOW = "Show me."
NOTHING = "Is there really nothing you'd change?"
MORE = "What else would you change?"

ROOM_RESERVE_USD = {"claude-opus-5-5": 0.45, "claude-sonnet-5-5": 0.25}   # a room's cost, erring high


def problems(fs) -> list:
    return [f for f in fs if f.kind not in ("good", "question")]


def key_findings(r: EvalRoom) -> list:
    """What the answer key lets the analyzer find: the room's measured truth, for the judge."""
    room = room_from_scene(r.scene())
    needs = parse_needs(room, r.key)
    return findings(room, needs, assess(room, needs))


def _card(s: Session, d: dict) -> dict:
    p = s.proposals.get(d["id"])
    return {"id": d["id"], "words": d["words"], "fixes": [f.key for f in p.fixes] if p else [],
            "fix_texts": d["fixes"], "leaves": d["leaves"], "adds": d["adds"]}


def _play(d: dict) -> dict | None:
    doc = d.get("plan")
    if not doc:
        return None
    return {"pieces": sorted(doc["tracks"]), "seconds": doc["duration"], "frames_checked": doc["checked"]["frames"],
            "methods": doc.get("methods")}


def _parsed(content):
    try:
        return json.loads(content) if isinstance(content, str) else content
    except ValueError:
        return content


def take_turn(s: Session, text: str) -> dict:
    events: list[tuple[str, dict]] = []
    start = len(s.messages)
    t = time.time()
    said = run_turn(s, text, lambda kind, data: events.append((kind, data)))
    blocks = [b for m in s.messages[start:] if isinstance(m["content"], list) for b in m["content"]]
    results = {b["tool_use_id"]: b["content"] for b in blocks if b.get("type") == "tool_result"}
    tools = [{"name": b["name"], "input": b["input"], "result": _parsed(results.get(b["id"]))}
             for b in blocks if b.get("type") == "tool_use"]
    done = next((d for k, d in reversed(events) if k == "done"), {})
    return {"person": None if text == OPENING else text, "said": said, "tools": tools,
            "cards": [_card(s, d) for k, d in events if k == "card"],
            "played": [p for k, d in events if k == "play" and (p := _play(d))],
            "flags": done.get("flags", []), "seconds": round(time.time() - t, 1)}


def ledger_totals(path: Path) -> dict:
    rows = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
    out: dict[str, dict] = {}
    for r in rows:
        st = out.setdefault(r["stage"], {"calls": 0, "input": 0, "cache_read": 0, "cache_write": 0, "output": 0,
                                          "billed_usd": 0.0, "priced_usd": 0.0})
        st["calls"] += 1
        for k in ("input", "cache_read", "cache_write", "output"):
            st[k] += r["usage"][k]
        st["billed_usd"] = round(st["billed_usd"] + r["billed_usd"], 5)
        st["priced_usd"] = round(st["priced_usd"] + r["cost_usd"], 5)
    return out


def run_room(r: EvalRoom, model: str, folder: Path, mode: str | None = None, stub=None) -> dict:
    folder.mkdir(parents=True, exist_ok=True)
    scene = folder / "scene.json"
    scene.write_text(json.dumps(r.scene(), indent=1))
    t = time.time()
    s = Session(scene, folder / "work", mode=mode, stub=stub, model=model)
    rules_seconds = round(time.time() - t, 1)
    found_fs = problems(s.engine.current_findings)
    keys = [f.key for f in found_fs]
    truth = problems(key_findings(r))
    truth_keys = {f.key for f in truth}

    turns = [take_turn(s, OPENING)]
    offered = any(turn["cards"] for turn in turns)
    turns.append(take_turn(s, SHOW if offered else NOTHING))
    turns.append(take_turn(s, MORE))

    cards = [c for turn in turns for c in turn["cards"]]
    result = {
        "room": r.name, "model": model, "problem": r.problem, "expect": r.expect,
        "rules": {"origin": s.needs.origin, "seconds": rules_seconds, "notes": s.notes,
                  "needs": needs_to_json(s.needs)},
        "findings": [{"key": f.key, "kind": f.kind, "severity": f.severity, "text": f.text} for f in found_fs],
        "found": {e: matches(e, keys) for e in r.expect},
        "extra_problems": [f.key for f in found_fs if f.severity >= 3 and f.key not in truth_keys
                           and not any(matches(e, [f.key]) for e in r.expect)],
        "turns": turns,
        "card_fixes_planted": any(matches(e, c["fixes"]) for e in r.expect for c in cards) if r.expect else None,
        "flags": [f for turn in turns for f in turn["flags"]],
        "spend": ledger_totals(folder / "work" / "llm" / "ledger.jsonl"),
    }
    result["billed_usd"] = round(sum(v["billed_usd"] for v in result["spend"].values()), 4)
    result["priced_usd"] = round(sum(v["priced_usd"] for v in result["spend"].values()), 4)
    (folder / "result.json").write_text(json.dumps(result, indent=1))
    return result


def summarise(results: list[dict], model: str) -> dict:
    planted = [r for r in results if r["expect"]]
    clean = [r for r in results if not r["expect"]]
    turns = [t for r in results for t in r["turns"]]
    return {
        "model": model, "rooms": len(results),
        "planted_found": sum(all(r["found"].values()) for r in planted), "planted": len(planted),
        "card_fixes_planted": sum(bool(r["card_fixes_planted"]) for r in planted),
        "clean_rooms_with_problems": sum(bool(r["findings"] and any(f["severity"] >= 3 for f in r["findings"]))
                                         for r in clean),
        "rules_defaults": sum(r["rules"]["origin"] != "rules pass" for r in results),
        "flags": sorted({f for r in results for f in r["flags"]}),
        "flagged_turns": sum(bool(t["flags"]) for t in turns), "turns": len(turns),
        "billed_usd": round(sum(r["billed_usd"] for r in results), 4),
        "priced_usd": round(sum(r["priced_usd"] for r in results), 4),
        "rules_seconds": round(sum(r["rules"]["seconds"] for r in results) / max(len(results), 1), 1),
        "turn_seconds": round(sum(t["seconds"] for t in turns) / max(len(turns), 1), 1),
        "words_per_turn": round(sum(len(t["said"].split()) for t in turns) / max(len(turns), 1), 1),
    }


def run(model: str, out: Path, names: list[str] | None = None, jobs: int = 3, ceiling: float = 10.0,
        mode: str | None = None, stub=None) -> dict:
    if model not in ALLOWED_MODELS:
        raise SystemExit(f"{model} may not see a room; allowed: {', '.join(ALLOWED_MODELS)}")
    rooms = [r for r in all_rooms() if names is None or r.name in names]
    base = out / model
    lock = threading.Lock()
    state = {"spent": 0.0, "stop": None}
    for r in rooms:
        done = base / r.name / "result.json"
        if done.exists():
            state["spent"] += json.loads(done.read_text())["billed_usd"]

    def one(r: EvalRoom) -> dict | None:
        done = base / r.name / "result.json"
        if done.exists():
            return json.loads(done.read_text())
        with lock:
            if state["stop"] or state["spent"] + ROOM_RESERVE_USD.get(model, 0.5) > ceiling:
                state["stop"] = state["stop"] or f"the ${ceiling:.2f} ceiling"
                return None
            state["spent"] += ROOM_RESERVE_USD.get(model, 0.5)
        try:
            res = run_room(r, model, base / r.name, mode=mode, stub=stub)
        except BudgetExceeded as e:
            with lock:
                state["stop"] = str(e)
            return None
        except Exception as e:      # one room's failure is recorded, and the rest still run
            (base / r.name).mkdir(parents=True, exist_ok=True)
            (base / r.name / "error.txt").write_text(f"{type(e).__name__}: {e}")
            print(f"[{model}] {r.name}: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
            if "authentication" in str(e).lower() or "401" in str(e):
                with lock:
                    state["stop"] = "the key was refused"
            return None
        with lock:
            state["spent"] += res["billed_usd"] - ROOM_RESERVE_USD.get(model, 0.5)
        print(f"[{model}] {r.name}: found={all(res['found'].values())} cards={sum(len(t['cards']) for t in res['turns'])} "
              f"${res['billed_usd']:.3f}", flush=True)
        return res

    with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        results = [r for r in pool.map(one, rooms) if r]
    summary = summarise(results, model)
    summary["stopped"] = state["stop"]
    summary["missing"] = sorted({r.name for r in rooms} - {r["room"] for r in results})
    base.mkdir(parents=True, exist_ok=True)
    (base / "summary.json").write_text(json.dumps(summary, indent=1))
    return summary


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--model", required=True, choices=ALLOWED_MODELS)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--rooms", help="comma-separated room names (default: all)")
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--ceiling", type=float, default=10.0, help="stop before a room would pass this many dollars")
    a = ap.parse_args(argv)
    names = a.rooms.split(",") if a.rooms else None
    unknown = set(names or []) - {make.__name__ for make in ROOMS}
    if unknown:
        raise SystemExit(f"no such rooms: {', '.join(sorted(unknown))}")
    mode = "auto" if os.environ.get("GUIDE_LIVE") == "1" else "replay"
    print(json.dumps(run(a.model, a.out, names, a.jobs, a.ceiling, mode=mode), indent=1))


if __name__ == "__main__":
    main()
