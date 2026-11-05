"""One boxed object -> one furniture model (decision 0355). Design 4.3 / 4.7.

    evidence   best frames of the box, person-masked capped crops  (code)
    write      Claude writes a spec in the closed vocabulary          (Claude)
    build      the package places it on the person's box by rule      (code)
    render     the renderer draws it from the evidence frames         (renderer)
    compare    masked lightness/hue error and silhouette-box gap       (code)
    critique   Claude sees photo | render and edits, or says done     (Claude)
    accept     an edit is kept only if no number gets worse than the tolerance

Ends with exactly one of two results, cached as JSON (never pixels) in
`work/furniture/<box_id>.json`:
    passed  the best accepted spec
    failed  and a reason. A failed piece shows NOTHING in the room.

After every accepted edit a `running` checkpoint is written, so a Cloud Tasks
retry resumes from the best spec instead of paying for the same calls again.
"""
from __future__ import annotations

import copy
import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image as PILImage
from thegoodguest_room_look.furniture_boxes import load_shell, parse_boxes
from thegoodguest_room_look.furniture_evidence import pick_spread, score_frames
from thegoodguest_room_look.furniture_placement import PlacementError, place_all

from . import constants as C
from . import gates, images, observe, prompts, schemas
from .client import ClaudeCaller, ClaudeRefused, ClaudeUnusable, Image
from .render import RenderError, Renderer, clear_renders
from .scene_port import ScenePort
from .spend import SpendCeilingReached
from .workspace import Workspace


def piece_path(box_id: str) -> str:
    return f"work/furniture/{box_id}.json"


def box_hash(box: dict) -> str:
    return hashlib.sha256(json.dumps(box, sort_keys=True).encode()).hexdigest()[:12]


@dataclass
class JobContext:
    port: ScenePort
    ws: Workspace
    caller: ClaudeCaller
    renderer: Renderer
    code_sha: str
    deadline_ts: float  # epoch seconds: stop editing, keep the best
    clock: callable = time.time
    cache: dict = field(default_factory=dict)


def load_boxes_doc(port: ScenePort) -> dict[str, dict]:
    doc = port.read_json("boxes.json")
    return parse_boxes(doc) if doc else {}


def _stamp(ctx: JobContext) -> dict:
    return {"code_sha": ctx.code_sha, "vocab_version": C.VOCAB_VERSION, "prompt_version": C.PROMPT_VERSION,
            "model": C.FURNITURE_MODEL, "renderer": ctx.renderer.name}


def _render_crop(ws: Path, e: dict) -> Image | None:
    rp = ws / "renders" / f"frame_{e['frame']}.png"
    if not rp.exists():
        return None
    photo_size = PILImage.open(ws / "captures" / "frames" / e["file"]).size
    r = PILImage.open(rp).convert("RGBA")
    r = PILImage.alpha_composite(PILImage.new("RGBA", r.size, (200, 200, 205, 255)), r).convert("RGB").resize(photo_size)
    x0, y0, x1, y1 = e["bbox"]
    pw, ph = (x1 - x0) * C.CROP_PAD, (y1 - y0) * C.CROP_PAD
    r = r.crop((int(max(x0 - pw, 0)), int(max(y0 - ph, 0)), int(min(x1 + pw, r.width)), int(min(y1 + ph, r.height))))
    if e["turn"]:
        r = r.rotate(e["turn"], expand=True)
    return images.render_image(r, f"our render, frame {e['frame']}")


def gather_evidence(ctx: JobContext, box: dict) -> list[tuple[dict, Image]]:
    """[(evidence row, masked photo crop)] for up to MAX_EVIDENCE_FRAMES usable frames."""
    ws = ctx.ws.root
    rows = score_frames(ws, box)
    out = []
    for e in pick_spread(rows, 3 * C.MAX_EVIDENCE_FRAMES):
        photo = PILImage.open(ws / "captures" / "frames" / e["file"])
        crop = images.photo_crop(photo, tuple(e["bbox"]), e["turn"], ctx.ws.person_mask(e["frame"]), f"photo, frame {e['frame']}")
        if crop is not None:
            out.append((e, crop))
        if len(out) >= C.MAX_EVIDENCE_FRAMES:
            break
    return out


def _evaluate(ctx: JobContext, box: dict, spec: dict, evidence: list[dict], offset_l: float, poly, floor_y: float):
    """Place the spec on its box alone, render it, score it. -> (score | None, placed object).
    Raises PlacementError on a spec the placement rules refuse, RenderError after the retry."""
    s = copy.deepcopy(spec)
    if (s.get("place") or {}).get("rule") in ("on", "over"):
        s["place"] = {"rule": "floor"}  # the neighbour is not here; the merge places the real thing
    objects, _ = place_all([s], {box["id"]: box}, poly, floor_y)
    doc = {"furniture_version": 1, "scene_id": ctx.port.scene_id, "objects": objects}
    for attempt in range(1 + C.RENDER_RETRIES):
        try:
            clear_renders(ctx.ws.root)
            ctx.renderer.render(ctx.ws.root, finish=None, furniture=doc, frames=[e["frame"] for e in evidence])
            break
        except RenderError as exc:
            observe.emit("render_failed", box_id=box["id"], attempt=attempt, error=type(exc).__name__)
            if attempt == C.RENDER_RETRIES:
                raise
    return gates.score_piece(ctx.ws.root, evidence, 0, offset_l), objects[0]


def run_piece(ctx: JobContext, box_id: str) -> dict:
    t0 = ctx.clock()
    boxes = load_boxes_doc(ctx.port)
    box = boxes[box_id]
    cached = ctx.port.read_json(piece_path(box_id))
    if cached and cached.get("status") in ("passed", "failed") and cached.get("box_hash") == box_hash(box) \
            and cached.get("generated_by", {}).get("vocab_version") == C.VOCAB_VERSION:
        return cached
    result = _run(ctx, box, boxes, cached if cached and cached.get("status") == "running" else None)
    result.update(piece=box_id, box_hash=box_hash(box), generated_by=_stamp(ctx), seconds=round(ctx.clock() - t0, 1))
    ctx.port.write_json(piece_path(box_id), result)
    observe.emit("piece_done", scene_id=ctx.port.scene_id, box_id=box_id, status=result["status"], reason=result.get("reason", ""),
                 edits=result.get("edits", 0), calls=result.get("calls", 0), seconds=result["seconds"],
                 dl=(result.get("score") or {}).get("dl"), gap=(result.get("score") or {}).get("gap"))
    return result


def _failed(reason: str, calls: int, history: list | None = None) -> dict:
    return {"status": "failed", "reason": reason, "calls": calls, "history": history or []}


def _run(ctx: JobContext, box: dict, boxes: dict, resume: dict | None) -> dict:
    caller = ctx.caller
    calls0 = caller.calls
    others = [b for k, b in boxes.items() if k != box["id"]]
    other_ids = {b["id"] for b in others}
    shell = load_shell(ctx.ws.root)
    poly = np.array([[p[0], p[2]] for p in shell["floor"]["polygon"]], float)
    floor_y = float(shell["floor"]["y"])
    fin = ctx.port.read_json("work/finish/result.json") or {}
    offset_l = float(fin.get("lightness_offset", 0.0))
    size = [float(x) for x in box["size"]]

    evidence_pairs = gather_evidence(ctx, box)
    if not evidence_pairs:
        return _failed("no frame shows the object well enough with its people masked out", 0)
    ev = [e for e, _ in evidence_pairs]
    photos = [c for _, c in evidence_pairs]

    best_spec = best_score = None
    history: list[dict] = []
    edits = accepted = 0
    state = gates.LoopState()
    stop = ""
    try:
        if resume and resume.get("spec"):
            best_spec, history, edits = resume["spec"], resume.get("history", []), resume.get("edits", 0)
            accepted = resume.get("accepted", 0)
            state.edits = edits
            best_score, _ = _score_or_none(ctx, box, best_spec, ev, offset_l, poly, floor_y)
        if best_score is None:
            spec = caller.ask(prompts.spec_request(box, others, photos, ctx.port.scene_id),
                              schemas.validate_spec_answer(box["id"], size, other_ids))
            score, _ = _evaluate(ctx, box, spec, ev, offset_l, poly, floor_y)
            why = gates.usable_first_render(score)
            if why:
                return _failed(why, caller.calls - calls0)
            best_spec, best_score = spec, score
            history.append({"edit": 0, "accepted": True, **score.as_json()})
            _checkpoint(ctx, box, best_spec, best_score, history, edits, accepted)
        validate = schemas.validate_critique_answer(box["id"], size, other_ids)
        while not (stop := state.stop_reason() or ("deadline" if ctx.clock() >= ctx.deadline_ts else "")):
            pairs = [(p, r) for (e, p) in evidence_pairs if (r := _render_crop(ctx.ws.root, e))]
            if not pairs:  # the checkpoint was resumed without a render on disk
                _evaluate(ctx, box, best_spec, ev, offset_l, poly, floor_y)
                pairs = [(p, r) for (e, p) in evidence_pairs if (r := _render_crop(ctx.ws.root, e))]
            verdict, payload = caller.ask(
                prompts.critique_request(box, others, best_spec, pairs, best_score.as_json(), history, state.edits + 1, ctx.port.scene_id),
                validate)
            if verdict == "done":
                stop = "model says done"
                break
            new_score, ok = None, False
            try:
                new_score, _ = _evaluate(ctx, box, payload, ev, offset_l, poly, floor_y)
                ok = new_score is not None and gates.edit_accepted(new_score, best_score)
            except (PlacementError, RenderError) as exc:
                history.append({"edit": state.edits + 1, "accepted": False, "error": type(exc).__name__})
            if new_score is not None:
                history.append({"edit": state.edits + 1, "accepted": ok, **new_score.as_json()})
            gain_l = gates.gain(new_score, best_score) if new_score else 0.0
            if ok:
                payload["revision"] = best_spec.get("revision", 1) + 1
                best_spec, best_score, accepted = payload, new_score, accepted + 1
            else:  # put the best spec's render back so the next critique shows the right picture
                _evaluate(ctx, box, best_spec, ev, offset_l, poly, floor_y)
            state.after_edit(ok, gain_l)
            edits = state.edits
            _checkpoint(ctx, box, best_spec, best_score, history, edits, accepted)
    except SpendCeilingReached as exc:
        stop = "spend ceiling"
        if best_spec is None:
            return _failed(f"spend ceiling reached before a model existed ({exc})", caller.calls - calls0)
    except (ClaudeRefused, ClaudeUnusable) as exc:
        stop = f"claude: {type(exc).__name__}"
        if best_spec is None:
            return _failed(f"no valid model from Claude ({type(exc).__name__}: {exc})", caller.calls - calls0)
    except (PlacementError, RenderError) as exc:
        if best_spec is None:
            return _failed(f"the first model could not be placed or rendered ({type(exc).__name__}: {exc})", caller.calls - calls0)
        stop = f"{type(exc).__name__} after a good model"
    return {"status": "passed", "spec": best_spec, "score": best_score.as_json(), "history": history, "edits": edits,
            "accepted": accepted, "stop": stop, "calls": caller.calls - calls0}


def _score_or_none(ctx, box, spec, ev, offset_l, poly, floor_y):
    try:
        return _evaluate(ctx, box, spec, ev, offset_l, poly, floor_y)
    except (PlacementError, RenderError):
        return None, None


def _checkpoint(ctx: JobContext, box: dict, spec: dict, score, history: list, edits: int, accepted: int) -> None:
    ctx.port.write_json(piece_path(box["id"]), {"status": "running", "piece": box["id"], "box_hash": box_hash(box), "spec": spec,
                                                "score": score.as_json(), "history": history, "edits": edits, "accepted": accepted,
                                                "generated_by": _stamp(ctx)})
