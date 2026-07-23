"""POST /shell receiver — the room-shell second stage (decisions 0066
architecture / 0069 parametric surfaces).

Enqueued by /process's success path after release_ready (fire-and-forget;
see shell_enqueue.py). Assembles the measured floor + wall set from the
bundle's plane anchors (room_planes via shell_geometry), closes the
envelope (0069: wall→floor, wall→wall seams, common top, floor snapped
and bounded to wall lines — joints, never loops), observes each plane
from the capture's own RGB (shell_observation), infers per-plane
parametric materials (shell_material: measured albedo + confidence-gated
family + roughness lookup), and writes ONE blob:

  gs://{PERCEPTION_OUTPUTS_BUCKET}/scenes/{scene_id}/shell.json

No raster textures exist in the serving contract (SHELL_VERSION 2 — the
photographic bake and its inpainting left serving per 0069; the viewer
renders materials from parameters). NEVER manifest.json (single writer
stays /process), NEVER Firestore — shell failure cannot un-ready a room,
and there is no scene lease: the shell.json write is a single idempotent
blob PUT, deterministic for identical inputs (the material vision call is
made at most once per plane per scene lifetime thanks to the write-once
noop; MATERIAL_VERSION + model are recorded in the doc).

The client-relied distinction (0066): shell.json ABSENT = not yet (keep
the grace window); status "unavailable" = never coming (stop waiting,
keep the grid). Unavailable is a WRITTEN file with a reason
("no_geometry_source" for pre-plane bundles / unusable anchors;
"capture_expired" when the captures bucket's 1-day lifecycle swept the
pixels), not an error.

Honesty invariants carried in the doc (0069, test-pinned): every wall
ships measured_quad (the DETECTED extent — what facts may read) beside
the rendered quad, with per-edge provenance; the floor ships
measured_polygon beside the rendered polygon with per-segment states;
closure never mutates measured geometry.

Response classification mirrors 0004's receiver semantics: completed
runs AND poison-class outcomes return 200 (Cloud Tasks drains);
environmental failures return 5xx (Cloud Tasks retries, maxAttempts=3).
A request-entry deadline (server.py, SHELL_REQUEST_BUDGET_SECONDS)
bounds the handler inside the Cloud Run request window; running out of
budget is environmental — the retry starts over.

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
    _download_gcs_uri,
    _gcs_blob_exists_and_get,
    _gcs_upload_for_scene,
)
from pydantic import BaseModel
from roomstudio_schemas import CaptureBundle
from roomstudio_schemas.placement_math import resize_mask_to
from shell_geometry import ShellClosure, ShellGeometry, assemble_shell, close_shell
from shell_material import MATERIAL_VERSION, MaterialResult, infer_material
from shell_observation import FrameSample, ObservationResult, observe_plane

logger = logging.getLogger(__name__)

SHELL_VERSION = 2

# Seconds held back from the deadline before STARTING a plane's
# observation + inference: must cover one plane's worst case (projection
# over the complete frames plus one bounded vision call with a retry).
SHELL_BUDGET_RESERVE_S = 90.0


class ShellRequest(BaseModel):
    """Cloud Tasks payload for POST /shell — same shape as /process."""

    scene_id: str
    bundle_uri: str


# ---------------------------------------------------------------------------
# shell.json assembly (deterministic: no timestamps, canonical key order,
# rounded floats)
# ---------------------------------------------------------------------------

def _round4(values) -> list:
    return [round(float(v), 4) for v in values]


def _points(arr: np.ndarray) -> list[list[float]]:
    return [_round4(p) for p in arr]


def _material_dict(mat: MaterialResult, obs: ObservationResult) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if mat.plank_direction_deg is not None:
        params["plank_direction_deg"] = mat.plank_direction_deg
    return {
        "family": mat.family,
        "family_confidence": mat.family_confidence,
        "albedo_hex": mat.albedo_hex,
        "secondary_hex": mat.secondary_hex,
        "params": params,
        "render": {"roughness": mat.roughness},
        "source": {
            "observed_fraction": obs.observed_fraction,
            "texel_count": obs.texel_count,
            "frames_used": obs.frames_used,
        },
        "inference": {"model": mat.model, "material_version": MATERIAL_VERSION},
    }


def build_shell_json(
    *,
    scene_id: str,
    status: str,
    reason: str | None,
    geometry: ShellGeometry | None = None,
    closure: ShellClosure | None = None,
    plane_results: dict[str, tuple[ObservationResult, MaterialResult]] | None = None,
    frames_used: int = 0,
) -> dict[str, Any]:
    """The shell.json v2 document. plane_results maps plane key ("floor" /
    wall_id) to (observation, material). Deterministic for identical
    inputs — no timestamps, floats rounded."""
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

    quality: dict[str, Any] = {
        **geometry.quality,
        "frames_used": frames_used,
    }
    if closure is not None:
        quality.update(closure.quality)
        quality["walls_detected"] = geometry.quality["wall_count"]
        quality["wall_count"] = len(closure.walls)
        quality["dropped_wall_ids"] = list(closure.dropped_wall_ids)
        quality["material_version"] = MATERIAL_VERSION
    doc["quality"] = quality

    if closure is None or plane_results is None:
        # Geometry known but nothing shipped (an unavailable status that
        # still records quality counts) — floor/walls stay empty.
        return doc

    if (
        geometry.floor is not None
        and closure.floor_polygon_rendered is not None
        and "floor" in plane_results
    ):
        obs, mat = plane_results["floor"]
        doc["floor"] = {
            "polygon": _points(closure.floor_polygon_rendered),
            "measured_polygon": _points(closure.floor_polygon_measured),
            "y": round(float(geometry.floor.origin[1]), 4),
            "provenance": {"edges": list(closure.floor_edge_states)},
            "material": _material_dict(mat, obs),
        }

    for cw in closure.walls:
        geom = cw.geom
        obs, mat = plane_results[geom.wall_id]
        rw = float(np.linalg.norm(cw.rendered_corners[1] - cw.rendered_corners[0]))
        rh = float(np.linalg.norm(cw.rendered_corners[3] - cw.rendered_corners[0]))
        ext_left = cw.edges["left"].extension_m
        ext_bottom = cw.edges["bottom"].extension_m
        openings = []
        for op in geom.openings:
            openings.append({
                "classification": op.classification,
                "rect_uv": [
                    _round4([
                        np.clip((op.u0 + ext_left) / rw, 0.0, 1.0),
                        np.clip((op.v0 + ext_bottom) / rh, 0.0, 1.0),
                    ]),
                    _round4([
                        np.clip((op.u1 + ext_left) / rw, 0.0, 1.0),
                        np.clip((op.v1 + ext_bottom) / rh, 0.0, 1.0),
                    ]),
                ],
            })
        doc["walls"].append({
            "wall_id": geom.wall_id,
            "quad": _points(cw.rendered_corners),
            "measured_quad": _points(geom.corners_world),
            "edges": {
                name: {"state": e.state, "extension_m": round(e.extension_m, 4)}
                for name, e in cw.edges.items()
            },
            "openings": openings,
            "classification": geom.classification or None,
            "material": _material_dict(mat, obs),
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
    bundle: CaptureBundle, manifest: dict
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
    """Produce shell.json for one scene. Returns the response body.
    Raises EnvironmentalError for retryable failures."""
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

    # Pre-plane bundles (every capture before the wire change) → unavailable.
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

    closure = close_shell(geometry)
    if geometry.floor is None and not closure.walls:
        # Everything vertical was a filtered fragment and no floor exists:
        # nothing measured is shippable — same honest degrade as unusable
        # anchors, with the closure stats recorded.
        return _write(build_shell_json(
            scene_id=scene_id, status="unavailable", reason="no_geometry_source",
            geometry=geometry, closure=closure,
        ))

    samples, rgb_missing = _load_frame_samples(bundle, manifest)
    if not samples and rgb_missing > 0:
        return _write(build_shell_json(
            scene_id=scene_id, status="unavailable", reason="capture_expired",
            geometry=geometry, closure=closure,
        ))

    planes: list[tuple[str, Any, list | None]] = []
    if geometry.floor is not None:
        planes.append(("floor", geometry.floor, geometry.floor_member_polygons))
    for cw in closure.walls:
        planes.append((cw.geom.wall_id, cw.geom, None))

    plane_results: dict[str, tuple[ObservationResult, MaterialResult]] = {}
    for key, geom, polygons in planes:
        if deadline is not None and time.monotonic() > deadline - SHELL_BUDGET_RESERVE_S:
            # Out of request budget mid-run: environmental — the Cloud
            # Tasks retry redoes the (deterministic) work from the top.
            raise EnvironmentalError(
                f"shell budget exhausted before plane {key} "
                f"({len(plane_results)}/{len(planes)} inferred)"
            )
        obs = observe_plane(geom, samples, floor_member_polygons=polygons)
        kind = "floor" if key == "floor" else "wall"
        mat = infer_material(obs, kind)
        plane_results[key] = (obs, mat)
        logger.info(
            "shell: scene %s plane %s observed=%.3f texels=%d crops=%d "
            "family=%s albedo=%s",
            scene_id, key, obs.observed_fraction, obs.texel_count,
            len(obs.crops), mat.family, mat.albedo_hex,
        )

    return _write(build_shell_json(
        scene_id=scene_id, status="ready", reason=None,
        geometry=geometry, closure=closure, plane_results=plane_results,
        frames_used=len(samples),
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
    stays responsive during the observation + inference walk."""
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
