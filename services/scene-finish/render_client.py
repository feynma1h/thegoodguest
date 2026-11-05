"""Python side of the headless renderer: one warm Chrome behind render_driver.mjs.

`Renderer.render` takes the room's documents as dicts and the camera poses of
the frames to draw, hands them to the Node driver (`render_driver.mjs serve`,
which keeps Chrome open between jobs) and returns the PNGs the viewer's compare
harness produced: for each frame `frame_<id>` (the look), `ids_<id>` (flat
region ids) and `mask_<id>` (each furniture twin in its own id).

The documents are written to a private temp directory for the driver to read
and removed afterwards; the PNGs come back as bytes and are never written
anywhere the caller did not ask. Nothing here logs pixels.

Failure policy (design 4.6): a crash, a hang or a driver that reports an error
gets ONE retry in a fresh driver process (fresh Chrome); a second failure
raises RenderError and the caller decides (a piece falls back to its stand-in).

Read by: server.py (/render). Track C's piece and finish routes call it too.
"""

from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
DRIVER = HERE / "render_driver.mjs"

# One whole job may take this long, matching JOB_TIMEOUT_MS in the driver plus
# a margin for the process itself; past it the driver is killed.
JOB_TIMEOUT_S = 660.0
# The driver's output width in px, and the most frames one job may carry.
DEFAULT_WIDTH_PX = 800
MAX_FRAMES = 12
MIN_WIDTH_PX, MAX_WIDTH_PX = 64, 1920


class RenderError(RuntimeError):
    """The render failed twice (or the job was invalid)."""


@dataclass
class RenderResult:
    images: dict[str, bytes]
    info: dict = field(default_factory=dict)


class Renderer:
    """A warm headless Chrome. Not thread-safe by design: one job at a time."""

    def __init__(self, *, command: list[str] | None = None, timeout_s: float = JOB_TIMEOUT_S):
        self._command = command or self.default_command()
        self._timeout_s = timeout_s
        self._proc: subprocess.Popen | None = None
        self._lines: queue.Queue[str | None] = queue.Queue()
        self._lock = threading.Lock()

    @staticmethod
    def default_command() -> list[str]:
        cmd = [os.environ.get("NODE", "node"), str(DRIVER), "serve", "--gl", os.environ.get("RENDER_GL", "swiftshader")]
        if os.environ.get("VIEWER_DIR"):
            cmd += ["--web", os.environ["VIEWER_DIR"]]
        if os.environ.get("CHROME_PATH"):
            cmd += ["--chrome", os.environ["CHROME_PATH"]]
        if os.environ.get("RENDER_CONTAINER") == "1":
            cmd.append("--container")
        return cmd

    # -- process handling --------------------------------------------------

    def _start(self) -> None:
        self._proc = subprocess.Popen(
            self._command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1,
        )
        self._lines = queue.Queue()
        proc, lines = self._proc, self._lines

        def pump() -> None:
            assert proc.stdout is not None
            for line in proc.stdout:
                lines.put(line)
            lines.put(None)  # the driver exited

        threading.Thread(target=pump, daemon=True).start()

    def close(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None:
            return
        try:
            if proc.stdin:
                proc.stdin.close()
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
            proc.wait()

    def _ask(self, job: dict) -> dict:
        if self._proc is None or self._proc.poll() is not None:
            self._start()
        assert self._proc is not None and self._proc.stdin is not None
        self._proc.stdin.write(json.dumps(job) + "\n")
        self._proc.stdin.flush()
        try:
            line = self._lines.get(timeout=self._timeout_s)
        except queue.Empty:
            self._proc.kill()
            raise RenderError(f"driver gave no answer in {self._timeout_s:.0f} s") from None
        if line is None:
            raise RenderError("driver exited")
        return json.loads(line)

    # -- the job -----------------------------------------------------------

    def render(
        self,
        *,
        shell: dict,
        frames: list[dict],
        finish: dict | None = None,
        furniture: dict | None = None,
        width: int = DEFAULT_WIDTH_PX,
    ) -> RenderResult:
        if not frames:
            raise RenderError("no frames to render")
        if len(frames) > MAX_FRAMES:
            raise RenderError(f"{len(frames)} frames is more than {MAX_FRAMES} in one job")
        if not MIN_WIDTH_PX <= width <= MAX_WIDTH_PX:
            raise RenderError(f"width {width} is outside {MIN_WIDTH_PX}..{MAX_WIDTH_PX}")
        work = Path(tempfile.mkdtemp(prefix="scene-finish-render-"))
        try:
            job = {"frames": frames, "width": width, "outDir": str(work / "out")}
            for name, doc in (("shell", shell), ("finish", finish), ("furniture", furniture)):
                if doc is not None:
                    (work / f"{name}.json").write_text(json.dumps(doc))
                    job[name] = str(work / f"{name}.json")
            with self._lock:
                result = self._with_one_retry(job)
            images = {p.stem: p.read_bytes() for p in sorted((work / "out").glob("*.png"))}
            expect = {f"{kind}_{f['id']}" for f in frames for kind in ("frame", "ids")}
            missing = expect - set(images)
            if missing:
                raise RenderError(f"driver reported success but {sorted(missing)[:3]} are missing")
            return RenderResult(images=images, info={k: result[k] for k in ("glRenderer", "readyMs", "runMs", "perFrameMs") if k in result})
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def _with_one_retry(self, job: dict) -> dict:
        last = "unknown"
        for attempt in (1, 2):
            try:
                result = self._ask(job)
                if result.get("ok"):
                    return result
                last = str(result.get("error", "driver reported failure"))
            except (RenderError, OSError, ValueError) as e:
                last = str(e)
            self.close()  # the retry gets a fresh Chrome
            shutil.rmtree(job["outDir"], ignore_errors=True)
        raise RenderError(last)
