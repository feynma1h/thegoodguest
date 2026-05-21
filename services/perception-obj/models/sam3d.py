"""SAM 3D Objects wrapper: per-object Gaussian splat reconstruction.

Uses Meta's high-level `Inference` class from notebook/inference.py. We
mirror Meta's `demo.py` import pattern (sys.path.append on the notebook
directory) because SAM 3D's package layout doesn't expose Inference as
part of the installable sam3d_objects package.

The Inference API:
    inference = Inference(config_path, compile=False)
    output = inference(image=rgba_np, mask=mask_np, seed=42)
    output["gs"].save_ply(path)
"""
from __future__ import annotations

import sys
from typing import Any

import numpy as np
from PIL import Image

# SAM 3D Objects ships its high-level Inference class in `notebook/inference.py`
# rather than as part of the installable sam3d_objects package. Match Meta's
# own demo.py pattern: add the notebook directory to sys.path.
_SAM3D_NOTEBOOK = "/opt/sam3d/notebook"
if _SAM3D_NOTEBOOK not in sys.path:
    sys.path.insert(0, _SAM3D_NOTEBOOK)

from inference import Inference as _Sam3dInference  # noqa: E402


class SAM3DModel:
    """Thin wrapper around SAM 3D Objects' high-level Inference class."""

    def __init__(
        self,
        config_path: str = "/opt/sam3d/checkpoints/hf/pipeline.yaml",
        compile: bool = False,
    ):
        self.inference = _Sam3dInference(config_path, compile=compile)

    def reconstruct(
        self, image: Image.Image, mask: np.ndarray, seed: int = 42
    ) -> dict[str, Any]:
        """Run SAM 3D on (image, mask). Returns dict with 'gs' (GaussianSplat)."""
        # Defensive: SAM 3 sometimes returns masks with a leading channel dim
        # (e.g. (1, H, W)). Upstream expects (H, W). Squeeze any singleton dims.
        # sam3.py already does this at the source; this is belt-and-suspenders.
        mask = np.squeeze(np.asarray(mask))
        if mask.ndim != 2:
            raise ValueError(
                f"SAM 3D expects a 2D (H, W) mask; got shape {mask.shape}"
            )
        rgb = np.asarray(image.convert("RGB"))
        alpha = (mask.astype(np.uint8) * 255)[..., None]
        rgba = np.concatenate([rgb, alpha], axis=-1)
        # Use positional args to match Meta's demo/README, which is the only
        # documented call signature. Avoids depending on the internal param
        # names in notebook/inference.py's __call__.
        return self.inference(rgba, mask, seed=seed)