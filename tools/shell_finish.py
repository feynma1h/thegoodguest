"""Derive a designed FINISH for a scan's room shell — offline, repeatable.

    python tools/shell_finish.py outputs/scene-<id>
    python tools/shell_finish.py --shell web/public/hero/room.json --no-frames

Reads shell.json (the pipeline's walls + floor + per-plane material +
openings), and when present the scene's camera bundle (captures/bundle.pb +
captures/frames/*.jpg), and writes `finish.json` next to the shell. The web
viewer's local-only finish override (web/src/lib/shellFinish.ts) draws it in
place of the flat wall/floor polygons: paint with a faint grain, soft corner
shading, baseboards, framed door/window openings, and the floor drawn per its
material family.

Nothing here changes the pipeline or its output; the pipeline's shell.json
is read-only input. No photo is baked: camera frames are only SAMPLED, to
check and refine each plane's colour, and the finish carries colours and
a few drawing parameters, never pixels.

What is measured vs assumed is written into the finish itself (`source`
fields and `checks`), so a viewer or a reviewer can tell. Dimensions of
trim (baseboard height, casing width) and slab/plank sizes are DESIGN
choices, marked `assumed`; the only observed things are colours, the
opening rectangles and the floor family.

Camera convention (ARKit, packages/schemas pose_math): world_from_camera
pose, camera looks down -Z, +X right, +Y up; intrinsics are for the
stored landscape image (the phone may have been held in portrait, which
is why frames look sideways when opened — projection is unaffected).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

from finish_hints import HintsError, parse_hints

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "packages/schemas"))

FINISH_VERSION = 2

# --- Design constants (assumed; they are the finish's taste, not the room's) --
BASEBOARD_H_M = 0.09
BASEBOARD_D_M = 0.014
CASING_W_M = 0.07
CASING_D_M = 0.016
TRIM_HEX = "#f3f1ec"  # soft warm white, the Apple-ish default
# Share of the measured wall-to-wall lightness spread kept. Walls in one room
# are one paint; their measured lightness differs mostly by daylight and
# shadow, so we keep a fraction of it for depth and not the whole swing.
LIGHTNESS_KEEP = 0.4
# A wall whose measured chroma is this far (Lab a,b distance) from the
# observation-weighted room consensus is treated as a bad measurement
# (a 2%-observed plane reading grey, say) and takes the consensus chroma.
CHROMA_OUTLIER = 14.0
# Mean-shift gate: a camera sample "agrees" with a plane's colour inside it.
AGREE_DELTA_E = 16.0
MIN_AGREE_SAMPLES = 400
WALL_LIT_PCT = 70
FLOOR_LIT_PCT = 65
DOOR_LIT_PCT = 75

STONE_SLAB_M = 0.6
WOOD_PLANK_M = 0.14
TILE_M = 0.6


# ----------------------------------------------------------------- colour --
def hex_to_rgb(h: str) -> np.ndarray:
    h = h.lstrip("#")
    return np.array([int(h[i : i + 2], 16) for i in (0, 2, 4)], dtype=float) / 255.0


def rgb_to_hex(rgb: np.ndarray) -> str:
    v = np.clip(np.round(np.asarray(rgb) * 255.0), 0, 255).astype(int)
    return "#{:02x}{:02x}{:02x}".format(*v)


def _lin(c: np.ndarray) -> np.ndarray:
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def _delin(c: np.ndarray) -> np.ndarray:
    c = np.clip(c, 0.0, 1.0)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * c ** (1 / 2.4) - 0.055)


_M = np.array(
    [[0.4124564, 0.3575761, 0.1804375],
     [0.2126729, 0.7151522, 0.0721750],
     [0.0193339, 0.1191920, 0.9503041]]
)
_WHITE = np.array([0.95047, 1.0, 1.08883])


def rgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    xyz = (_lin(np.asarray(rgb, dtype=float)) @ _M.T) / _WHITE
    f = np.where(xyz > 216 / 24389, np.cbrt(xyz), (24389 / 27 * xyz + 16) / 116)
    return np.stack(
        [116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])],
        axis=-1,
    )


def lab_to_rgb(lab: np.ndarray) -> np.ndarray:
    lab = np.asarray(lab, dtype=float)
    fy = (lab[..., 0] + 16) / 116
    fx = fy + lab[..., 1] / 500
    fz = fy - lab[..., 2] / 200
    f = np.stack([fx, fy, fz], axis=-1)
    xyz = np.where(f**3 > 216 / 24389, f**3, (116 * f - 16) / (24389 / 27)) * _WHITE
    return _delin(xyz @ np.linalg.inv(_M).T)


def shift_hex(hex_: str, delta) -> str:
    """A colour moved by a Lab offset (the render-compare calibration)."""
    lab = rgb_to_lab(hex_to_rgb(hex_)) + np.asarray(delta, float)
    lab[0] = float(np.clip(lab[0], 0, 100))
    return rgb_to_hex(lab_to_rgb(lab))


# ---------------------------------------------------------------- geometry --
def quat_to_matrix(q: tuple[float, float, float, float]) -> np.ndarray:
    x, y, z, w = q
    n = (x * x + y * y + z * z + w * w) ** 0.5
    x, y, z, w = x / n, y / n, z / n, w / n
    return np.array(
        [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
         [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
         [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]
    )


def wall_frame(polygon: np.ndarray) -> dict | None:
    """Mirror of web/src/lib/shell3d.ts wallFrame: interior normal from the
    winding (Newell), axis_u = up x n, origin at the bounding rect's min
    corner. Openings' rect_uv are normalized on this rect."""
    p = np.asarray(polygon, dtype=float)
    q = np.roll(p, -1, axis=0)
    n = np.array([
        np.sum((p[:, 1] - q[:, 1]) * (p[:, 2] + q[:, 2])),
        np.sum((p[:, 2] - q[:, 2]) * (p[:, 0] + q[:, 0])),
        np.sum((p[:, 0] - q[:, 0]) * (p[:, 1] + q[:, 1])),
    ])
    h = float(np.hypot(n[0], n[2]))
    if h < 1e-9:
        return None
    normal = np.array([n[0] / h, 0.0, n[2] / h])
    axis_u = np.array([normal[2], 0.0, -normal[0]])
    u = p[:, 0] * axis_u[0] + p[:, 2] * axis_u[2]
    width = float(u.max() - u.min())
    height = float(p[:, 1].max() - p[:, 1].min())
    if width < 1e-9 or height < 1e-9:
        return None
    u0 = p[0, 0] * axis_u[0] + p[0, 2] * axis_u[2]
    origin = np.array([
        p[0, 0] + (u.min() - u0) * axis_u[0],
        p[:, 1].min(),
        p[0, 2] + (u.min() - u0) * axis_u[2],
    ])
    return {"normal": normal, "axis_u": axis_u, "origin": origin, "w": width, "h": height}


def wall_grid(frame: dict, step_m: float, holes: list | None = None) -> np.ndarray:
    """World points on a regular grid over the wall's bounding rect, minus the
    openings (their colour is a different surface)."""
    us = np.arange(step_m / 2, frame["w"], step_m)
    vs = np.arange(step_m / 2, frame["h"], step_m)
    uu, vv = np.meshgrid(us, vs)
    keep = np.ones(uu.shape, bool)
    for (u0, v0), (u1, v1) in holes or []:
        keep &= ~((uu / frame["w"] >= u0) & (uu / frame["w"] <= u1)
                  & (vv / frame["h"] >= v0) & (vv / frame["h"] <= v1))
    uu, vv = uu[keep], vv[keep]
    return (frame["origin"][None, :] + uu[:, None] * frame["axis_u"][None, :]
            + vv[:, None] * np.array([0, 1.0, 0])[None, :])


def rect_grid(frame: dict, rect_uv, n: int = 14, shrink: float = 0.15) -> np.ndarray:
    (u0, v0), (u1, v1) = rect_uv
    du, dv = (u1 - u0) * shrink, (v1 - v0) * shrink
    us = np.linspace(u0 + du, u1 - du, n) * frame["w"]
    vs = np.linspace(v0 + dv, v1 - dv, n) * frame["h"]
    uu, vv = np.meshgrid(us, vs)
    uu, vv = uu.ravel(), vv.ravel()
    return (frame["origin"][None, :] + uu[:, None] * frame["axis_u"][None, :]
            + vv[:, None] * np.array([0, 1.0, 0])[None, :])


def floor_grid(polygon: np.ndarray, step_m: float) -> np.ndarray:
    p = np.asarray(polygon, dtype=float)
    xs = np.arange(p[:, 0].min(), p[:, 0].max(), step_m)
    zs = np.arange(p[:, 2].min(), p[:, 2].max(), step_m)
    xx, zz = np.meshgrid(xs, zs)
    pts = np.stack([xx.ravel(), np.full(xx.size, p[0, 1]), zz.ravel()], axis=1)
    inside = np.zeros(len(pts), bool)
    n = len(p)
    for i in range(n):  # even-odd ray cast in XZ
        a, b = p[i], p[(i + 1) % n]
        cond = (a[2] > pts[:, 2]) != (b[2] > pts[:, 2])
        with np.errstate(divide="ignore", invalid="ignore"):
            xint = (b[0] - a[0]) * (pts[:, 2] - a[2]) / (b[2] - a[2]) + a[0]
        inside ^= cond & (pts[:, 0] < xint)
    return pts[inside]


# ------------------------------------------------------------- camera data --
class Camera:
    """One frame: pose, intrinsics and (lazily) pixels."""

    def __init__(self, path: Path, pose, intr):
        self.path = path
        self.rot = quat_to_matrix((pose.quat_x, pose.quat_y, pose.quat_z, pose.quat_w))
        self.pos = np.array([pose.pos_x, pose.pos_y, pose.pos_z])
        self.fx, self.fy, self.cx, self.cy = intr.fx, intr.fy, intr.cx, intr.cy
        self.w, self.h = int(intr.width), int(intr.height)
        self._img: np.ndarray | None = None

    @property
    def image(self) -> np.ndarray:
        if self._img is None:
            from PIL import Image

            im = Image.open(self.path).convert("RGB")
            if im.size != (self.w, self.h):
                im = im.resize((self.w, self.h))
            self._img = np.asarray(im, dtype=np.uint8)  # uint8: 80 frames stay ~330 MB
        return self._img

    def project(self, pts: np.ndarray):
        """-> (px, py, depth, in_front_mask). ARKit: -Z forward, image y down."""
        c = (pts - self.pos[None, :]) @ self.rot  # world -> camera (R^T v)
        z = -c[:, 2]
        with np.errstate(divide="ignore", invalid="ignore"):
            px = self.fx * c[:, 0] / z + self.cx
            py = self.cy - self.fy * c[:, 1] / z
        return px, py, z, z > 0.15

    def sample(self, pts: np.ndarray, normal: np.ndarray | None, margin: int = 24):
        """Colours of the points this camera sees on a surface facing `normal`
        (None: horizontal floor, normal up). Grazing views (>72 deg off the
        normal) and image borders are skipped."""
        px, py, z, front = self.project(pts)
        ok = front & (px >= margin) & (px < self.w - margin) & (py >= margin) & (py < self.h - margin)
        n = np.array([0, 1.0, 0]) if normal is None else normal
        view = pts - self.pos[None, :]
        cosang = -(view @ n) / (np.linalg.norm(view, axis=1) + 1e-9)
        ok &= cosang > 0.3
        if not ok.any():
            return np.zeros((0, 3))
        ix, iy = px[ok].astype(int), py[ok].astype(int)
        return self.image[iy, ix].astype(np.float32) / 255.0


def load_cameras(scene: Path, max_frames: int = 80) -> list[Camera]:
    from thegoodguest_schemas import CaptureBundle

    bundle = scene / "captures" / "bundle.pb"
    frames_dir = scene / "captures" / "frames"
    if not bundle.exists() or not frames_dir.is_dir():
        return []
    b = CaptureBundle()
    b.ParseFromString(bundle.read_bytes())
    cams = []
    for f in b.frames:
        p = frames_dir / Path(f.rgb_gcs_path).name
        if p.exists():
            cams.append(Camera(p, f.camera_pose, f.intrinsics))
    if len(cams) > max_frames:
        idx = np.linspace(0, len(cams) - 1, max_frames).round().astype(int)
        cams = [cams[i] for i in sorted(set(idx))]
    return cams


# --------------------------------------------------------- colour inference --
def mean_shift_mode(lab: np.ndarray, seed: np.ndarray, delta_e: float = AGREE_DELTA_E):
    """Dominant colour near `seed`: iterate the median of samples within
    delta_e of the centre. Returns (centre_lab, agree_count, agree_fraction)."""
    c = np.asarray(seed, dtype=float)
    if len(lab) == 0:
        return c, 0, 0.0
    for _ in range(8):
        d = np.linalg.norm(lab - c[None, :], axis=1)
        near = lab[d < delta_e]
        if len(near) < 20:
            break
        nc = np.median(near, axis=0)
        if np.linalg.norm(nc - c) < 0.3:
            c = nc
            break
        c = nc
    d = np.linalg.norm(lab - c[None, :], axis=1)
    n = int((d < delta_e).sum())
    return c, n, n / len(lab)


def lit(lab: np.ndarray, centre: np.ndarray, pct: float, delta_e: float = AGREE_DELTA_E) -> np.ndarray:
    """The mode's chroma at the LIT lightness: paint under shade photographs
    darker than the paint is, so the finish takes the `pct`-th percentile of
    the lightness of the samples that agree with the colour, never the median
    that shadow drags down. Only ever lifts."""
    near = lab[np.linalg.norm(lab - centre[None, :], axis=1) < delta_e]
    out = np.asarray(centre, dtype=float).copy()
    if len(near):
        out[0] = max(out[0], float(np.percentile(near[:, 0], pct)))
    return out


def free_mode(lab: np.ndarray) -> np.ndarray:
    """Dominant colour with no seed: densest of a few random candidates."""
    rng = np.random.default_rng(0)
    cand = lab[rng.choice(len(lab), size=min(len(lab), 40), replace=False)]
    best, best_n = cand[0], -1
    for c in cand:
        n = int((np.linalg.norm(lab - c[None, :], axis=1) < AGREE_DELTA_E).sum())
        if n > best_n:
            best, best_n = c, n
    return mean_shift_mode(lab, best)[0]


def gather(cams: list[Camera], pts: np.ndarray, normal: np.ndarray | None) -> np.ndarray:
    out = [c.sample(pts, normal) for c in cams]
    out = [o for o in out if len(o)]
    return rgb_to_lab(np.concatenate(out)) if out else np.zeros((0, 3))


# -------------------------------------------------------------- derivation --
def _seed_for(scene_id: str | None, shell: dict) -> int:
    key = (scene_id or json.dumps(shell.get("floor", {}).get("polygon", []))).encode()
    return int.from_bytes(hashlib.sha256(key).digest()[:4], "big")


def derive_finish(shell: dict, cams: list[Camera], hints: dict | None = None) -> dict:
    hints = hints or {}
    walls = shell.get("walls", [])
    floor = shell.get("floor")
    scene_id = shell.get("scene_id")

    per_wall = []
    for i, w in enumerate(walls):
        poly = np.array(w["polygon"] if "polygon" in w else w["quad"], dtype=float)
        frame = wall_frame(poly)
        mat = w.get("material", {})
        measured = mat.get("albedo_hex")
        obs = float(mat.get("source", {}).get("observed_fraction") or 0.0)
        entry = {
            "i": i, "wall": w, "frame": frame, "measured": measured, "obs": obs,
            "lab": rgb_to_lab(hex_to_rgb(measured)) if measured else None,
            "sampled": None, "agree_n": 0, "agree_frac": 0.0, "n_samples": 0,
        }
        if frame is not None and cams and measured:
            holes = [o["rect_uv"] for o in w.get("openings", [])]
            lab = gather(cams, wall_grid(frame, 0.08, holes), frame["normal"])
            entry["n_samples"] = len(lab)
            if len(lab):
                c, n, frac = mean_shift_mode(lab, entry["lab"])
                entry["agree_n"], entry["agree_frac"] = n, frac
                if n >= MIN_AGREE_SAMPLES:
                    entry["sampled"] = lit(lab, c, WALL_LIT_PCT)
        per_wall.append(entry)

    def best_lab(e):
        return e["sampled"] if e["sampled"] is not None else e["lab"]

    # Room consensus: weight by how well each wall was actually seen.
    usable = [e for e in per_wall if best_lab(e) is not None]
    consensus = None
    if usable:
        wts = np.array([
            (e["agree_n"] if e["sampled"] is not None else 0) + 4000 * e["obs"] + 1
            for e in usable
        ], dtype=float)
        consensus = np.average(np.stack([best_lab(e) for e in usable]), axis=0, weights=wts)
        # Pick chroma by the best-seen walls, not an average dragged by a bad one:
        # weight-median of a,b over the walls.
        ab = np.stack([best_lab(e)[1:] for e in usable])
        order = np.argsort(wts)[::-1]
        sampled_L = [e["sampled"][0] for e in usable if e["sampled"] is not None]
        if sampled_L:
            consensus[0] = max(sampled_L)  # paint is as light as its best-lit wall
        consensus[1:] = ab[order[0]] if len(usable) == 1 else np.average(
            ab[order[: max(2, len(usable) // 2)]], axis=0, weights=wts[order[: max(2, len(usable) // 2)]]
        )

    wall_out = []
    for e in per_wall:
        w, lab = e["wall"], best_lab(e)
        if consensus is not None and lab is None:
            source, hex_ = "room_consensus", rgb_to_hex(lab_to_rgb(consensus))
        elif lab is None or consensus is None:
            source = "neutral"
            hex_ = "#e9e8e4"
        else:
            source = "frames+measured" if e["sampled"] is not None else "measured"
            lab = lab.copy()
            if np.linalg.norm(lab[1:] - consensus[1:]) > CHROMA_OUTLIER:
                lab[1:] = consensus[1:]
                source = "room_consensus_chroma"
            lab[0] = consensus[0] + (lab[0] - consensus[0]) * LIGHTNESS_KEEP
            hex_ = rgb_to_hex(lab_to_rgb(lab))
        fam = (w.get("material", {}) or {}).get("family")
        openings = []
        for k, op in enumerate(w.get("openings", [])):
            openings.append(_derive_opening(k, op, e["frame"], cams))
        wall_out.append({
            "wall_id": w.get("wall_id", f"wall_{e['i']:02d}"),
            "paint": {
                "hex": hex_,
                "source": source,
                "measured_hex": e["measured"],
                "sheen": 0.10,
                "grain": 0.03,
            },
            "pipeline_family": fam,
            "openings": openings,
        })

    structure = _structure(shell, cams, hints, wall_out)

    floor_out = None
    if floor and len(floor.get("polygon", [])) >= 3:
        floor_out = _derive_floor(floor, cams, _seed_for(scene_id, shell), hints.get("floor"))

    height = None
    if walls:
        h = [wall_frame(np.array(w.get("polygon") or w.get("quad")))["h"] for w in walls
             if wall_frame(np.array(w.get("polygon") or w.get("quad")))]
        height = round(float(np.median(h)), 3) if h else None

    finish = {
        "finish_version": FINISH_VERSION,
        "scene_id": scene_id,
        "wall_count": len(walls),
        "generator": {"tool": "tools/shell_finish.py", "frames_sampled": len(cams)},
        "room": {
            "height_m": height,
            "wall_consensus_hex": rgb_to_hex(lab_to_rgb(consensus)) if consensus is not None else None,
        },
        "trim": {
            "hex": TRIM_HEX,
            "baseboard_h_m": BASEBOARD_H_M,
            "baseboard_d_m": BASEBOARD_D_M,
            "casing_w_m": CASING_W_M,
            "casing_d_m": CASING_D_M,
            "assumed": True,
        },
        "walls": wall_out,
        "floor": floor_out,
        "checks": {
            "per_wall": [
                {
                    "wall_id": w["wall_id"],
                    "measured_hex": w["paint"]["measured_hex"],
                    "frame_samples": e["n_samples"],
                    "frame_agree_fraction": round(e["agree_frac"], 3),
                    "frame_mode_hex": rgb_to_hex(lab_to_rgb(e["sampled"])) if e["sampled"] is not None else None,
                    "final_hex": w["paint"]["hex"],
                    "source": w["paint"]["source"],
                }
                for w, e in zip(wall_out, per_wall)
            ],
        },
    }
    _calibrate(finish, hints.get("calibration") or {})
    return finish


def _calibrate(finish: dict, cal: dict) -> None:
    """Apply the render-compare offsets (finish_compare.py calibrate --write):
    each region's colour moves by the Lab error measured against the real
    photos. Offsets live in the hints' `calibration` so a re-derive keeps them."""
    for w in finish["walls"]:
        if "paint" in cal:
            w["paint"]["hex"] = shift_hex(w["paint"]["hex"], cal["paint"])
        wn = w.get("wainscot")
        if wn and "tile" in cal:
            for k in ("tile_hex", "joint_hex", "border_hex"):
                wn[k] = shift_hex(wn[k], cal["tile"])
        for op in w["openings"]:
            if op["kind"] == "door" and "door" in cal:
                for k in ("leaf_hex", "frame_hex", "casing_hex"):
                    if op.get(k):
                        op[k] = shift_hex(op[k], cal["door"])
            if op["kind"] == "window" and "glass" in cal and op.get("glass_hex"):
                op["glass_hex"] = shift_hex(op["glass_hex"], cal["glass"])
    fl = finish.get("floor")
    if fl:
        if "floor" in cal:
            fl["hex"] = shift_hex(fl["hex"], cal["floor"])
        g = float(cal.get("texture_gain", 1.0))
        st = fl["style"]
        st["mottle"] = round(min(st["mottle"] * g, 0.3), 3)
        st["speckle"] = round(min(st["speckle"] * g, 0.15), 3)
        st["texture_gain"] = g
    if cal:
        finish["calibration"] = {k: v for k, v in cal.items() if k != "source"}




def _structure(shell: dict, cams: list[Camera], hints: dict, wall_out: list[dict]) -> dict | None:
    """Merge atlas-measured structure (shell_structure) into the walls:
    paint above a tiled band, the band, openings' frame/glass colours.
    Mutates wall_out. Returns the measurement summary, or None with no frames."""
    if not cams:
        return None
    import shell_structure as ss

    m = ss.measure(shell, cams, hints, {i: w["paint"]["hex"] for i, w in enumerate(wall_out)})
    wh = hints.get("wainscot") or {}
    h = wh.get("height_m", m["wainscot_height_auto"])
    src = wh["source"] if "height_m" in wh else "frames"
    paints = [e["paint_lab"] for e in m["walls"] if e["paint_lab"] is not None]
    tiles = [e["tile_lab"] for e in m["walls"] if e["tile_lab"] is not None]
    paint_c = np.median(np.stack(paints), axis=0) if paints else None
    tile_c = np.median(np.stack(tiles), axis=0) if tiles else None
    for w, e in zip(wall_out, m["walls"]):
        if paint_c is not None:
            mine = e["paint_lab"] if e["paint_lab"] is not None else paint_c
            lab = paint_c.copy()
            lab[0] = paint_c[0] + (mine[0] - paint_c[0]) * 0.5
            w["paint"]["hex"], w["paint"]["source"] = rgb_to_hex(lab_to_rgb(lab)), "atlas"
        if h and tile_c is not None:
            mine = e["tile_lab"] if e["tile_lab"] is not None else tile_c
            lab = tile_c.copy()
            lab[0] = tile_c[0] + (mine[0] - tile_c[0]) * 0.5
            joint = lab.copy()
            joint[0] += 9.0 if wh.get("joint") == "light" else -7.0
            border = lab.copy()
            border[0] = min(border[0] + 12.0, 96.0)
            w["wainscot"] = {
                "height_m": round(float(h), 3),
                "tile_hex": rgb_to_hex(lab_to_rgb(lab)),
                "joint_hex": rgb_to_hex(lab_to_rgb(joint)),
                "border_hex": rgb_to_hex(lab_to_rgb(border)),
                "tile_u_m": wh.get("tile_u_m"),
                "tile_v_m": wh.get("tile_v_m"),
                "source": src,
                "pitch_source": wh["source"] if wh.get("tile_u_m") else None,
            }
        for op, om in zip(w["openings"], e["openings"]):
            fl, gl = om["frame_lab"], om["glass_lab"]
            if fl is not None:
                op["frame_hex"] = rgb_to_hex(lab_to_rgb(fl))
                if op["kind"] == "door":
                    op["leaf_hex"], op["source"] = op["frame_hex"], "frames"
            if gl is not None and op["kind"] == "window":
                op["glass_hex"] = rgb_to_hex(lab_to_rgb(gl))
            oh = (hints.get("openings") or {}).get(op["kind"]) or {}
            if oh.get("glass_hex"):
                op["glass_hex"] = oh["glass_hex"]  # what the pane actually shows
            if oh:
                op["hint_source"] = oh["source"]
            if oh.get("panels"):
                op["panels"] = oh["panels"]
            mode = oh.get("casing", "frame")
            if mode == "frame":
                op["casing_hex"] = op.get("frame_hex")
            elif isinstance(mode, str) and mode.startswith("#"):
                op["casing_hex"] = mode
            else:
                op["casing_hex"] = None
    for w in wall_out:
        bb = (hints.get("baseboard") or {})
        w["baseboard"] = ({"hex": bb.get("hex", TRIM_HEX), "height_m": bb.get("height_m", BASEBOARD_H_M), "source": bb["source"]}
                          if bb.get("present") else None)
    return {"wainscot_height_candidates": m["wainscot_height_candidates"], "wainscot_height_auto": m["wainscot_height_auto"]}


def _derive_opening(k: int, op: dict, frame: dict | None, cams: list[Camera]) -> dict:
    kind = op.get("classification", "opening")
    out = {"index": k, "kind": kind, "leaf_hex": None, "source": "default"}
    default = {"door": "#8a6a4a", "window": "#c3cfdb"}.get(kind, "#d8d6d0")
    out["leaf_hex"] = default
    # A window shows whatever is behind it that day (curtains, an AC unit):
    # not part of the room's finish, so it stays a soft neutral glass. Doors
    # are what they are, so the leaf takes the observed colour.
    if kind == "door" and frame is not None and cams:
        lab = gather(cams, rect_grid(frame, op["rect_uv"]), frame["normal"])
        if len(lab) >= 120:
            c = lit(lab, free_mode(lab), DOOR_LIT_PCT)
            c[0] = float(np.clip(c[0], 18, 82))  # keep it a leaf, not a glare or a hole
            out["leaf_hex"], out["source"] = rgb_to_hex(lab_to_rgb(c)), "frames"
    return out


def _derive_floor(floor: dict, cams: list[Camera], seed: int, hints: dict | None = None) -> dict:
    mat = floor.get("material", {})
    fam = mat.get("family")
    measured = mat.get("albedo_hex")
    poly = np.array(floor["polygon"], dtype=float)
    hex_, source, mottle, speckle = measured or "#cfcdc8", "measured" if measured else "neutral", 0.05, 0.0
    check = {"measured_hex": measured, "frame_samples": 0, "frame_agree_fraction": 0.0, "frame_mode_hex": None}
    if cams and measured:
        lab = gather(cams, floor_grid(poly, 0.06), None)
        check["frame_samples"] = len(lab)
        if len(lab):
            c, n, frac = mean_shift_mode(lab, rgb_to_lab(hex_to_rgb(measured)), delta_e=22.0)
            check["frame_agree_fraction"] = round(frac, 3)
            if n >= MIN_AGREE_SAMPLES:
                c = lit(lab, c, FLOOR_LIT_PCT, 22.0)
                hex_, source = rgb_to_hex(lab_to_rgb(c)), "frames+measured"
                check["frame_mode_hex"] = hex_
                # Observed spread of lightness around the mode, calmed: it is
                # how much the stone mottles, and the finish shows a fraction.
                near = lab[np.linalg.norm(lab - c[None, :], axis=1) < 22.0]
                mottle = float(np.clip(np.std(near[:, 0]) / 100.0 * 0.8, 0.02, 0.08))
                dark = lab[(lab[:, 0] < c[0] - 12)]
                speckle = float(np.clip(len(dark) / max(len(lab), 1) * 0.6, 0.0, 0.05))
    style = {"kind": fam or "plain", "mottle": round(mottle, 3), "speckle": round(speckle, 3), "seed": seed}
    if fam == "wood":
        style.update(plank_w_m=WOOD_PLANK_M, plank_dir_deg=(mat.get("params") or {}).get("plank_direction_deg", 0), assumed_dims=True)
    elif fam in ("stone", "tile"):
        base = STONE_SLAB_M if fam == "stone" else TILE_M
        h = hints or {}
        style.update(
            slab_u_m=h.get("slab_u_m", base),
            slab_v_m=h.get("slab_v_m", base),
            assumed_dims=not h.get("slab_u_m"),
            dims_source=h["source"] if h.get("slab_u_m") else "assumed",
        )
    return {
        "hex": hex_,
        "source": source,
        "family": fam,
        "family_confidence": mat.get("family_confidence"),
        "roughness": mat.get("render", {}).get("roughness"),
        "style": style,
        "check": check,
    }


# --------------------------------------------------------------------- CLI --
def debug_overlay(scene: Path, shell: dict, cams: list[Camera], out_dir: Path, n: int = 4) -> list[Path]:
    """Frames with the shell's wall outlines + floor polygon projected on top:
    a visual proof the camera model lines up with the geometry."""
    from PIL import Image, ImageDraw

    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    picks = [cams[i] for i in np.linspace(0, len(cams) - 1, n).round().astype(int)] if cams else []
    for cam in picks:
        im = Image.fromarray(cam.image)
        d = ImageDraw.Draw(im)
        polys = [(np.array(w.get("polygon") or w.get("quad")), (255, 0, 80)) for w in shell.get("walls", [])]
        if shell.get("floor"):
            polys.append((np.array(shell["floor"]["polygon"]), (0, 200, 80)))
        for poly, col in polys:
            # Densify edges so a polygon crossing the camera plane clips sanely.
            pts = []
            for a, b in zip(poly, np.roll(poly, -1, axis=0)):
                pts.extend(a + (b - a) * t for t in np.linspace(0, 1, 24, endpoint=False))
            px, py, z, front = cam.project(np.array(pts))
            for x, y, ok in zip(px, py, front):
                if ok and -50 < x < cam.w + 50 and -50 < y < cam.h + 50:
                    d.ellipse([x - 4, y - 4, x + 4, y + 4], fill=col)
        p = out_dir / f"{cam.path.stem}.jpg"
        im.resize((cam.w // 3, cam.h // 3)).save(p, quality=85)
        paths.append(p)
    return paths


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scene", nargs="?", type=Path, help="scene dir with shell.json (+ captures/)")
    ap.add_argument("--shell", type=Path, help="shell.json (or an assets json with a `shell` key); default <scene>/shell.json")
    ap.add_argument("--out", type=Path, help="default <scene>/finish.json, or ./finish.json with --shell")
    ap.add_argument("--no-frames", action="store_true", help="derive from the shell alone (no camera check)")
    ap.add_argument("--max-frames", type=int, default=80)
    ap.add_argument("--debug-dir", type=Path, help="write frames with the shell projected on them (and the analysis atlases)")
    ap.add_argument("--hints", type=Path, help="reviewed structure, validated by finish_hints.py (default <scene>/finish_hints.json if present)")
    args = ap.parse_args()
    if not args.scene and not args.shell:
        ap.error("give a scene dir or --shell")

    shell_path = args.shell or args.scene / "shell.json"
    doc = json.loads(shell_path.read_text())
    shell = doc.get("shell", doc) if "walls" not in doc else doc
    cams = [] if args.no_frames or not args.scene else load_cameras(args.scene, args.max_frames)

    hints_path = args.hints or ((args.scene / "finish_hints.json") if args.scene else None)
    try:
        hints = parse_hints(json.loads(hints_path.read_text())) if hints_path and hints_path.exists() else None
    except HintsError as exc:
        ap.error(f"{hints_path}: {exc}")
    finish = derive_finish(shell, cams, hints)
    if hints:
        finish["hints"] = hints
    out = args.out or ((args.scene / "finish.json") if args.scene else Path("finish.json"))
    out.write_text(json.dumps(finish, indent=2) + "\n")
    print(f"wrote {out}  ({len(cams)} frames sampled)")
    for c in finish["checks"]["per_wall"]:
        print(f"  {c['wall_id']}: measured {c['measured_hex']} frames {c['frame_mode_hex']} "
              f"(agree {c['frame_agree_fraction']:.0%} of {c['frame_samples']}) -> {c['final_hex']} [{c['source']}]")
    if finish["floor"]:
        f = finish["floor"]
        print(f"  floor: {f['family']} measured {f['check']['measured_hex']} frames {f['check']['frame_mode_hex']} -> {f['hex']} [{f['source']}]")
    if args.debug_dir and cams:
        for p in debug_overlay(args.scene, shell, cams, args.debug_dir):
            print("  debug", p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
