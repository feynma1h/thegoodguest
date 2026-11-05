"""The real thing: headless Chrome drawing the real viewer with software GL.

Skipped unless a viewer build (web/ built with NEXT_PUBLIC_SHELL_FINISH=1) and a
Chrome are both available, so the suite stays hermetic. To run it:

    NEXT_PUBLIC_SHELL_FINISH=1 npm --prefix web run build
    (cd services/scene-finish && npm ci)
    VIEWER_DIR=web/out CHROME_PATH="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
        pytest services/scene-finish/tests/test_real_render.py

Uses the public hero room's shell (no photos, nothing private) and a camera
standing inside it. Pins what the cloud depends on: the viewer settles, a frame
comes back with all passes, and the same job twice gives byte-identical output
(the renderer is deterministic once the viewer has settled).
"""

import json
import os
from pathlib import Path

import pytest
from image_diff import diff_images
from render_client import Renderer
from thegoodguest_room_look import shell_finish as sf

REPO = Path(__file__).resolve().parents[3]
VIEWER = Path(os.environ.get("VIEWER_DIR", REPO / "web" / "out"))
CHROME = os.environ.get("CHROME_PATH")
DRIVER_DEPS = REPO / "services" / "scene-finish" / "node_modules" / "playwright-core"

pytestmark = pytest.mark.skipif(
    not ((VIEWER / "shell-finish.html").exists() and CHROME and DRIVER_DEPS.exists()),
    reason="needs a flagged viewer build, CHROME_PATH and `npm ci` in services/scene-finish",
)

# A camera standing in the middle of the hero room, looking along +x.
FRAME = {"id": 1, "pos": [0.8, 0.0, -0.4], "quat": [0.0, 0.7071068, 0.0, 0.7071068], "fy": 960.0, "h": 600, "w": 800}


def test_the_viewer_settles_and_renders_the_same_frame_twice():
    shell = json.loads((REPO / "web" / "public" / "hero" / "room.json").read_text())["shell"]
    finish = sf.derive_finish(shell, [])
    r = Renderer()
    try:
        first = r.render(shell=shell, finish=finish, frames=[FRAME], width=400)
        second = r.render(shell=shell, finish=finish, frames=[FRAME], width=400)
    finally:
        r.close()
    assert set(first.images) >= {"frame_1", "ids_1"}
    assert "SwiftShader" in first.info["glRenderer"]
    for name in ("frame_1", "ids_1"):
        assert diff_images(first.images[name], second.images[name], name).identical
