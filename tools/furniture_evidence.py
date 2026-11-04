"""Step 1 of the furniture-twin flow: find the frames that show each piece
well, and cut upright crops of it for a vision model (Claude) to read.

    python tools/furniture_evidence.py outputs/scene-<id>            # all objects
    python tools/furniture_evidence.py outputs/scene-<id> --only box_0 --top 6

Per box (boxes.json; windows and doors from the shell) it projects the 8 corners into every camera frame
and scores the frame on what a modeller needs: the box fully in view, big in
the image, close to square-on, sharp (Laplacian variance of the crop), and
a different viewpoint from the frames already chosen. It writes, outside git,
`<scene>/furniture/evidence/<obj>/` with upright crops + `evidence.json`
(frame ids, scores, distance, azimuth) — the measured part. What the piece
looks like (material, details) is read off those crops by Claude afterwards.

Occlusion is not measured here (a box has no visibility); a crop that is
mostly something else standing in front is rejected by the reader, and the
spread-of-viewpoints rule makes that cheap.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "packages/schemas"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from furniture_boxes import box_corners, load_boxes


def upright_turn(gravity) -> int:
    """PIL rotate() degrees that make a stored (sideways) frame upright."""
    g = np.array([gravity.x, gravity.y, gravity.z])
    return -90 if g[0] > 0.5 else (90 if g[0] < -0.5 else 0)


def sharpness(gray: np.ndarray) -> float:
    lap = (-4 * gray[1:-1, 1:-1] + gray[:-2, 1:-1] + gray[2:, 1:-1] + gray[1:-1, :-2] + gray[1:-1, 2:])
    return float(lap.var())


def score_frames(scene: Path, obj: dict, step: int = 1, min_in: float = 0.55) -> list[dict]:
    from PIL import Image
    from shell_finish import load_cameras

    cams = load_cameras(scene, max_frames=10_000)
    corners, centre, rot = box_corners(obj)
    from thegoodguest_schemas import CaptureBundle

    b = CaptureBundle()
    b.ParseFromString((scene / "captures" / "bundle.pb").read_bytes())
    grav = {Path(f.rgb_gcs_path).name: f.gravity for f in b.frames}
    idx = {Path(f.rgb_gcs_path).name: f.frame_index for f in b.frames}
    rows = []
    for cam in cams[::step]:
        px, py, z, front = cam.project(corners)
        if not front.all():
            continue
        x0, x1, y0, y1 = px.min(), px.max(), py.min(), py.max()
        inside = max(min(x1, cam.w) - max(x0, 0), 0) * max(min(y1, cam.h) - max(y0, 0), 0)
        area = (x1 - x0) * (y1 - y0)
        frac_in = inside / area if area > 0 else 0
        if frac_in < min_in:
            continue
        cover = inside / (cam.w * cam.h)
        view = cam.pos - centre
        dist = float(np.linalg.norm(view))
        az = float(np.degrees(np.arctan2(view[0], view[2])))
        rows.append({
            "frame": idx[cam.path.name], "file": cam.path.name, "cover": round(cover, 3), "in_frame": round(float(frac_in), 2), "dist_m": round(dist, 2),
            "azimuth_deg": round(az, 1), "elev_deg": round(float(np.degrees(np.arcsin(view[1] / dist))), 1),
            "bbox": [float(x0), float(y0), float(x1), float(y1)], "turn": upright_turn(grav[cam.path.name]),
        })
    # Sharpness only for the plausible ones (decoding 499 jpgs is slow).
    rows.sort(key=lambda r: -r["cover"])
    for r in rows[:60]:
        im = Image.open(scene / "captures" / "frames" / r["file"]).convert("L")
        x0, y0, x1, y1 = [int(v) for v in r["bbox"]]
        crop = np.asarray(im.crop((max(x0, 0), max(y0, 0), x1, y1)), float)
        r["sharp"] = round(sharpness(crop), 1) if min(crop.shape) > 8 else 0.0
    rows = [r for r in rows if "sharp" in r]
    smax = max((r["sharp"] for r in rows), default=1) or 1
    for r in rows:
        r["score"] = round(r["cover"] * r["in_frame"] ** 2 * (0.4 + 0.6 * r["sharp"] / smax), 4)
    return rows


def pick_spread(rows: list[dict], k: int, min_sep_deg: float = 15.0) -> list[dict]:
    chosen: list[dict] = []
    for r in sorted(rows, key=lambda r: -r["score"]):
        if all(abs((r["azimuth_deg"] - c["azimuth_deg"] + 180) % 360 - 180) >= min_sep_deg for c in chosen):
            chosen.append(r)
        if len(chosen) >= k:
            break
    return chosen


def write_crops(scene: Path, name: str, picks: list[dict], pad: float = 0.12) -> None:
    from PIL import Image

    out = scene / "furniture" / "evidence" / name
    out.mkdir(parents=True, exist_ok=True)
    for r in picks:
        im = Image.open(scene / "captures" / "frames" / r["file"]).convert("RGB")
        x0, y0, x1, y1 = r["bbox"]
        pw, ph = (x1 - x0) * pad, (y1 - y0) * pad
        crop = im.crop((int(max(x0 - pw, 0)), int(max(y0 - ph, 0)), int(min(x1 + pw, im.width)), int(min(y1 + ph, im.height))))
        if r["turn"]:
            crop = crop.rotate(r["turn"], expand=True)
        crop.thumbnail((900, 900))
        crop.save(out / f"f{r['frame']:04d}.jpg", quality=90)
    (out / "evidence.json").write_text(json.dumps(picks, indent=1))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scene", type=Path)
    ap.add_argument("--only")
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--min-in", type=float, default=0.55, help="share of the box that must be inside the frame")
    a = ap.parse_args()
    for name, obj in load_boxes(a.scene).items():
        if a.only and a.only != name:
            continue
        rows = score_frames(a.scene, obj, min_in=a.min_in)
        picks = pick_spread(rows, a.top)
        write_crops(a.scene, name, picks)
        cat = obj["category"]
        print(name, cat, f"{len(rows)} frames see it whole;", "picked", [(p["frame"], float(p["cover"]), p["in_frame"], p["sharp"], p["azimuth_deg"]) for p in picks])


if __name__ == "__main__":
    main()
