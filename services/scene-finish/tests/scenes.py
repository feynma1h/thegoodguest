"""A small invented scene on disk: a 4 x 4 m room, one 1 m cube-ish box in it, six
cameras around it looking at it. Photos are noise, not anyone's home."""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
from PIL import Image
from thegoodguest_schemas import CaptureBundle

W, H, F = 320, 240, 300.0
BOX = {"id": "box_0", "category": "table", "label": "table", "center": [0.0, 0.5, 0.0], "yaw": 0.0, "size": [1.0, 1.0, 1.0]}


def _quat(pos, target):
    f = np.array(target, float) - pos
    f /= np.linalg.norm(f)
    r = np.cross(f, [0, 1, 0])
    r /= np.linalg.norm(r)
    u = np.cross(r, f)
    m = np.stack([r, u, -f], axis=1)
    t = np.trace(m)
    if t > 0:
        s = math.sqrt(t + 1) * 2
        return [(m[2, 1] - m[1, 2]) / s, (m[0, 2] - m[2, 0]) / s, (m[1, 0] - m[0, 1]) / s, s / 4]
    i = int(np.argmax(np.diag(m)))
    j, k = (i + 1) % 3, (i + 2) % 3
    s = math.sqrt(1 + m[i, i] - m[j, j] - m[k, k]) * 2
    q = [0.0] * 4
    q[i] = s / 4
    q[3] = (m[k, j] - m[j, k]) / s
    q[j] = (m[j, i] + m[i, j]) / s
    q[k] = (m[k, i] + m[i, k]) / s
    return q


def shell() -> dict:
    c = [(-2, -2), (2, -2), (2, 2), (-2, 2)]
    walls = [{"wall_id": f"wall_{i}", "classification": "wall", "openings": [],
              "polygon": [[a[0], 0, a[1]], [b[0], 0, b[1]], [b[0], 2.6, b[1]], [a[0], 2.6, a[1]]]}
             for i, (a, b) in enumerate(zip(c, c[1:] + c[:1]))]
    return {"shell_version": 3, "scene_id": "scene-x", "status": "ok", "walls": walls,
            "floor": {"y": 0.0, "polygon": [[a[0], 0, a[1]] for a in c], "material": {}}}


def build(root: Path, n_frames: int = 6, boxes: list[dict] | None = None) -> Path:
    """-> the scene dir: shell.json, boxes.json, captures/{bundle.pb, frames/}."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "captures" / "frames").mkdir(parents=True)
    (root / "shell.json").write_text(json.dumps(shell()))
    (root / "boxes.json").write_text(json.dumps({"boxes_version": 1, "boxes": boxes or [BOX]}))
    b = CaptureBundle()
    rng = np.random.default_rng(1)
    for i in range(n_frames):
        a = 2 * math.pi * i / n_frames
        pos = np.array([1.7 * math.sin(a), 1.2, 1.7 * math.cos(a)])
        f = b.frames.add()
        f.frame_index = i
        f.rgb_gcs_path = f"frames/{i:06d}.jpg"
        p = f.camera_pose
        p.pos_x, p.pos_y, p.pos_z = pos
        p.quat_x, p.quat_y, p.quat_z, p.quat_w = _quat(pos, [0, 0.5, 0])
        f.intrinsics.fx = f.intrinsics.fy = F
        f.intrinsics.cx, f.intrinsics.cy = W / 2, H / 2
        f.intrinsics.width, f.intrinsics.height = W, H
        f.gravity.y = -1.0
        Image.fromarray(rng.integers(90, 170, (H, W, 3), dtype=np.uint8)).save(root / "captures" / "frames" / f"{i:06d}.jpg")
    (root / "captures" / "bundle.pb").write_bytes(b.SerializeToString())
    return root


def spec_answer(size=(1.0, 1.0, 1.0), colour="#8a6a4a", name="top") -> dict:
    """A valid Claude answer: a slab on four legs, inside the box."""
    sx, sy, sz = size
    return {"label": "table", "note": "invented", "materials": [{"name": "wood", "color": colour, "rough": 0.5}],
            "parts": [{"kind": "box", "name": name, "mat": "wood", "size": [sx, 0.1, sz], "at": [0, sy - 0.05, 0]},
                      {"kind": "box", "name": "body", "mat": "wood", "size": [sx * 0.9, sy - 0.1, sz * 0.9], "at": [0, (sy - 0.1) / 2, 0]}]}
