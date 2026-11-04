"""Measurements taken from the rectified atlases (shell_atlas.py).

Each function turns a picture of a plane into a few NUMBERS the finish can
draw from: where a tiled band meets paint, the tile pitch and joint phase,
whether a strip at the foot of a wall is a baseboard, what colour the frame
around an opening is, how a floor's slabs are laid. A measurement that is not
clear enough returns None and the finish draws nothing for it — never a guess
that the scan did not support.

Lab arrays are (rows, cols, 3) with row 0 at the plane's v=0 edge (wall foot)
for walls; NaN = unseen.
"""
from __future__ import annotations

import numpy as np

from .shell_finish import AGREE_DELTA_E, lit, mean_shift_mode


def _interp_nan(x: np.ndarray) -> np.ndarray:
    x = x.copy()
    ok = np.isfinite(x[:, 0])
    if ok.sum() < 3:
        return x
    idx = np.arange(len(x))
    for c in range(x.shape[1]):
        x[:, c] = np.interp(idx, idx[ok], x[ok, c])
    return x


def wall_like(lab: np.ndarray, paint_lab: np.ndarray, chroma_tol: float = 14.0) -> np.ndarray:
    """Atlas with everything that is not the wall's own hue set to NaN:
    furniture, curtains and floor bleed are grey or another colour, while
    paint and tile share one hue (they differ mostly in lightness). Gating on
    chroma direction only keeps both."""
    d = np.linalg.norm(lab[:, :, 1:] - paint_lab[None, None, 1:], axis=2)
    out = lab.copy()
    out[~(d < chroma_tol)] = np.nan
    return out


def row_profile(lab: np.ndarray, min_frac: float = 0.15) -> np.ndarray:
    """Median Lab per row; rows seen across <min_frac of their width are NaN."""
    fin = np.isfinite(lab[:, :, 0])
    prof = np.full((lab.shape[0], 3), np.nan)
    for r in range(lab.shape[0]):
        if fin[r].mean() >= min_frac:
            prof[r] = np.median(lab[r][fin[r]], axis=0)
    return prof


def step_height(lab: np.ndarray, dv: float, lo_m: float = 0.45, hi_m: float = 1.8):
    """Where a wall changes from one finish to another going up: the split of
    the row profile into two flat levels with the least squared error.
    Returns (height_m, delta_e, below_mean_lab, above_mean_lab) or None."""
    prof = row_profile(lab)
    seen = np.isfinite(prof[:, 0])
    if seen.sum() < 20:
        return None
    p = _interp_nan(prof)
    # Keep the cut away from the wall's very foot and head (shadow gradients).
    r0, r1 = int(0.06 / dv), len(p) - int(0.3 / dv)
    best = None
    for k in range(int(lo_m / dv), min(int(hi_m / dv), r1 - 10)):
        a, b = p[r0:k], p[k + 2 : r1]
        if len(a) < 8 or len(b) < 8:
            continue
        sse = ((a - a.mean(0)) ** 2).sum() + ((b - b.mean(0)) ** 2).sum()
        if best is None or sse < best[0]:
            best = (sse, k, a.mean(0), b.mean(0))
    if best is None:
        return None
    _, k, below, above = best
    # Each side must actually have been seen, not interpolated across a gap.
    if seen[r0:k].mean() < 0.5 or seen[k + 2 : r1].mean() < 0.3:
        return None
    return k * dv, float(np.linalg.norm(below - above)), below, above


def band_colour(lab: np.ndarray, r0: int, r1: int, pct: float = 70) -> np.ndarray | None:
    """Dominant colour of rows [r0, r1): mean-shift mode (furniture and
    shadow fall outside it), lifted to the lit lightness."""
    px = lab[r0:r1].reshape(-1, 3)
    px = px[np.isfinite(px[:, 0])]
    if len(px) < 300:
        return None
    c, n, frac = mean_shift_mode(px, np.median(px, axis=0), delta_e=10.0)
    if frac < 0.15:
        return None
    return lit(px, c, pct, delta_e=10.0)


def _autocorr_peak(sig: np.ndarray, step: float, lo: float, hi: float):
    """(lag_m, strength 0..1) of the strongest periodicity in a 1-D signal."""
    s = np.asarray(sig, float)
    ok = np.isfinite(s)
    if ok.sum() < 20:
        return None
    s = np.where(ok, s, np.nanmean(s))
    k = max(3, int(0.1 / step) | 1)
    s = s - np.convolve(s, np.ones(k) / k, mode="same")  # drop slow trend
    s = s - s.mean()
    var = (s * s).sum()
    if var < 1e-9:
        return None
    ac = np.correlate(s, s, mode="full")[len(s) - 1 :] / var
    a, b = int(lo / step), min(int(hi / step), len(ac) - 2)
    if b <= a + 2:
        return None
    seg = ac[a:b]
    j = int(np.argmax(seg))
    return (a + j) * step, float(seg[j])


def tile_joints(lab: np.ndarray, du: float, dv: float, r0: int, r1: int, holes: np.ndarray | None = None):
    """Joint pitch (u, v), phase and contrast inside rows [r0, r1) of a wall
    atlas. Joints are thin lines, so they show as periodic spikes in the
    lightness gradient. Returns a dict, or None when the lines are not
    clearly periodic in both directions."""
    L = lab[r0:r1, :, 0].copy()
    if holes is not None:
        L[holes[r0:r1]] = np.nan
    gv = np.nanmean(np.abs(L[2:] - L[:-2]), axis=1)  # per row: horizontal joints
    gu = np.nanmean(np.abs(L[:, 2:] - L[:, :-2]), axis=0)  # per col: vertical joints
    pv = _autocorr_peak(gv, dv, 0.12, 0.7)
    pu = _autocorr_peak(gu, du, 0.12, 0.7)
    if not pv or not pu or min(pv[1], pu[1]) < 0.22:
        return None

    def phase(sig, step, pitch):
        # Offset of the strongest joint within one pitch, by folding.
        n = int(round(pitch / step))
        if n < 4:
            return 0.0
        idx = (np.arange(len(sig)) % n)
        fold = np.array([np.nanmean(sig[idx == i]) if (idx == i).any() else 0.0 for i in range(n)])
        return float(np.argmax(fold) * step)

    # Contrast: how much darker/lighter the joint rows are than the tile.
    return {
        "pitch_u_m": round(pu[0], 3),
        "pitch_v_m": round(pv[0], 3),
        "strength": round(min(pu[1], pv[1]), 2),
        "phase_u_m": round(phase(gu, du, pu[0]), 3),
        "phase_v_m": round(phase(gv, dv, pv[0]), 3),
    }


def foot_strip(lab: np.ndarray, dv: float, wall_lab: np.ndarray | None):
    """Is there a baseboard? A strip of constant colour at the wall's foot,
    distinct from the wall just above it. Returns {height_m, lab} or None."""
    prof = _interp_nan(row_profile(lab))
    if not np.isfinite(prof[:, 0]).all() or len(prof) < int(0.4 / dv):
        return None
    n = len(prof)
    for h in np.arange(0.05, 0.16, 0.01):
        k = int(h / dv)
        strip, above = prof[1:k], prof[k + 1 : k + 1 + int(0.08 / dv)]
        if len(strip) < 2 or len(above) < 3:
            continue
        if np.linalg.norm(strip.mean(0) - above.mean(0)) > 9.0 and strip.std(0).max() < 4.0:
            return {"height_m": round(float(h), 3), "lab": strip.mean(0)}
    return None


def ring_colour(lab: np.ndarray, du: float, dv: float, rect_m, width_m: float = 0.07, pad_m: float = 0.0):
    """Colour of the frame around an opening: a band of `width_m` just
    OUTSIDE the rect (casing sits outside the cut) — and, separately, just
    inside it (a window's sash)."""
    u0, u1, v0, v1 = rect_m
    H, W = lab.shape[:2]
    mask = np.zeros((H, W), bool)
    a0, a1 = int((u0 - width_m - pad_m) / du), int((u1 + width_m + pad_m) / du)
    b0, b1 = int(max(v0 - width_m, 0) / dv), int((v1 + width_m + pad_m) / dv)
    ia0, ia1 = int((u0 - pad_m) / du), int((u1 + pad_m) / du)
    ib0, ib1 = int((v0 - pad_m) / dv), int((v1 + pad_m) / dv)
    mask[max(b0, 0) : min(b1, H), max(a0, 0) : min(a1, W)] = True
    mask[max(ib0, 0) : min(ib1, H), max(ia0, 0) : min(ia1, W)] = False
    px = lab[mask]
    px = px[np.isfinite(px[:, 0])]
    if len(px) < 120:
        return None
    c, n, frac = mean_shift_mode(px, np.median(px, axis=0), delta_e=10.0)
    return c if frac > 0.2 else None


def rect_core_colour(lab: np.ndarray, du: float, dv: float, rect_m, shrink: float = 0.12):
    u0, u1, v0, v1 = rect_m
    H, W = lab.shape[:2]
    px = lab[int((v0 + (v1 - v0) * shrink) / dv) : int((v1 - (v1 - v0) * shrink) / dv),
             int((u0 + (u1 - u0) * shrink) / du) : int((u1 - (u1 - u0) * shrink) / du)].reshape(-1, 3)
    px = px[np.isfinite(px[:, 0])]
    if len(px) < 100:
        return None
    c, n, frac = mean_shift_mode(px, np.median(px, axis=0), delta_e=14.0)
    return c


def floor_slabs(lab: np.ndarray, res: float):
    """Slab joint pitch/phase along the atlas's two axes, from joint spikes
    in the lightness gradient; per-slab tone from the detected grid."""
    L = lab[:, :, 0]
    gx = np.nanmean(np.abs(L[:, 2:] - L[:, :-2]), axis=0)
    gy = np.nanmean(np.abs(L[2:, :] - L[:-2, :]), axis=1)
    px = _autocorr_peak(gx, res, 0.3, 1.0)
    py = _autocorr_peak(gy, res, 0.3, 1.0)
    return px, py
