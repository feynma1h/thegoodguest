"""VGGT-1B wrapper: scene-level geometric reconstruction from N photos."""
from __future__ import annotations

import sys
from typing import Any

import numpy as np
import torch
from huggingface_hub import hf_hub_download

# VGGT is installed as an editable package in the container at /opt/vggt
sys.path.insert(0, "/opt/vggt")

from vggt.models.vggt import VGGT  # noqa: E402
from vggt.utils.load_fn import load_and_preprocess_images  # noqa: E402


class VGGTModel:
    """Thin wrapper around the VGGT model. One instance per container."""

    def __init__(self, device: str, dtype: torch.dtype):
        self.device = device
        self.dtype = dtype
        weights = hf_hub_download(
            repo_id="facebook/VGGT-1B", filename="model.pt", cache_dir="/models"
        )
        self.model = VGGT()
        self.model.load_state_dict(torch.load(weights, map_location=device, weights_only=False))
        self.model = self.model.to(device).eval()

    def infer(self, image_paths: list[str]) -> dict[str, Any]:
        """Run VGGT on the given images.

        Returns a dict containing:
            world_points:       (1, N, H, W, 3) world-space 3D points per pixel
            world_points_conf:  (1, N, H, W)    confidence per pixel
            pose_enc:           (1, N, 9)       camera pose encoding per view
            _input_tensor:      (N, 3, H, W)    the preprocessed input images
        """
        imgs = load_and_preprocess_images(image_paths).to(self.device)
        with torch.no_grad():
            if self.device == "cuda":
                with torch.amp.autocast("cuda", dtype=self.dtype):
                    predictions = self.model(imgs)
            else:
                predictions = self.model(imgs)
        predictions["_input_tensor"] = imgs
        return predictions

    @staticmethod
    def predictions_to_pointcloud(
        predictions: dict[str, Any], conf_percentile: float = 50.0
    ) -> tuple[np.ndarray, np.ndarray]:
        """Convert VGGT predictions to (points, colors) numpy arrays."""
        points = predictions["world_points"].squeeze(0).cpu().float().numpy()
        confs = predictions["world_points_conf"].squeeze(0).cpu().float().numpy()
        imgs = predictions["_input_tensor"].cpu().float().numpy().transpose(0, 2, 3, 1)

        threshold = np.percentile(confs, conf_percentile)
        mask = confs > threshold
        return points[mask], (imgs[mask].clip(0, 1) * 255).astype(np.uint8)
