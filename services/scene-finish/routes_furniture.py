"""POST /furniture-piece and POST /furniture-merge (decisions 0355, 0356).

/furniture-piece  {scene_id, bundle_uri, box_id}   one boxed object -> work/furniture/<box>.json
/furniture-merge  {scene_id, force?}               publishes finish.json + furniture.json when the
                                                    whole room is ready or the deadline has passed

A piece task that finds the room already published does nothing (it cannot add to a
published room; a re-drive republishes). Each piece task asks for a merge when it ends;
the merge is idempotent, so the last one to finish publishes and the others are no-ops.
A merge that wrote finish.json or furniture.json asks for the room's still picture to
be drawn again (/still, decision 0363), since the room now looks different.
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from claude_layer import publish
from claude_layer.jobs import job_context
from claude_layer.piece_loop import run_piece

router = APIRouter()


class PieceRequest(BaseModel):
    scene_id: str
    bundle_uri: str
    box_id: str


class MergeRequest(BaseModel):
    scene_id: str
    force: bool = False


@router.post("/furniture-piece")
def furniture_piece(request: Request, req: PieceRequest) -> JSONResponse:
    deps = request.app.state.scene_finish_deps
    deps.authorize(request, "/furniture-piece")
    port = deps.port_for(req.scene_id, req.bundle_uri)
    job = port.read_json(publish.JOB)
    if job is None or req.box_id not in job["pieces"]:
        return JSONResponse({"status": "unknown piece"}, status_code=422)  # poison: drains
    if port.read_json(publish.SUMMARY) is not None:
        return JSONResponse({"status": "already published"})
    with job_context(deps, port, f"piece-{req.box_id}") as ctx:
        result = run_piece(ctx, req.box_id)
    deps.enqueuer.enqueue("/furniture-merge", {"scene_id": req.scene_id}, name=f"merge-{req.scene_id}-{req.box_id}")
    return JSONResponse({"status": result["status"], "reason": result.get("reason", "")})


@router.post("/furniture-merge")
def furniture_merge(request: Request, req: MergeRequest) -> JSONResponse:
    deps = request.app.state.scene_finish_deps
    deps.authorize(request, "/furniture-merge")
    port = deps.port_for(req.scene_id, "")
    out = publish.merge(port, deps.clock(), code_sha=deps.code_sha, force=req.force)
    if out.get("wrote"):
        deps.enqueuer.enqueue("/still", {"scene_id": req.scene_id}, name=f"still-{req.scene_id}")
    return JSONResponse({k: v for k, v in out.items() if k != "summary"})
