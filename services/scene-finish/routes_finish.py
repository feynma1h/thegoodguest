"""POST /finish: the first task after /shell (decisions 0354, 0356).

    {scene_id, bundle_uri}

Starts the job clock, runs the finish pass, then enqueues one /furniture-piece
per boxed object (or the merge at once when there are none), and a
/furniture-merge at the job's deadline so one hung task can never block the
room. Writes only work/ files; finish.json and furniture.json are written by
/furniture-merge, together.
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from claude_layer import publish
from claude_layer.finish_pass import RESULT, run_finish
from claude_layer.jobs import job_context
from claude_layer.piece_loop import load_boxes_doc

router = APIRouter()


class FinishRequest(BaseModel):
    scene_id: str
    bundle_uri: str


@router.post("/finish")
def finish(request: Request, req: FinishRequest) -> JSONResponse:
    deps = request.app.state.scene_finish_deps
    deps.authorize(request, "/finish")
    port = deps.port_for(req.scene_id, req.bundle_uri)
    shell = port.read_json("shell.json") or {}
    if shell.get("status") == "unavailable" or ("walls" not in shell and "shell" not in shell):
        # Never coming (or not yet there and not ours to wait for): written, so the task drains.
        port.write_json(RESULT, {"status": "unavailable", "reason": f"shell {shell.get('status', 'missing')}: {shell.get('reason', '')}"})
        return JSONResponse({"status": "unavailable"})
    if port.read_json("boxes.json") is None:  # /process has not written it yet: let Cloud Tasks retry
        return JSONResponse({"status": "waiting", "why": "boxes.json not written yet"}, status_code=503)
    boxes = load_boxes_doc(port)
    job = publish.start_job(port, deps.clock(), sorted(boxes))
    ready = port.read_json(RESULT) or {}
    if ready.get("status") not in ("done", "unavailable") or ready.get("generated_by", {}).get("code_sha") != deps.code_sha:
        with job_context(deps, port, "finish") as ctx:
            ready = run_finish(ctx)
    deps.enqueuer.enqueue("/furniture-merge", {"scene_id": req.scene_id}, name=f"merge-deadline-{req.scene_id}",
                          delay_s=max(job["started_ts"] + job["deadline_s"] - deps.clock(), 0) + 5)
    for box_id in job["pieces"]:
        deps.enqueuer.enqueue("/furniture-piece", {"scene_id": req.scene_id, "bundle_uri": req.bundle_uri, "box_id": box_id},
                              name=f"piece-{req.scene_id}-{box_id}")
    if not job["pieces"]:
        deps.enqueuer.enqueue("/furniture-merge", {"scene_id": req.scene_id}, name=f"merge-{req.scene_id}")
    return JSONResponse({"status": ready["status"], "pieces": job["pieces"]})
