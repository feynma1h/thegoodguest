"""POST /shell receiver — the room-shell second stage (decision 0066).

Enqueued by /process's success path after release_ready (fire-and-forget;
see shell_enqueue.py). Assembles floor+wall quads from the bundle's
plane anchors (shell_geometry), bakes textures from the capture's own
RGB with SAM 3 masks excluding furniture (shell_texture + shell_inpaint),
and writes:

  gs://{PERCEPTION_OUTPUTS_BUCKET}/scenes/{scene_id}/shell.json
  gs://{PERCEPTION_OUTPUTS_BUCKET}/scenes/{scene_id}/shell/textures/*.png

NEVER manifest.json (single writer stays /process), NEVER Firestore —
shell failure cannot un-ready a room, and there is no scene lease: the
shell.json write is a single idempotent blob PUT, deterministic for
identical inputs, so concurrent runs are benign.

The client-relied distinction (0066): shell.json ABSENT = not yet (keep
the grace window); status "unavailable" = never coming (stop waiting,
keep the grid). Unavailable is a WRITTEN file with a reason
("no_geometry_source" for pre-plane bundles / unusable anchors;
"capture_expired" when the captures bucket's 1-day lifecycle swept the
pixels), not an error.

Response classification mirrors 0004's receiver semantics: completed
runs AND poison-class outcomes return 200 (Cloud Tasks drains);
environmental failures return 5xx (Cloud Tasks retries, maxAttempts=3).
A request-entry deadline (server.py, SHELL_REQUEST_BUDGET_SECONDS)
bounds the handler inside the Cloud Run request window; running out of
budget is environmental — the retry starts over (textures re-upload
idempotently).

reads: bundle proto (poses/intrinsics/plane_anchors) from the captures
bucket; manifest.json READ-ONLY for the complete-frame list; masks.npz
per complete frame and RGB per frame. No SAM model is ever touched on
this path — cold start is seconds.

Consumers: server.py (POST /shell), tests/test_shell_receiver.py.
"""
from __future__ import annotations

import asyncio
import io
import json
import logging
import time
from typing import Any

import numpy as np
from fastapi import Request
from fastapi.responses import JSONResponse
from process_receiver import (
    EnvironmentalError,
    PoisonError,
    _bundle_prefix,
    _download_gcs_uri,
    _gcs_blob_exists_and_get,
    _gcs_upload_for_scene,
)
from pydantic import BaseModel
from roomstudio_schemas import CaptureBundle
from roomstudio_schemas.placement_math import resize_mask_to
from shell_geometry import ShellGeometry, assemble_shell
from shell_texture import BakeResult, FrameSample, bake_plane_texture

logger = logging.getLogger(__name__)

SHELL_VERSION = 1

# Seconds held back from the deadline for the shell.json upload + response.
SHELL_BUDGET_RESERVE_S = 30.0


class ShellRequest(BaseModel):
    """Cloud Tasks payload for POST /shell — same shape as /process."""

    scene_id: str
    bundle_uri: str


# ---------------------------------------------------------------------------
# shell.json assembly (deterministic: no timestamps, canonical key order,
# rounded floats)
# ---------------------------------------------------------------------------

def _round3(values) -> list:
    return [round(float(v), 4) for v in values]


def _quad(corners: np.ndarray) -> list[list[float]]:
    return [_round3(c) for c in corners]


def build_shell_json(
    *,
    scene_id: str,
    status: str,
    reason: str | None,
    geometry: ShellGeometry | None = None,
    bakes: dict[str, tuple[BakeResult, str | None]] | None = None,
    frames_used: int = 0,
) -> dict[str, Any]:
    """The shell.json document. bakes maps plane key ("floor" / wall_id) to
    (BakeResult, texture_gcs_uri | None). Deterministic for identical
    inputs — the body carries no timestamps and floats are rounded."""
    doc: dict[str, Any] = {
        "shell_version": SHELL_VERSION,
        "scene_id": scene_id,
        "status": status,
        "reason": reason,
        "method": "arkit_planes",
        "floor": None,
        "walls": [],
        "quality": {"planes_in_bundle": 0, "frames_used": frames_used},
    }
    if geometry is None:
        return doc

    doc["quality"] = {**geometry.quality, "frames_used": frames_used}

    if bakes is None:
        # Geometry known but nothing baked (an unavailable status that
        # still records quality counts) — floor/walls stay empty.
        return doc

    if geometry.floor is not None:
        bake, uri = bakes["floor"]
        doc["floor"] = {
            "quad": _quad(geometry.floor.corners_world),
            "y": round(float(geometry.floor.origin[1]), 4),
            "texture_gcs_uri": uri,
            "observed_fraction": bake.observed_fraction,
            "inpainted_fraction": bake.inpainted_fraction,
            "source": bake.source,
        }
    for wall in geometry.walls:
        bake, uri = bakes[wall.wall_id]
        doc["walls"].append({
            "wall_id": wall.wall_id,
            "quad": _quad(wall.corners_world),
            "texture_gcs_uri": uri,
            "observed_fraction": bake.observed_fraction,
            "inpainted_fraction": bake.inpainted_fraction,
            "source": bake.source,
            "classification": wall.classification or None,
        })
    return doc


def shell_json_bytes(doc: dict[str, Any]) -> bytes:
    """Canonical serialization — sorted keys, no whitespace jitter — so
    identical inputs produce byte-identical shell.json."""
    return json.dumps(doc, sort_keys=True, separators=(",", ":")).encode("utf-8")


# ---------------------------------------------------------------------------
# Frame loading
# ---------------------------------------------------------------------------

def _load_frame_samples(
    bundle: CaptureBundle, manifest: dict, bundle_prefix: str
) -> tuple[list[FrameSample], int]:
    """Build FrameSamples for the manifest's COMPLETE frames (entries
    without budget_stopped — the ones whose masks.npz exists).

    Returns (samples, rgb_missing_count). A frame whose masks or RGB blob
    is gone is skipped (logged); the caller decides whether zero usable
    frames means capture_expired.
    """
    by_index = {f.frame_index: f for f in bundle.frames}
    samples: list[FrameSample] = []
    rgb_missing = 0

    for entry in manifest.get("frames", []):
        if entry.get("budget_stopped"):
            continue
        idx = entry.get("frame_index")
        frame = by_index.get(idx)
        masks_uri = entry.get("masks_gcs_uri")
        if frame is None or not masks_uri:
            logger.warning("shell: frame %s unusable (no bundle frame/masks)", idx)
            continue

        try:
            rgb_bytes = _download_gcs_uri(entry["rgb_gcs_uri"])
        except PoisonError:
            rgb_missing += 1
            logger.info("shell: frame %s RGB swept by lifecycle", idx)
            continue

        from PIL import Image  # deferred: keep module import light

        try:
            rgb = np.asarray(Image.open(io.BytesIO(rgb_bytes)).convert("RGB"))
        except Exception as exc:
            raise PoisonError(
                f"shell: frame {idx} image cannot be opened: {exc}"
            ) from exc

        try:
            masks_bytes = _download_gcs_uri(masks_uri)
            with np.load(io.BytesIO(masks_bytes)) as npz:
                masks = npz["masks"]
        except PoisonError:
            logger.warning("shell: frame %s masks.npz missing; skipping frame", idx)
            continue

        if masks.ndim == 3 and masks.shape[0] > 0:
            exclusion = masks.any(axis=0)
            if exclusion.shape != rgb.shape[:2]:
                exclusion = resize_mask_to(
                    exclusion, (rgb.shape[1], rgb.shape[0])
                )
        else:
            exclusion = np.zeros(rgb.shape[:2], dtype=bool)

        samples.append(
            FrameSample(
                frame_index=idx,
                rgb=rgb,
                exclusion_mask=exclusion,
                pose=frame.camera_pose,
                intrinsics=frame.intrinsics,
            )
        )
    return samples, rgb_missing


def _production_inpaint_fn():
    """shell_inpaint when its baked weights exist; a deterministic mean-
    color fill otherwise (dev/local only — the image build asserts
    availability, so production always has the model)."""
    import shell_inpaint

    if shell_inpaint.is_available():
        return shell_inpaint.inpaint

    logger.warning(
        "shell: LaMa weights unavailable; holes get a mean-color fill "
        "(dev fallback — production images bake the model)"
    )

    def _mean_fill(rgb: np.ndarray, holes: np.ndarray) -> np.ndarray:
        out = rgb.copy()
        observed = ~holes
        if np.any(observed):
            out[holes] = rgb[observed].mean(axis=0).astype(np.uint8)
        return out

    return _mean_fill


# ---------------------------------------------------------------------------
# Core (sync; run via asyncio.to_thread from the route)
# ---------------------------------------------------------------------------

def run_shell(
    *,
    scene_id: str,
    bundle_uri: str,
    outputs_bucket: str,
    deadline: float | None,
) -> dict[str, Any]:
    """Produce shell.json + textures for one scene. Returns the response
    body. Raises EnvironmentalError for retryable failures."""
    shell_blob = f"scenes/{scene_id}/shell.json"

    # Redelivery fast-path: the output is deterministic, so an existing
    # shell.json (ready OR unavailable — neither changes on re-run: the
    # bundle is immutable and swept pixels never return) means done.
    if _gcs_blob_exists_and_get(outputs_bucket, shell_blob) is not None:
        logger.info("shell: scene %s already has shell.json; noop", scene_id)
        return {"status": "noop", "reason": "already_present"}

    def _write(doc: dict[str, Any]) -> dict[str, Any]:
        _gcs_upload_for_scene(
            f"gs://{outputs_bucket}/", shell_blob, shell_json_bytes(doc),
            "application/json",
        )
        logger.info(
            "shell: scene %s wrote shell.json status=%s reason=%s",
            scene_id, doc["status"], doc["reason"],
        )
        return {"status": doc["status"], "reason": doc["reason"]}

    # Bundle: gone (1-day lifecycle) → unavailable/capture_expired.
    try:
        raw = _download_gcs_uri(bundle_uri)
    except PoisonError:
        return _write(build_shell_json(
            scene_id=scene_id, status="unavailable", reason="capture_expired",
        ))
    bundle = CaptureBundle()
    try:
        bundle.ParseFromString(raw)
    except Exception as exc:
        # Post-ready corrupt bundle: ingest validated it and /process
        # parsed it, so this is an operator-visible anomaly, not a state
        # to persist. Drain with a log; write nothing.
        logger.error("shell: scene %s bundle unparseable: %s", scene_id, exc)
        return {"status": "noop", "reason": "bundle_unparseable"}

    # Pre-plane bundles (every capture before chunk A) → unavailable.
    if len(bundle.plane_anchors) == 0:
        return _write(build_shell_json(
            scene_id=scene_id, status="unavailable", reason="no_geometry_source",
        ))

    # Manifest: read-only, for the complete-frame list. Absent = the scene
    # is not actually post-ready (mis-enqueued/mid-flight) — write nothing.
    manifest_bytes = _gcs_blob_exists_and_get(
        outputs_bucket, f"scenes/{scene_id}/manifest.json"
    )
    if manifest_bytes is None:
        logger.warning("shell: scene %s has no manifest.json; noop", scene_id)
        return {"status": "noop", "reason": "manifest_missing"}
    manifest = json.loads(manifest_bytes)

    geometry = assemble_shell(bundle.plane_anchors)
    if geometry.floor is None and not geometry.walls:
        return _write(build_shell_json(
            scene_id=scene_id, status="unavailable", reason="no_geometry_source",
            geometry=geometry,
        ))

    samples, rgb_missing = _load_frame_samples(
        bundle, manifest, _bundle_prefix(bundle_uri)
    )
    if not samples and rgb_missing > 0:
        return _write(build_shell_json(
            scene_id=scene_id, status="unavailable", reason="capture_expired",
            geometry=geometry,
        ))

    inpaint_fn = _production_inpaint_fn()
    wall_planes = [(w.normal, w.origin) for w in geometry.walls]

    planes = ([("floor", geometry.floor)] if geometry.floor else []) + [
        (w.wall_id, w) for w in geometry.walls
    ]
    bakes: dict[str, tuple[BakeResult, str | None]] = {}
    for key, geom in planes:
        if deadline is not None and time.monotonic() > deadline - SHELL_BUDGET_RESERVE_S:
            # Out of request budget mid-bake: environmental — the Cloud
            # Tasks retry redoes the (deterministic) work from the top.
            raise EnvironmentalError(
                f"shell budget exhausted before plane {key} "
                f"({len(bakes)}/{len(planes)} baked)"
            )
        bake = bake_plane_texture(
            geom,
            samples,
            inpaint_fn=inpaint_fn,
            floor_member_polygons=(
                geometry.floor_member_polygons if key == "floor" else None
            ),
            wall_planes=wall_planes if key == "floor" else None,
        )
        uri: str | None = None
        if bake.png_bytes is not None:
            uri = _gcs_upload_for_scene(
                f"gs://{outputs_bucket}/",
                f"scenes/{scene_id}/shell/textures/{key}.png",
                bake.png_bytes,
                "image/png",
            )
        bakes[key] = (bake, uri)
        logger.info(
            "shell: scene %s plane %s source=%s observed=%.3f inpainted=%.3f",
            scene_id, key, bake.source, bake.observed_fraction,
            bake.inpainted_fraction,
        )

    return _write(build_shell_json(
        scene_id=scene_id, status="ready", reason=None,
        geometry=geometry, bakes=bakes, frames_used=len(samples),
    ))


# ---------------------------------------------------------------------------
# Route handler (registered in server.py)
# ---------------------------------------------------------------------------

async def handle_shell(
    request: Request,
    req: ShellRequest,
    *,
    oidc_verifier,  # OIDCVerifier | None (None disables auth, for tests)
    outputs_bucket: str,
    deadline: float | None = None,
) -> JSONResponse:
    """Core handler for POST /shell. No scene lease, no Firestore — see the
    module docstring. The sync core runs off the event loop so /health
    stays responsive during minutes-long bakes."""
    from oidc import OIDCError

    if oidc_verifier is not None:
        try:
            oidc_verifier.verify(request.headers.get("Authorization"))
        except OIDCError as exc:
            logger.warning("shell OIDC rejected: %s %s", exc.code, exc.detail)
            return JSONResponse(
                status_code=401,
                content={"error": exc.code, "detail": exc.detail},
            )

    try:
        body = await asyncio.to_thread(
            run_shell,
            scene_id=req.scene_id,
            bundle_uri=req.bundle_uri,
            outputs_bucket=outputs_bucket,
            deadline=deadline,
        )
    except PoisonError as exc:
        # Poison drains: retrying cannot change the outcome.
        logger.error("shell: poison failure for scene %s: %s", req.scene_id, exc)
        return JSONResponse({"status": "failed", "reason": str(exc)})
    except EnvironmentalError as exc:
        logger.error("shell: environmental failure for scene %s: %s", req.scene_id, exc)
        return JSONResponse(status_code=500, content={"status": "error", "reason": str(exc)})
    except Exception as exc:
        logger.exception("shell: unexpected failure for scene %s", req.scene_id)
        return JSONResponse(status_code=500, content={"status": "error", "reason": str(exc)})

    return JSONResponse(body)
