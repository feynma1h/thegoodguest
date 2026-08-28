"""Segmentation-only probe: SAM 3 on named frames, no reconstruction.

WHY THIS EXISTS. Judging whether a different frame would produce a better
object begins with a question that costs almost nothing to answer: what does
SAM 3 actually see there? The mask IS SAM 3D's input — alpha is the mask
(`models/sam3d.py`) — so a shredded or truncated mask settles the question
before a single reconstruction runs. `/process` cannot answer it: its request
carries only {scene_id, bundle_uri}, it re-runs the census sampler, and it
always reconstructs. A frame the sampler did not pick is unreachable.

So this route takes an EXPLICIT frame list, runs pass 1 only, and returns what
the model saw. SAM 3 is ~4 s a frame against ~25 s an object for SAM 3D, and
this never loads SAM 3D at all — which also saves its ~124 s cold load.

TWO THINGS IT DELIBERATELY DOES NOT DO, both to keep it unable to affect a
room a person can see:

  1. **It never writes under `scenes/{scene_id}/frames/`.** Everything lands in
     `scenes/{scene_id}/segment_probe/`. A `masks.npz` written into the real
     frame prefix would be read as production cache by the next `/process`
     (`Frame N cache hit`), so a probe of an unsampled frame could silently
     become pipeline state. The prefix is the boundary.
  2. **It never touches Firestore.** No claim, no lease, no status. The scene
     is read-only here, so a probe cannot regress a `ready` room the way a
     re-drive does.

It also renders a PNG per detection — the frame with the mask lit beside the
RGBA cut-out the model would receive — because the artifact this exists to
produce is something a person looks at, and an .npz is not that.
"""

from __future__ import annotations

import io
import logging
from typing import Any

import numpy as np
from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Everything this route writes lives under this prefix, never under frames/.
PROBE_PREFIX = "segment_probe"

MAX_FRAMES_PER_CALL = 24


def click_refine(sam3_model, pil, detections, seed_index: int, rounds: int,
                 extra_click: list[int] | None = None) -> dict | None:
    """Seed SAM 3's visual path with one mask, click in its own leftover, repeat.

    The loop the operator specified, with one change: the candidate taken each
    round is the HIGHEST-SCORING, not the largest. Upstream says to select on
    the model's predicted quality, and the largest candidate is the "object plus
    surroundings" reading — the merge that 0198 measured at 113,465 px with a
    chair base and a stool absorbed.

    The mask prompt is 288x288, not the 256 every upstream docstring names.
    SAM's prompt encoder sets `mask_input_size = 4 * image_embedding_size` and
    this tracker runs at 1008/14, so the grid is 72 and the mask must be 288.
    The 256 in those docstrings is SAM 2's number (1024/16 -> 64 -> 256),
    inherited verbatim and stale. Passing 256 dies in the decoder with "The size
    of tensor a (72) must match the size of tensor b (64) at non-singleton
    dimension 3" — measured on a live GPU before the sizes were read.

    After round 0 the mask prompt is the model's OWN low-res logits from the
    previous round, which upstream says need no transformation. Points
    accumulate alongside, which is SAM's canonical interactive form.

    Records every round and decides nothing. Whether growth is acceptable is a
    guard, the guard has been the weak link three times in this investigation,
    and it belongs where it can be changed without a GPU rebuild.
    """
    import numpy as np

    if seed_index >= len(detections):
        return None
    seed = np.asarray(detections[seed_index]["mask"], dtype=bool)
    accepted = seed.copy()
    others = [
        np.asarray(d["mask"], dtype=bool)
        for i, d in enumerate(detections) if i != seed_index
    ]
    rounds_out, stack = [], []
    # Every candidate, not only the winner. Keeping just the chosen mask made
    # "would the runner-up have been better" unanswerable without another GPU
    # run — which is exactly the question the first run raised.
    all_cands, all_scores = [], []
    # The first click is the seed mask's own interior — the pixel nearest its
    # centroid that is actually IN the mask, because a centroid can fall in the
    # hole of a concave shape and this desk's mask is concave.
    ys0, xs0 = np.nonzero(seed)
    cy, cx = float(ys0.mean()), float(xs0.mean())
    k = int(np.argmin((xs0 - cx) ** 2 + (ys0 - cy) ** 2))
    points = [(float(xs0[k]), float(ys0[k]))]
    labels = [1]
    if extra_click is not None and len(extra_click) == 2:
        points.append((float(extra_click[0]), float(extra_click[1])))
        labels.append(1)
    carry = None      # the chosen candidate's low-res logits, round to round

    for r in range(max(1, rounds)):
        got = sam3_model.refine_with_points(
            pil, list(points), list(labels),
            seed_mask=seed if carry is None else None,
            mask_logits=carry,
            multimask_output=True,
        )
        if got is None:
            break
        masks, scores, low_res = got
        best = masks[0]                       # highest-scoring, not largest
        grew = best & ~accepted
        rec = {
            "round": r,
            "scores": [round(float(s), 4) for s in scores],
            "candidate_px": [int(m.sum()) for m in masks],
            "chosen_px": int(best.sum()),
            "accepted_px": int(accepted.sum()),
            "growth_px": int(grew.sum()),
            "points": [[int(x), int(y)] for x, y in points],
            "mask_prompt": "seed" if carry is None else "previous round",
        }
        # how much of any OTHER detection the growth covers — the guard's input
        worst, who = 0.0, None
        for j, o in enumerate(others):
            n = int(o.sum())
            if n and grew.any():
                sh = int((grew & o).sum()) / n
                if sh > worst:
                    worst, who = sh, j
        rec["worst_other_covered"] = round(worst, 4)
        rec["worst_other_index"] = who
        rounds_out.append(rec)
        stack.append(best)
        all_cands.append(np.stack([np.asarray(c, dtype=bool) for c in masks]))
        all_scores.append([float(x) for x in scores])

        # the next click goes in the leftover, and ACCUMULATES — SAM's
        # interactive form is a growing point set, not one click at a time
        leftover = best & ~accepted
        if not leftover.any():
            break
        ys, xs = np.nonzero(leftover)
        my, mx = float(ys.mean()), float(xs.mean())
        j = int(np.argmin((xs - mx) ** 2 + (ys - my) ** 2))
        points.append((float(xs[j]), float(ys[j])))
        labels.append(1)
        carry = low_res[0]          # the chosen candidate's own logits
        accepted = best

    if not stack:
        return None
    buf = io.BytesIO()
    np.savez_compressed(
        buf, masks=np.stack(stack), seed=seed,
        seed_index=np.asarray([seed_index], dtype=np.int32),
        # (rounds, candidates, H, W) and (rounds, candidates). `masks` above is
        # candidate 0 of each round — the chosen one — kept for compatibility.
        candidates=np.stack(all_cands),
        candidate_scores=np.asarray(all_scores, dtype=np.float32),
    )
    return {"rounds": rounds_out, "npz": buf.getvalue()}


def probs_npz_bytes(detections: list) -> bytes | None:
    """One frame's mask PROBABILITY maps, quantised to uint8, in detection
    order — or None when no detection carries one.

    Quantised because the question these answer is "where would the boundary be
    at a different cut", and 1/255 is finer than any threshold anyone would
    choose. Full float32 at 1920x1440 is 11 MB per detection; this is 2.7 MB
    before compression and reconstructs the cut exactly at every multiple of
    1/255.

    Deliberately a SEPARATE file from masks.npz: that writer's bytes are
    load-bearing (decision 0089 keeps them identical to the pre-suppression
    writer) and production reads it on every warm re-drive.
    """
    import numpy as np

    # Indexed by enumeration, never by list.index(): these dicts hold numpy
    # arrays, and `==` on them raises rather than comparing.
    keep = [(i, d) for i, d in enumerate(detections) if d.get("mask_prob") is not None]
    if not keep:
        return None
    stack = np.stack([
        np.clip(np.asarray(d["mask_prob"], dtype=np.float32) * 255.0, 0, 255).astype(np.uint8)
        for _, d in keep
    ])
    idx = np.asarray([i for i, _ in keep], dtype=np.int32)
    buf = io.BytesIO()
    np.savez_compressed(buf, probs=stack, mask_index=idx)
    return buf.getvalue()


class SegmentRequest(BaseModel):
    """Explicit frames, because the whole point is reaching ones the sampler
    did not choose."""

    scene_id: str
    bundle_uri: str
    frame_indices: list[int] = Field(..., min_length=1)
    object_prompt: str | None = None
    write_png: bool = True
    # Also write the per-pixel probability map each binary mask was thresholded
    # from, so the 0.5 cut can be re-examined offline without another GPU run.
    write_prob: bool = False
    # Click-refinement loop: seed SAM 3's VISUAL path with one detection's mask,
    # click in its own leftover, repeat. Every round is recorded; nothing is
    # decided here — the guard belongs offline where it can change without a
    # rebuild.
    refine_seed_mask: int | None = None
    refine_rounds: int = 3
    # An extra opening click, in ORIGINAL image pixels (x, y). The loop's own
    # first click lands in the seed's interior, which asks "what object is
    # here" and can only return the object it already has. A click placed on
    # the part that is MISSING is a different question, and it is the one this
    # investigation could not ask until the part had been located.
    refine_click: list[int] | None = None


def _mask_panels(pil, mask: np.ndarray, suppressed: np.ndarray | None):
    """(frame with the mask lit, RGBA cut-out) — the two panels a person
    needs to judge a mask: where it is, and what the model would receive."""
    from PIL import Image

    rgb = np.asarray(pil.convert("RGB"))
    if mask.shape != rgb.shape[:2]:
        m = Image.fromarray((mask * 255).astype(np.uint8)).resize(pil.size, Image.NEAREST)
        mask = np.asarray(m) > 127

    lit = np.where(mask[..., None], rgb, (rgb * 0.28).astype(np.uint8))
    if suppressed is not None and suppressed.shape == mask.shape:
        # Tint what privacy removed, so a hole punched by 0089 is legible as
        # suppression rather than read as a segmentation failure.
        tint = np.array([200, 60, 50], dtype=np.uint8)
        lit = np.where(
            (suppressed & ~mask)[..., None], (lit * 0.5 + tint * 0.5).astype(np.uint8), lit
        )
    panel_a = Image.fromarray(lit)

    ys, xs = np.where(mask)
    if len(ys) == 0:
        return panel_a, None
    y0, y1, x0, x1 = int(ys.min()), int(ys.max()), int(xs.min()), int(xs.max())
    rgba = np.dstack([rgb, (mask * 255).astype(np.uint8)])
    return panel_a, Image.fromarray(rgba, "RGBA").crop((x0, y0, x1 + 1, y1 + 1))


def _sheet_png(pil, mask, suppressed, caption: str) -> bytes:
    """One PNG: the lit frame beside the cut-out, on a checkerboard so an
    absent alpha reads as absent rather than as white geometry."""
    from PIL import Image, ImageDraw

    panel_a, cut = _mask_panels(pil, mask, suppressed)
    H = 620
    a = panel_a.resize((max(1, int(panel_a.width * H / panel_a.height)), H))
    if cut is None:
        b = Image.new("RGB", (H, H), (238, 238, 238))
    else:
        sq = 16
        bg = Image.new("RGB", cut.size, (235, 235, 235))
        d0 = ImageDraw.Draw(bg)
        for yy in range(0, cut.height, sq):
            for xx in range(0, cut.width, sq):
                if (xx // sq + yy // sq) % 2:
                    d0.rectangle([xx, yy, xx + sq, yy + sq], fill=(205, 205, 205))
        bg.paste(cut, (0, 0), cut)
        b = bg.resize((max(1, int(bg.width * H / bg.height)), H))

    sheet = Image.new("RGB", (a.width + b.width + 30, H + 46), (250, 250, 250))
    sheet.paste(a, (0, 46))
    sheet.paste(b, (a.width + 30, 46))
    d = ImageDraw.Draw(sheet)
    d.text((10, 14), caption, fill=(30, 30, 30))
    d.text((a.width + 34, 14), "what SAM 3D would receive (alpha = mask)", fill=(90, 90, 90))
    out = io.BytesIO()
    sheet.save(out, format="PNG")
    return out.getvalue()


async def handle_segment(
    request: Request,
    req: SegmentRequest,
    *,
    oidc_verifier,
    outputs_bucket: str,
    sam3_model,
    object_prompt: str,
) -> JSONResponse:
    """Segment the named frames and report what SAM 3 found.

    Returns 200 with a per-frame, per-detection summary. Poison inputs (a
    frame index outside the bundle, an undecodable image) are reported in the
    body rather than raised: this is a probe, and a partial answer beats none.
    """
    from oidc import OIDCError
    from PIL import Image
    from privacy import masks_npz_bytes, partition_detections, segmentation_prompt, suppressed_union
    from process_receiver import (
        _bundle_prefix,
        _download_gcs_uri,
        _gcs_upload_for_scene,
    )
    from roomstudio_schemas import CaptureBundle

    # verify() takes the HEADER VALUE and raises; it is not async and does not
    # take the Request. Same shape as /process, /shell and /compress.
    if oidc_verifier is not None:
        try:
            oidc_verifier.verify(request.headers.get("Authorization"))
        except OIDCError as exc:
            logger.warning("OIDC rejected: %s %s", exc.code, exc.detail)
            return JSONResponse(
                status_code=401,
                content={"error": exc.code, "detail": exc.detail},
            )

    wanted = list(dict.fromkeys(req.frame_indices))[:MAX_FRAMES_PER_CALL]
    prompt = req.object_prompt or object_prompt

    bundle = CaptureBundle()
    bundle.ParseFromString(_download_gcs_uri(req.bundle_uri))
    prefix = _bundle_prefix(req.bundle_uri)
    by_index = {f.frame_index: f for f in bundle.frames}

    frames_out: list[dict[str, Any]] = []
    for fi in wanted:
        frame = by_index.get(fi)
        if frame is None:
            frames_out.append({"frame_index": fi, "ok": False, "error": "not in bundle"})
            continue
        try:
            raw = _download_gcs_uri(prefix + frame.rgb_gcs_path)
            pil = Image.open(io.BytesIO(raw)).convert("RGB")
        except Exception as exc:
            frames_out.append({"frame_index": fi, "ok": False, "error": f"image: {exc}"})
            continue

        try:
            detections = sam3_model.segment(
                pil, segmentation_prompt(prompt), want_prob=req.write_prob
            )
        except Exception as exc:
            frames_out.append({"frame_index": fi, "ok": False, "error": f"sam3: {exc}"})
            continue
        detections, suppressed = partition_detections(detections)
        union = suppressed_union(suppressed)
        if suppressed:
            logger.info(
                "segment probe: frame %d scene %s suppressed=%d labels=%s",
                fi, req.scene_id, len(suppressed),
                sorted({d["label"] for d in suppressed}),
            )

        base = f"scenes/{req.scene_id}/{PROBE_PREFIX}/{fi:04d}"
        masks_uri = _gcs_upload_for_scene(
            f"gs://{outputs_bucket}/", f"{base}/masks.npz",
            masks_npz_bytes(detections, suppressed), "application/octet-stream",
        )

        probs_uri = None
        if req.write_prob:
            raw = probs_npz_bytes(detections)
            if raw is not None:
                probs_uri = _gcs_upload_for_scene(
                    f"gs://{outputs_bucket}/", f"{base}/probs.npz",
                    raw, "application/octet-stream",
                )

        refine_out = None
        if req.refine_seed_mask is not None:
            got = click_refine(
                sam3_model, pil, detections, req.refine_seed_mask, req.refine_rounds,
                extra_click=req.refine_click,
            )
            if got is not None:
                _gcs_upload_for_scene(
                    f"gs://{outputs_bucket}/",
                    f"{base}/refine_{req.refine_seed_mask:02d}.npz",
                    got["npz"], "application/octet-stream",
                )
                refine_out = got["rounds"]
                logger.info("click refine: frame %d rounds=%s", fi, refine_out)

        objs = []
        for i, det in enumerate(detections):
            mask = np.asarray(det["mask"], dtype=bool)
            area = int(mask.sum())
            entry = {
                "mask_index": i,
                "label": det.get("label"),
                "score": det.get("score"),
                "mask_px": area,
                "mask_frac_of_frame": round(area / float(mask.size), 5) if mask.size else 0.0,
            }
            if req.write_png and area:
                cap = (
                    f"{det.get('label')}   frame {fi}, mask {i}   "
                    f"{100.0 * area / mask.size:.1f}% of frame"
                )
                entry["png_gcs_uri"] = _gcs_upload_for_scene(
                    f"gs://{outputs_bucket}/",
                    f"{base}/{i:02d}_{str(det.get('label','obj')).replace('/', '_')}.png",
                    _sheet_png(pil, mask, union, cap), "image/png",
                )
            objs.append(entry)

        frames_out.append({
            "frame_index": fi,
            "ok": True,
            "image_size": [pil.width, pil.height],
            "masks_gcs_uri": masks_uri,
            **({"probs_gcs_uri": probs_uri} if probs_uri else {}),
            **({"refine": refine_out} if refine_out else {}),
            "suppressed_count": len(suppressed),
            "suppressed_px": int(union.sum()) if union is not None else 0,
            "objects": objs,
        })

    logger.info(
        "segment probe: scene=%s frames=%d detections=%d",
        req.scene_id, len(frames_out),
        sum(len(f.get("objects", [])) for f in frames_out),
    )
    return JSONResponse(
        status_code=200,
        content={
            "scene_id": req.scene_id,
            "prefix": f"gs://{outputs_bucket}/scenes/{req.scene_id}/{PROBE_PREFIX}/",
            "frames": frames_out,
        },
    )
