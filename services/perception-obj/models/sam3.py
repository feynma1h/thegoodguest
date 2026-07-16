"""SAM 3 wrapper: open-vocabulary segmentation by text prompt."""
from __future__ import annotations

import logging
import sys
from contextlib import nullcontext
from typing import Any

import numpy as np
import torch
from PIL import Image

logger = logging.getLogger(__name__)


class SAM3Model:
    """Thin wrapper around SAM 3 image model. One instance per container."""

    def __init__(self):
        # SAM 3 is installed as an editable package at /opt/sam3. These imports
        # are deferred to __init__ (not module level) so that importing
        # models.sam3 does NOT trigger CUDA initialisation at server startup.
        # The heavy work happens only when the first request constructs this
        # instance. See docs/decisions/0007.
        sys.path.insert(0, "/opt/sam3")
        from sam3.model_builder import build_sam3_image_model  # noqa: PLC0415
        from sam3.model.sam3_image_processor import Sam3Processor  # noqa: PLC0415

        self.model = build_sam3_image_model()
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

    def segment(self, image: Image.Image, prompt: str) -> list[dict[str, Any]]:
        """Run SAM 3 with a comma-separated text prompt on a single image.

        Returns a list of detected object instances, each:
            {label, instance_idx, bbox: [x1,y1,x2,y2], score, mask: HxW bool}
        Sorted by score descending.
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

                    objects.append({
                        "label": cls,
                        "instance_idx": j,
                        "bbox": bbox,
                        "score": score,
                        "mask": mask_np.astype(bool),
                    })
            except Exception:
                logger.exception("[sam3] class '%s' raised; skipping class", cls)

        objects.sort(key=lambda o: -o["score"])
        return objects