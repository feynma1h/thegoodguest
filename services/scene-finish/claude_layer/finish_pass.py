"""/finish: the measured finish, plus Claude's structure hints, each gated by
rendering against the scan's own photos (decision 0354). Design 4.3 route 1.

    measure   the package derives colours/openings from the frames       (code)
    read      Claude sees atlases + opening patches, reports structure   (Claude)
    validate  every section against the closed vocabulary; the rest dropped
    gate      each hint group is rendered ALONE on top of the measured finish and
              kept only if the render-vs-photo residual falls (and the wainscot's
              claimed height lies near the edge the atlases show)
    calibrate up to CALIBRATION_ROUNDS rounds of clamped colour fold-in
    record    work/finish/result.json: the finish document, what was rejected and why

Nothing here writes finish.json. The merge writes it, together with
furniture.json, when the whole room is ready (decision 0356).

If Claude fails or is refused, the finish is the measured one: `hints` is empty
and the reason is recorded. If the finish cannot be measured at all (no frames),
the result says `unavailable` and no finish is published.
"""
from __future__ import annotations

import copy
import statistics

import numpy as np
from thegoodguest_room_look import finish_compare as fc
from thegoodguest_room_look import shell_atlas as atl
from thegoodguest_room_look import shell_structure as struct
from thegoodguest_room_look.furniture_boxes import load_shell
from thegoodguest_room_look.shell_finish import derive_finish, load_cameras, wall_frame

from . import constants as C
from . import gates, images, observe, prompts, schemas
from .client import ClaudeRefused, ClaudeUnusable
from .piece_loop import JobContext
from .render import RenderError, clear_renders
from .spend import SpendCeilingReached

RESULT = "work/finish/result.json"


def _evidence_ids(ws, n: int) -> list[int]:
    from thegoodguest_schemas import CaptureBundle

    b = CaptureBundle()
    b.ParseFromString((ws / "captures" / "bundle.pb").read_bytes())
    have = [f.frame_index for f in b.frames if (ws / "captures" / "frames" / f.rgb_gcs_path.split("/")[-1]).exists()]
    if len(have) <= n:
        return have
    return [have[i] for i in sorted({int(round(x)) for x in np.linspace(0, len(have) - 1, n)})]


def _atlas_images(shell: dict, cams) -> list:
    out = []
    for i, w in enumerate(shell.get("walls", [])[:4]):
        fr = wall_frame(np.array(w.get("polygon") or w.get("quad"), float))
        if fr is None:
            continue
        lab, seen, du, dv = atl.wall_atlas(fr, cams)
        unseen = float(np.mean(~np.isfinite(lab[:, :, 0])))
        out.append(images.atlas_image(lab, f"wall_{i}: {fr['w']:.2f} m wide x {fr['h']:.2f} m high, {unseen:.0%} never seen; bottom = floor edge", flip_v=True))
        for k, op in enumerate(w.get("openings", [])[:2]):
            (u0, v0), (u1, v1) = op["rect_uv"]
            patch = lab[int(v0 * fr["h"] / dv):int(v1 * fr["h"] / dv) + 1, int(u0 * fr["w"] / du):int(u1 * fr["w"] / du) + 1]
            if patch.size and np.isfinite(patch[:, :, 0]).mean() > 0.3 and len(out) < C.FINISH_MAX_IMAGES - 1:
                out.append(images.atlas_image(patch, f"{op.get('classification', 'opening')} in wall_{i}: {(u1 - u0) * fr['w']:.2f} x {(v1 - v0) * fr['h']:.2f} m", flip_v=True))
    floor = (shell.get("floor") or {}).get("polygon")
    if floor and len(out) < C.FINISH_MAX_IMAGES:
        p = np.array(floor, float)
        edges = np.roll(p, -1, axis=0) - p
        e = edges[int(np.argmax(np.hypot(edges[:, 0], edges[:, 2])))]
        lab, *_ = atl.floor_atlas(p, cams, float(np.arctan2(e[2], e[0])))
        out.append(images.atlas_image(lab, "floor: face-on from above, aligned to the longest wall; texel = 1.5 cm"))
    return out[:C.FINISH_MAX_IMAGES]


def _measured_summary(finish: dict) -> dict:
    return {"walls": [{"id": w.get("wall_id"), "paint": (w.get("paint") or {}).get("hex")} for w in finish.get("walls", [])],
            "floor": {"family": (finish.get("floor") or {}).get("family"), "hex": (finish.get("floor") or {}).get("hex")}}


def _render_calibrate(ctx: JobContext, finish: dict, ids: list[int]) -> dict:
    last: Exception | None = None
    for _ in range(1 + C.RENDER_RETRIES):
        try:
            clear_renders(ctx.ws.root)
            ctx.renderer.render(ctx.ws.root, finish=finish, furniture=None, frames=ids)
            return fc.calibrate(ctx.ws.root, ids)
        except RenderError as exc:
            last = exc
            observe.emit("render_failed", stage="finish", error=type(exc).__name__)
    raise last  # type: ignore[misc]


def _derive(shell, cams, hints: dict) -> dict:
    f = derive_finish(shell, cams, hints or None)
    if hints:
        f["hints"] = hints
    return f


def _groups(accepted: dict) -> dict[str, dict]:
    """Hint groups tested one at a time: a section, or one opening kind."""
    g = {k: {k: v} for k, v in accepted.items() if k != "openings"}
    for kind, v in (accepted.get("openings") or {}).items():
        g[f"openings.{kind}"] = {"openings": {kind: v}}
    return g


def _merge(into: dict, group: dict) -> None:
    for k, v in group.items():
        if k == "openings":
            into.setdefault("openings", {}).update(v)
        else:
            into[k] = v


def fold_calibration(hints: dict, summary: dict, strength: float = C.CALIBRATION_STRENGTH) -> None:
    """finish_compare's `calibrate --write`, with each round's step clamped (the
    saturation guard) and one-frame regions ignored."""
    cal = hints.setdefault("calibration", {"source": "measured"})
    for name, v in summary.items():
        if name == "casing" or (v["frames"] < 2 and name != "door"):
            continue
        step = gates.clamp_calibration_step([strength * d for d in v["delta_lab"]])
        cal[name] = [round(o + s, 1) for o, s in zip(cal.get(name, [0, 0, 0]), step)]
    fl = summary.get("floor")
    if fl and fl["render_std_L"] > 0:
        ratio = min(max(fl["photo_std_L"] / fl["render_std_L"], 0.5), 4.0)
        cal["texture_gain"] = round(cal.get("texture_gain", 1.0) * ratio ** 0.7, 2)


def run_finish(ctx: JobContext) -> dict:
    ws, caller = ctx.ws.root, ctx.caller
    calls0 = caller.calls
    shell = load_shell(ws)
    cams = load_cameras(ws, 80)
    if not cams:
        res = {"status": "unavailable", "reason": "no capture frames to measure the finish from"}
        ctx.port.write_json(RESULT, res)
        observe.emit("finish_done", scene_id=ctx.port.scene_id, status="unavailable")
        return res
    ids = _evidence_ids(ws, C.FINISH_EVIDENCE_FRAMES)
    rejected: dict[str, str] = {}
    hints: dict = {}

    measured = _derive(shell, cams, {})
    accepted_sections: dict = {}
    try:
        ans = caller.ask(prompts.finish_request(_atlas_images(shell, cams), _measured_summary(measured), ctx.port.scene_id),
                         lambda d: d)  # sections are validated one by one below
        accepted_sections, bad = schemas.hints_from_answer(ans)
        rejected.update({k: f"outside the vocabulary: {v}" for k, v in bad.items()})
    except (ClaudeRefused, ClaudeUnusable, SpendCeilingReached) as exc:
        rejected["all"] = f"no hints: {type(exc).__name__}"

    base_summary = _render_calibrate(ctx, measured, ids)
    wain_edge = None
    if "wainscot" in accepted_sections:
        m = struct.measure(shell, cams, None, {})
        cand = m["wainscot_height_candidates"]
        wain_edge = (m["wainscot_height_auto"] or (statistics.median(cand) if cand else None), m["wainscot_height_auto"])
    for name, group in _groups(accepted_sections).items():
        if name == "wainscot":
            ok, why = gates.wainscot_edge_ok(group["wainscot"]["height_m"], *wain_edge)
            if not ok:
                rejected[name] = f"structure: {why}"
                continue
        try:
            summ = _render_calibrate(ctx, _derive(shell, cams, copy.deepcopy(group)), ids)
        except RenderError:
            rejected[name] = "could not be rendered"
            continue
        ok, why = gates.finish_gate(base_summary, summ)
        if ok:
            _merge(hints, group)
        else:
            rejected[name] = f"residual: {why}"

    current = _derive(shell, cams, copy.deepcopy(hints))
    summary = _render_calibrate(ctx, current, ids)
    if hints and not gates.finish_gate(base_summary, summary)[0]:
        rejected["combined"] = "the accepted hints together did not improve the residual; measured finish kept"
        hints, current, summary = {}, measured, base_summary
    before = gates.residual(base_summary)[0]
    for _ in range(C.CALIBRATION_ROUNDS):
        trial = copy.deepcopy(hints)
        fold_calibration(trial, summary)
        cand = _derive(shell, cams, trial)
        cand_summary = _render_calibrate(ctx, cand, ids)
        if gates.residual(cand_summary)[0] >= gates.residual(summary)[0]:
            break
        hints, current, summary = trial, cand, cand_summary
    after = gates.residual(summary)[0]
    signed = [v["delta_lab"][0] for k, v in summary.items() if k != "casing"]
    result = {
        "status": "done",
        "finish": {**current, "rejected": rejected, "residual": {"before_l": round(before, 2), "after_l": round(after, 2)}},
        "lightness_offset": round(statistics.median(signed), 2) if signed else 0.0,
        "calls": caller.calls - calls0,
        "generated_by": {"code_sha": ctx.code_sha, "vocab_version": C.VOCAB_VERSION, "prompt_version": C.PROMPT_VERSION,
                         "model": C.FINISH_MODEL, "renderer": ctx.renderer.name},
    }
    ctx.port.write_json(RESULT, result)
    observe.emit("finish_done", scene_id=ctx.port.scene_id, status="done", hints=sorted(hints), rejected=sorted(rejected),
                 residual_before=round(before, 2), residual_after=round(after, 2), calls=result["calls"])
    return result
