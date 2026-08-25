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


class SegmentRequest(BaseModel):
    """Explicit frames, because the whole point is reaching ones the sampler
    did not choose."""

    scene_id: str
    bundle_uri: str
    frame_indices: list[int] = Field(..., min_length=1)
    object_prompt: str | None = None
    write_png: bool = True


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
    from process_receiver import (
        _bundle_prefix,
        _download_gcs_uri,
        _gcs_upload_for_scene,
    )
    from privacy import masks_npz_bytes, partition_detections, segmentation_prompt, suppressed_union
    from PIL import Image
    from roomstudio_schemas import CaptureBundle

    if oidc_verifier is not None:
        err = await oidc_verifier.verify(request)
        if err is not None:
            return err

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
            detections = sam3_model.segment(pil, segmentation_prompt(prompt))
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
