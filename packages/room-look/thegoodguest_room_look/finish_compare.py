"""Render-and-compare: pose the viewer's camera exactly where a real camera
frame was taken, render the finish, and set the two side by side.

    python tools/finish_compare.py poses outputs/scene-<id> --frames 58,296,383,444
        -> prints a JS snippet to run in the viewer page (browser console or
           the preview tool): it poses the camera for each frame, renders,
           and POSTs renders/frame_<id>.png to tools/serve_scene.py.
    python tools/finish_compare.py sheet outputs/scene-<id> --frames 58,296,383,444
        -> writes outputs/scene-<id>/renders/compare.png: photo | render
           per frame, turned upright by the frame's gravity.

This is the feedback step of the finish flow: look at the sheet (a person,
or a vision model asked "what differs from the photo?"), adjust
finish_hints.json or the drawing, re-derive, render again. RoomPlan's
geometry drifts a few centimetres, so compare structure and colour, not
pixels. The render has no furniture: wall/floor/trim only.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .finish_hints import parse_hints


def erode(mask, r: int):
    """Binary erosion by a (2r+1) square, without scipy."""
    import numpy as np

    m = mask.copy()
    for _ in range(r):
        n = m.copy()
        n[1:] &= m[:-1]
        n[:-1] &= m[1:]
        n[:, 1:] &= m[:, :-1]
        n[:, :-1] &= m[:, 1:]
        m = n
    return m


def _frames(scene: Path, ids: list[int]):
    from thegoodguest_schemas import CaptureBundle

    b = CaptureBundle()
    b.ParseFromString((scene / "captures" / "bundle.pb").read_bytes())
    by = {f.frame_index: f for f in b.frames}
    return [by[i] for i in ids]


def poses(scene: Path, ids: list[int], port: int) -> str:
    items = []
    for f in _frames(scene, ids):
        p, i = f.camera_pose, f.intrinsics
        items.append({
            "id": f.frame_index,
            "pos": [p.pos_x, p.pos_y, p.pos_z],
            "quat": [p.quat_x, p.quat_y, p.quat_z, p.quat_w],
            "fy": i.fy, "h": i.height, "w": i.width,
        })
    return (
        "window.__shellFinishView.harness.run(" + json.dumps(items) + f",{port})"
    )


def _srgb(v: int) -> int:
    """The id the PNG carries: the harness writes linear ids, the canvas
    encodes them as sRGB on the way out."""
    x = v / 255.0
    y = 12.92 * x if x <= 0.0031308 else 1.055 * x ** (1 / 2.4) - 0.055
    return round(y * 255)


REGIONS = {_srgb(k): n for k, n in {40: "paint", 80: "tile", 120: "floor", 160: "door", 200: "glass", 240: "casing"}.items()}


def calibrate(scene: Path, ids: list[int]) -> dict:
    """Per-region colour error between the real photos and the renders:
    for every region the id pass drew, the photo's dominant colour among
    pixels near the render's colour, minus the render's mean — in Lab, then
    the median over frames. Positive dL = the photo is lighter than the
    render. Also the lightness spread (std) of each, the texture-energy
    check for floors."""
    import numpy as np
    from PIL import Image
    from .shell_finish import mean_shift_mode, rgb_to_lab

    per: dict[str, list] = {}
    out_dir = scene / "renders"
    for f in _frames(scene, ids):
        rp, ip = out_dir / f"frame_{f.frame_index}.png", out_dir / f"ids_{f.frame_index}.png"
        if not (rp.exists() and ip.exists()):
            continue
        photo = Image.open(scene / "captures" / "frames" / Path(f.rgb_gcs_path).name).convert("RGB")
        size = (800, 600)
        photo_lab = rgb_to_lab(np.asarray(photo.resize(size, Image.BOX), float) / 255.0)
        rend = Image.open(rp).convert("RGBA").resize(size, Image.NEAREST)
        idm = np.asarray(Image.open(ip).convert("RGBA").resize(size, Image.NEAREST))
        rend_lab = rgb_to_lab(np.asarray(rend.convert("RGB"), float) / 255.0)
        for rid, name in REGIONS.items():
            mask = (idm[:, :, 3] > 200) & (np.abs(idm[:, :, 0].astype(int) - rid) < 6)
            mask = erode(mask, 4)
            if mask.sum() < 1500:
                continue
            r_mean = rend_lab[mask].mean(axis=0)
            ph = photo_lab[mask]
            c, n, frac = mean_shift_mode(ph, r_mean, delta_e=30.0)
            if frac < 0.12:
                continue
            near = ph[np.linalg.norm(ph - c, axis=1) < 30.0]
            per.setdefault(name, []).append({
                "frame": f.frame_index, "n": int(mask.sum()), "frac": round(frac, 2),
                "delta": (c - r_mean).tolist(), "photo_std_L": float(near[:, 0].std()),
                "render_std_L": float(rend_lab[mask][:, 0].std()),
            })
    summary = {}
    for name, rows in per.items():
        d = np.median(np.array([r["delta"] for r in rows]), axis=0)
        summary[name] = {
            "delta_lab": [round(float(x), 1) for x in d],
            "frames": len(rows),
            "photo_std_L": round(float(np.median([r["photo_std_L"] for r in rows])), 1),
            "render_std_L": round(float(np.median([r["render_std_L"] for r in rows])), 1),
        }
    return summary


def sheet(scene: Path, ids: list[int]) -> Path:
    import numpy as np
    from PIL import Image

    out_dir = scene / "renders"
    tiles = []
    for f in _frames(scene, ids):
        photo = Image.open(scene / "captures" / "frames" / Path(f.rgb_gcs_path).name).convert("RGB")
        r = out_dir / f"frame_{f.frame_index}.png"
        if not r.exists():
            continue
        rend = Image.open(r).convert("RGBA")
        bg = Image.new("RGBA", rend.size, (200, 200, 205, 255))
        rend = Image.alpha_composite(bg, rend).convert("RGB").resize(photo.size)
        g = np.array([f.gravity.x, f.gravity.y, f.gravity.z])
        # Gravity along the image's +x means down is to the right: turn clockwise.
        turn = -90 if g[0] > 0.5 else (90 if g[0] < -0.5 else 0)
        both = [im.rotate(turn, expand=True) if turn else im for im in (photo, rend)]
        w, h = both[0].size
        s = 600 / h
        both = [im.resize((int(w * s), 600)) for im in both]
        row = Image.new("RGB", (both[0].width * 2 + 8, 600), (255, 255, 255))
        row.paste(both[0], (0, 0))
        row.paste(both[1], (both[0].width + 8, 0))
        tiles.append(row)
    if not tiles:
        raise SystemExit("no renders found; run the poses snippet first")
    W = max(t.width for t in tiles)
    out = Image.new("RGB", (W, 608 * len(tiles)), (255, 255, 255))
    for k, t in enumerate(tiles):
        out.paste(t, (0, k * 608))
    path = out_dir / "compare.png"
    out.save(path)
    return path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["poses", "sheet", "calibrate"])
    ap.add_argument("scene", type=Path)
    ap.add_argument("--frames", required=True, help="comma-separated frame indices")
    ap.add_argument("--port", type=int, default=8791)
    ap.add_argument("--write", action="store_true", help="calibrate: fold the measured errors into <scene>/finish_hints.json")
    ap.add_argument("--strength", type=float, default=0.9, help="calibrate --write: share of the error applied per round")
    a = ap.parse_args()
    ids = [int(x) for x in a.frames.split(",")]
    if a.cmd == "poses":
        print(poses(a.scene, ids, a.port))
    elif a.cmd == "calibrate":
        summ = calibrate(a.scene, ids)
        print(json.dumps(summ, indent=2))
        if a.write:
            hp = a.scene / "finish_hints.json"
            hints = parse_hints(json.loads(hp.read_text())) if hp.exists() else {}
            cal = hints.setdefault("calibration", {"source": "measured"})
            for name, v in summ.items():
                if name == "casing" or v["frames"] < 2 and name != "door":
                    continue  # casing rings border other regions; one frame is an anecdote
                old = cal.get(name, [0, 0, 0])
                cal[name] = [round(o + a.strength * d, 1) for o, d in zip(old, v["delta_lab"])]
            fl = summ.get("floor")
            if fl and fl["render_std_L"] > 0:
                ratio = fl["photo_std_L"] / fl["render_std_L"]
                cal["texture_gain"] = round(cal.get("texture_gain", 1.0) * min(max(ratio, 0.5), 4.0) ** 0.7, 2)
            parse_hints(hints)  # never write a hints file the finish would refuse
            hp.write_text(json.dumps(hints, indent=2) + "\n")
            print("wrote", hp)
    else:
        print(sheet(a.scene, ids))


if __name__ == "__main__":
    main()
