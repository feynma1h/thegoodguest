"""Privacy suppression: concepts SAM 3 must SEE but the product must never SHIP.

Decision 0070 recorded the gap: "person" is not in the object vocabulary, so
anyone standing in the room during a capture is observed as if they were the
surface behind them. The shipped manifestation was scene f3d70236's wall_03,
whose measured albedo is a person lying in front of that wall.

The fix is a SUPPRESSION-ONLY concept class. A suppressed concept is added to
the SAM 3 text prompt — the model finds it — and its masks are then used for
exactly one purpose: excluding those pixels from surface evidence. They are
never reconstructed, never placed, never fused, never inventoried, never
written into the manifest, and therefore never reachable by the conversation
layer's scene_facts. The seam that makes this cheap is sam3.py's prompt split:
the concept list IS the comma-separated prompt, so adding a concept costs one
extra class pass and nothing else.

The suppression itself rides mechanisms that already exist (0066/0069):
  - the per-frame masks.npz gains a `suppressed` union beside `masks`, and
    shell_receiver ORs it into the exclusion mask that already keeps furniture
    out of surface samples — so albedo evidence loses those pixels for free;
  - shell_observation rejects any evidence crop that would contain a
    suppressed pixel, preferring a person-free frame for the same tile;
  - when too little person-free evidence survives, the EXISTING gates fire:
    no crops → family None (shell_material's fallback rule), too few observed
    texels → albedo None → the viewer's honest neutral treatment.

THE RISK THIS FIX INTRODUCES, and the invariant that contains it: a concept
added here is fed to the segmenter, so it is one careless call site away from
becoming a reconstructed object. partition_detections is the ONLY sanctioned
way to consume a segmentation result, and tests/test_privacy_suppression.py
pins the whole downstream chain (reconstruction, fusion, dedup, manifest)
against ever seeing a suppressed label.

`masks` in masks.npz stays index-aligned with objects.json (fusion reads it by
detection order) because suppressed detections are partitioned out BEFORE
indices are assigned. Suppressed concepts were absent from the vocabulary
before this module existed, so kept-list ordering — and therefore every
per-object splat cache key — is unchanged by their arrival.

Consumers: process_receiver.py (both the legacy and census two-pass paths),
shell_receiver.py, server.py, tests/test_privacy_suppression.py.
"""
from __future__ import annotations

import io
import os
from typing import Any

import numpy as np

# The masks.npz key holding the suppressed union. Kept beside the writer and
# reader below so the two can never drift; ABSENT in every masks.npz written
# before this module existed, which readers must treat as "no suppression"
# rather than as an error.
SUPPRESSED_NPZ_KEY = "suppressed"


def _parse_concepts(raw: str) -> tuple[str, ...]:
    """Comma-separated concepts, normalized the way labels are compared."""
    seen: list[str] = []
    for part in raw.split(","):
        c = part.strip().lower()
        if c and c not in seen:
            seen.append(c)
    return tuple(seen)


# The suppression vocabulary. Env-overridable so a capture-time finding can be
# answered without a code change; empty disables suppression entirely (and
# reproduces pre-0089 behaviour exactly — the degrade lock).
SUPPRESSED_CONCEPTS: tuple[str, ...] = _parse_concepts(
    os.environ.get("PERCEPTION_SUPPRESSED_CONCEPTS", "person")
)


def is_suppressed_label(label: str) -> bool:
    """True when a detection's label names a suppressed concept."""
    return str(label).strip().lower() in SUPPRESSED_CONCEPTS


def segmentation_prompt(object_prompt: str) -> str:
    """The prompt actually sent to SAM 3: the object vocabulary plus the
    suppressed concepts. Concepts already present in the object prompt are not
    duplicated (SAM 3 would run the class twice)."""
    if not SUPPRESSED_CONCEPTS:
        return object_prompt
    present = {c.strip().lower() for c in object_prompt.split(",") if c.strip()}
    extra = [c for c in SUPPRESSED_CONCEPTS if c not in present]
    if not extra:
        return object_prompt
    return ",".join([object_prompt, *extra]) if object_prompt else ",".join(extra)


def partition_detections(
    detections: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split a SAM 3 result into (kept, suppressed), preserving order.

    `kept` is what the pipeline may reconstruct, fuse, and ship. `suppressed`
    exists only to build the exclusion union — callers must not index it into
    objects.json, the manifest, or any output the product reads.
    """
    kept: list[dict[str, Any]] = []
    suppressed: list[dict[str, Any]] = []
    for det in detections:
        (suppressed if is_suppressed_label(det.get("label", "")) else kept).append(det)
    return kept, suppressed


def suppressed_union(
    suppressed: list[dict[str, Any]], shape: tuple[int, int] | None = None
) -> np.ndarray | None:
    """(H, W) bool union of the suppressed detections' masks, or None when
    there are none — None is the signal every consumer degrades on, and it is
    what every masks.npz written before this module existed implies."""
    masks = [np.asarray(d["mask"], dtype=bool) for d in suppressed if d.get("mask") is not None]
    if not masks:
        return None
    union = masks[0].copy()
    for m in masks[1:]:
        if m.shape != union.shape:
            continue  # defensive: a shape-mismatched mask cannot be unioned
        union |= m
    if shape is not None and union.shape != shape:
        return None
    return union


def masks_npz_bytes(
    detections: list[dict[str, Any]], suppressed: list[dict[str, Any]]
) -> bytes:
    """Serialize one frame's masks.npz: `masks` (the kept detection-order
    stack fusion and the shell read) plus, only when non-empty, `suppressed`
    (the union of suppressed masks). Omitting the key when there is nothing to
    suppress keeps the bytes identical to the pre-0089 writer."""
    buf = io.BytesIO()
    arrays: dict[str, np.ndarray] = {}
    if detections:
        arrays["masks"] = np.stack([np.asarray(d["mask"], dtype=bool) for d in detections])
    else:
        arrays["masks"] = np.zeros((0,), dtype=bool)
    union = suppressed_union(suppressed)
    if union is not None:
        arrays[SUPPRESSED_NPZ_KEY] = union
    np.savez_compressed(buf, **arrays)
    return buf.getvalue()


def read_suppressed(npz) -> np.ndarray | None:
    """The suppressed union from an opened masks.npz, or None when the key is
    absent (every pre-0089 file) or unreadable."""
    try:
        if SUPPRESSED_NPZ_KEY not in npz.files:
            return None
        arr = np.asarray(npz[SUPPRESSED_NPZ_KEY], dtype=bool)
    except Exception:
        return None
    return arr if arr.ndim == 2 and arr.size else None
