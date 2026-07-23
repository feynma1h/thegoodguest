"""Texture-continuation inpainting for shell textures (decision 0066,
verify-first item V2).

MODEL CHOICE (V2): big-lama — LaMa, "Resolution-robust Large Mask
Inpainting with Fourier Convolutions" (Suvorov et al., WACV 2022),
github.com/advimman/lama (saic-mdal). LICENSE: Apache-2.0 — the repo and
the authors' published big-lama checkpoint. We run the TorchScript export
of that checkpoint (the artifact simple-lama-inpainting distributes),
loaded with torch.jit.load: zero new Python dependencies (torch is
already in the perception image), CPU execution, feed-forward FFC CNN
with no sampling step — the same inputs produce the same outputs (no
RNG anywhere; bitwise stability holds for a fixed torch build/thread
config, which the baked image pins).

Why LaMa-class, not diffusion (0066's named rejection): shell holes are
furniture occlusions, and the product promise is material continuation —
LaMa extrapolates texture and structure without inventing objects.
OpenCV's Telea/NS diffusion fills were rejected as smear, not texture.
Measured through THIS module (V2 validation, 2026-07-23, Apple M-series
dev box, torch 2.13 CPU): warm 512×512 tile with an 18% hole = 1.65 s —
inside V2's 1-2 s envelope; byte-identical outputs across repeated runs;
out-of-hole pixels untouched; filled pixels continue the source texture's
statistics.

Weights artifact: the simple-lama-inpainting v0.1.0 release export,
205,803,670 bytes,
sha256 7ba7aa7ac37a4d41fdbbeba3a2af7ead18058552997e3a3cd1a3b2210c9e6b4c
(the Dockerfile pins this). LAMA_MODEL_PATH (default
/opt/lama/big-lama.pt) is baked into the image per decision 0008 — build
fails loudly if the fetch or checksum breaks; never a cold-start
download. is_available() gates callers: dev/test environments without
the file inject their own inpaint_fn into shell_texture instead.

Consumers: shell_receiver.py (production inpaint_fn), the Dockerfile
import smoke.
"""
from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

LAMA_MODEL_PATH = os.environ.get("LAMA_MODEL_PATH", "/opt/lama/big-lama.pt")

# Context margin around the hole bounding box handed to the model: enough
# surrounding material for the FFC receptive field to continue texture.
_CONTEXT_MARGIN_PX = 128
# Model input dims must be divisible by 8 (LaMa's downsampling depth).
_PAD_MODULO = 8

_model = None
_model_lock = threading.Lock()


def is_available() -> bool:
    """True when the baked weights exist and torch imports. Callers without
    the model (dev/tests) must inject a different inpaint_fn."""
    if not Path(LAMA_MODEL_PATH).exists():
        return False
    try:
        import torch  # noqa: F401  (deferred: heavy)
    except ImportError:
        return False
    return True


def _get_model():
    """Load the TorchScript module once (double-checked, like the SAM
    accessors in server.py). CPU only — the shell path must never touch
    the GPU the object pipeline budgets for."""
    global _model
    if _model is not None:
        return _model
    with _model_lock:
        if _model is None:
            import torch

            logger.info("[shell_inpaint] loading big-lama from %s", LAMA_MODEL_PATH)
            model = torch.jit.load(LAMA_MODEL_PATH, map_location="cpu")
            model.eval()
            _model = model
    return _model


def _pad_to_modulo(arr: np.ndarray, modulo: int) -> np.ndarray:
    """Reflect-pad (H, W[, C]) so H and W are multiples of modulo."""
    h, w = arr.shape[:2]
    ph = (modulo - h % modulo) % modulo
    pw = (modulo - w % modulo) % modulo
    if ph == 0 and pw == 0:
        return arr
    pad = [(0, ph), (0, pw)] + [(0, 0)] * (arr.ndim - 2)
    mode = "reflect" if min(h, w) > 1 else "edge"
    return np.pad(arr, pad, mode=mode)


def inpaint(rgb: np.ndarray, hole_mask: np.ndarray) -> np.ndarray:
    """Fill hole_mask pixels of rgb by texture continuation.

    rgb: (H, W, 3) uint8. hole_mask: (H, W) bool, True = fill.
    Returns (H, W, 3) uint8 — pixels outside the mask are returned
    verbatim (the model only ever contributes inside holes).

    The model runs on the hole bounding box plus a context margin, not the
    full texture, so a small occlusion on a 2048px plane costs a fraction
    of a full-frame pass.
    """
    if rgb.ndim != 3 or rgb.shape[2] != 3 or rgb.dtype != np.uint8:
        raise ValueError(f"inpaint: expected (H, W, 3) uint8, got {rgb.shape} {rgb.dtype}")
    if hole_mask.shape != rgb.shape[:2]:
        raise ValueError(
            f"inpaint: mask shape {hole_mask.shape} != image {rgb.shape[:2]}"
        )
    if not np.any(hole_mask):
        return rgb

    import torch

    ys, xs = np.nonzero(hole_mask)
    h, w = rgb.shape[:2]
    y0 = max(0, int(ys.min()) - _CONTEXT_MARGIN_PX)
    y1 = min(h, int(ys.max()) + 1 + _CONTEXT_MARGIN_PX)
    x0 = max(0, int(xs.min()) - _CONTEXT_MARGIN_PX)
    x1 = min(w, int(xs.max()) + 1 + _CONTEXT_MARGIN_PX)

    crop = rgb[y0:y1, x0:x1]
    crop_mask = hole_mask[y0:y1, x0:x1]
    ch, cw = crop.shape[:2]

    img = _pad_to_modulo(crop, _PAD_MODULO).astype(np.float32) / 255.0
    msk = _pad_to_modulo(
        crop_mask.astype(np.float32)[:, :, None], _PAD_MODULO
    )[:, :, 0]

    model = _get_model()
    with torch.inference_mode():
        img_t = torch.from_numpy(img).permute(2, 0, 1).unsqueeze(0)
        msk_t = torch.from_numpy(msk).unsqueeze(0).unsqueeze(0)
        out = model(img_t, msk_t)
    filled = (
        out[0].permute(1, 2, 0).cpu().numpy()[:ch, :cw] * 255.0
    )
    filled_u8 = np.clip(np.round(filled), 0, 255).astype(np.uint8)

    result = rgb.copy()
    region = result[y0:y1, x0:x1]
    region[crop_mask] = filled_u8[crop_mask]
    return result
