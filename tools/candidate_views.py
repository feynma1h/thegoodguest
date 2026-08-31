#!/usr/bin/env python3
"""Every candidate view of every box, ranked, with the selector's own pick.

A judgment aid, not an analysis: it renders what a person needs in order to
disagree with the selector. It calls the SHIPPED functions — box_visibility,
box_is_whole, frame_sharpness, select_box_whole_views — so what it draws IS
what the selector decided, and cannot drift the way a reimplementation would.

    PERCEPTION_BOX_WHOLE_VIEWS=1 python3 tools/candidate_views.py \\
        <capture_dir> <room_json> [out_dir]

`capture_dir` holds bundle.pb and frames/NNNNNN.jpg; `room_json` is the
CapturedRoom the scene was built from. It takes paths rather than a scene id
because the captures bucket sweeps at 24 h and these files outlive it.

Green = the selector's pick. Amber = whole but not chosen. Grey = cut off at
the image edge. EVERY candidate is drawn, tail included, because the question
this exists to answer is whether something good was passed over.
"""

from __future__ import annotations

import os
import sys

import numpy as np
from PIL import Image, ImageDraw

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "services", "perception-obj"))
sys.path.insert(0, os.path.join(_HERE, "..", "packages", "schemas"))

import box_placement as bp  # noqa: E402  (needs the sys.path lines above)
import census_sampling as cs  # noqa: E402
import roomplan_room  # noqa: E402
from thegoodguest_schemas import CaptureBundle  # noqa: E402

TILE_W, TILE_H = 250, 250
COLS, PAD, HEADER, CAPTION = 7, 6, 64, 30
GREEN, AMBER, GREY = (25, 130, 60), (205, 140, 30), (200, 200, 200)


def _load(capture_dir: str, room_json: str):
    bundle = CaptureBundle()
    with open(os.path.join(capture_dir, "bundle.pb"), "rb") as fh:
        bundle.ParseFromString(fh.read())
    with open(room_json, "rb") as fh:
        room = roomplan_room.parse_captured_room(fh.read())
    return list(bundle.frames), list(room.objects)


def _open(capture_dir: str, frame_index: int):
    path = os.path.join(capture_dir, "frames", f"{frame_index:06d}.jpg")
    try:
        return Image.open(path).convert("RGB")
    except Exception:
        return None


def _rgb(capture_dir: str, frame):
    im = _open(capture_dir, frame.frame_index)
    return None if im is None else np.asarray(im)


def _crop(capture_dir: str, box, frame):
    """The frame cropped around the box, with margin, rotated upright.

    The margin is generous on purpose: the extremities that decide whether a
    view is any good — a chair's legs, a desk's base — sit OUTSIDE the box.
    """
    hull, _frac = bp.project_box_footprint(box, frame.intrinsics, frame.camera_pose)
    if hull is None:
        return None
    im = _open(capture_dir, frame.frame_index)
    if im is None:
        return None
    hu = np.asarray(hull, dtype=float)
    x0, y0 = hu[:, 0].min(), hu[:, 1].min()
    x1, y1 = hu[:, 0].max(), hu[:, 1].max()
    mx, my = 0.30 * (x1 - x0), 0.30 * (y1 - y0)
    crop = im.crop((
        max(0, int(x0 - mx)), max(0, int(y0 - my)),
        min(im.width, int(x1 + mx)), min(im.height, int(y1 + my)),
    ))
    if crop.width < 30 or crop.height < 30:
        return None
    return crop.rotate(-90, expand=True)


def _sheet(bid: str, category: str, tiles: list, chosen_index, bar: float):
    rows = (len(tiles) + COLS - 1) // COLS
    sheet = Image.new(
        "RGB",
        (COLS * TILE_W + (COLS + 1) * PAD, HEADER + rows * (TILE_H + CAPTION) + PAD),
        (250, 250, 250),
    )
    d = ImageDraw.Draw(sheet)
    d.text(
        (10, 10),
        f"{bid}  {category}  —  ALL {len(tiles)} candidate views, "
        "ranked by the selector's score",
        fill=(20, 20, 20),
    )
    d.text(
        (10, 30),
        f"GREEN = chosen (frame {chosen_index}).  AMBER = whole but not chosen.  "
        "GREY = cut off at the image edge.",
        fill=(110, 110, 110),
    )
    d.text(
        (10, 46),
        f"sharpness is this capture's own percentile; the bar sits at {bar:.0f}.",
        fill=(110, 110, 110),
    )
    for k, (rank, frame_index, whole, pct, tile) in enumerate(tiles):
        row, col = divmod(k, COLS)
        x = PAD + col * (TILE_W + PAD)
        y = HEADER + row * (TILE_H + CAPTION)
        sheet.paste(tile, (x, y))
        if frame_index == chosen_index:
            colour, width = GREEN, 4
        elif whole:
            colour, width = AMBER, 2
        else:
            colour, width = GREY, 1
        d.rectangle(
            [x - 2, y - 2, x + TILE_W + 2, y + TILE_H + 2],
            outline=colour, width=width,
        )
        d.text(
            (x + 3, y + TILE_H + 4),
            f"#{rank} f{frame_index}  {'whole' if whole else 'CUT'}",
            fill=colour,
        )
        if pct >= 0:
            d.text((x + 3, y + TILE_H + 16), f"sharp p{pct:.0f}", fill=(140, 140, 140))
    return sheet


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    capture_dir = args[0] if args else "outputs/capture-90eebfc4"
    room_json = args[1] if len(args) > 1 else "outputs/selection-eyes/room.json"
    out_dir = args[2] if len(args) > 2 else "outputs/candidates-all"
    os.makedirs(out_dir, exist_ok=True)

    frames, boxes = _load(capture_dir, room_json)
    V, _Q = cs.box_visibility(frames, boxes)
    _picks, info = cs.select_box_whole_views(
        frames, boxes, V, get_rgb=lambda fr: _rgb(capture_dir, fr)
    )
    if not info:
        print("the selector returned nothing — is PERCEPTION_BOX_WHOLE_VIEWS=1 set?")
        return 1

    sharp = {f.frame_index: cs.frame_sharpness(_rgb(capture_dir, f)) for f in frames}
    finite = np.array([v for v in sharp.values() if v == v])
    bar = float(info.get("sharpness_bar", 0.0))

    for bi, box in enumerate(boxes):
        bid = f"box_{bi:02d}"
        category = getattr(box, "category", "?")
        chosen = (info.get("box_whole_views", {}).get(bid) or {}).get("frame_index")
        ranked = sorted(
            (fi for fi in range(len(frames)) if V[fi, bi] > 0),
            key=lambda fi: (-V[fi, bi], fi),
        )
        tiles = []
        for rank, fi in enumerate(ranked, 1):
            crop = _crop(capture_dir, box, frames[fi])
            if crop is None:
                continue
            crop.thumbnail((TILE_W, TILE_H))
            tile = Image.new("RGB", (TILE_W, TILE_H), (240, 240, 240))
            tile.paste(crop, ((TILE_W - crop.width) // 2, (TILE_H - crop.height) // 2))
            value = sharp.get(frames[fi].frame_index, float("nan"))
            pct = 100.0 * float((finite < value).mean()) if value == value else -1.0
            tiles.append(
                (rank, frames[fi].frame_index, cs.box_is_whole(box, frames[fi]), pct, tile)
            )
        if not tiles:
            continue
        path = os.path.join(out_dir, f"all_{bid}_{category}.png")
        _sheet(bid, category, tiles, chosen, bar).save(path)
        print(f"  {bid} {category:10} {len(tiles):>3} candidates, "
              f"chosen f{chosen} -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
