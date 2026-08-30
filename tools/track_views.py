#!/usr/bin/env python3
"""Every frame that holds a tracked instance, with its mask, on one sheet.

    python3 tools/track_views.py <capture_dir> <track_dir> [--out DIR]
                                 [--instance monitor#3] [--max-tiles N]

The tracked-instance counterpart to `tools/candidate_views.py`, and it exists
for the same reason: the operator judges from images, not tables. A purity
number says an id is consistent; only the sheet says whether the thing it is
consistent ABOUT is one object. Those are different questions and the second
one has repeatedly been the one that mattered — that method has already found
two real defects on the boxed path.

One sheet per (concept, obj_id). The mask is lit and everything else is dimmed,
which is the same treatment /segment's per-detection PNG uses, so a mask that
has quietly grown to include the wall reads immediately.

GREEN marks the frame where the instance covers the most pixels — its best
view, and the one a downstream consumer would reach for first. The tiles are in
capture-frame order, so a handoff (the object leaving and a different one
arriving under the same id) reads as a discontinuity along the sheet.

When an instance appears in more frames than `--max-tiles`, the sheet SAMPLES
evenly and says so in its header rather than silently truncating: a sheet that
looks complete and is not is worse than one that admits its gaps.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np
from PIL import Image, ImageDraw

TILE_W, TILE_H = 240, 180
COLS, PAD, HEADER, CAPTION = 6, 6, 58, 26
GREEN, GREY = (25, 130, 60), (205, 205, 205)


def _load_tracks(track_dir: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for name in sorted(os.listdir(track_dir)):
        d = os.path.join(track_dir, name)
        meta_path = os.path.join(d, "tracks.json")
        if not (os.path.isdir(d) and os.path.exists(meta_path)):
            continue
        with open(meta_path) as fh:
            meta = json.load(fh)
        mask_path = os.path.join(d, "masks.npz")
        out[meta.get("concept", name)] = {
            "meta": meta,
            "masks": np.load(mask_path) if os.path.exists(mask_path) else None,
        }
    return out


def _mask_of(entry: dict, frame_index: int, obj_id: int):
    masks = entry["masks"]
    if masks is None or "mask_shape" not in masks.files:
        return None
    key = f"f{frame_index:06d}_o{obj_id:04d}"
    if key not in masks.files:
        return None
    h, w = (int(v) for v in masks["mask_shape"])
    return np.unpackbits(masks[key])[: h * w].reshape(h, w).astype(bool)


def _tile(capture_dir: str, frame_index: int, mask) -> Image.Image | None:
    path = os.path.join(capture_dir, "frames", f"{frame_index:06d}.jpg")
    try:
        pil = Image.open(path).convert("RGB")
    except Exception:
        return None
    rgb = np.asarray(pil)
    if mask is not None:
        m = np.asarray(
            Image.fromarray((mask * 255).astype(np.uint8)).resize(pil.size, Image.NEAREST)
        ) > 127
        rgb = np.where(m[..., None], rgb, (rgb * 0.30).astype(np.uint8))
    return Image.fromarray(rgb).resize((TILE_W, TILE_H))


def _sheet(title: str, subtitle: str, tiles: list[tuple[int, Image.Image, bool]]):
    rows = max(1, (len(tiles) + COLS - 1) // COLS)
    w = COLS * (TILE_W + PAD) + PAD
    h = HEADER + rows * (TILE_H + CAPTION + PAD) + PAD
    sheet = Image.new("RGB", (w, h), (250, 250, 250))
    d = ImageDraw.Draw(sheet)
    d.text((PAD, 14), title, fill=(20, 20, 20))
    d.text((PAD, 34), subtitle, fill=(110, 110, 110))

    for i, (frame_index, tile, is_best) in enumerate(tiles):
        r, c = divmod(i, COLS)
        x = PAD + c * (TILE_W + PAD)
        y = HEADER + r * (TILE_H + CAPTION + PAD)
        sheet.paste(tile, (x, y))
        colour = GREEN if is_best else GREY
        d.rectangle([x - 2, y - 2, x + TILE_W + 1, y + TILE_H + 1], outline=colour, width=2)
        label = f"frame {frame_index}" + ("   best view" if is_best else "")
        d.text((x, y + TILE_H + 6), label, fill=(60, 60, 60) if is_best else (130, 130, 130))
    return sheet


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("capture_dir")
    ap.add_argument("track_dir")
    ap.add_argument("--out", default=None)
    ap.add_argument("--instance", help="only this one, e.g. 'monitor#3'")
    ap.add_argument("--max-tiles", type=int, default=48)
    ap.add_argument("--min-frames", type=int, default=1,
                    help="skip instances thinner than this")
    args = ap.parse_args(argv)

    tracks = _load_tracks(args.track_dir)
    out_dir = args.out or os.path.join(
        os.path.dirname(os.path.abspath(args.track_dir)), "sheets"
    )
    os.makedirs(out_dir, exist_ok=True)

    written = 0
    for concept, entry in sorted(tracks.items()):
        per_id: dict[int, list[dict]] = {}
        for det in entry["meta"].get("detections", []):
            per_id.setdefault(int(det["obj_id"]), []).append(det)

        for obj_id, dets in sorted(per_id.items()):
            name = f"{concept}#{obj_id}"
            if args.instance and args.instance != name:
                continue
            if len(dets) < args.min_frames:
                continue
            dets.sort(key=lambda d: d["frame_index"])
            best_frame = max(dets, key=lambda d: d["area_px"])["frame_index"]

            shown = dets
            note = ""
            if len(dets) > args.max_tiles:
                step = len(dets) / float(args.max_tiles)
                idx = sorted({int(i * step) for i in range(args.max_tiles)})
                shown = [dets[i] for i in idx]
                if not any(d["frame_index"] == best_frame for d in shown):
                    shown.append(next(d for d in dets if d["frame_index"] == best_frame))
                    shown.sort(key=lambda d: d["frame_index"])
                note = f"   SAMPLED {len(shown)} of {len(dets)} frames, evenly"

            tiles = []
            for det in shown:
                fi = int(det["frame_index"])
                tile = _tile(args.capture_dir, fi, _mask_of(entry, fi, obj_id))
                if tile is not None:
                    tiles.append((fi, tile, fi == best_frame))
            if not tiles:
                continue

            areas = [d["area_px"] for d in dets]
            subtitle = (
                f"{len(dets)} frames, {dets[0]['frame_index']}-{dets[-1]['frame_index']}   "
                f"median {int(np.median(areas)):,} px, max {max(areas):,} px   "
                f"mean prob {np.mean([d['prob'] for d in dets]):.3f}{note}"
            )
            path = os.path.join(out_dir, f"{concept.replace(' ', '-')}-{obj_id:02d}.png")
            _sheet(name, subtitle, tiles).save(path)
            written += 1
            print(f"  {name:<24} {len(dets):>4} frames -> {os.path.basename(path)}")

    print(f"\n{written} sheets written to {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
