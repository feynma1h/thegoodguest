#!/usr/bin/env python3
"""Pick each tracked object's best frame, over a real capture.

    python3 tools/track_select.py <capture_dir> <track_dir> [--merge-duplicates]
                                  [--out DIR] [--no-rgb]

`capture_dir` holds bundle.pb and frames/NNNNNN.jpg; `track_dir` holds what
/track wrote, one directory per concept. This is the offline driver for
`services/perception-obj/track_selection.py` -- the selector itself takes plain
arrays and knows nothing about GCS, protos or JPEGs, so it is testable without
either a GPU or a network.

WHAT `--merge-duplicates` DOES AND DOES NOT DO. The tracker runs one concept per
pass, so one physical object is found under every prompt that fits it and
arrives as several instances. Where those instances SHARE frames the duplication
is measurable exactly -- their masks either coincide or they do not -- and the
flag collapses them. Where they do not share frames (0279's `nightstand#1/#2/#3`
in disjoint windows) nothing here can see it and the flag does not pretend to;
0280 measured the obvious geometric route to that half and found it
insufficient. Default OFF, so the raw instances are what you get unless you ask.
"""

from __future__ import annotations

import argparse
import functools
import json
import os
import sys

import numpy as np
from PIL import Image

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "services", "perception-obj"))
sys.path.insert(0, os.path.join(_HERE, "..", "packages", "schemas"))

from thegoodguest_schemas import CaptureBundle  # noqa: E402
from track_selection import (  # noqa: E402
    Detection,
    apply_key_map,
    merge_nested_instances,
    select_best_frames,
)


def load_detections(track_dir: str) -> tuple[list[Detection], dict]:
    """Every (concept, obj_id, frame) the tracker wrote, with its raster."""
    dets: list[Detection] = []
    meta_out: dict = {"concepts": [], "mask_shape": None, "image_size": None}
    for name in sorted(os.listdir(track_dir)):
        d = os.path.join(track_dir, name)
        meta_path, mask_path = os.path.join(d, "tracks.json"), os.path.join(d, "masks.npz")
        if not (os.path.isdir(d) and os.path.exists(meta_path)):
            continue
        with open(meta_path) as fh:
            meta = json.load(fh)
        if not os.path.exists(mask_path):
            continue
        z = np.load(mask_path)
        if "mask_shape" not in z.files:
            continue          # a concept the tracker found nothing for
        h, w = (int(v) for v in z["mask_shape"])
        meta_out["mask_shape"] = (h, w)
        meta_out["image_size"] = tuple(meta.get("image_size", ()))
        concept = meta.get("concept", name)
        meta_out["concepts"].append(concept)
        for rec in meta.get("detections", []):
            fi, oid = int(rec["frame_index"]), int(rec["obj_id"])
            key = f"f{fi:06d}_o{oid:04d}"
            if key not in z.files:
                continue
            flat = np.unpackbits(z[key])[: h * w]
            dets.append(Detection(
                object_key=f"{concept}#{oid}",
                frame_index=fi,
                mask=flat.reshape(h, w).astype(bool),
            ))
    return dets, meta_out


def load_timestamps(capture_dir: str) -> dict[int, float]:
    """frame_index -> seconds on the device-monotonic clock."""
    bundle = CaptureBundle()
    with open(os.path.join(capture_dir, "bundle.pb"), "rb") as fh:
        bundle.ParseFromString(fh.read())
    return {int(f.frame_index): f.timestamp_us / 1e6 for f in bundle.frames}


def rgb_loader(capture_dir: str, cache: int = 24):
    """Decode on demand. Small cache on purpose: the selector walks
    object-major, so frames barely repeat and a big one would just hold
    1.5 GiB of JPEG to no effect."""
    root = os.path.join(capture_dir, "frames")

    @functools.lru_cache(maxsize=cache)
    def _get(frame_index: int):
        path = os.path.join(root, f"{frame_index:06d}.jpg")
        if not os.path.exists(path):
            return None
        with Image.open(path) as im:
            return np.asarray(im.convert("RGB"), dtype=np.float32)

    return _get


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("capture_dir")
    ap.add_argument("track_dir")
    ap.add_argument("--merge-duplicates", action="store_true",
                    help="collapse instances whose masks coincide in shared frames")
    ap.add_argument("--no-rgb", action="store_true",
                    help="skip the sharpness term (no JPEG decoding)")
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    dets, meta = load_detections(args.track_dir)
    if not dets:
        raise SystemExit(f"no detections under {args.track_dir}")
    timestamps = load_timestamps(args.capture_dir)

    merged_from: dict[str, list[str]] = {}
    if args.merge_duplicates:
        key_map = merge_nested_instances(dets)
        for src, dst in sorted(key_map.items()):
            merged_from.setdefault(dst, []).append(src)
        dets = apply_key_map(dets, key_map)

    get_rgb = None if args.no_rgb else rgb_loader(args.capture_dir)
    choices = select_best_frames(dets, get_rgb=get_rgb, timestamps=timestamps)

    print(f"concepts       : {len(meta['concepts'])}")
    print(f"detections     : {len(dets)}")
    print(f"objects        : {len(choices)}"
          + ("  (after merging duplicates)" if args.merge_duplicates else ""))
    print(f"mask raster    : {meta['mask_shape']}   image {meta['image_size']}")
    print(f"sharpness      : {'off (--no-rgb)' if args.no_rgb else 'on'}")
    print()
    print(f"{'object':<22}{'best':>6}{'score':>7}{'kept':>6}{'of':>5}  "
          f"{'shp':>5}{'siz':>5}{'sol':>5}{'ctr':>5}{'tmp':>5}  why not")
    rejected_tally: dict[str, int] = {}
    for key in sorted(choices, key=lambda k: (choices[k].is_fallback, k)):
        c = choices[key]
        terms = next((f.normalized for f in c.frames if f.frame_index == c.frame_index), {})
        cells = "".join(
            f"{terms[t]:>5.2f}" if t in terms else "   --"
            for t in ("sharpness", "size", "solidity", "centeredness", "temporal")
        )
        why: dict[str, int] = {}
        for f in c.frames:
            for r in f.reasons:
                why[r] = why.get(r, 0) + 1
                rejected_tally[r] = rejected_tally.get(r, 0) + 1
        flag = " FALLBACK" if c.is_fallback else ""
        print(f"{key:<22}{c.frame_index:>6}{c.score:>7.3f}{c.n_kept:>6}{c.n_frames:>5}  "
              f"{cells}  {','.join(f'{k}:{v}' for k, v in sorted(why.items())) or '-'}{flag}")

    fb = [k for k, c in choices.items() if c.is_fallback]
    print()
    print(f"rejections by rule: {rejected_tally}")
    print(f"objects on the fallback path: {len(fb)}"
          + (f"  {sorted(fb)}" if fb else ""))

    out_dir = args.out or os.path.join(
        os.path.dirname(os.path.abspath(args.track_dir)), "analysis"
    )
    os.makedirs(out_dir, exist_ok=True)
    name = "best_frames_merged.json" if args.merge_duplicates else "best_frames.json"
    payload = {
        "n_objects": len(choices),
        "n_detections": len(dets),
        "merged_from": merged_from,
        "rejections": rejected_tally,
        "choices": [choices[k].as_dict() for k in sorted(choices)],
    }
    with open(os.path.join(out_dir, name), "w") as fh:
        json.dump(payload, fh, indent=1)
    print(f"written: {os.path.join(out_dir, name)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
