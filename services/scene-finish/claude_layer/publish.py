"""All-at-once publishing (decision 0356). Design 4.3 route 3, plan decision 4.

Nothing is written to the scene (`finish.json`, `furniture.json`) until the
finish and EVERY boxed piece has a terminal result in `work/`, or the job's
deadline has passed. Then both files are written together by this one function,
the only writer of either. Until then the scene stays "processing" and the room
shows nothing of this stage.

    work/job.json                    started_ts, the piece ids, the deadline
    work/finish/result.json          terminal: done | unavailable
    work/furniture/<box>.json        terminal: passed | failed  (running = not yet)
    work/summary.json                what was published and what it cost

A failed piece, and a piece still running at the deadline, shows nothing: it is
simply absent from furniture.json. A finish that could not be measured is absent
from the publish. The merge uses cached JSON only, so a re-drive needs no pixels.
Because pieces are placed together here (not in their own task), pieces that
stand on or hang over another are placed with that neighbour, and a neighbour
that did not pass turns the rule into a plain floor placement.
"""
from __future__ import annotations

import copy

import numpy as np
from thegoodguest_room_look.furniture_boxes import parse_boxes
from thegoodguest_room_look.furniture_placement import PlacementError, place_all

from . import constants as C
from . import observe
from .piece_loop import piece_path
from .scene_port import ScenePort
from .spend import SpendLedger

JOB = "work/job.json"
FINISH_RESULT = "work/finish/result.json"
SUMMARY = "work/summary.json"


def start_job(port: ScenePort, now: float, piece_ids: list[str]) -> dict:
    """First writer wins; a retried /finish reads the original clock."""
    job = port.read_json(JOB)
    if job is None:
        job = {"scene_id": port.scene_id, "started_ts": now, "deadline_s": C.JOB_DEADLINE_S, "pieces": sorted(piece_ids)}
        port.write_json(JOB, job)
    return job


def _shell(port: ScenePort) -> dict:
    doc = port.read_json("shell.json") or {}
    return doc if "walls" in doc else doc.get("shell", {})


def _place(specs: list[dict], boxes: dict, shell: dict) -> tuple[list[dict], dict[str, str]]:
    """Place the passed specs together; a piece the rules refuse is dropped with the reason."""
    poly = np.array([[p[0], p[2]] for p in shell["floor"]["polygon"]], float)
    floor_y = float(shell["floor"]["y"])
    keys = {s["key"] for s in specs}
    specs = copy.deepcopy(specs)
    for s in specs:
        pl = s.get("place") or {}
        if pl.get("rule") in ("on", "over") and pl.get("target") not in keys:
            s["place"] = {"rule": "floor"}
    dropped: dict[str, str] = {}
    while specs:
        try:
            objects, _ = place_all(specs, boxes, poly, floor_y)
            return objects, dropped
        except PlacementError as exc:
            bad = [s for s in specs if any(s["key"] in line for line in str(exc).splitlines())]
            if not bad:
                bad = specs[-1:]
            for s in bad:
                dropped[s["key"]] = f"placement refused: {str(exc)[:160]}"
            specs = [s for s in specs if s not in bad]
    return [], dropped


def merge(port: ScenePort, now: float, *, code_sha: str, force: bool = False, only: set[str] | None = None) -> dict:
    """Publish when ready or at the deadline. `only` (re-drive): replace just these
    pieces' objects in the existing furniture.json; implies a rewrite."""
    job = port.read_json(JOB)
    if job is None:
        return {"published": False, "why": "no job"}
    if port.read_json(SUMMARY) is not None and not force:
        return {"published": True, "noop": True}  # a later piece's merge task, or a retry
    pieces = {pid: port.read_json(piece_path(pid)) for pid in job["pieces"]}
    fin = port.read_json(FINISH_RESULT)
    terminal_piece = {k: v for k, v in pieces.items() if v and v.get("status") in ("passed", "failed")}
    waiting = sorted(k for k in pieces if k not in terminal_piece) + ([] if fin and fin.get("status") in ("done", "unavailable") else ["finish"])
    deadline_hit = now >= job["started_ts"] + job["deadline_s"]
    if waiting and not deadline_hit and not force:
        return {"published": False, "waiting": waiting}

    boxes = parse_boxes(port.read_json("boxes.json") or {"boxes_version": 1, "boxes": []})
    passed = [v["spec"] for k, v in sorted(terminal_piece.items()) if v["status"] == "passed"]
    status = {k: {"status": v["status"], "reason": v.get("reason", ""), "stop": v.get("stop", ""), "calls": v.get("calls", 0),
                  "edits": v.get("edits", 0)} for k, v in terminal_piece.items()}
    for k in waiting:
        if k != "finish":
            status[k] = {"status": "failed", "reason": "not finished by the deadline", "stop": "deadline", "calls": 0, "edits": 0}
    objects, dropped = _place(passed, boxes, _shell(port)) if passed else ([], {})
    for k, why in dropped.items():
        status[k] = {"status": "failed", "reason": why, "stop": "", "calls": 0, "edits": 0}

    stamp = {"code_sha": code_sha, "vocab_version": C.VOCAB_VERSION, "prompt_version": C.PROMPT_VERSION,
             "models": {"finish": C.FINISH_MODEL, "furniture": C.FURNITURE_MODEL},
             "renderer": (fin or {}).get("generated_by", {}).get("renderer", "unknown")}
    furniture = {"furniture_version": 1, "scene_id": port.scene_id, "objects": objects, "generated_by": stamp}
    wrote = []
    existing = port.read_json("furniture.json")
    if only is not None and existing:  # re-drive of some pieces: the rest stay as published
        fresh = {o["key"]: o for o in objects if o["key"] in only}
        objects = [fresh.pop(o["key"], o) for o in existing["objects"]] + list(fresh.values())
        furniture["objects"] = objects
    if force or not existing or existing.get("generated_by") != stamp:
        port.write_json("furniture.json", furniture)
        wrote.append("furniture.json")
    if fin and fin.get("status") == "done":
        finish = {**fin["finish"], "generated_by": stamp}
        existing_f = port.read_json("finish.json")
        if force or not existing_f or existing_f.get("generated_by") != stamp:
            port.write_json("finish.json", finish)
            wrote.append("finish.json")
    ledger = SpendLedger(port, "merge")
    summary = {"scene_id": port.scene_id, "published_ts": now, "time_to_look_s": round(now - job["started_ts"], 1),
               "deadline_hit": bool(waiting) and deadline_hit, "finish": (fin or {}).get("status", "missing"),
               "pieces": status, "spend_usd": round(ledger.spent_usd(), 4), "spend_ceiling_usd": ledger.ceiling,
               "wrote": wrote}
    port.write_json(SUMMARY, summary)
    observe.emit("published", **{k: v for k, v in summary.items() if k != "pieces"},
                 passed=sum(1 for v in status.values() if v["status"] == "passed"), failed=sum(1 for v in status.values() if v["status"] != "passed"))
    for a in observe.alerts(summary):
        observe.emit("alert", scene_id=port.scene_id, **a)
    return {"published": True, "wrote": wrote, "summary": summary}
