"""Tracking probe: SAM 3.1 across a capture's frames, producing an object->frame map.

WHY THIS EXISTS. Every selection instrument this project owns takes a RoomPlan
box as its argument — `box_visibility` projects it to score a view,
`box_is_whole` to ask whether the object is cut, association matches masks to
it, `arm_fit` measures a reconstruction against it. An object RoomPlan never
boxed is invisible to all of them. Segmenting 19 frames of one capture found
fourteen object kinds and RoomPlan had boxed six; the monitor was detected in
sixteen of nineteen frames and is absent from the shipped room (0271).

`/segment` (0260) answers "what is in THIS frame", one frame at a time, with no
identity between frames. That is the detector's contract and no amount of
calling it produces a map: instances are rows of a tensor, and nothing relates
row 3 of frame 41 to row 3 of frame 42. The identity comes from SAM 3.1's video
tracker, which is why this route exists beside `/segment` rather than replacing
it — see `models/sam3_video.py` for what was read upstream and why.

THE SAME TWO CONTAINMENT INVARIANTS AS /segment, for the same reasons:

  1. **It never writes under `scenes/{scene_id}/frames/`.** Everything lands in
     `scenes/{scene_id}/track_probe/`. `/process` treats a frame's
     `objects.json` as a cache and logs `Frame N cache hit`, so anything a
     probe leaves in the real frame prefix is read as production state by the
     next real run. The prefix is the boundary.
  2. **It never touches Firestore.** No claim, no lease, no status. A warm
     re-drive regresses a `ready` scene to `queued` (0247); a probe that
     answers a question about a room must not be able to take that room away
     from the person while it does so.

IT WRITES NUMBERS AND BINARY MASKS, NEVER IMAGERY. `/segment` renders a PNG per
detection because the artifact it exists to produce is something a person looks
at. This route's artifact is a map, so it writes `tracks.json` and a packed
mask raster and nothing else. That matters more than it sounds: the preserved
capture has a person asleep on the bed in frame 0, and while a suppressed
concept can never be TRACKED here (below), a `bed` mask in such a frame may
well include the person lying on it. A bool raster at stride 4 is not a
photograph, and no frame pixels leave the container.

ONE CONCEPT PER PASS, AND IDS ARE SCOPED TO THE PASS. The session holds a
single text prompt — upstream's notebook resets the session before switching
prompts and says the results are otherwise wrong — so a capture is tracked once
per concept and `obj_id` restarts each time. The map's key is therefore
(concept, obj_id), not obj_id, and two concepts may legitimately cover one
physical object. That is recorded rather than reconciled here: reconciling it is
a judgement about the room, and this route only reports what the model returned.
"""

from __future__ import annotations

import io
import json
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import numpy as np
from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Everything this route writes lives under this prefix, never under frames/.
PROBE_PREFIX = "track_probe"

# Stride of the STORED raster. Masks come back at full video resolution, bool,
# one per tracked object per frame; for 189 frames that is gigabytes, and
# nothing downstream needs per-pixel precision from the raster. The exact
# numbers — area and bounding box — are taken on the full mask before it is
# decimated, so this costs no measurement. It lives here rather than in
# models/sam3_video.py because this module must stay importable without torch:
# it is on the Dockerfile's deferred-import smoke line (0211).
MASK_STRIDE = 4

# A capture is a few hundred keyframes; this is a guard against a pathological
# request, not a working limit. 189 is the preserved capture.
MAX_FRAMES_PER_CALL = 400

# Concepts per call. The wall-clock ceiling is the Cloud Run request budget
# (900 s), and the cost is one propagation over every frame per concept, so the
# caller chunks the vocabulary across calls rather than this route guessing how
# many will fit. Frame decode is paid once per call, not once per concept.
MAX_CONCEPTS_PER_CALL = 12

# 189 serial GCS round-trips is a minute of a request that has better uses for
# it. The rest of this service downloads serially because it downloads a
# handful of frames; this one needs all of them before the first inference.
_DOWNLOAD_WORKERS = 8


class TrackRequest(BaseModel):
    """Explicit concepts, because one pass tracks exactly one of them."""

    scene_id: str
    bundle_uri: str
    concepts: list[str] = Field(..., min_length=1)
    # Absent means every frame in the bundle, which is the point of a map.
    frame_indices: list[int] | None = None
    prompt_frame_position: int = 0
    output_prob_thresh: float = 0.5


def _slug(text: str) -> str:
    """A concept as a path segment: 'dining table' -> 'dining-table'."""
    return re.sub(r"[^a-z0-9]+", "-", text.strip().lower()).strip("-") or "concept"


def _fetch_frames(prefix: str, frames: list, download) -> tuple[list, list[int], list[dict]]:
    """Download and decode frames, keeping the order the bundle declares.

    Returns (pil_images, frame_indices, failures). A frame that will not
    download or decode is reported and skipped rather than raised: this is a
    probe, and a map over 188 frames beats no map. The returned index list is
    the mapping from position in the tracked sequence back to capture frame
    index, which every caller of the output needs.
    """
    from PIL import Image

    def _one(item):
        pos, frame = item
        try:
            raw = download(prefix + frame.rgb_gcs_path)
            pil = Image.open(io.BytesIO(raw)).convert("RGB")
            return pos, frame.frame_index, pil, None
        except Exception as exc:
            return pos, frame.frame_index, None, f"{type(exc).__name__}: {exc}"

    with ThreadPoolExecutor(max_workers=_DOWNLOAD_WORKERS) as pool:
        results = list(pool.map(_one, enumerate(frames)))

    results.sort(key=lambda r: r[0])
    images: list = []
    indices: list[int] = []
    failures: list[dict] = []
    for _pos, fidx, pil, err in results:
        if pil is None:
            failures.append({"frame_index": fidx, "error": err})
            continue
        images.append(pil)
        indices.append(fidx)
    return images, indices, failures


async def handle_track(
    request: Request,
    req: TrackRequest,
    *,
    oidc_verifier,
    outputs_bucket: str,
    sam3_video_model,
) -> JSONResponse:
    """Track each concept across the capture and write the object->frame map.

    Returns 200 with a per-concept summary. Poison inputs (an unfetchable
    frame, a concept the model rejects) are reported in the body rather than
    raised, for the same reason /segment does it: a partial answer beats none.
    """
    from oidc import OIDCError
    from process_receiver import (
        _bundle_prefix,
        _download_gcs_uri,
        _gcs_upload_for_scene,
    )
    from thegoodguest_schemas import CaptureBundle

    # verify() takes the HEADER VALUE and raises; it is not async and does not
    # take the Request. Same shape as /process, /shell, /compress and /segment.
    if oidc_verifier is not None:
        try:
            oidc_verifier.verify(request.headers.get("Authorization"))
        except OIDCError as exc:
            logger.warning("OIDC rejected: %s %s", exc.code, exc.detail)
            return JSONResponse(
                status_code=401,
                content={"error": exc.code, "detail": exc.detail},
            )

    from privacy import is_suppressed_label

    asked = list(dict.fromkeys(c.strip() for c in req.concepts if c.strip()))
    # `person` is a suppression-only concept (0089): segmented so the shell can
    # exclude it, never shipped. This route WRITES a mask per instance per
    # frame, so tracking one would put person rasters in a bucket — which is
    # the thing 0089 exists to prevent, arriving through a probe rather than
    # through the pipeline. /segment has to partition after the fact because
    # one prompt returns every class at once; here the concepts are explicit
    # and one per pass, so refusal is exact and happens before any GPU work.
    refused = [c for c in asked if is_suppressed_label(c)]
    if refused:
        logger.warning("track probe: refused suppressed concepts %s", refused)
    asked = [c for c in asked if not is_suppressed_label(c)]
    concepts = asked[:MAX_CONCEPTS_PER_CALL]
    # A cap that truncates without saying so reads downstream as "this capture
    # contains no sofa" rather than "nobody looked for one".
    dropped = asked[MAX_CONCEPTS_PER_CALL:]
    if dropped:
        logger.warning("track probe: dropped %d concepts over the cap: %s", len(dropped), dropped)
    if not concepts:
        return JSONResponse(
            status_code=422,
            content={"error": "no usable concepts", "refused_suppressed": refused},
        )

    bundle = CaptureBundle()
    bundle.ParseFromString(_download_gcs_uri(req.bundle_uri))
    prefix = _bundle_prefix(req.bundle_uri)

    if req.frame_indices:
        # SORTED, always. The frame list IS the video: the tracker's memory
        # carries forward from one entry to the next, so an out-of-order list
        # asks it to follow a scene that jumps around in time. Capture order is
        # the only order that means anything here, and a caller who passes
        # indices in some other order almost certainly did not intend to.
        wanted = sorted(dict.fromkeys(req.frame_indices))
        by_index = {f.frame_index: f for f in bundle.frames}
        frames = [by_index[i] for i in wanted if i in by_index]
    else:
        frames = list(bundle.frames)
    frames = frames[:MAX_FRAMES_PER_CALL]
    if not frames:
        return JSONResponse(status_code=422, content={"error": "no frames selected"})

    t0 = time.time()
    images, indices, failures = _fetch_frames(prefix, frames, _download_gcs_uri)
    if not images:
        return JSONResponse(
            status_code=200,
            content={
                "scene_id": req.scene_id,
                "error": "no frame downloaded or decoded",
                "frame_failures": failures,
            },
        )
    t_fetch = time.time() - t0

    base = f"scenes/{req.scene_id}/{PROBE_PREFIX}"
    width, height = images[0].size

    t0 = time.time()
    state = sam3_video_model.open_video(images)
    t_open = time.time() - t0

    concepts_out: list[dict[str, Any]] = []
    try:
        for concept in concepts:
            t0 = time.time()
            try:
                tracked = sam3_video_model.track_concept(
                    state,
                    concept,
                    prompt_frame=req.prompt_frame_position,
                    output_prob_thresh=req.output_prob_thresh,
                )
            except Exception as exc:
                logger.exception("[track] concept %r raised", concept)
                concepts_out.append(
                    {"concept": concept, "ok": False, "error": f"{type(exc).__name__}: {exc}"}
                )
                continue
            elapsed = time.time() - t0

            # Position in the tracked sequence -> capture frame index. Every
            # number that leaves this route is in capture frame indices; the
            # sequence position is an internal detail of one propagation.
            rows: list[dict[str, Any]] = []
            masks: dict[str, np.ndarray] = {}
            mask_shape: list[int] | None = None
            for pos, dets in sorted(tracked.items()):
                if pos < 0 or pos >= len(indices):
                    continue
                fidx = indices[pos]
                for det in dets:
                    oid = det["obj_id"]
                    rows.append({
                        "frame_index": fidx,
                        "obj_id": oid,
                        "prob": round(det["prob"], 5),
                        "bbox_px": [round(v, 2) for v in det["bbox_px"]],
                        "area_px": det["area_px"],
                    })
                    # packbits is 1-D, so the raster's shape has to travel with
                    # it or nothing can unpack it back into a mask.
                    masks[f"f{fidx:06d}_o{oid:04d}"] = det["mask_small"]
                    mask_shape = det["mask_small_shape"]
            if mask_shape is not None:
                masks["mask_shape"] = np.asarray(mask_shape, dtype=np.int32)

            per_object: dict[int, dict[str, Any]] = {}
            for r in rows:
                e = per_object.setdefault(
                    r["obj_id"],
                    {"obj_id": r["obj_id"], "frames": [], "areas": [], "probs": []},
                )
                e["frames"].append(r["frame_index"])
                e["areas"].append(r["area_px"])
                e["probs"].append(r["prob"])

            slug = _slug(concept)
            tracks_uri = _gcs_upload_for_scene(
                f"gs://{outputs_bucket}/",
                f"{base}/{slug}/tracks.json",
                json.dumps({
                    "concept": concept,
                    "image_size": [width, height],
                    "frame_indices": indices,
                    "mask_stride": MASK_STRIDE,
                    "detections": rows,
                }).encode(),
                "application/json",
            )
            buf = io.BytesIO()
            np.savez_compressed(buf, **masks)
            masks_uri = _gcs_upload_for_scene(
                f"gs://{outputs_bucket}/",
                f"{base}/{slug}/masks.npz",
                buf.getvalue(),
                "application/octet-stream",
            )

            objects = [
                {
                    "obj_id": o["obj_id"],
                    "n_frames": len(o["frames"]),
                    "first_frame": min(o["frames"]),
                    "last_frame": max(o["frames"]),
                    "median_area_px": int(np.median(o["areas"])),
                    "max_area_px": int(max(o["areas"])),
                    "mean_prob": round(float(np.mean(o["probs"])), 4),
                }
                for o in sorted(per_object.values(), key=lambda e: -len(e["frames"]))
            ]
            logger.info(
                "track probe: scene=%s concept=%r objects=%d detections=%d %.1fs",
                req.scene_id, concept, len(objects), len(rows), elapsed,
            )
            concepts_out.append({
                "concept": concept,
                "ok": True,
                "seconds": round(elapsed, 1),
                "n_objects": len(objects),
                "n_detections": len(rows),
                "objects": objects,
                "tracks_gcs_uri": tracks_uri,
                "masks_gcs_uri": masks_uri,
            })
    finally:
        sam3_video_model.close_video(state)

    summary = {
        "scene_id": req.scene_id,
        # Which revision answered. The `candidate` tag is one mutable pointer
        # shared by every concurrent lane (0275), so a probe can authenticate
        # correctly and run against a revision another lane deployed — and
        # nothing in the output would say so. K_REVISION is set by Cloud Run.
        "revision": os.environ.get("K_REVISION", "unknown"),
        "prefix": f"gs://{outputs_bucket}/{base}/",
        "n_frames": len(images),
        "frame_indices": indices,
        "image_size": [width, height],
        "seconds_fetch": round(t_fetch, 1),
        "seconds_open_video": round(t_open, 1),
        "frame_failures": failures,
        "concepts_dropped_over_cap": dropped,
        "concepts_refused_suppressed": refused,
        "concepts": concepts_out,
    }
    _gcs_upload_for_scene(
        f"gs://{outputs_bucket}/",
        f"{base}/summary-{int(time.time())}.json",
        json.dumps(summary).encode(),
        "application/json",
    )
    return JSONResponse(status_code=200, content=summary)
