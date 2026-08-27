"""SAM 3 wrapper: open-vocabulary segmentation by text prompt."""
from __future__ import annotations

import logging
import os
import sys
from contextlib import nullcontext
from typing import Any

import numpy as np
import torch
from PIL import Image

logger = logging.getLogger(__name__)


# SAM 3's VISUAL path (predict_inst) needs the interactive predictor, and
# `build_sam3_image_model` leaves it OFF by default — with it off,
# `model.inst_interactive_predictor` is None and predict_inst raises
# `AttributeError: 'NoneType' object has no attribute 'model'`, which is how
# this was found. Enabling it builds the video tracker and loads its weights
# from the SAME facebook/sam3 checkpoint (`tracker.*` keys), so nothing extra
# downloads — but it does occupy GPU memory, and 0228 measured headroom as the
# binding constraint on this card: the models already hold ~16.4 GiB with about
# 5.26 left, against forward passes peaking at 5.23-6.43. So it stays OFF unless
# asked for, and turning it on in production wants that measurement first.
INTERACTIVE_ENABLED = os.environ.get("PERCEPTION_SAM3_INTERACTIVE", "0") == "1"


class SAM3Model:
    """Thin wrapper around SAM 3 image model. One instance per container."""

    def __init__(self):
        # SAM 3 is installed editable from /opt/sam3-repo (Dockerfile), so the
        # `sam3` package is already importable and this insert is belt-and-
        # braces. It named /opt/sam3 until 2026-08-28 — a directory the image
        # has never contained, which made the insert a silent no-op and sent
        # anyone looking for the source to a path that does not exist. A
        # readable copy of what this file calls is vendored at
        # ../upstream/sam3/, pinned to the commit the Dockerfile clones.
        #
        # The imports are deferred to __init__ (not module level) so that
        # importing models.sam3 does NOT trigger CUDA initialisation at server
        # startup. The heavy work happens only when the first request
        # constructs this instance. See docs/decisions/0007.
        sys.path.insert(0, "/opt/sam3-repo")
        from sam3.model.sam3_image_processor import Sam3Processor  # noqa: PLC0415
        from sam3.model_builder import build_sam3_image_model  # noqa: PLC0415

        self.model = build_sam3_image_model(
            enable_inst_interactivity=INTERACTIVE_ENABLED
        )
        self.processor = Sam3Processor(self.model)
        # SAM 3's Sam3Processor.set_image does NOT wrap the encoder in autocast,
        # so the vitdet linear layers (fp32 weights) get fed bf16 activations
        # and crash with "mat1 and mat2 must have the same dtype". Upstream's
        # own notebooks (sam3_agent.ipynb) work around this with a global
        # torch.autocast(...).__enter__(); we scope it to per-call to avoid
        # polluting SAM 3D Objects, which has its own dtype regime.
        # See facebookresearch/sam3#526.
        self._use_bf16_autocast = torch.cuda.is_available()

    def _autocast(self):
        if self._use_bf16_autocast:
            return torch.autocast(device_type="cuda", dtype=torch.bfloat16)
        return nullcontext()

    def segment(
        self, image: Image.Image, prompt: str, *, want_prob: bool = False
    ) -> list[dict[str, Any]]:
        """Run SAM 3 with a comma-separated text prompt on a single image.

        Returns a list of detected object instances, each:
            {label, instance_idx, bbox: [x1,y1,x2,y2], score, mask: HxW bool}
        Sorted by score descending.

        WHAT `score` IS, read from the pinned processor rather than assumed
        (../upstream/sam3/sam3_image_processor.py, and upstream/README.md):
        `out_logits.sigmoid() * presence_logit_dec.sigmoid()` — a per-query
        match probability times a per-image presence probability for the
        prompted concept. It is a DETECTION confidence. Nothing in it measures
        mask quality or completeness, and there is no IoU head to ask.
        Upstream drops everything below `confidence_threshold` (default 0.5)
        before returning, which is why no score here is under ~0.504.

        Upstream applies NO NMS and NO deduplication, so several instances of
        one object are expected output and reconciling them is our job —
        `fusion._dedup_same_frame` is where that happens.

        `want_prob` additionally returns `mask_prob`, the per-pixel probability
        the binary mask is thresholded from. Off by default because it is a
        full-resolution float array per detection and production has no use for
        it; the probe route asks for it. Upstream computes
        `masks = masks_logits > 0.5` with a bare literal — `masks_logits` is
        post-sigmoid despite its name, so 0.5 is a probability and there is no
        parameter behind it. A part the model scored just under it is deleted
        with no record, and this is how that record is recovered.
        """
        with self._autocast():
            inference_state = self.processor.set_image(image)
        classes = [c.strip() for c in prompt.split(",") if c.strip()]

        objects: list[dict[str, Any]] = []
        for cls in classes:
            try:
                with self._autocast():
                    out = self.processor.set_text_prompt(state=inference_state, prompt=cls)
                masks = out.get("masks", [])
                boxes = out.get("boxes", [])
                scores = out.get("scores", [])
                # Same length and order as `masks` — upstream sets both from
                # one array in the same statement.
                probs = out.get("masks_logits", []) if want_prob else []

                # These are parallel arrays (one entry per detected instance).
                # A length mismatch means an upstream anomaly; surface it and
                # skip the class rather than silently truncating/misindexing.
                if not (len(masks) == len(boxes) == len(scores)):
                    logger.warning(
                        "[sam3] class '%s': parallel array length mismatch "
                        "masks=%d boxes=%d scores=%d; skipping class",
                        cls, len(masks), len(boxes), len(scores),
                    )
                    continue

                for j, (m, b, s) in enumerate(zip(masks, boxes, scores, strict=True)):
                    mask_np = m.cpu().numpy() if hasattr(m, "cpu") else np.asarray(m)
                    # SAM 3 returns masks with a leading singleton channel dim
                    # (e.g. (1, H, W)). SAM 3D's reconstruct path expects 2D
                    # (H, W) masks, and np.concatenate downstream fails with
                    # "input arrays must have same number of dimensions" if
                    # extra singleton dims survive. Squeeze them.
                    mask_np = np.squeeze(mask_np)
                    if mask_np.ndim != 2:
                        logger.warning(
                            "[sam3] class '%s' instance %d: unexpected mask "
                            "shape after squeeze: %s; skipping",
                            cls, j, mask_np.shape,
                        )
                        continue
                    bbox = b.tolist() if hasattr(b, "tolist") else list(b)
                    score = s.item() if hasattr(s, "item") else float(s)

                    entry = {
                        "label": cls,
                        "instance_idx": j,
                        "bbox": bbox,
                        "score": score,
                        "mask": mask_np.astype(bool),
                    }
                    if want_prob and j < len(probs):
                        pr = probs[j]
                        pr = pr.cpu().numpy() if hasattr(pr, "cpu") else np.asarray(pr)
                        pr = np.squeeze(pr)
                        if pr.shape == mask_np.shape:
                            entry["mask_prob"] = pr.astype(np.float32)
                    objects.append(entry)
            except Exception:
                logger.exception("[sam3] class '%s' raised; skipping class", cls)

        objects.sort(key=lambda o: -o["score"])
        return objects

    def refine_with_points(
        self,
        image: Image.Image,
        seed_mask: np.ndarray | None,
        points: list[tuple[float, float]],
        labels: list[int],
        *,
        multimask_output: bool = True,
    ) -> tuple[list[np.ndarray], list[float]] | None:
        """SAM 3's VISUAL path: clicks, optionally seeded with a mask.

        This is the OTHER half of SAM 3 (upstream/README.md). `segment` above
        drives the detector — text in, every matching instance out. This drives
        the tracker — points in, ONE instance out, with the model's own quality
        score per candidate. Same model object, same `inference_state`; nothing
        extra is loaded.

        Returns ([masks], [scores]) sorted best-first by the model's score, or
        None when the model returns nothing.

        `seed_mask` is off-label and says so: upstream types `mask_input` as
        "a low resolution mask input... typically coming from a PREVIOUS
        prediction iteration", 1x256x256. A binary detector mask is not that, so
        it is resized and mapped to +/-10 logits. That is the conventional
        encoding and it is still an assumption, which is why every round's
        score is recorded rather than trusted.

        Upstream's own guidance on `multimask_output`: three masks help for an
        AMBIGUOUS prompt such as a single click, and "for non-ambiguous prompts,
        such as multiple input prompts, multimask_output=False can give better
        results". Candidates come back ranked by the model's predicted quality,
        which is what upstream says to select on.
        """
        from PIL import Image as _Image

        with self._autocast():
            state = self.processor.set_image(image)

        mask_input = None
        if seed_mask is not None and seed_mask.any():
            lo = np.asarray(
                _Image.fromarray((np.asarray(seed_mask, dtype=bool) * 255).astype(np.uint8))
                .resize((256, 256), _Image.BILINEAR),
                dtype=np.float32,
            ) / 255.0
            mask_input = ((lo * 2.0) - 1.0)[None] * 10.0

        if getattr(self.model, "inst_interactive_predictor", None) is None:
            logger.error(
                "[sam3] predict_inst needs the interactive predictor, which is "
                "off: set PERCEPTION_SAM3_INTERACTIVE=1 (see the note on "
                "INTERACTIVE_ENABLED for what it costs)"
            )
            return None
        try:
            with self._autocast():
                masks, scores, _logits = self.model.predict_inst(
                    state,
                    point_coords=np.asarray(points, dtype=np.float32) if points else None,
                    point_labels=np.asarray(labels, dtype=np.int32) if labels else None,
                    mask_input=mask_input,
                    multimask_output=multimask_output,
                )
        except Exception:
            logger.exception("[sam3] predict_inst failed")
            return None

        out = []
        for m, sc in zip(np.asarray(masks), np.asarray(scores).ravel(), strict=False):
            mm = np.squeeze(np.asarray(m))
            if mm.ndim == 2:
                out.append((float(sc), mm.astype(bool)))
        if not out:
            return None
        out.sort(key=lambda t: -t[0])
        return [m for _s, m in out], [s for s, _m in out]

    def refine_with_box(
        self,
        image: Image.Image,
        label: str,
        box_cxcywh: list[float],
        target_bbox: list[float] | None = None,
    ) -> np.ndarray | None:
        """Re-segment ONE object with a positive box prompt (decision 0198).

        `add_geometric_prompt` is upstream's interactive refinement: it
        appends the box to the state's geometric prompt and re-runs
        grounding on top of the text prompt, so the answer is still "the
        `label` in this picture" rather than a fresh box-driven instance.
        It has been in the image we ship since SAM 3 landed and this wrapper
        had simply never called it.

        `box_cxcywh` is normalized [cx, cy, w, h] — upstream's format, and
        what mask_refine.prompt_box_cxcywh emits. `target_bbox` is the
        original mask's [x0, y0, x1, y1] in pixels; the returned instance is
        the one whose box overlaps it most, because a refined prompt can
        return several instances of the class and only one of them is the
        object we are repairing. Without it the highest-scoring instance is
        taken.

        Returns a 2D bool mask, or None when nothing usable came back —
        the caller keeps the original mask, which is what ships today.
        This re-encodes the image: the segmentation pass's inference state
        is not held across the reconstruction pass, and holding twelve
        frames' encoder state on the GPU costs more than re-running one.
        """
        try:
            with self._autocast():
                state = self.processor.set_image(image)
                self.processor.set_text_prompt(state=state, prompt=label)
                out = self.processor.add_geometric_prompt(
                    box=list(box_cxcywh), label=True, state=state
                )
        except Exception:
            logger.exception("[sam3] refine_with_box failed for label '%s'", label)
            return None

        masks = out.get("masks", []) if isinstance(out, dict) else []
        boxes = out.get("boxes", []) if isinstance(out, dict) else []
        scores = out.get("scores", []) if isinstance(out, dict) else []
        if len(masks) == 0:
            logger.info("[sam3] refine_with_box returned no instance for '%s'", label)
            return None

        best_i, best_key = None, None
        for j in range(len(masks)):
            box = boxes[j] if j < len(boxes) else None
            box = box.tolist() if hasattr(box, "tolist") else box
            score = scores[j] if j < len(scores) else 0.0
            score = score.item() if hasattr(score, "item") else float(score)
            key = (_bbox_iou(box, target_bbox), score) if target_bbox else (0.0, score)
            if best_key is None or key > best_key:
                best_i, best_key = j, key
        if best_i is None:
            return None

        m = masks[best_i]
        mask_np = m.cpu().numpy() if hasattr(m, "cpu") else np.asarray(m)
        mask_np = np.squeeze(mask_np)
        if mask_np.ndim != 2:
            logger.warning(
                "[sam3] refine_with_box: unexpected mask shape %s", mask_np.shape
            )
            return None
        return mask_np.astype(bool)


def _bbox_iou(a, b) -> float:
    """IoU of two [x0, y0, x1, y1] boxes; 0.0 when either is unusable."""
    if a is None or b is None or len(a) != 4 or len(b) != 4:
        return 0.0
    x0 = max(float(a[0]), float(b[0]))
    y0 = max(float(a[1]), float(b[1]))
    x1 = min(float(a[2]), float(b[2]))
    y1 = min(float(a[3]), float(b[3]))
    if x1 <= x0 or y1 <= y0:
        return 0.0
    inter = (x1 - x0) * (y1 - y0)
    area_a = max(0.0, float(a[2]) - float(a[0])) * max(0.0, float(a[3]) - float(a[1]))
    area_b = max(0.0, float(b[2]) - float(b[0])) * max(0.0, float(b[3]) - float(b[1]))
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0
