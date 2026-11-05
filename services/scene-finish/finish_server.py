"""scene-finish: the cloud step that finishes a room after its shell is made.

This is the skeleton: the container, the headless renderer and the routes that
prove them. The finish, furniture-piece and furniture-merge routes (and the
Claude calls behind them) are added to this app by the Claude-layer track.

  GET  /health   startup probe; 200 as soon as uvicorn is up. Does not start Chrome.
  POST /render   draw frames of a room from given camera poses and return the
                 PNGs. The room's documents travel in the request; nothing is
                 read from or written to a bucket.

Access is the platform's: the service is deployed --no-allow-unauthenticated
and only the Cloud Tasks invoker holds run.invoker (infra/deploy_scene_finish.sh),
the posture decision 0106 set for perception-obj. The routes the queue calls add
app-side OIDC checks with the same per-route audience pattern when they land.

Read by: infra/deploy_scene_finish.sh (startup probe), the Dockerfile (CMD: finish_server:app).
"""

from __future__ import annotations

import base64
import contextlib
import logging
import os
from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from render_client import (
    DEFAULT_WIDTH_PX,
    MAX_FRAMES,
    MAX_WIDTH_PX,
    MIN_WIDTH_PX,
    RenderError,
    Renderer,
)

log = logging.getLogger("scene-finish")


class Frame(BaseModel):
    """One camera: where it stood and how it saw (what the compare harness takes)."""

    id: int
    pos: list[float] = Field(min_length=3, max_length=3)
    quat: list[float] = Field(min_length=4, max_length=4)
    fy: float = Field(gt=0)
    h: int = Field(gt=0)
    w: int = Field(gt=0)


class RenderRequest(BaseModel):
    shell: dict[str, Any]
    finish: dict[str, Any] | None = None
    furniture: dict[str, Any] | None = None
    frames: list[Frame] = Field(min_length=1, max_length=MAX_FRAMES)
    width: int = Field(default=DEFAULT_WIDTH_PX, ge=MIN_WIDTH_PX, le=MAX_WIDTH_PX)


def create_app(renderer_factory: Callable[[], Renderer] = Renderer) -> FastAPI:
    state: dict[str, Renderer] = {}

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        if "r" in state:
            state["r"].close()

    app = FastAPI(title="scene-finish", lifespan=lifespan)

    def renderer() -> Renderer:
        # Started on first use, so /health and a cold start never wait for Chrome.
        if "r" not in state:
            state["r"] = renderer_factory()
        return state["r"]

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/render")
    def render(req: RenderRequest) -> dict[str, Any]:
        try:
            result = renderer().render(
                shell=req.shell, finish=req.finish, furniture=req.furniture,
                frames=[f.model_dump() for f in req.frames], width=req.width,
            )
        except RenderError as e:
            log.warning("render failed: %s", e)
            raise HTTPException(status_code=502, detail=f"render failed: {e}") from None
        # Sizes and timings only; never pixels.
        log.info("render ok frames=%d images=%d info=%s", len(req.frames), len(result.images), result.info)
        return {
            "images": {k: base64.b64encode(v).decode("ascii") for k, v in result.images.items()},
            "info": result.info,
        }

    return app


app = create_app()

if os.environ.get("LOG_LEVEL"):
    logging.basicConfig(level=os.environ["LOG_LEVEL"])
