"""What the routes depend on, and the one function that attaches them to the app.

track B's app entry adds exactly one line:

    from claude_layer.wiring import register
    register(app, deps)          # deps = deps_from_env(renderer, authorize)

`renderer` is B's headless renderer behind the `Renderer` contract (render.py);
`authorize(request, route_path)` is B's OIDC check (raise HTTPException(401)).
"""
from __future__ import annotations

import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from .client import ClaudeClient
from .enqueue import Enqueuer
from .render import Renderer
from .scene_port import ScenePort


@dataclass
class Deps:
    port_for: Callable[[str, str], ScenePort]  # (scene_id, bundle_uri) -> port
    client: ClaudeClient
    renderer: Renderer
    enqueuer: Enqueuer
    code_sha: str = "dev"
    clock: Callable[[], float] = time.time
    authorize: Callable[[object, str], None] = lambda request, path: None
    assume_no_people: bool = False  # only the local fake-client run sets this
    extra: dict = field(default_factory=dict)


def deps_from_env(renderer: Renderer, authorize: Callable[[object, str], None]) -> Deps:
    from google.cloud import storage  # deferred: not installed in tests

    from .client import AnthropicClient
    from .enqueue import CloudTasksEnqueuer
    from .scene_port import GcsScenePort

    storage_client = storage.Client()
    outputs = storage_client.bucket(os.environ["PERCEPTION_OUTPUTS_BUCKET"])
    return Deps(
        port_for=lambda scene_id, bundle_uri: GcsScenePort(scene_id, outputs, storage_client, bundle_uri),
        client=AnthropicClient(), renderer=renderer, enqueuer=CloudTasksEnqueuer(),
        code_sha=os.environ.get("GIT_SHA", "dev"), authorize=authorize)


def register(app, deps: Deps) -> None:
    from routes_finish import router as finish_router
    from routes_furniture import router as furniture_router

    app.state.scene_finish_deps = deps
    app.include_router(finish_router)
    app.include_router(furniture_router)
