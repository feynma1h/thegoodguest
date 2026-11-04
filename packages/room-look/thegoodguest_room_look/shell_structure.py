"""Structure measured from the atlases, assembled per wall: the paint above a
tiled band, the band's colour and top edge, and the colour of door/window
frames. Joint pitch is NOT inferred here — periodic-edge detection proved
unreliable under furniture clutter on the reference scan (see the hand-over
note) — so it comes from `finish_hints.json`, written after looking at the
atlases (by a person or a vision model), and is recorded as source "review".
"""
from __future__ import annotations

import warnings

import numpy as np

from . import shell_atlas as atl
from . import shell_measure as meas
from .shell_finish import lab_to_rgb, rgb_to_hex, rgb_to_lab, hex_to_rgb, wall_frame

warnings.simplefilter("ignore", category=RuntimeWarning)


def border_height(lab: np.ndarray, dv: float, lo=0.8, hi=1.9):
    """Top edge of a wainscot: a row where, across most of the wall's width,
    lightness steps by >3 L over 3 texels — a long unbroken horizontal line.
    Furniture makes edges in a few columns, a border line makes them in
    nearly all. Returns (height_m, score) or None."""
    d = lab[3:, :, 0] - lab[:-3, :, 0]
    fin = np.isfinite(d)
    best = None
    for r in range(int(lo / dv), min(int(hi / dv), len(d))):
        if fin[r].sum() < 0.25 * lab.shape[1]:
            continue
        score = float(((np.abs(d[r]) > 3.0) & fin[r]).sum() / fin[r].sum())
        if best is None or score > best[1]:
            best = (r, score)
    if best is None or best[1] < 0.6:
        return None
    return (best[0] + 1.5) * dv, best[1]


def measure(shell: dict, cams, hints: dict | None, paint_hint_hex: dict[int, str]):
    """Per wall: atlas-derived colours and structure. `paint_hint_hex` maps
    wall index -> the frame-sampled paint colour used to gate wall-like
    pixels."""
    hints = hints or {}
    walls = shell.get("walls", [])
    atlases, frames = [], []
    for w in walls:
        fr = wall_frame(np.array(w.get("polygon") or w.get("quad"), float))
        frames.append(fr)
        atlases.append(atl.wall_atlas(fr, cams) if fr else None)

    heights = []
    for a in atlases:
        if a is None:
            continue
        bh = border_height(a[0], a[3])
        if bh:
            heights.append(bh[0])
    h_auto = None
    if len(heights) >= 2 and np.ptp(heights) < 0.12:
        h_auto = float(np.median(heights))
    elif len(heights) == 1:
        h_auto = None  # one wall is not a consensus
    wain = hints.get("wainscot") or {}
    h_band = wain.get("height_m", h_auto)

    out = []
    for i, (w, fr, a) in enumerate(zip(walls, frames, atlases)):
        e = {"wall": i, "tile_lab": None, "paint_lab": None, "openings": []}
        if a is None or fr is None:
            out.append(e)
            continue
        lab, seen, du, dv = a
        seed = rgb_to_lab(hex_to_rgb(paint_hint_hex[i])) if i in paint_hint_hex else None
        wl = meas.wall_like(lab, seed, 16.0) if seed is not None else lab
        # Opening columns carry other materials; blank them out.
        for op in w.get("openings", []):
            (u0, v0), (u1, v1) = op["rect_uv"]
            wl[int(v0 * fr["h"] / dv) : int(v1 * fr["h"] / dv) + 1,
               int(u0 * fr["w"] / du) : int(u1 * fr["w"] / du) + 1] = np.nan
        if h_band:
            k = int(h_band / dv)
            e["tile_lab"] = meas.band_colour(wl, int(0.15 / dv), max(k - int(0.05 / dv), 1))
            e["paint_lab"] = meas.band_colour(wl, k + int(0.05 / dv), len(wl) - int(0.35 / dv))
        else:
            e["paint_lab"] = meas.band_colour(wl, int(0.3 / dv), len(wl) - int(0.35 / dv))
        for op in w.get("openings", []):
            (u0, v0), (u1, v1) = op["rect_uv"]
            rect_m = (u0 * fr["w"], u1 * fr["w"], v0 * fr["h"], v1 * fr["h"])
            e["openings"].append(opening_materials(lab, du, dv, rect_m, seed))
        out.append(e)
    return {"wainscot_height_auto": h_auto, "wainscot_height_candidates": heights, "walls": out}


def hex_of(lab) -> str | None:
    return None if lab is None else rgb_to_hex(lab_to_rgb(lab))


def opening_materials(lab: np.ndarray, du: float, dv: float, rect_m, wall_lab) -> dict:
    """What an opening is made of, from the pixels inside its rect: the
    dominant dark colour that is NOT the wall's hue is the leaf / sash
    (wood, painted steel), the bright pixels are glass or sky. Both are
    lifted a little toward the lit lightness. None where the rect was not
    seen well enough."""
    u0, u1, v0, v1 = rect_m
    sub = lab[int(v0 / dv) : int(v1 / dv), int(u0 / du) : int(u1 / du)].reshape(-1, 3)
    sub = sub[np.isfinite(sub[:, 0])]
    out = {"frame_lab": None, "glass_lab": None}
    if len(sub) < 150:
        return out
    if wall_lab is not None:
        off_wall = np.linalg.norm(sub[:, 1:] - wall_lab[1:], axis=1) > 18.0
    else:
        off_wall = np.ones(len(sub), bool)
    dark = sub[off_wall & (sub[:, 0] < 68)]
    if len(dark) >= 120:
        c, n, frac = meas.mean_shift_mode(dark, np.median(dark, axis=0), delta_e=14.0)
        out["frame_lab"] = meas.lit(dark, c, 75, delta_e=14.0)
    bright = sub[sub[:, 0] > 74]
    if len(bright) >= 120:
        out["glass_lab"] = np.median(bright, axis=0)
    return out
