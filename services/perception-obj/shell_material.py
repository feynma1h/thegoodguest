"""Shell material inference: per-plane parametric materials from observed
pixels (decision 0069 — the surface the viewer renders instead of a bake).

Three independent estimators feed one MaterialResult per plane:

  ALBEDO — measured, the recognition anchor. Weighted-median chroma over
  the plane's observed texels (shell_observation's median-selected colors
  + weights), restricted to a high-lightness band around the weighted
  75th-percentile luminance: shadows darken matte surfaces and rarely
  brighten them, so the bright band is the best albedo evidence; a top
  cap excludes blown speculars. Below SHELL_MATERIAL_MIN_TEXELS observed
  texels the estimate is None (the viewer's neutral treatment).
  secondary_hex is deliberately always None in v1 (two-tone separation
  deferred as noisy — the brief's "defer if noisy" clause).

  FAMILY — classified, confidence-gated. The plane's rectified evidence
  crops go to ONE Anthropic vision call (SHELL_MATERIAL_MODEL, default
  claude-sonnet-5) returning constrained JSON {family, confidence} over
  the closed vocabulary (floor: wood|tile|stone|carpet|concrete; wall:
  painted|wallpaper|tile|exposed; plus "other" as the honesty valve for
  materials outside the vocabulary). THE LOAD-BEARING FALLBACK RULE
  (test-pinned): below SHELL_MATERIAL_MIN_CONF, "other", any call
  failure, no evidence crops, or no API key → family = None → the plane
  renders clean matte in the measured albedo. Degrade to clean-neutral,
  never wrong-specific; a missing/failed inference NEVER blocks
  shell.json.

  Note on the 0069 brief's "temperature 0": non-default sampling params
  are rejected (400) on claude-sonnet-5, so temperature is omitted;
  thinking is explicitly disabled (the model's silent default is
  adaptive). Determinism rests on the receiver's write-once noop, with
  MATERIAL_VERSION + model recorded in the doc.

  ROUGHNESS — family→constant lookup, never estimated from pixels
  (estimation is the (c)-era relighting direction). PLANK DIRECTION —
  dominant gradient orientation over the floor's evidence crops when
  family = wood, via the axial (2θ) circular mean; a weak orientation
  consensus yields None.

Pure numpy except the one API call (anthropic SDK, deferred import; the
same >=0.100,<1.0 pin api-public's conversation stage uses). Callers
inject classify_fn in tests; production uses classify_family_via_api.

Consumers: shell_receiver.py, tests/test_shell_material.py.
"""
from __future__ import annotations

import base64
import io
import json
import logging
import math
import os
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from shell_observation import EvidenceCrop, ObservationResult

logger = logging.getLogger(__name__)

MATERIAL_VERSION = 1

FLOOR_FAMILIES = ("wood", "tile", "stone", "carpet", "concrete")
WALL_FAMILIES = ("painted", "wallpaper", "tile", "exposed")

# ---------------------------------------------------------------------------
# Tunables (env-overridable)
# ---------------------------------------------------------------------------

SHELL_MATERIAL_MODEL = os.environ.get("SHELL_MATERIAL_MODEL", "claude-sonnet-5")
SHELL_MATERIAL_MIN_CONF = float(os.environ.get("SHELL_MATERIAL_MIN_CONF", "0.6"))
SHELL_MATERIAL_MIN_TEXELS = int(os.environ.get("SHELL_MATERIAL_MIN_TEXELS", "100"))

# Albedo lightness band around the weighted 75th-percentile luminance:
# below the floor is shadow evidence, above the cap is likely specular.
_ALBEDO_BAND_LO = 0.8
_ALBEDO_BAND_HI = 1.1
_ALBEDO_REF_QUANTILE = 0.75

# family -> roughness (viewer's MeshStandardMaterial input). Constants by
# design; None = unknown family -> clean matte.
_ROUGHNESS: dict[str | None, float] = {
    "wood": 0.6,
    "tile": 0.25,
    "stone": 0.55,
    "carpet": 0.95,
    "concrete": 0.7,
    "painted": 0.85,
    "wallpaper": 0.9,
    "exposed": 0.75,
    None: 0.9,
}

# Plank direction: minimum axial resultant (0..1 consensus of gradient
# orientations) to claim a direction at all.
_PLANK_MIN_RESULTANT = 0.2

# Vision call bounds: one attempt + one SDK retry at a 30 s timeout keeps
# a plane's worst case inside shell_receiver's 90 s budget reserve.
_API_TIMEOUT_S = 30.0
_API_MAX_RETRIES = 1
_API_MAX_TOKENS = 256

# classify_fn contract: (crops, kind) -> (family, confidence) | None.
# None = no classification obtained (failure/no key); the gate is applied
# by infer_material, not the classifier.
ClassifyFn = Callable[[list[EvidenceCrop], str], "tuple[str, float] | None"]


# ---------------------------------------------------------------------------
# Result shape
# ---------------------------------------------------------------------------

@dataclass
class MaterialResult:
    """One plane's inferred material (the shell.json material {} dict's
    content; assembly into the doc happens in shell_receiver)."""

    family: str | None
    family_confidence: float | None
    albedo_hex: str | None
    secondary_hex: str | None  # always None in v1 (deferred as noisy)
    plank_direction_deg: float | None
    roughness: float
    model: str | None  # model that produced a shipped family, else None


# ---------------------------------------------------------------------------
# Albedo (measured)
# ---------------------------------------------------------------------------

def _weighted_quantile(values: np.ndarray, weights: np.ndarray, q: float) -> float:
    """Value at the weighted q-quantile; deterministic (stable sort)."""
    order = np.argsort(values, kind="stable")
    cum = np.cumsum(weights[order])
    idx = int(np.searchsorted(cum, q * cum[-1]))
    return float(values[order[min(idx, len(values) - 1)]])


def compute_albedo(
    colors: np.ndarray, weights: np.ndarray
) -> str | None:
    """Dominant albedo hex from observed texel colors (N, 3) float32 RGB
    0..255 and per-texel weights (N,). None below the texel gate."""
    if colors is None or len(colors) < SHELL_MATERIAL_MIN_TEXELS:
        return None
    lum = (
        0.2126 * colors[:, 0] + 0.7152 * colors[:, 1] + 0.0722 * colors[:, 2]
    )
    l_ref = _weighted_quantile(lum, weights, _ALBEDO_REF_QUANTILE)
    band = (lum >= _ALBEDO_BAND_LO * l_ref) & (lum <= _ALBEDO_BAND_HI * l_ref)
    if not np.any(band):
        return None
    rgb = []
    for c in range(3):
        rgb.append(_weighted_quantile(colors[band, c], weights[band], 0.5))
    r, g, b = (int(np.clip(round(v), 0, 255)) for v in rgb)
    return f"#{r:02x}{g:02x}{b:02x}"


# ---------------------------------------------------------------------------
# Family (classified, gated)
# ---------------------------------------------------------------------------

def families_for(kind: str) -> tuple[str, ...]:
    return FLOOR_FAMILIES if kind == "floor" else WALL_FAMILIES


def _crop_png_b64(crop: EvidenceCrop) -> str:
    from PIL import Image  # deferred: keep module import light

    buf = io.BytesIO()
    Image.fromarray(crop.rgb, mode="RGB").save(buf, format="PNG")
    return base64.standard_b64encode(buf.getvalue()).decode("ascii")


def classify_family_via_api(
    crops: list[EvidenceCrop], kind: str
) -> tuple[str, float] | None:
    """ONE vision call for one plane. Returns (family, confidence) or None
    on any failure — the caller's fallback rule turns None into a clean
    neutral, so this function never raises."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        logger.info("shell_material: no ANTHROPIC_API_KEY; family inference off")
        return None
    if not crops:
        return None

    vocab = families_for(kind)
    try:
        import anthropic  # deferred: tests never touch the SDK

        client = anthropic.Anthropic(
            api_key=api_key, timeout=_API_TIMEOUT_S, max_retries=_API_MAX_RETRIES
        )
        content: list[dict] = []
        for i, crop in enumerate(crops):
            side = crop.u1 - crop.u0
            content.append({
                "type": "text",
                "text": (
                    f"Crop {i + 1}: a {side:.2f} m square patch of the "
                    f"surface, rectified to face-on view"
                    + (
                        f" ({crop.fill_fraction:.0%} of its pixels were "
                        f"unobserved and filled with the median color)"
                        if crop.fill_fraction > 0
                        else ""
                    )
                    + "."
                ),
            })
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": _crop_png_b64(crop),
                },
            })
        content.append({
            "type": "text",
            "text": (
                f"These crops all come from ONE {kind} surface in a home, "
                f"photographed by a phone camera and reprojected to face-on "
                f"view at roughly 2-3 mm per pixel. Classify the surface's "
                f"dominant material family. Answer with one family from "
                f"exactly this list: {', '.join(vocab)} — or 'other' if "
                f"none of them fits what you see. confidence is your "
                f"probability (0 to 1) that the chosen family is correct."
            ),
        })

        response = client.messages.create(
            model=SHELL_MATERIAL_MODEL,
            max_tokens=_API_MAX_TOKENS,
            thinking={"type": "disabled"},
            output_config={
                "format": {
                    "type": "json_schema",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "family": {
                                "type": "string",
                                "enum": list(vocab) + ["other"],
                            },
                            "confidence": {"type": "number"},
                        },
                        "required": ["family", "confidence"],
                        "additionalProperties": False,
                    },
                }
            },
            messages=[{"role": "user", "content": content}],
        )
        if response.stop_reason == "refusal":
            logger.warning("shell_material: classification refused")
            return None
        text = next(b.text for b in response.content if b.type == "text")
        data = json.loads(text)
        family = str(data["family"])
        confidence = float(data["confidence"])
        if family not in vocab and family != "other":
            logger.warning("shell_material: off-vocabulary family %r", family)
            return None
        return family, confidence
    except Exception as exc:
        logger.warning("shell_material: classification failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Plank direction (wood floors)
# ---------------------------------------------------------------------------

def plank_direction(crops: list[EvidenceCrop]) -> float | None:
    """Dominant plank direction in degrees within the plane's UV frame
    (0 = +U axis, increasing toward +V, range [0, 180)). None when the
    crops' gradient orientations have no clear axial consensus.

    Plank seams are parallel lines: image gradients concentrate
    PERPENDICULAR to them, so the plank direction is the dominant
    gradient orientation rotated 90 degrees. Axial data (theta and
    theta+180 are the same orientation) uses the 2-theta circular mean.
    """
    if not crops:
        return None
    s_sum = 0.0
    c_sum = 0.0
    m_sum = 0.0
    for crop in crops:
        gray = crop.rgb.astype(np.float32).mean(axis=2)
        gy, gx = np.gradient(gray)
        # Crop rows run top-down (+V flipped at raster time); flip gy so
        # angles are in the UV frame (+U right, +V up).
        gy = -gy
        mag = np.hypot(gx, gy)
        theta = np.arctan2(gy, gx)
        s_sum += float(np.sum(mag * np.sin(2.0 * theta)))
        c_sum += float(np.sum(mag * np.cos(2.0 * theta)))
        m_sum += float(np.sum(mag))
    if m_sum <= 0.0:
        return None
    resultant = math.hypot(s_sum, c_sum) / m_sum
    if resultant < _PLANK_MIN_RESULTANT:
        return None
    gradient_deg = math.degrees(0.5 * math.atan2(s_sum, c_sum))
    return round((gradient_deg + 90.0) % 180.0, 1)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def infer_material(
    observation: ObservationResult,
    kind: str,
    *,
    classify_fn: ClassifyFn | None = None,
) -> MaterialResult:
    """One plane's material from its observation. classify_fn defaults to
    the production API call; tests inject a fake. NEVER raises — every
    failure lands on the clean-neutral fallback."""
    albedo = compute_albedo(observation.colors, observation.weights)

    family: str | None = None
    confidence: float | None = None
    model: str | None = None
    fn = classify_fn if classify_fn is not None else classify_family_via_api
    if observation.crops:
        try:
            result = fn(observation.crops, kind)
        except Exception as exc:  # a classify_fn must not break the shell
            logger.warning("shell_material: classify_fn raised: %s", exc)
            result = None
        if result is not None:
            raw_family, raw_conf = result
            if raw_family != "other" and raw_conf >= SHELL_MATERIAL_MIN_CONF:
                family = raw_family
                confidence = round(float(raw_conf), 4)
                model = SHELL_MATERIAL_MODEL
                # Log ADMISSIONS too, not just rejections (decision 0100). The
                # family-instability finding — byte-identical evidence yielding
                # a different family across two bakes — was only findable by
                # diffing two shell.json files by hand, because a family
                # admitted at the gate floor left no trace anywhere. An
                # admission at or near SHELL_MATERIAL_MIN_CONF is the model
                # reporting a coin flip, and it should be greppable as one.
                logger.info(
                    "shell_material: %s classified family=%s conf=%.2f%s",
                    kind, family, raw_conf,
                    " AT_GATE_FLOOR" if raw_conf <= SHELL_MATERIAL_MIN_CONF else "",
                )
            else:
                logger.info(
                    "shell_material: %s classification gated (family=%s conf=%.2f)",
                    kind, raw_family, raw_conf,
                )

    plank: float | None = None
    if family == "wood" and kind == "floor":
        plank = plank_direction(observation.crops)

    return MaterialResult(
        family=family,
        family_confidence=confidence,
        albedo_hex=albedo,
        secondary_hex=None,
        plank_direction_deg=plank,
        roughness=_ROUGHNESS[family],
        model=model,
    )
