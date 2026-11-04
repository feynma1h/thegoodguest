"""Render-vs-photo loop for the furniture twins (see tools/FURNITURE_TWIN_FLOW.md).

    python tools/furniture_compare.py poses outputs/scene-<id> --obj box_0 [--frames 158,206]
        -> writes <scene>/poses.json and prints the one-line JS call to run
           in the /shell-finish page (preview pane console). The page poses the camera on each real frame's pose and
           intrinsics and POSTs frame_<id>.png / mask_<id>.png to
           tools/serve_scene.py.
    python tools/furniture_compare.py sheet outputs/scene-<id> --obj box_0 --iter 2 [--note "..."]
        -> <scene>/furniture/iterations/<key>/iter_02.png: per frame, the
           photo crop | the render crop, turned upright, plus the measured
           numbers (below). Every iteration is kept, so the progression can
           be shown.

Measured by code (the numbers on the sheet, not a pass/fail): inside the
render's own mask of the piece — mean Lab colour of the photo vs the render
(dL, dE; a coloured thing in front of the piece in the photo pollutes it),
the mask's share of the box's projected rectangle (a piece that is too thin
or too small shows up), and how far the mask's bounding box is from the
box's projected rectangle. What it cannot measure: material feel, details,
whether it "looks like" the piece — that is the reader's judgement, written
into iterations.md.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import finish_compare as fc  # noqa: E402
from furniture_evidence import upright_turn  # noqa: E402


def load_evidence(scene: Path, obj: str) -> list[dict]:
    return json.loads((scene / "furniture" / "evidence" / obj / "evidence.json").read_text())


def spec_for(scene: Path, obj: str) -> dict:
    for p in sorted((scene / "furniture" / "specs").glob("*.json")):
        s = json.loads(p.read_text())
        if s["object"] == obj:
            return s
    raise SystemExit(f"no spec for {obj} in {scene / 'furniture' / 'specs'}")


def pick_ids(scene: Path, obj: str, frames: str | None) -> list[int]:
    if frames:
        return [int(x) for x in frames.split(",")]
    return [e["frame"] for e in load_evidence(scene, obj)][:3]


def upright(im, turn: int):
    return im.rotate(turn, expand=True) if turn else im


def sheet(scene: Path, obj: str, ids: list[int], it: int, note: str) -> Path:
    from PIL import Image, ImageDraw
    from shell_finish import rgb_to_lab

    ev = {e["frame"]: e for e in load_evidence(scene, obj)}
    spec = spec_for(scene, obj)
    key = spec["key"]
    rdir = scene / "renders"
    rows = []
    stats = []
    idx = None
    try:
        idx = [o["key"] for o in json.loads((scene / "furniture.json").read_text())["objects"]].index(key)
    except (FileNotFoundError, ValueError):
        pass
    for f in fc._frames(scene, ids):
        e = ev.get(f.frame_index)
        rp = rdir / f"frame_{f.frame_index}.png"
        mp = rdir / f"mask_{f.frame_index}.png"
        if not rp.exists():
            continue
        photo = Image.open(scene / "captures" / "frames" / Path(f.rgb_gcs_path).name).convert("RGB")
        rend = Image.open(rp).convert("RGBA")
        bg = Image.new("RGBA", rend.size, (200, 200, 205, 255))
        rend = Image.alpha_composite(bg, rend).convert("RGB").resize(photo.size)
        if e:
            x0, y0, x1, y1 = e["bbox"]
            turn = e["turn"]
        else:  # frame not in the evidence list: whole frame
            x0, y0, x1, y1, turn = 0, 0, photo.width, photo.height, upright_turn(f.gravity)
        pw, ph = (x1 - x0) * 0.12, (y1 - y0) * 0.12
        box = (int(max(x0 - pw, 0)), int(max(y0 - ph, 0)), int(min(x1 + pw, photo.width)), int(min(y1 + ph, photo.height)))
        pc, rc = photo.crop(box), rend.crop(box)
        line = ""
        if mp.exists() and idx is not None:
            m = np.asarray(Image.open(mp).convert("RGBA").resize(photo.size, Image.NEAREST))
            want = fc._srgb(30 * (idx + 1))
            mask = (m[:, :, 3] > 200) & (np.abs(m[:, :, 0].astype(int) - want) < 5)
            mask = fc.erode(mask, 3)
            if mask.sum() > 800:
                ph_lab = rgb_to_lab(np.asarray(photo, float) / 255.0)
                rd_lab = rgb_to_lab(np.asarray(rend, float) / 255.0)
                a, b = ph_lab[mask].mean(0), rd_lab[mask].mean(0)
                d = a - b
                ys, xs = np.nonzero(mask)
                proj = (x1 - x0) * (y1 - y0)
                fill = float(mask.sum()) / proj if proj else 0
                bbox_gap = float(np.abs(np.array([xs.min() - x0, ys.min() - y0, xs.max() - x1, ys.max() - y1])).mean())
                stats.append({"frame": f.frame_index, "dL": round(float(d[0]), 1), "dE": round(float(np.linalg.norm(d)), 1),
                              "photo_Lab": np.round(a, 0).tolist(), "render_Lab": np.round(b, 0).tolist(),
                              "mask_share_of_box": round(fill, 2), "bbox_gap_px": round(bbox_gap, 0)})
                line = f"f{f.frame_index}  dL {d[0]:+.1f}  dE {np.linalg.norm(d):.1f}  mask/box {fill:.2f}  bbox gap {bbox_gap:.0f}px"
        pc, rc = upright(pc, turn), upright(rc, turn)
        h = 560
        pc = pc.resize((int(pc.width * h / pc.height), h))
        rc = rc.resize((int(rc.width * h / rc.height), h))
        row = Image.new("RGB", (pc.width + rc.width + 8, h + 22), (255, 255, 255))
        row.paste(pc, (0, 22))
        row.paste(rc, (pc.width + 8, 22))
        ImageDraw.Draw(row).text((4, 5), f"photo | render   {line}", fill=(0, 0, 0))
        rows.append(row)
    if not rows:
        raise SystemExit("no renders found; run the poses snippet in the page first")
    W = max(r.width for r in rows)
    out = Image.new("RGB", (W, sum(r.height + 6 for r in rows) + 24), (255, 255, 255))
    ImageDraw.Draw(out).text((4, 6), f"{key} iteration {it}: {note}", fill=(0, 0, 0))
    y = 24
    for r in rows:
        out.paste(r, (0, y))
        y += r.height + 6
    d = scene / "furniture" / "iterations" / key
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"iter_{it:02d}.png"
    out.save(path)
    (d / f"iter_{it:02d}.json").write_text(json.dumps({"iter": it, "note": note, "frames": ids, "stats": stats, "spec_revision": spec.get("revision")}, indent=1))
    print(json.dumps(stats, indent=1))
    return path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["poses", "sheet"])
    ap.add_argument("scene", type=Path)
    ap.add_argument("--obj", required=True)
    ap.add_argument("--frames")
    ap.add_argument("--iter", type=int, default=1)
    ap.add_argument("--note", default="")
    ap.add_argument("--port", type=int, default=8791)
    a = ap.parse_args()
    ids = pick_ids(a.scene, a.obj, a.frames)
    if a.cmd == "poses":
        js = fc.poses(a.scene, ids, a.port)
        # poses.json is what the page's harness.runFrom() fetches from the scene server.
        arr = js[js.index("(") + 1 : js.rindex(",")]
        (a.scene / "poses.json").write_text(arr)
        print(f"window.__shellFinishView.harness.runFrom({a.port})   // frames {ids}")
    else:
        print(sheet(a.scene, a.obj, ids, a.iter, a.note))


if __name__ == "__main__":
    main()
