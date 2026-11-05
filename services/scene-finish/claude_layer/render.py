"""What the layer needs from a renderer, and a stand-in for tests and local runs.

The real renderer is track B's headless viewer (SwiftShader). The layer talks
to it through `Renderer.render`, which has the same contract as the viewer's
harness: it writes, under `<workspace>/renders/`, for every requested frame,

    frame_<id>.png   the beauty pass (RGBA, transparent where nothing is drawn)
    ids_<id>.png     the region-id pass (finish regions, see finish_compare.REGIONS)
    mask_<id>.png    the furniture mask pass (piece number n has red = srgb(30 * n))

`furniture` is a furniture.json document (the pieces to draw, in mask order),
`finish` a finish.json document or None. A failure raises RenderError and the
caller retries once in a fresh renderer before giving up on the piece.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Protocol

import numpy as np


class RenderError(RuntimeError):
    """The renderer could not produce the passes (crash, lost context, timeout)."""


class Renderer(Protocol):
    name: str

    def render(self, ws: Path, *, finish: dict | None, furniture: dict | None, frames: list[int]) -> None: ...


def _hull(points: np.ndarray) -> np.ndarray:
    pts = sorted(map(tuple, points.tolist()))
    if len(pts) < 3:
        return np.array(pts)

    def half(seq):
        h: list = []
        for p in seq:
            while len(h) >= 2 and (h[-1][0] - h[-2][0]) * (p[1] - h[-2][1]) - (h[-1][1] - h[-2][1]) * (p[0] - h[-2][0]) <= 0:
                h.pop()
            h.append(p)
        return h

    lower, upper = half(pts), half(reversed(pts))
    return np.array(lower[:-1] + upper[:-1])


class StubRenderer:
    """NOT A RENDER. Paints each piece's projected parts as a flat silhouette in
    the colour of its first material, on a grey room, with a correct mask pass
    and an empty region-id pass. It exists so the whole chain (frames, masks,
    comparison, the loop, publishing) can run where the real renderer is not
    available. Nothing it produces says anything about how a model looks;
    everything that used it says so (`generated_by.renderer == "stub"`)."""

    name = "stub"
    WIDTH = 400

    def render(self, ws: Path, *, finish: dict | None, furniture: dict | None, frames: list[int]) -> None:
        from PIL import Image, ImageDraw
        from thegoodguest_room_look.finish_compare import _frames, _srgb
        from thegoodguest_room_look.furniture_clearance import twin_parts
        from thegoodguest_room_look.furniture_geometry import corners
        from thegoodguest_room_look.shell_finish import Camera, hex_to_rgb

        out = ws / "renders"
        out.mkdir(exist_ok=True)
        for f in _frames(ws, frames):
            cam = Camera(ws / "captures" / "frames" / Path(f.rgb_gcs_path).name, f.camera_pose, f.intrinsics)
            scale = self.WIDTH / cam.w
            size = (self.WIDTH, int(cam.h * scale))
            beauty = Image.new("RGBA", size, (200, 200, 205, 255))
            mask = Image.new("RGBA", size, (0, 0, 0, 0))
            db, dm = ImageDraw.Draw(beauty), ImageDraw.Draw(mask)
            for n, obj in enumerate((furniture or {}).get("objects", []), start=1):
                spec = obj["spec"]
                pts = []
                for _, obb in twin_parts(obj):
                    px, py, _, front = cam.project(corners(obb))
                    if front.all():
                        pts += list(zip(px * scale, py * scale))
                if len(pts) < 3:
                    continue
                poly = [tuple(p) for p in _hull(np.array(pts))]
                first = next(iter(spec["materials"].values()))["color"]
                db.polygon(poly, fill=(*[int(v * 255) for v in hex_to_rgb(first)], 255))
                dm.polygon(poly, fill=(_srgb(30 * n), 0, 0, 255))
            beauty.save(out / f"frame_{f.frame_index}.png")
            mask.save(out / f"mask_{f.frame_index}.png")
            Image.new("RGBA", size, (0, 0, 0, 0)).save(out / f"ids_{f.frame_index}.png")


_FRAME = re.compile(r"^(frame|ids|mask)_(\d+)\.png$")


def clear_renders(ws: Path) -> None:
    for p in (ws / "renders").glob("*.png"):
        if _FRAME.match(p.name):
            p.unlink()
