"""POST /still: the room's still picture for the app (decision 0363).

    {scene_id}

Draws the room the way the website's room page opens it — the diorama's first
corner view — from the scene's own shell.json, plus finish.json and
furniture.json when they are there, and writes it beside them:

    scenes/<scene_id>/still.jpg         by day, always
    scenes/<scene_id>/still-night.jpg   by night, only when twins were drawn
                                        (deleted otherwise: the website has no
                                        night without them)

Only then is the scene document marked (`still: {night, rendered_at}`), which
is how api-public knows to sign links without asking the bucket. A room deleted
while it was drawn gets its pictures taken back out.

Render only: no Claude call, no spend, and nothing else in the scene is
written. Enqueued by perception-obj when a shell is ready (still_enqueue.py
there) and by /furniture-merge when it publishes; any re-drive is idempotent,
since the same documents draw the same pictures.

Answers: 200 when done or when there is nothing to draw (the task drains);
503 when the render failed twice (Cloud Tasks retries, maxAttempts 3).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from render_client import RenderError
from still_ports import STILL_DAY, STILL_NIGHT, StillMarker, StillStore

log = logging.getLogger("scene-finish")

router = APIRouter()


@dataclass
class StillDeps:
    store: StillStore
    marker: StillMarker
    authorize: Callable[[Request, str], None]


class StillRequest(BaseModel):
    # A scene id names a bucket prefix; nothing else may.
    scene_id: str = Field(pattern=r"^[A-Za-z0-9-]{1,64}$")


def _skip(scene_id: str, reason: str) -> JSONResponse:
    log.info("still skipped scene=%s reason=%s", scene_id, reason)
    return JSONResponse({"status": "skipped", "reason": reason})


def _optional(store: StillStore, scene_id: str, name: str) -> dict | None:
    """finish.json / furniture.json: unreadable counts as absent, as on the website."""
    try:
        return store.read_json(scene_id, name)
    except ValueError as e:
        log.warning("still: %s unreadable for scene %s, drawn without it: %s", name, scene_id, e)
        return None


@router.post("/still")
def still(request: Request, req: StillRequest) -> JSONResponse:
    deps: StillDeps = request.app.state.still_deps()
    deps.authorize(request, "/still")
    sid = req.scene_id
    if not deps.marker.scene_exists(sid):
        return _skip(sid, "no_scene")
    try:
        shell = deps.store.read_json(sid, "shell.json")
    except ValueError:
        return _skip(sid, "shell_unreadable")
    if shell is None:
        return _skip(sid, "no_shell")
    if shell.get("status") != "ready":
        return _skip(sid, f"shell_{shell.get('status', 'unknown')}")
    finish = _optional(deps.store, sid, "finish.json")
    furniture = _optional(deps.store, sid, "furniture.json")

    try:
        result = request.app.state.renderer().render_still(shell=shell, finish=finish, furniture=furniture)
    except RenderError as e:
        log.warning("still render failed scene=%s: %s", sid, e)
        return JSONResponse({"status": "error", "reason": f"render failed: {e}"}, status_code=503)

    deps.store.put(sid, STILL_DAY, result.day, "image/jpeg")
    if result.night is not None:
        deps.store.put(sid, STILL_NIGHT, result.night, "image/jpeg")
    else:
        deps.store.delete(sid, STILL_NIGHT)
    if not deps.marker.mark(sid, night=result.night is not None):
        # Deleted while it was drawn: the pictures must not outlive the room.
        deps.store.delete(sid, STILL_DAY)
        deps.store.delete(sid, STILL_NIGHT)
        return _skip(sid, "no_scene")
    # Sizes and timings only; never pixels.
    log.info("still ok scene=%s night=%s finished=%s day_bytes=%d info=%s", sid, result.night is not None,
             result.info.get("finished"), len(result.day), result.info)
    return JSONResponse({"status": "done", "night": result.night is not None, "finished": result.info.get("finished")})
