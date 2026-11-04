"""Rectified ANALYSIS atlases of a scan's walls and floor — measurement only.

For each shell plane, every camera frame that sees it is projected onto the
plane's own (u, v) grid and the per-texel MEDIAN across frames is kept (so a
chair that hides the wall in a few frames drops out). The result is a
fronto-parallel picture of the plane as the camera saw it. The finish
derivation (shell_finish.py) MEASURES things from it — where a tiled band
meets paint, the tile pitch and joint phase, the colour of a baseboard strip
or a door casing, a floor's slab joints — and writes those numbers, never
the atlas, into finish.json. Atlases are written to --debug-dir for a human
(or a vision model) to look at, and nowhere else: no pixels ship, which is
what keeps the no-photo-bake ruling intact.

Everything is in Lab; NaN marks a texel no frame saw.
"""
from __future__ import annotations

import numpy as np

from shell_finish import Camera, rgb_to_lab

RES_M = 0.015  # atlas texel size, metres
REDUCE = 4  # frames are box-averaged 4x before sampling (a texel is ~4 px)


def _small(cam: Camera) -> np.ndarray:
    """The frame, box-reduced, cached on the camera (uint8)."""
    s = getattr(cam, "_small", None)
    if s is None:
        h, w = cam.h // REDUCE * REDUCE, cam.w // REDUCE * REDUCE
        img = cam.image[:h, :w].astype(np.float32)
        s = img.reshape(h // REDUCE, REDUCE, w // REDUCE, REDUCE, 3).mean(axis=(1, 3))
        cam._small = s.astype(np.uint8)
        cam._img = None  # release the full frame
    return s


def _gather_atlas(cams: list[Camera], pts: np.ndarray, normal: np.ndarray, min_cos=0.35, margin=6):
    """Per-camera colours for each point -> median Lab over cameras, plus
    the number of cameras that saw each point."""
    n = len(pts)
    stack = np.full((len(cams), n, 3), np.nan, np.float32)
    for k, cam in enumerate(cams):
        px, py, z, front = cam.project(pts)
        px, py = px / REDUCE, py / REDUCE
        small = _small(cam)
        hh, ww = small.shape[:2]
        ok = front & (px >= margin) & (px < ww - margin) & (py >= margin) & (py < hh - margin)
        view = pts - cam.pos[None, :]
        cos = -(view @ normal) / (np.linalg.norm(view, axis=1) + 1e-9)
        ok &= cos > min_cos
        if ok.any():
            rgb = small[py[ok].astype(int), px[ok].astype(int)].astype(np.float32) / 255.0
            stack[k, ok] = rgb_to_lab(rgb)
    seen = np.isfinite(stack[:, :, 0]).sum(axis=0)
    with np.errstate(all="ignore"):
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=RuntimeWarning)
            med = np.nanmedian(stack, axis=0)
    med[seen < 2] = np.nan  # one sighting is an anecdote, not a measurement
    return med, seen


def wall_atlas(frame: dict, cams: list[Camera]):
    """(H, W, 3) Lab atlas of a wall, row 0 = FLOOR edge (v up), plus seen
    counts. u runs along axis_u from the wall's bounding-rect left."""
    nw = max(8, int(round(frame["w"] / RES_M)))
    nh = max(8, int(round(frame["h"] / RES_M)))
    us = (np.arange(nw) + 0.5) * frame["w"] / nw
    vs = (np.arange(nh) + 0.5) * frame["h"] / nh
    uu, vv = np.meshgrid(us, vs)
    pts = (frame["origin"][None, :] + uu.reshape(-1, 1) * frame["axis_u"][None, :]
           + vv.reshape(-1, 1) * np.array([0, 1.0, 0])[None, :])
    med, seen = _gather_atlas(cams, pts, frame["normal"])
    return med.reshape(nh, nw, 3), seen.reshape(nh, nw), frame["w"] / nw, frame["h"] / nh


def floor_atlas(polygon: np.ndarray, cams: list[Camera], angle: float):
    """(H, W, 3) Lab atlas of the floor in a frame rotated by `angle` (the
    room's dominant edge): x along it, y across it. Texels outside the
    polygon are NaN. Returns atlas, seen, texel size, and the (cos, sin,
    x0, y0) transform from atlas to world."""
    p = np.asarray(polygon, float)
    c, s = np.cos(angle), np.sin(angle)
    along = p[:, 0] * c + p[:, 2] * s
    across = -p[:, 0] * s + p[:, 2] * c
    x0, x1, y0, y1 = along.min(), along.max(), across.min(), across.max()
    nw, nh = int(np.ceil((x1 - x0) / RES_M)), int(np.ceil((y1 - y0) / RES_M))
    xs = x0 + (np.arange(nw) + 0.5) * RES_M
    ys = y0 + (np.arange(nh) + 0.5) * RES_M
    xx, yy = np.meshgrid(xs, ys)
    wx = xx * c - yy * s
    wz = xx * s + yy * c
    pts = np.stack([wx.ravel(), np.full(wx.size, p[0, 1]), wz.ravel()], axis=1)
    inside = np.zeros(len(pts), bool)
    n = len(p)
    for i in range(n):
        a, b = p[i], p[(i + 1) % n]
        cond = (a[2] > pts[:, 2]) != (b[2] > pts[:, 2])
        with np.errstate(divide="ignore", invalid="ignore"):
            xint = (b[0] - a[0]) * (pts[:, 2] - a[2]) / (b[2] - a[2]) + a[0]
        inside ^= cond & (pts[:, 0] < xint)
    med, seen = _gather_atlas(cams, pts, np.array([0, 1.0, 0]), min_cos=0.3)
    med[~inside] = np.nan
    return med.reshape(nh, nw, 3), seen.reshape(nh, nw), (x0, y0), (c, s)


def save_png(lab: np.ndarray, path, flip_v: bool = False) -> None:
    """Write a Lab atlas as an sRGB PNG (NaN = magenta), v-up if flip_v."""
    from PIL import Image

    from shell_finish import lab_to_rgb

    filled = np.nan_to_num(lab, nan=0.0)
    rgb = (lab_to_rgb(filled) * 255).clip(0, 255).astype(np.uint8)
    rgb[~np.isfinite(lab[:, :, 0])] = (255, 0, 255)
    if flip_v:
        rgb = rgb[::-1]
    Image.fromarray(rgb).save(path)
