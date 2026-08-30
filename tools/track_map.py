#!/usr/bin/env python3
"""The object->frame map, and the number that says whether it can be believed.

    python3 tools/track_map.py <capture_dir> <track_dir> [--room-json PATH] [--out DIR]

`capture_dir` holds bundle.pb and frames/NNNNNN.jpg; `track_dir` holds what
/track wrote, one directory per concept, each with tracks.json and masks.npz.
`--room-json` is the CapturedRoom the scene was built from — optional, because
only the box-grounded half of the measurement needs it.

WHY THE MEASUREMENT COMES BEFORE THE MAP. A tracked id is a claim that the
thing in frame 41 and the thing in frame 42 are the same object. If that claim
is wrong the map still looks complete — it just quietly says one monitor where
there were two, or two where there was one — and nothing downstream could tell,
which is why 0271 makes id stability the acceptance test rather than "3.1 runs".
So this tool reports the stability numbers beside the map and refuses to
present one without the other.

TWO INSTRUMENTS, because neither alone covers the corpus.

**Box purity** is the grounded one and it only works for the six objects
RoomPlan measured. Each box is projected into every frame through the shipped
`project_box_footprint`, and in every frame where it is genuinely visible we
ask which tracked instance overlaps it most. If ids are stable, one id wins
almost every frame:

    purity       = winning frames / visible frames, for the dominant id
    fragments    = how many distinct ids ever win a frame

Purity is the direct measure of "one id means one object". It is label-blind on
purpose — every instance of every concept competes for every box — so it also
catches an id that is stable but attached to the wrong thing.

**Handoffs** need no ground truth and therefore cover the unboxed nine. A
fragmentation event has a signature: id A is last seen at frame f, and id B is
first seen a frame or two later in nearly the same place. Measured as an IoU
between A's last mask and B's first mask, that is a split reported without any
knowledge of what the object is.

Neither instrument is the whole answer and they are reported separately rather
than blended into a score, because they fail differently: purity is exact but
covers six objects, and handoffs cover everything but infer.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "services", "perception-obj"))
sys.path.insert(0, os.path.join(_HERE, "..", "packages", "schemas"))

import box_placement as bp  # noqa: E402  (needs the sys.path lines above)
import roomplan_room  # noqa: E402
from roomstudio_schemas import CaptureBundle  # noqa: E402

# A box has to occupy a real part of the image before "which id owns it" is a
# fair question; a sliver at the edge is a frame where any answer is luck. The
# test is on the hull AFTER clipping to the frame, not before: a box that
# overflows the image is fully visible, not barely visible, and an
# in-frame-FRACTION gate rejects exactly the close-up frames where the object
# is largest. Measured on the preserved capture, a 0.55 fraction gate saw the
# bed in 14 frames of 189; the bed is in shot for far more than that.
MIN_HULL_FRAC_OF_FRAME = 0.01
# Below this the instance is not really claiming the box; without a floor the
# "winner" of an empty frame is whichever mask happens to graze it.
MIN_CLAIM_IOU = 0.10
# A handoff is a disappearance and a reappearance close in TIME and PLACE.
HANDOFF_MAX_GAP_FRAMES = 3
HANDOFF_MIN_IOU = 0.30


def _load_tracks(track_dir: str) -> dict[str, dict]:
    """{concept: {"meta": tracks.json, "masks": npz}} for every concept written."""
    out: dict[str, dict] = {}
    for name in sorted(os.listdir(track_dir)):
        d = os.path.join(track_dir, name)
        meta_path, mask_path = os.path.join(d, "tracks.json"), os.path.join(d, "masks.npz")
        if not (os.path.isdir(d) and os.path.exists(meta_path)):
            continue
        with open(meta_path) as fh:
            meta = json.load(fh)
        masks = np.load(mask_path) if os.path.exists(mask_path) else None
        out[meta.get("concept", name)] = {"meta": meta, "masks": masks, "dir": d}
    return out


def _mask_of(entry: dict, frame_index: int, obj_id: int) -> np.ndarray | None:
    """Unpack one stored raster. packbits is 1-D, so the shape travels beside it."""
    masks = entry["masks"]
    if masks is None:
        return None
    key = f"f{frame_index:06d}_o{obj_id:04d}"
    if key not in masks.files or "mask_shape" not in masks.files:
        return None
    h, w = (int(v) for v in masks["mask_shape"])
    flat = np.unpackbits(masks[key])[: h * w]
    return flat.reshape(h, w).astype(bool)


def _iou(a: np.ndarray, b: np.ndarray) -> float:
    inter = int(np.logical_and(a, b).sum())
    if inter == 0:
        return 0.0
    return inter / float(np.logical_or(a, b).sum())


def _hull_mask(hull_uv: np.ndarray, shape: tuple[int, int], stride: int) -> np.ndarray:
    """Rasterise a projected box hull at the stored rasters' resolution."""
    h, w = shape
    img = Image.new("1", (w, h), 0)
    pts = [(float(u) / stride, float(v) / stride) for u, v in hull_uv]
    if len(pts) >= 3:
        ImageDraw.Draw(img).polygon(pts, fill=1)
    return np.asarray(img, dtype=bool)


# ── the map ──────────────────────────────────────────────────────────────────


def build_map(tracks: dict[str, dict]) -> dict[str, Any]:
    """Every instance, which frames hold it, and where it is in each."""
    instances: list[dict[str, Any]] = []
    for concept, entry in sorted(tracks.items()):
        per_id: dict[int, list[dict]] = defaultdict(list)
        for det in entry["meta"].get("detections", []):
            per_id[int(det["obj_id"])].append(det)
        for obj_id, dets in sorted(per_id.items()):
            dets.sort(key=lambda d: d["frame_index"])
            frames = [int(d["frame_index"]) for d in dets]
            areas = [int(d["area_px"]) for d in dets]
            instances.append({
                # The key is (concept, obj_id) and never obj_id alone: ids
                # restart every concept because the session holds one prompt.
                "instance": f"{concept}#{obj_id}",
                "concept": concept,
                "obj_id": obj_id,
                "n_frames": len(frames),
                "first_frame": frames[0],
                "last_frame": frames[-1],
                "frames": frames,
                "median_area_px": int(np.median(areas)),
                "max_area_px": int(max(areas)),
                "mean_prob": round(float(np.mean([d["prob"] for d in dets])), 4),
                "where": {
                    str(d["frame_index"]): [round(v, 1) for v in d["bbox_px"]]
                    for d in dets
                },
            })
    instances.sort(key=lambda e: -e["n_frames"])
    return {"instances": instances}


# ── instrument 1: box purity ─────────────────────────────────────────────────


def measure_box_purity(
    capture_dir: str, room_json: str, tracks: dict[str, dict], stride: int
) -> list[dict[str, Any]]:
    """For each RoomPlan box, which id owns it and how consistently."""
    bundle = CaptureBundle()
    with open(os.path.join(capture_dir, "bundle.pb"), "rb") as fh:
        bundle.ParseFromString(fh.read())
    with open(room_json, "rb") as fh:
        room = roomplan_room.parse_captured_room(fh.read())

    by_index = {f.frame_index: f for f in bundle.frames}
    # Every detection, indexed by frame, across every concept — the contest for
    # a box is open to all of them.
    dets_by_frame: dict[int, list[tuple[str, int]]] = defaultdict(list)
    for concept, entry in tracks.items():
        for det in entry["meta"].get("detections", []):
            dets_by_frame[int(det["frame_index"])].append((concept, int(det["obj_id"])))

    shape = None
    for entry in tracks.values():
        if entry["masks"] is not None and "mask_shape" in entry["masks"].files:
            shape = tuple(int(v) for v in entry["masks"]["mask_shape"])
            break
    if shape is None:
        return []

    results = []
    for box in room.objects:
        winners: list[str] = []
        visible = 0
        for fidx, frame in sorted(by_index.items()):
            hull, _in_frame = bp.project_box_footprint(
                box, frame.intrinsics, frame.camera_pose
            )
            if hull is None:
                continue
            # Rasterising clips to the frame for free, so this area IS the
            # on-screen footprint.
            hm = _hull_mask(hull, shape, stride)
            if hm.sum() < MIN_HULL_FRAC_OF_FRAME * hm.size:
                continue
            visible += 1
            best, best_iou = None, 0.0
            for concept, obj_id in dets_by_frame.get(fidx, []):
                m = _mask_of(tracks[concept], fidx, obj_id)
                if m is None or m.shape != hm.shape:
                    continue
                score = _iou(hm, m)
                if score > best_iou:
                    best, best_iou = f"{concept}#{obj_id}", score
            if best is not None and best_iou >= MIN_CLAIM_IOU:
                winners.append(best)

        counts: dict[str, int] = defaultdict(int)
        for w in winners:
            counts[w] += 1
        dominant, dom_n = (
            max(counts.items(), key=lambda kv: kv[1]) if counts else (None, 0)
        )
        results.append({
            "box_id": getattr(box, "identifier", None) or getattr(box, "box_id", "?"),
            "category": getattr(box, "category", "?"),
            "frames_visible": visible,
            "frames_claimed": len(winners),
            "dominant_instance": dominant,
            "dominant_frames": dom_n,
            # The headline: of the frames where SOMETHING claimed this box, how
            # many did the single dominant id win.
            "purity": round(dom_n / len(winners), 4) if winners else None,
            "fragments": len(counts),
            "all_claimants": dict(sorted(counts.items(), key=lambda kv: -kv[1])),
        })
    return results


# ── instrument 2: handoffs ───────────────────────────────────────────────────


def measure_handoffs(tracks: dict[str, dict], instances: list[dict]) -> list[dict[str, Any]]:
    """Find id A ending where id B begins — a split, with no ground truth."""
    by_concept: dict[str, list[dict]] = defaultdict(list)
    for inst in instances:
        by_concept[inst["concept"]].append(inst)

    events = []
    for concept, insts in by_concept.items():
        entry = tracks[concept]
        for a in insts:
            for b in insts:
                if a["obj_id"] == b["obj_id"]:
                    continue
                gap = b["first_frame"] - a["last_frame"]
                if not (0 < gap <= HANDOFF_MAX_GAP_FRAMES):
                    continue
                ma = _mask_of(entry, a["last_frame"], a["obj_id"])
                mb = _mask_of(entry, b["first_frame"], b["obj_id"])
                if ma is None or mb is None or ma.shape != mb.shape:
                    continue
                score = _iou(ma, mb)
                if score >= HANDOFF_MIN_IOU:
                    events.append({
                        "concept": concept,
                        "from": f"{concept}#{a['obj_id']}",
                        "to": f"{concept}#{b['obj_id']}",
                        "at_frame": a["last_frame"],
                        "gap_frames": gap,
                        "iou": round(score, 4),
                    })
    events.sort(key=lambda e: -e["iou"])
    return events


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("capture_dir")
    ap.add_argument("track_dir")
    ap.add_argument("--room-json", help="CapturedRoom; enables the box-purity instrument")
    ap.add_argument("--out", default=None, help="defaults to <track_dir>/../analysis")
    args = ap.parse_args(argv)

    tracks = _load_tracks(args.track_dir)
    if not tracks:
        raise SystemExit(f"no concept directories under {args.track_dir}")
    stride = int(next(iter(tracks.values()))["meta"].get("mask_stride", 4))

    out_dir = args.out or os.path.join(os.path.dirname(os.path.abspath(args.track_dir)), "analysis")
    os.makedirs(out_dir, exist_ok=True)

    mapping = build_map(tracks)
    instances = mapping["instances"]
    handoffs = measure_handoffs(tracks, instances)
    purity = (
        measure_box_purity(args.capture_dir, args.room_json, tracks, stride)
        if args.room_json
        else []
    )

    payload = {
        "concepts": sorted(tracks),
        "n_instances": len(instances),
        "instances": instances,
        "box_purity": purity,
        "handoffs": handoffs,
    }
    with open(os.path.join(out_dir, "object_frame_map.json"), "w") as fh:
        json.dump(payload, fh, indent=1)

    print(f"concepts tracked : {len(tracks)}")
    print(f"instances found  : {len(instances)}")
    print()
    print("instance                     frames  first  last   med.area  prob")
    for inst in instances[:40]:
        print(f"  {inst['instance']:<26} {inst['n_frames']:>5}  {inst['first_frame']:>5}"
              f"  {inst['last_frame']:>4}  {inst['median_area_px']:>8}  {inst['mean_prob']:.3f}")
    if purity:
        print()
        print("box purity (RoomPlan-grounded)")
        print("  box                         vis  claimed  purity  frags  dominant")
        for r in purity:
            p = "n/a" if r["purity"] is None else f"{r['purity']:.3f}"
            print(f"  {str(r['category'])[:24]:<26} {r['frames_visible']:>4}"
                  f"  {r['frames_claimed']:>7}  {p:>6}  {r['fragments']:>5}"
                  f"  {r['dominant_instance']}")
        vals = [r["purity"] for r in purity if r["purity"] is not None]
        if vals:
            print(f"  MEAN PURITY over {len(vals)} boxes: {float(np.mean(vals)):.4f}")
    print()
    print(f"handoff events (possible splits): {len(handoffs)}")
    for e in handoffs[:15]:
        print(f"  {e['from']} -> {e['to']} at frame {e['at_frame']} "
              f"(gap {e['gap_frames']}, IoU {e['iou']:.3f})")
    print()
    print(f"written: {os.path.join(out_dir, 'object_frame_map.json')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
