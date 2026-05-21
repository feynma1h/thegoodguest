"""SAM 3 wrapper: open-vocabulary segmentation by text prompt."""
from __future__ import annotations

import sys
from contextlib import nullcontext
from typing import Any

import numpy as np
import torch
from PIL import Image

# SAM 3 is installed as an editable package at /opt/sam3
sys.path.insert(0, "/opt/sam3")

# NOTE: these import paths are best-guess based on the model card snippet.
# May need adjustment after first deploy; see services/perception/README.md.
from sam3.model_builder import build_sam3_image_model  # noqa: E402
from sam3.model.sam3_image_processor import Sam3Processor  # noqa: E402


class SAM3Model:
    """Thin wrapper around SAM 3 image model. One instance per container."""

    def __init__(self):
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

                for j, (m, b, s) in enumerate(zip(masks, boxes, scores, strict=False)):
                    mask_np = m.cpu().numpy() if hasattr(m, "cpu") else np.asarray(m)
                    # SAM 3 returns masks with a leading singleton channel dim
                    # (e.g. (1, H, W)). SAM 3D's reconstruct path expects 2D
                    # (H, W) masks, and np.concatenate downstream fails with
                    # "input arrays must have same number of dimensions" if
                    # extra singleton dims survive. Squeeze them.
                    mask_np = np.squeeze(mask_np)
                    if mask_np.ndim != 2:
                        print(
                            f"[sam3] class '{cls}' instance {j}: unexpected mask "
                            f"shape after squeeze: {mask_np.shape}; skipping",
                            flush=True,
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
            except Exception as e:
                print(f"[sam3] class '{cls}' raised: {e}", flush=True)

        objects.sort(key=lambda o: -o["score"])
        return objects