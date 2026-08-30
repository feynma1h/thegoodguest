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

Two modes, because there are two questions.

Without `--decisions` the sheet answers "is this id ONE object?" and GREEN marks
the frame where the instance covers the most pixels — a proxy for its best view.

With `--decisions` it answers "did the selector pick the right frame?" and every
tile carries `track_selection`'s actual verdict: GREEN chosen, AMBER chosen but
on the fallback path (nothing survived), GREY a surviving candidate that lost,
RED refused with the rule that refused it. The proxy is not used at all in this
mode — a sheet that marked the largest mask while the pipeline picked something
else would be showing a decision nobody made.

The tiles are in capture-frame order, so a handoff (the object leaving and a
different one arriving under the same id) reads as a discontinuity along the
sheet.

When an instance appears in more frames than `--max-tiles`, the sheet SAMPLES
evenly and says so in its header rather than silently truncating: a sheet that
looks complete and is not is worse than one that admits its gaps.
"""

from __future__ import annotations

import argparse
import functools
import json
import os
import sys

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "services", "perception-obj"))

TILE_W, TILE_H = 240, 180
COLS, PAD, HEADER, CAPTION = 6, 6, 58, 40
GREEN, GREY = (25, 130, 60), (205, 205, 205)
RED, AMBER = (190, 45, 45), (205, 130, 20)
INK = {GREEN: (25, 110, 55), AMBER: (160, 100, 15),
       RED: (160, 45, 45), GREY: (130, 130, 130)}


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


@functools.lru_cache(maxsize=64)
def _frame(capture_dir: str, frame_index: int):
    path = os.path.join(capture_dir, "frames", f"{frame_index:06d}.jpg")
    try:
        return Image.open(path).convert("RGB")
    except Exception:
        return None


def _tile(capture_dir: str, frame_index: int, mask) -> Image.Image | None:
    pil = _frame(capture_dir, frame_index)
    if pil is None:
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
    d.text((PAD, 10), title, fill=(20, 20, 20))
    for j, line in enumerate(subtitle.split("\n")[:2]):
        d.text((PAD, 26 + j * 14), line, fill=(110, 110, 110))

    for i, (_frame_index, tile, colour, lines) in enumerate(tiles):
        r, c = divmod(i, COLS)
        x = PAD + c * (TILE_W + PAD)
        y = HEADER + r * (TILE_H + CAPTION + PAD)
        sheet.paste(tile, (x, y))
        width = 4 if colour in (GREEN, AMBER) else 2
        d.rectangle([x - 2, y - 2, x + TILE_W + 1, y + TILE_H + 1],
                    outline=colour, width=width)
        for j, line in enumerate(lines[:2]):
            d.text((x, y + TILE_H + 5 + j * 13), line, fill=INK.get(colour, GREY))
    return sheet


def _uncontested(choice) -> str:
    """Why a score of 1.000 is not a quality claim.

    The terms are min-max normalised within the object's OWN surviving frames
    and a term with zero variance maps to 1.0, so an object with a single
    survivor scores 1.000 by construction — measured on the preserved capture,
    all ten objects at 1.000 have at most one, against a median of 0.739 among
    those with a real contest. Saying it on the sheet costs one line and stops
    the number being read as excellent when it means uncontested.
    """
    return "   UNCONTESTED - one survivor, so every term normalises to 1.0" \
        if choice.n_kept <= 1 else ""


def _outline(mask: np.ndarray) -> np.ndarray:
    """The mask's boundary, by 4-neighbour erosion. Used instead of dimming on
    the chosen-frames sheet: dimming makes a mask legible, and an outline keeps
    the PHOTOGRAPH legible, which is the thing being judged there."""
    e = mask.copy()
    e[1:, :] &= mask[:-1, :]
    e[:-1, :] &= mask[1:, :]
    e[:, 1:] &= mask[:, :-1]
    e[:, :-1] &= mask[:, 1:]
    return mask & ~e


def _chosen_sheet(capture_dir, rows, out_path):
    """One tile per OBJECT: the frame the selector chose, undimmed.

    The whole review on one page, in the order a person would read it, so the
    question "is this the right photograph of that thing" can be asked 48 times
    without opening 48 files.
    """
    TW, TH, C, CAP = 360, 270, 4, 46
    n = len(rows)
    r = max(1, (n + C - 1) // C)
    sheet = Image.new("RGB", (C * (TW + PAD) + PAD, 46 + r * (TH + CAP + PAD) + PAD),
                      (250, 250, 250))
    d = ImageDraw.Draw(sheet)
    d.text((PAD, 12), "the frame chosen for every tracked object", fill=(20, 20, 20))
    d.text((PAD, 28), f"{n} objects, {capture_dir}   "
                      "GREEN chosen from surviving frames, AMBER fallback "
                      "(no uncut view existed)", fill=(110, 110, 110))
    for i, (name, fi, mask, colour, note) in enumerate(rows):
        rr, cc = divmod(i, C)
        x, y = PAD + cc * (TW + PAD), 46 + rr * (TH + CAP + PAD)
        pil = _frame(capture_dir, fi)
        if pil is None:
            continue
        rgb = np.asarray(pil).copy()
        if mask is not None:
            big = np.asarray(Image.fromarray((mask * 255).astype(np.uint8))
                             .resize(pil.size, Image.NEAREST)) > 127
            edge = _outline(big)
            for k in range(3):
                edge_wide = edge.copy()
                edge_wide[k + 1:, :] |= edge[: -(k + 1), :]
                edge_wide[:, k + 1:] |= edge[:, : -(k + 1)]
                edge = edge_wide
            rgb[edge] = (60, 230, 120)
        sheet.paste(Image.fromarray(rgb).resize((TW, TH)), (x, y))
        d.rectangle([x - 3, y - 3, x + TW + 2, y + TH + 2], outline=colour, width=4)
        d.text((x, y + TH + 6), f"{name}    frame {fi}", fill=(20, 20, 20))
        d.text((x, y + TH + 22), note, fill=INK.get(colour, GREY))
    sheet.save(out_path)
    return out_path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("capture_dir")
    ap.add_argument("track_dir")
    ap.add_argument("--out", default=None)
    ap.add_argument("--instance", help="only this one, e.g. 'monitor#3'")
    ap.add_argument("--max-tiles", type=int, default=48,
                    help="0 = every candidate frame, never sampled")
    ap.add_argument("--decisions", action="store_true",
                    help="annotate with track_selection's real verdicts")
    ap.add_argument("--chosen-sheet", action="store_true",
                    help="also write one page holding every object's chosen frame")
    ap.add_argument("--capture-timestamps", action="store_true", default=True)
    ap.add_argument("--min-frames", type=int, default=1,
                    help="skip instances thinner than this")
    args = ap.parse_args(argv)

    tracks = _load_tracks(args.track_dir)
    out_dir = args.out or os.path.join(
        os.path.dirname(os.path.abspath(args.track_dir)), "sheets"
    )
    os.makedirs(out_dir, exist_ok=True)

    # The selector is run here rather than read from its JSON, because the
    # sheet needs the PER-FRAME verdict and the reasons behind it, and the
    # written summary carries only the winner. One source of truth, and the
    # sheet cannot drift from the decision it is drawing.
    decisions: dict = {}
    if args.decisions:
        sys.path.insert(0, os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "packages", "schemas"))
        from track_select import load_detections, load_timestamps, rgb_loader
        from track_selection import select_best_frames

        dets, _meta = load_detections(args.track_dir)
        decisions = select_best_frames(
            dets,
            get_rgb=rgb_loader(args.capture_dir),
            timestamps=load_timestamps(args.capture_dir),
        )

    written = 0
    chosen_rows: list = []
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
            choice = decisions.get(name)
            best_frame = (
                choice.frame_index if choice
                else max(dets, key=lambda d: d["area_px"])["frame_index"]
            )
            verdict = {f.frame_index: f for f in choice.frames} if choice else {}

            shown = dets
            note = ""
            if args.max_tiles and len(dets) > args.max_tiles:
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
                if tile is None:
                    continue
                chosen = fi == best_frame
                v = verdict.get(fi)
                if v is None:
                    colour = GREEN if chosen else GREY
                    lines = [f"f{fi}" + ("   best view" if chosen else "")]
                else:
                    if chosen:
                        colour = GREEN if v.kept else AMBER
                    else:
                        colour = GREY if v.kept else RED
                    tag = ("CHOSEN" if chosen and v.kept else
                           "CHOSEN - fallback" if chosen else
                           "kept" if v.kept else ",".join(v.reasons))
                    lines = [f"f{fi}   {tag}", f"score {v.score:.3f}" if v.score else ""]
                tiles.append((fi, tile, colour, lines))
            if not tiles:
                continue

            areas = [d["area_px"] for d in dets]
            subtitle = (
                f"{len(dets)} frames, {dets[0]['frame_index']}-{dets[-1]['frame_index']}   "
                f"median {int(np.median(areas)):,} px, max {max(areas):,} px   "
                f"mean prob {np.mean([d['prob'] for d in dets]):.3f}{note}"
            )
            if choice:
                subtitle = (
                    f"CHOSE FRAME {choice.frame_index}  score {choice.score:.3f}   "
                    f"{choice.n_kept} of {choice.n_frames} frames survived"
                    + ("   FALLBACK: nothing survived" if choice.is_fallback else "")
                    + _uncontested(choice)
                    + f"{note}\n{subtitle}"
                )
            if choice and choice.frame_index is not None:
                chosen_rows.append((
                    name, choice.frame_index,
                    _mask_of(entry, choice.frame_index, obj_id),
                    AMBER if choice.is_fallback else GREEN,
                    (f"score {choice.score:.3f}   "
                     f"{choice.n_kept}/{choice.n_frames} survived"
                     + ("   FALLBACK" if choice.is_fallback else "")
                     + ("   UNCONTESTED" if choice.n_kept <= 1 else "")),
                ))

            path = os.path.join(out_dir, f"{concept.replace(' ', '-')}-{obj_id:02d}.png")
            _sheet(name, subtitle, tiles).save(path)
            written += 1
            print(f"  {name:<24} {len(dets):>4} frames -> {os.path.basename(path)}")

    if args.chosen_sheet and chosen_rows:
        p = _chosen_sheet(args.capture_dir, chosen_rows,
                          os.path.join(out_dir, "_chosen.png"))
        print(f"\n  every object's chosen frame -> {p}")

    print(f"\n{written} sheets written to {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
