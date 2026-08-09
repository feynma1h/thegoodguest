"""POST /process receiver for Cloud Tasks-dispatched perception jobs.

Implements the contract from docs/decisions/0004-perception-receiver-semantics.md:

  1. Verify OIDC token (Cloud Tasks attaches it when oidc_token is set on the
     task — see the OIDC verification in services/api-internal/dispatcher.py).
  2. Claim the scene atomically via ReceiverRepository (lease-TTL crash
     recovery). Exit 200 without processing on ALREADY_OWNED, WRONG_STATE,
     NOT_FOUND.
  3. Fetch the CaptureBundle proto from GCS.
  4. For each frame: download RGB, run SAM 3 + SAM 3D, write outputs to GCS.
  5. Write a top-level manifest to GCS; update scene→ready; fire FCM.
  On PoisonError: update scene→failed, fire FCM, return 200 (drain queue).
  On EnvironmentalError: return 5xx (Cloud Tasks retries). On the final
  attempt (X-CloudTasks-TaskRetryCount >= maxAttempts-1 = 2): update
  scene→failed, fire FCM before returning 5xx.

Output structure (keyed by scene_id):
  gs://{PERCEPTION_OUTPUTS_BUCKET}/scenes/{scene_id}/manifest.json
  gs://{PERCEPTION_OUTPUTS_BUCKET}/scenes/{scene_id}/frames/{idx:04d}/objects.json
  gs://{PERCEPTION_OUTPUTS_BUCKET}/scenes/{scene_id}/frames/{idx:04d}/masks.npz
  gs://{PERCEPTION_OUTPUTS_BUCKET}/scenes/{scene_id}/frames/{idx:04d}/splats/{i:02d}_{label}.ply

The scene manifest URI is stored in Scene.result_uri on success.

Manifest contract (manifest_version 2):
  {scene_id, bundle_uri, schema_version, manifest_version: 2, frame_count,
   frames_total, frames_sampled, sampling: {...},
   roomplan: {...} (only on bundles claiming a CapturedRoom),
   objects: [...], frames: [...]}
  "sampling" records the frame-selection policy, the selected indices,
  whether the budget stopped the run, and whether fusion refinement was
  skipped (see sampling.py / census_sampling.py / budget.py).
  "objects" is the scene-level fused array (one entry per physical object,
  with a world transform in the ARKit world frame — see fusion.py); it is
  what the web viewer renders. "frames" carries the per-frame observations
  for provenance: each object entry there includes "placement" (see
  placement.py) and "view_ray". world_transform is
  {position: [x,y,z] meters, rotation_xyzw: unit quat, scale: float} —
  splat local frame -> ARKit world.

Environment variables:
  RECEIVER_URL            — full HTTPS URL of this Cloud Run service
                            (e.g. https://perception-obj-xxx.run.app).
                            Used as the OIDC token audience.
  CLOUD_TASKS_INVOKER_SA  — Cloud Tasks invoker service-account email.
                            Verified against the token's `email` claim.
  SCENE_LEASE_TTL_SECONDS — lease duration in seconds (default 300).
  PERCEPTION_OUTPUTS_BUCKET — GCS bucket for outputs (inherited from server.py).

Consumers: server.py (app.post("/process")).
"""
from __future__ import annotations

import asyncio
import gc
import io
import json
import logging
import os
import signal
import threading
import time
import uuid
from typing import Any, Optional

from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from roomstudio_schemas import CaptureBundle

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
RECEIVER_URL: str = os.environ.get("RECEIVER_URL", "http://localhost:8081")
CLOUD_TASKS_INVOKER_SA: str = os.environ.get("CLOUD_TASKS_INVOKER_SA", "")
SCENE_LEASE_TTL_SECONDS: int = int(os.environ.get("SCENE_LEASE_TTL_SECONDS", "300"))

# ---------------------------------------------------------------------------
# Worker identity and lease tracking
# ---------------------------------------------------------------------------

_WORKER_ID: str = uuid.uuid4().hex

# Scenes currently held by this worker. Protected by _held_scenes_lock.
# Populated on claim, cleared on any release path. Read by the SIGTERM handler.
_held_scenes_lock = threading.Lock()
_held_scene_ids: set[str] = set()

# Set on first call to handle_process; used by the SIGTERM handler which runs
# outside the normal call stack and can't receive the repo as an argument.
_sigterm_repo_ref = None

# maxAttempts - 1 (per 0003: maxAttempts=3, so final attempt index = 2)
_FINAL_ATTEMPT_INDEX: int = 2

# ---------------------------------------------------------------------------
# Structured lease logging
# ---------------------------------------------------------------------------

def _log_lease_action(
    action: str,
    *,
    scene_id: str,
    lease_expires_at=None,
) -> None:
    """Emit one structured log line for every lease state transition.

    action is one of: claim, reclaim_stale, release_error, release_shutdown,
    noop_live_lease.
    """
    logger.info(
        "lease_action worker_id=%s scene_id=%s lease_expires_at=%s action=%s",
        _WORKER_ID,
        scene_id,
        lease_expires_at.isoformat() if lease_expires_at is not None else "none",
        action,
    )


# ---------------------------------------------------------------------------
# SIGTERM handler — release held leases on Cloud Run rolling deploy drain
# ---------------------------------------------------------------------------

def _sigterm_handler(signum, frame) -> None:
    """Release all leases held by this worker on SIGTERM.

    Cloud Run sends SIGTERM with a 10s drain before SIGKILL during rolling
    deploys. Any in-flight /process call will be killed before it completes.
    Releasing leases here lets Cloud Tasks retries find a clean state (queued)
    on the new revision rather than a live lease that blocks reclamation until
    it expires. See docs/decisions/0012.

    Best-effort: if SIGKILL fires before this completes, the lease-expiration
    check in claim() (docs/decisions/0011) covers the residual case.
    """
    repo = _sigterm_repo_ref
    if repo is None:
        return
    with _held_scenes_lock:
        held = set(_held_scene_ids)
    for scene_id in held:
        try:
            repo.release_queued(scene_id, holder_id=_WORKER_ID)
            with _held_scenes_lock:
                _held_scene_ids.discard(scene_id)
            _log_lease_action("release_shutdown", scene_id=scene_id)
        except Exception as exc:
            logger.error("sigterm release failed scene=%s: %s", scene_id, exc)


signal.signal(signal.SIGTERM, _sigterm_handler)


# ---------------------------------------------------------------------------
# Failure classification (per 0004)
# ---------------------------------------------------------------------------

class PoisonError(Exception):
    """Failure that will occur on every retry. Drain from queue: return 2xx,
    write scene→failed, fire FCM.

    Examples: malformed payload, bundle URI 404, structurally invalid bundle.
    """


class EnvironmentalError(Exception):
    """Failure that might succeed on retry. Return 5xx for Cloud Tasks retry.
    On the final attempt, write scene→failed and fire FCM before returning 5xx.

    Examples: transient GCS error, model crash, Firestore write failure.
    """


# ---------------------------------------------------------------------------
# Request model
# ---------------------------------------------------------------------------

class ProcessRequest(BaseModel):
    """Cloud Tasks payload for POST /process.

    Cloud Tasks delivers this as a JSON POST body. FastAPI parses it;
    a malformed body produces a 422 (4xx) which Cloud Tasks does not retry,
    so malformed payloads are naturally drained without explicit handling.
    """
    scene_id: str
    bundle_uri: str  # absolute gs:// URI of the CaptureBundle proto


# ---------------------------------------------------------------------------
# GCS helpers for the receiver (bundle fetch + frame fetch)
# ---------------------------------------------------------------------------

def _bundle_prefix(bundle_uri: str) -> str:
    """Return the absolute gs:// directory prefix containing bundle_uri.

    The bundle's frame paths are relative to this prefix; callers prepend it
    to resolve them into absolute gs:// URIs.

    bundle_uri = "gs://bucket/captures/id/bundle.pb"
    prefix     = "gs://bucket/captures/id/"
    """
    return bundle_uri.rsplit("/", 1)[0] + "/"


def _download_gcs_uri(gcs_uri: str) -> bytes:
    """Download bytes from an absolute gs:// URI.

    Raises PoisonError on 404 (bundle/frame not found).
    Raises EnvironmentalError on other GCS failures.
    """
    from google.cloud import storage  # deferred
    from google.cloud.exceptions import NotFound

    if not gcs_uri.startswith("gs://"):
        raise PoisonError(f"Expected gs:// URI, got: {gcs_uri!r}")

    without_scheme = gcs_uri[5:]
    bucket_name, blob_path = without_scheme.split("/", 1)
    try:
        client = storage.Client()
        return client.bucket(bucket_name).blob(blob_path).download_as_bytes()
    except NotFound:
        raise PoisonError(f"GCS object not found: {gcs_uri}")
    except Exception as exc:
        raise EnvironmentalError(f"GCS download failed: {exc}") from exc


def _gcs_upload_for_scene(gcs_uri_prefix: str, blob_path: str, data: bytes,
                           content_type: str) -> str:
    """Upload bytes and return the gs:// URI.

    gcs_uri_prefix is the full gs://bucket/... path prefix; blob_path is
    appended after the bucket extraction. Raises EnvironmentalError on failure.
    """
    from google.cloud import storage  # deferred

    # Parse bucket from the prefix URI
    without_scheme = gcs_uri_prefix[5:]  # strip "gs://"
    bucket_name = without_scheme.split("/")[0]

    try:
        client = storage.Client()
        blob = client.bucket(bucket_name).blob(blob_path)
        blob.upload_from_string(data, content_type=content_type)
        return f"gs://{bucket_name}/{blob_path}"
    except Exception as exc:
        raise EnvironmentalError(f"GCS upload failed for {blob_path}: {exc}") from exc


def _gcs_blob_exists(bucket_name: str, blob_path: str) -> bool:
    """Return True if the blob exists. Suppresses exceptions (treat as missing)."""
    try:
        from google.cloud import storage
        return storage.Client().bucket(bucket_name).blob(blob_path).exists()
    except Exception:
        return False


def _fetch_frame_depth(frame, bundle_prefix: str):
    """Download and decode a frame's LiDAR depth payload, if present.

    Returns (depth, confidence, intrinsics): the float32 (H, W) z-depth
    raster in meters, the optional uint8 confidence raster, and the depth
    raster's own Intrinsics message — or (None, None, None) when the frame
    carries no depth (ARKIT_ONLY tier).

    Raises PoisonError on malformed rasters (wrong byte count — retrying
    cannot fix the uploaded blob) and propagates _download_gcs_uri's
    Poison/Environmental classification for fetch failures.
    """
    import numpy as np  # deferred: heavy dep, only needed during processing

    if frame is None or not frame.HasField("depth"):
        return None, None, None
    d = frame.depth
    raw = _download_gcs_uri(bundle_prefix + d.depth_gcs_path)
    expected = d.width * d.height * 4
    if len(raw) != expected:
        raise PoisonError(
            f"Depth raster {d.depth_gcs_path} is {len(raw)} bytes; expected "
            f"{expected} ({d.width}x{d.height} float32)"
        )
    depth = np.frombuffer(raw, dtype="<f4").reshape(d.height, d.width)
    confidence = None
    if d.HasField("confidence_gcs_path") and d.confidence_gcs_path:
        raw_c = _download_gcs_uri(bundle_prefix + d.confidence_gcs_path)
        if len(raw_c) != d.width * d.height:
            raise PoisonError(
                f"Confidence raster {d.confidence_gcs_path} is {len(raw_c)} "
                f"bytes; expected {d.width * d.height} ({d.width}x{d.height} uint8)"
            )
        confidence = np.frombuffer(raw_c, dtype=np.uint8).reshape(d.height, d.width)
    return depth, confidence, d.intrinsics


# ---------------------------------------------------------------------------
# Per-frame perception
# ---------------------------------------------------------------------------

def _safe_label(label: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in label)[:32]


def _free_gpu_memory() -> None:
    """Collect Python garbage, then release CUDA cache blocks to the driver.

    gc.collect() must come first: exception tracebacks form frame<->traceback
    reference cycles, so tensors pinned by a handled exception's frames are
    only reclaimed by the cycle collector — after which empty_cache() can
    actually return their blocks. Cheap no-op without CUDA (dev/tests).
    """
    gc.collect()
    try:
        import torch as _torch
        if _torch.cuda.is_available():
            _torch.cuda.empty_cache()
    except ImportError:
        pass


def _log_vram(scene_id: str, point: str) -> None:
    """One structured line of CUDA memory state; resets the peak counter.

    The memory-lifecycle invariant — allocated VRAM roughly flat across
    frames — is verified in production from these lines. peak_mib is the
    high-water mark since the previous _log_vram call (per-frame peak when
    called at frame boundaries). Never raises; no-op without CUDA.
    """
    try:
        import torch as _torch
        if not _torch.cuda.is_available():
            return
        allocated = float(_torch.cuda.memory_allocated()) / 2**20
        reserved = float(_torch.cuda.memory_reserved()) / 2**20
        peak = float(_torch.cuda.max_memory_allocated()) / 2**20
        logger.info(
            "vram scene_id=%s point=%s allocated_mib=%.0f reserved_mib=%.0f peak_mib=%.0f",
            scene_id, point, allocated, reserved, peak,
        )
        _torch.cuda.reset_peak_memory_stats()
    except Exception:
        pass  # observability must never break processing


def _reconstruct_with_retry(sam3d_model: Any, pil, mask, seed: int):
    """One SAM 3D reconstruct with a single retry that can actually succeed.

    The retry MUST run after the except block exits. While an exception is
    being handled, its traceback pins every frame of the failed attempt —
    including the pipeline's intermediate GPU tensors — so a retry launched
    inside the handler competes against the very memory it needs freed.
    Production evidence (scene 25a14caf, 2026-07-21): every logged OOM
    reported ~21.7 GiB "allocated by PyTorch" with <90 MiB reserved-but-
    unallocated — the retry was double-booked against the pinned first
    attempt, so a 20 MiB allocation failed on a 22 GiB card. Restructured,
    the first attempt's tensors are collectable (traceback cycles swept by
    _free_gpu_memory's gc.collect) before attempt two begins.
    """
    try:
        return sam3d_model.reconstruct(pil, mask, seed=seed)
    except Exception:
        logger.warning(
            "reconstruct attempt 1 failed; retrying once after freeing GPU memory",
            exc_info=True,
        )
    _free_gpu_memory()
    return sam3d_model.reconstruct(pil, mask, seed=seed)


def _reconstruct_one_object(
    *,
    scene_id: str,
    frame_idx: int,
    i: int,
    obj: dict,
    pil,
    outputs_bucket: str,
    sam3d_model: Any,
    budget,
    frame,
    depth_raster,
    depth_confidence,
    depth_intrinsics,
    objects_done: int = 0,
    objects_detected: int = 0,
) -> tuple[Optional[dict], bool]:
    """Reconstruct + place ONE detected object; the per-object body shared
    verbatim by the legacy frame loop and the census two-pass driver
    (decision 0077 — extracting it keeps the cache blobs, layout sidecar,
    budget admission, soft-fail, and GPU-memory hygiene identical on both
    paths).

    Returns (entry, budget_stopped): entry is the objects.json record (ok
    or soft-fail), or None exactly when the budget refused the fresh
    reconstruction (budget_stopped True — the caller stops and does NOT
    cache the frame). objects_done/objects_detected only feed the
    budget_stop log line.
    """
    import placement as placement_mod  # deferred with the other heavy imports

    frame_prefix = f"scenes/{scene_id}/frames/{frame_idx:04d}"
    result = None
    ply_bytes = None
    safe = _safe_label(obj["label"])
    splat_blob = f"{frame_prefix}/splats/{i:02d}_{safe}.ply"

    meta = {
        "label": obj["label"],
        "instance_idx": obj["instance_idx"],
        "bbox": obj["bbox"],
        "score": obj["score"],
        "mask_index": i,
    }

    try:
        layout = None
        # Per-object cache: reuse the uploaded splat if present. The
        # bytes are downloaded (not just existence-checked) because
        # placement needs the vertex positions either way.
        cached_ply = _gcs_blob_exists_and_get(outputs_bucket, splat_blob)
        layout_blob = splat_blob[: -len(".ply")] + ".layout.json"
        if cached_ply is not None:
            # The layout sidecar (written at fresh-reconstruct time)
            # carries the RAW model rotation, so the rotation survives
            # cross-attempt cache hits; extract_layout re-applies the
            # current conventions at read time — a stored sidecar can
            # never go stale against a convention fix. Splats from
            # before sidecars existed have none and degrade to
            # rotation_source "none" as before.
            cached_layout = _gcs_blob_exists_and_get(outputs_bucket, layout_blob)
            if cached_layout is not None:
                try:
                    layout = placement_mod.extract_layout(
                        json.loads(cached_layout)
                    )
                except Exception:
                    logger.warning(
                        "unreadable layout sidecar %s; placing without "
                        "rotation", layout_blob,
                    )
                    layout = None
            ply_bytes = cached_ply
            entry = {
                **meta,
                "ok": True,
                "cached": True,
                "splat_gcs_uri": f"gs://{outputs_bucket}/{splat_blob}",
            }
        else:
            # Budget admission gates only FRESH reconstructions —
            # cache hits above cost seconds, a reconstruct costs tens.
            if budget is not None and not budget.can_start_object():
                logger.info(
                    "budget_stop point=object scene_id=%s frame=%d "
                    "objects_done=%d objects_detected=%d %s",
                    scene_id, frame_idx, objects_done, objects_detected,
                    budget.snapshot(),
                )
                return None, True

            object_started = time.monotonic()
            result = _reconstruct_with_retry(
                sam3d_model, pil, obj["mask"], seed=42 + i
            )
            if budget is not None:
                budget.note_object(time.monotonic() - object_started)

            # Runtime confirmation seam for the layout-key/convention
            # assumptions in placement.py (no GPU exists in dev).
            logger.info(
                "sam3d result keys frame=%d obj=%d: %s",
                frame_idx, i, sorted(result.keys()),
            )
            layout = placement_mod.extract_layout(result)

            # Convert to PLY bytes.
            gs = result.get("gs")
            if gs is None:
                raise RuntimeError("No 'gs' output in SAM 3D result")
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".ply", delete=True) as tmp:
                gs.save_ply(tmp.name)
                with open(tmp.name, "rb") as f:
                    ply_bytes = f.read()

            # Everything downstream needs is now on the CPU (layout is
            # numpy via extract_layout, the splat is bytes). Drop the
            # result dict — 15 keys of GPU tensors — BEFORE the upload
            # and placement tail work, not seconds later in finally.
            result = None
            del gs
            _free_gpu_memory()

            splat_uri = _gcs_upload_for_scene(
                f"gs://{outputs_bucket}/", splat_blob, ply_bytes,
                "application/octet-stream"
            )
            if layout is not None:
                # Persist the RAW rotation (+ translation/scale) beside
                # the splat so a later attempt's cache hit keeps the
                # orientation. Raw, not converted: read-time
                # extract_layout applies whatever conventions are then
                # current (see the cache-hit branch above).
                _gcs_upload_for_scene(
                    f"gs://{outputs_bucket}/",
                    layout_blob,
                    json.dumps(
                        {
                            "rotation": layout["raw_rotation"],
                            "translation": layout["translation"],
                            "scale": layout["scale"],
                        }
                    ).encode("utf-8"),
                    "application/json",
                )
            entry = {
                **meta,
                "ok": True,
                "cached": False,
                "splat_gcs_uri": splat_uri,
                "splat_size_bytes": len(ply_bytes),
            }

        if frame is not None:
            view_ray = placement_mod.object_view_ray(
                obj["mask"], frame.intrinsics, frame.camera_pose
            )
            if view_ray is not None:
                entry["view_ray"] = view_ray
            # compute_frame_placement never raises: placement bugs
            # degrade the object to unplaced, never abort the scene.
            entry["placement"] = placement_mod.compute_frame_placement(
                ply_bytes=ply_bytes,
                layout=layout,
                mask_rgb=obj["mask"],
                depth_raster=depth_raster,
                depth_confidence=depth_confidence,
                depth_intrinsics=depth_intrinsics,
                camera_pose=frame.camera_pose,
            )
        return entry, False
    except (PoisonError, EnvironmentalError):
        # GCS upload failures stay environmental: the whole attempt is
        # retryable, and a scene must not go `ready` with objects missing
        # only because the output bucket was briefly unavailable.
        raise
    except Exception as exc:
        # Model/conversion failure on ONE object soft-fails that object
        # and continues the frame, rather than aborting the whole scene.
        logger.error(
            "SAM 3D failed on frame %d object %d (%s); continuing: %s",
            frame_idx, i, obj["label"], exc,
        )
        return {**meta, "ok": False, "error": str(exc)}, False
    finally:
        # Safety net: the fresh path already dropped result eagerly; this
        # covers the cache-hit and exception paths, and sweeps the
        # traceback cycles a soft-failed object leaves behind.
        del result
        del ply_bytes
        _free_gpu_memory()


def _process_frame(
    *,
    scene_id: str,
    frame_idx: int,
    rgb_gcs_uri: str,
    outputs_bucket: str,
    sam3_model: Any,
    sam3d_model: Any,
    object_prompt: str,
    frame=None,
    bundle_prefix: Optional[str] = None,
    budget=None,
) -> dict:
    """Run SAM 3 + SAM 3D on one frame. Returns a dict with per-object results.

    budget is an optional budget.BudgetTracker. When provided, each fresh
    (non-cached) reconstruction is admitted against the remaining request
    budget; on refusal the frame stops early and the returned dict carries
    "budget_stopped": True. A budget-stopped frame is NOT cached to GCS
    (neither objects.json nor masks.npz) — caching would make the partial
    result permanent, since cache hits skip reprocessing. Its completed
    objects keep their per-object splat cache for a future attempt.

    Per frame: fetch the RGB image from GCS, segment it with SAM 3, reconstruct
    each detected object with SAM 3D, and upload each splat PLY plus a packed
    masks.npz and a per-frame objects.json manifest under
    scenes/{scene_id}/frames/{frame_idx}/. Frame and per-object outputs already
    present in GCS are reused as a cache (partial-run recovery on retry).
    Each fresh reconstruct also writes a {splat}.layout.json sidecar holding
    the RAW layout fields, so per-object cache hits on later attempts keep
    the object's rotation (converted at read time under current
    conventions).

    frame is the CaptureBundle Frame proto (pose/intrinsics/gravity/depth);
    when provided (with bundle_prefix for depth blob resolution), each
    object entry gains a world "placement" (LiDAR depth fit, or an
    unplaced record pending scene-level ray triangulation on ARKIT_ONLY
    frames) and a "view_ray" observation. When None (legacy callers/tests),
    entries carry no placement fields.

    Raises PoisonError if the image or a depth raster can't be fetched or
    decoded. Raises EnvironmentalError on model or GCS failures.
    """
    from PIL import Image

    frame_prefix = f"scenes/{scene_id}/frames/{frame_idx:04d}"
    objects_blob = f"{frame_prefix}/objects.json"

    # Whole-frame cache hit: a previous run already processed this frame.
    cached_bytes = _gcs_blob_exists_and_get(outputs_bucket, objects_blob)
    if cached_bytes:
        logger.info("Frame %d cache hit for scene %s", frame_idx, scene_id)
        return json.loads(cached_bytes)

    # Fetch + open the RGB image.
    try:
        img_bytes = _download_gcs_uri(rgb_gcs_uri)
    except PoisonError:
        raise
    except Exception as exc:
        raise EnvironmentalError(f"Failed to fetch frame {frame_idx}: {exc}") from exc

    try:
        pil = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    except Exception as exc:
        raise PoisonError(f"Frame {frame_idx} image cannot be opened: {exc}") from exc

    # SAM 3 segmentation. Suppressed concepts (decision 0089) ride the same
    # pass and are partitioned straight back out: they exist only to build the
    # exclusion union the shell reads, and must never reach reconstruction.
    from privacy import masks_npz_bytes, partition_detections, segmentation_prompt

    try:
        detections = sam3_model.segment(pil, segmentation_prompt(object_prompt))
    except Exception as exc:
        raise EnvironmentalError(f"SAM 3 failed on frame {frame_idx}: {exc}") from exc
    detections, suppressed = partition_detections(detections)
    if suppressed:
        logger.info(
            "privacy: frame %d scene %s suppressed=%d labels=%s",
            frame_idx, scene_id, len(suppressed),
            sorted({d["label"] for d in suppressed}),
        )

    # LiDAR depth payload for this frame; (None, None, None) on ARKIT_ONLY
    # frames or when the caller provided no Frame proto.
    if frame is not None and bundle_prefix is not None:
        depth_raster, depth_confidence, depth_intrinsics = _fetch_frame_depth(
            frame, bundle_prefix
        )
    else:
        depth_raster = depth_confidence = depth_intrinsics = None

    # SAM 3D per object.
    objects_out: list[dict] = []
    budget_stopped = False
    for i, obj in enumerate(detections):
        entry, stopped = _reconstruct_one_object(
            scene_id=scene_id,
            frame_idx=frame_idx,
            i=i,
            obj=obj,
            pil=pil,
            outputs_bucket=outputs_bucket,
            sam3d_model=sam3d_model,
            budget=budget,
            frame=frame,
            depth_raster=depth_raster,
            depth_confidence=depth_confidence,
            depth_intrinsics=depth_intrinsics,
            objects_done=len(objects_out),
            objects_detected=len(detections),
        )
        if stopped:
            budget_stopped = True
            break
        objects_out.append(entry)

    if budget_stopped:
        # Incomplete frame: no masks.npz, no objects.json cache (see
        # docstring). The caller banks the completed objects and stops.
        return {
            "frame_index": frame_idx,
            "rgb_gcs_uri": rgb_gcs_uri,
            "image_size": [pil.width, pil.height],
            "masks_gcs_uri": None,
            "objects": objects_out,
            "ok": True,
            "budget_stopped": True,
        }

    # Upload masks.npz (kept stack + the suppressed union, when any).
    masks_uri = _gcs_upload_for_scene(
        f"gs://{outputs_bucket}/", f"{frame_prefix}/masks.npz",
        masks_npz_bytes(detections, suppressed), "application/octet-stream"
    )

    frame_result = {
        "frame_index": frame_idx,
        "rgb_gcs_uri": rgb_gcs_uri,
        "image_size": [pil.width, pil.height],
        "masks_gcs_uri": masks_uri,
        "objects": objects_out,
        "ok": True,
    }

    # Cache the per-frame manifest.
    _gcs_upload_for_scene(
        f"gs://{outputs_bucket}/", objects_blob,
        json.dumps(frame_result).encode(), "application/json"
    )
    return frame_result


def _gcs_blob_exists_and_get(bucket_name: str, blob_path: str) -> Optional[bytes]:
    """Return blob bytes if it exists, None otherwise."""
    try:
        from google.cloud import storage
        blob = storage.Client().bucket(bucket_name).blob(blob_path)
        if blob.exists():
            return blob.download_as_bytes()
    except Exception:
        pass
    return None


def _load_scene_room_plan(
    *, bundle: CaptureBundle, bundle_uri: str, scene_id: str, outputs_bucket: str
):
    """Load + parse the bundle's CapturedRoom JSON (decision 0077).

    Returns (room, parse_reason, source): room is a
    roomplan_room.RoomPlanRoom or None; parse_reason records WHY it is None
    when the bundle claimed one (the roomplan_parse_failed manifest note);
    source is "cached" | "bundle" when parsed.

    The verbatim JSON is cached to the outputs bucket on first read
    (scenes/{id}/roomplan/room.json) so the geometry survives the captures
    bucket's 1-day sweep — the 0065 sidecar lesson; /shell and warm
    re-drives read the cached copy. The cached copy is also preferred here,
    so every attempt of a scene parses the same bytes. A missing/corrupt
    room.json NEVER fails the scene — the caller degrades to LIDAR_ARKIT
    semantics (structured log + manifest note).
    """
    from roomplan_room import try_parse_captured_room  # deferred, heavy-path only

    if not (bundle.HasField("room_plan") and bundle.room_plan.json_gcs_path):
        return None, None, None

    cache_blob = f"scenes/{scene_id}/roomplan/room.json"
    raw = _gcs_blob_exists_and_get(outputs_bucket, cache_blob)
    source = "cached"
    if raw is None:
        source = "bundle"
        try:
            raw = _download_gcs_uri(
                _bundle_prefix(bundle_uri) + bundle.room_plan.json_gcs_path
            )
        except PoisonError:
            return None, "room_json_missing", None
        # Cache write-through: an EnvironmentalError here propagates (the
        # whole attempt retries cheaply pre-model-load), keeping the cache
        # guarantee — a ready ROOMPLAN scene always has the cached copy.
        _gcs_upload_for_scene(
            f"gs://{outputs_bucket}/", cache_blob, raw, "application/json"
        )

    room, reason = try_parse_captured_room(raw)
    if room is not None and not room.has_geometry:
        room, reason = None, "no walls or floor in CapturedRoom"
    if room is None:
        return None, reason, None
    return room, None, source


def _build_refinement_context(
    *, bundle: CaptureBundle, scene_id: str, bundle_uri: str, outputs_bucket: str,
    budget, room_plan=None,
):
    """Wire fusion.py's RefinementContext (decision 0067) to this
    service's actual GCS-backed evidence sources.

    Everything is memoized for the lifetime of one fusion pass: splat
    BYTES are fetched once and parsed twice (vertices for tier 1 and the
    fits, colors/opacity for tier 2), mask stacks once per frame, and
    frame RGB once per frame — cached as uint8 (~8 MB/frame, bounded by
    the <= PERCEPTION_MAX_FRAMES sampled frames) rather than float
    (tier 2's NCC is intensity-scale-invariant, so the small form loses
    nothing). RGB comes from the captures bucket, whose 1-day lifecycle
    can outlive the objects on a warm re-drive — a missing frame degrades
    that frame's scoring to tier-1-only inside reproject, recorded in
    tiers_used, exactly like any other cache miss.
    """
    import contact_priors as contact_priors_mod
    import fusion as fusion_mod
    import placement as placement_mod
    import reproject as reproject_mod

    frames_by_idx = {f.frame_index: f for f in bundle.frames}
    bundle_prefix = _bundle_prefix(bundle_uri)
    splat_bytes_cache: dict[str, Optional[bytes]] = {}
    splat_pts_cache: dict[str, Optional[Any]] = {}
    appearance_cache: dict[str, Optional[Any]] = {}
    rgb_cache: dict[int, Optional[Any]] = {}
    depth_cache: dict[int, Optional[tuple]] = {}

    # Measured room planes, parsed once (via room_planes — the same reading
    # the shell renders) and reused for every single-view contact-prior
    # placement. A bundle with no plane anchors yields empty planes, so
    # priors are inert and single-view objects stay unplaced (decision 0067's
    # degrade lock). Cached because fusion may call it per unplaced object.
    room_planes_holder: list = []

    def get_room_planes():
        if not room_planes_holder:
            room_planes_holder.append(
                contact_priors_mod.extract_room_planes(bundle.plane_anchors)
            )
        return room_planes_holder[0]

    def get_camera(frame_index):
        frame = frames_by_idx.get(frame_index)
        if frame is None:
            return None
        return (frame.camera_pose, frame.intrinsics)

    def get_mask_stack(frame_index):
        import numpy as np  # deferred: heavy dep, only needed during refinement

        raw = _gcs_blob_exists_and_get(
            outputs_bucket, f"scenes/{scene_id}/frames/{frame_index:04d}/masks.npz"
        )
        if raw is None:
            return None
        try:
            return np.load(io.BytesIO(raw))["masks"]
        except Exception:
            logger.warning("refinement: unreadable masks.npz for frame %d", frame_index)
            return None

    def _splat_bytes(splat_uri: str) -> Optional[bytes]:
        if splat_uri not in splat_bytes_cache:
            raw = None
            if splat_uri.startswith("gs://"):
                bucket_name, blob_path = splat_uri[5:].split("/", 1)
                raw = _gcs_blob_exists_and_get(bucket_name, blob_path)
            splat_bytes_cache[splat_uri] = raw
        return splat_bytes_cache[splat_uri]

    def get_splat(splat_uri: str):
        if splat_uri not in splat_pts_cache:
            pts = None
            raw = _splat_bytes(splat_uri)
            if raw is not None:
                try:
                    pts = placement_mod.parse_ply_vertices(raw)
                except Exception:
                    logger.warning("refinement: unparseable splat %s", splat_uri)
            splat_pts_cache[splat_uri] = pts
        return splat_pts_cache[splat_uri]

    def get_appearance(splat_uri: str):
        if splat_uri not in appearance_cache:
            appearance = None
            raw = _splat_bytes(splat_uri)
            if raw is not None:
                try:
                    appearance = reproject_mod.load_splat_appearance(raw)
                except Exception:
                    logger.warning("refinement: unparseable splat appearance %s", splat_uri)
            appearance_cache[splat_uri] = appearance
        return appearance_cache[splat_uri]

    def get_rgb(frame_index):
        if frame_index not in rgb_cache:
            import numpy as np  # deferred

            rgb = None
            frame = frames_by_idx.get(frame_index)
            if frame is not None and frame.rgb_gcs_path:
                uri = bundle_prefix + frame.rgb_gcs_path
                bucket_name, blob_path = uri[5:].split("/", 1)
                raw = _gcs_blob_exists_and_get(bucket_name, blob_path)
                if raw is not None:
                    try:
                        from PIL import Image  # deferred

                        rgb = np.asarray(Image.open(io.BytesIO(raw)).convert("RGB"))
                    except Exception:
                        logger.warning("refinement: undecodable rgb for frame %d", frame_index)
            rgb_cache[frame_index] = rgb
        return rgb_cache[frame_index]

    def get_depth(frame_index):
        """(depth_raster, confidence, intrinsics) | None — the 0081 cloud
        scorer's evidence. Same captures-bucket sourcing (and the same
        swept-capture degrade) as get_rgb; a malformed raster is a warning
        + None here, never the poison it is on the reconstruction path —
        scoring is optional, reconstruction is not."""
        if frame_index not in depth_cache:
            payload = None
            frame = frames_by_idx.get(frame_index)
            if frame is not None and frame.HasField("depth"):
                try:
                    depth, conf, dintr = _fetch_frame_depth(frame, bundle_prefix)
                    if depth is not None:
                        payload = (depth, conf, dintr)
                except Exception:
                    logger.warning(
                        "refinement: depth unavailable for frame %d", frame_index
                    )
            depth_cache[frame_index] = payload
        return depth_cache[frame_index]

    return fusion_mod.RefinementContext(
        get_camera=get_camera,
        get_mask_stack=get_mask_stack,
        get_splat=get_splat,
        get_appearance=get_appearance,
        get_rgb=get_rgb,
        get_depth=get_depth,
        get_room_planes=get_room_planes,
        get_roomplan=(lambda: room_plan),
        budget=budget,
    )


# ---------------------------------------------------------------------------
# Census two-pass driver (decision 0077 lock 6 — LIDAR_ROOMPLAN scenes)
# ---------------------------------------------------------------------------

# How many associated views per box the reconstruction plan admits (best +
# second view; further views of a covered box are policy-skipped — cached
# with a skipped_reason, deterministically).
_PLAN_VIEWS_PER_BOX = int(os.environ.get("PERCEPTION_PLAN_VIEWS_PER_BOX", "2"))


class _PlanCtx:
    """Association accessor over the two-pass state: pass-1 masks unpack
    on demand (they are held bit-packed — ~30 full-res bool masks per
    frame x 12 frames would be ~1 GB raw); whole-frame-CACHED frames'
    masks lazy-load from their masks.npz so a warm retry's plan can see
    which box views prior attempts already reconstructed."""

    def __init__(
        self, frames_by_idx: dict, states: dict, cached_masks: dict
    ) -> None:
        self._frames = frames_by_idx
        self._states = states
        self._cached_loaders = cached_masks  # frame_index -> () -> stack|None
        self._cached_stacks: dict[int, Any] = {}

    def get_camera(self, frame_index):
        frame = self._frames.get(frame_index)
        if frame is None:
            return None
        return (frame.camera_pose, frame.intrinsics)

    def mask_for(self, frame_index, mask_index):
        if mask_index is None:
            return None
        st = self._states.get(frame_index)
        if st is not None:
            if mask_index >= len(st["detections"]):
                return None
            return st["unpack_mask"](mask_index)
        if frame_index in self._cached_loaders:
            if frame_index not in self._cached_stacks:
                self._cached_stacks[frame_index] = self._cached_loaders[frame_index]()
            stack = self._cached_stacks[frame_index]
            if stack is None or mask_index >= stack.shape[0]:
                return None
            return stack[mask_index]
        return None


def _build_reconstruction_plan(
    boxes: list, states: dict, frames_by_idx: dict, cached_results: dict,
    outputs_bucket: str, scene_id: str,
) -> tuple[list[tuple[int, int, str]], dict]:
    """The deterministic pass-2 order: (frame_index, mask_index, tier)
    triples over the PASS-1 (uncached) frames. Priority (decision 0077):
    uncovered boxes' best views first, then second views (boxes with the
    WEAKEST best association first — the low-margin ones benefit most from
    another view), then the long tail by detection score. Views of a box
    beyond _PLAN_VIEWS_PER_BOX are policy-skipped (recorded, cached — a
    deterministic decision, unlike a budget cut).

    Association runs over cached frames too (their masks.npz lazy-loads):
    a box view a prior attempt already reconstructed counts toward the
    per-box view budget, so a warm retry never re-reconstructs a covered
    box from scratch. Returns (plan, {"info", "skipped"})."""
    import box_placement  # deferred with the other heavy imports
    import numpy as np  # deferred

    observations = []
    done_ok: set[tuple[int, Optional[int]]] = set()
    cached_masks: dict[int, Any] = {}
    for frame_index, st in states.items():
        for mi, det in enumerate(st["detections"]):
            observations.append({
                "frame_index": frame_index,
                "label": det["label"],
                "score": float(det["score"]),
                "mask_index": mi,
                "splat_gcs_uri": "",
                "placement": {},
                "view_ray": None,
            })
    for frame_index, result in cached_results.items():
        for entry in result.get("objects", []):
            if entry.get("ok"):
                done_ok.add((frame_index, entry.get("mask_index")))
                observations.append({
                    "frame_index": frame_index,
                    "label": entry.get("label"),
                    "score": float(entry.get("score", 0.0)),
                    "mask_index": entry.get("mask_index"),
                    "splat_gcs_uri": entry.get("splat_gcs_uri", ""),
                    "placement": {},
                    "view_ray": None,
                })

        def _loader(fi=frame_index):
            raw = _gcs_blob_exists_and_get(
                outputs_bucket, f"scenes/{scene_id}/frames/{fi:04d}/masks.npz"
            )
            if raw is None:
                return None
            try:
                return np.load(io.BytesIO(raw))["masks"]
            except Exception:
                return None

        cached_masks[frame_index] = _loader
    observations.sort(key=lambda o: (o["frame_index"], o["mask_index"]))

    ctx = _PlanCtx(frames_by_idx, states, cached_masks)
    assoc_by_box = box_placement.associate_observations(boxes, observations, ctx)

    plan: list[tuple[int, int, str]] = []
    planned: set[tuple[int, int]] = set()
    skipped: list[tuple[int, int]] = []

    def _views_left(bi: int) -> int:
        already = sum(
            1 for a in assoc_by_box.get(bi, [])
            if (a.frame_index, a.mask_index) in done_ok
        )
        return max(0, _PLAN_VIEWS_PER_BOX - already)

    # Tier 1: every box's best not-yet-reconstructed view, census order.
    for bi in range(len(boxes)):
        if _views_left(bi) < 1:
            continue
        for a in assoc_by_box.get(bi, []):
            key = (a.frame_index, a.mask_index)
            if key in done_ok or key in planned:
                continue
            plan.append((*key, "box_best_view"))
            planned.add(key)
            break

    # Tier 2: second views, weakest best-association first.
    seconds = [
        (assoc_by_box[bi][0].overlap, bi)
        for bi in sorted(assoc_by_box)
        if _views_left(bi) >= 2
    ]
    seconds.sort(key=lambda p: (p[0], p[1]))
    for _overlap, bi in seconds:
        taken = sum(
            1 for a in assoc_by_box[bi]
            if (a.frame_index, a.mask_index) in planned
        )
        budget_left = _views_left(bi) - taken
        for a in assoc_by_box[bi]:
            if budget_left <= 0:
                break
            key = (a.frame_index, a.mask_index)
            if key in done_ok or key in planned:
                continue
            plan.append((*key, "box_second_view"))
            planned.add(key)
            budget_left -= 1

    # Policy skips: associated pass-1 views beyond the per-box budget.
    for bi in sorted(assoc_by_box):
        for a in assoc_by_box[bi]:
            key = (a.frame_index, a.mask_index)
            if key in done_ok or key in planned or a.frame_index not in states:
                continue
            skipped.append(key)
            planned.add(key)

    # Tier 3: the long tail (unassociated pass-1 masks), score desc.
    tail = [
        o for o in observations
        if o["frame_index"] in states
        and (o["frame_index"], o["mask_index"]) not in planned
    ]
    tail.sort(key=lambda o: (-o["score"], o["frame_index"], o["mask_index"]))
    for o in tail:
        key = (o["frame_index"], o["mask_index"])
        plan.append((*key, "long_tail"))
        planned.add(key)

    plan_info = {
        "box_best_views": sum(1 for p in plan if p[2] == "box_best_view"),
        "box_second_views": sum(1 for p in plan if p[2] == "box_second_view"),
        "long_tail": sum(1 for p in plan if p[2] == "long_tail"),
        "policy_skipped": len(skipped),
        "associated_boxes": sorted(f"box_{bi:02d}" for bi in assoc_by_box),
    }
    return plan, {"info": plan_info, "skipped": skipped}


def _run_census_two_pass(
    *,
    scene_id: str,
    bundle: CaptureBundle,
    bundle_uri: str,
    selected: list,
    boxes: list,
    outputs_bucket: str,
    sam3_model: Any,
    sam3d_model: Any,
    object_prompt: str,
    budget,
) -> tuple[list[dict], bool, dict]:
    """Two-pass frame processing for census scenes (decision 0077): pass 1
    segments the sampled frames (masks.npz written per frame — it is
    complete at segmentation time); pass 2 reconstructs per the plan under
    budget admission. Returns (frame_results, budget_stopped, plan_info).

    Cache contract (frozen; additive only): a frame's objects.json is
    written exactly when every planned mask in it was ATTEMPTED — masks
    deliberately not reconstructed carry `skipped_reason` (a deterministic
    policy decision, safe to cache); a frame with a budget-cut planned
    mask is NOT cached (0062's law — a budget stop must never become
    permanent), and its completed objects keep their per-object splat
    caches for the next attempt. Whole-frame cache hits (legacy or
    two-pass) are used verbatim.
    """
    import numpy as np  # deferred: heavy dep, only during processing
    from PIL import Image
    from privacy import masks_npz_bytes, partition_detections, segmentation_prompt

    prefix = _bundle_prefix(bundle_uri)
    frames_by_idx = {f.frame_index: f for f in bundle.frames}
    frame_results_by_idx: dict[int, dict] = {}
    states: dict[int, dict] = {}
    budget_stopped = False

    # ---- Pass 1: segmentation (cache-aware) -------------------------------
    for frame in selected:
        frame_idx = frame.frame_index
        frame_prefix = f"scenes/{scene_id}/frames/{frame_idx:04d}"
        cached_bytes = _gcs_blob_exists_and_get(
            outputs_bucket, f"{frame_prefix}/objects.json"
        )
        if cached_bytes:
            logger.info("Frame %d cache hit for scene %s", frame_idx, scene_id)
            frame_results_by_idx[frame_idx] = json.loads(cached_bytes)
            continue

        # Segmentation admission: a SAM 3 pass costs a few seconds — the
        # object estimate is a conservative upper bound for "one more
        # cheap step" without teaching the tracker a new cost class.
        if budget is not None and not budget.can_start_object():
            budget_stopped = True
            logger.info(
                "budget_stop point=segment scene_id=%s frames_segmented=%d %s",
                scene_id, len(states), budget.snapshot(),
            )
            break

        rgb_uri = prefix + frame.rgb_gcs_path
        try:
            img_bytes = _download_gcs_uri(rgb_uri)
        except PoisonError:
            raise
        except Exception as exc:
            raise EnvironmentalError(
                f"Failed to fetch frame {frame_idx}: {exc}"
            ) from exc
        try:
            pil = Image.open(io.BytesIO(img_bytes)).convert("RGB")
        except Exception as exc:
            raise PoisonError(
                f"Frame {frame_idx} image cannot be opened: {exc}"
            ) from exc

        try:
            detections = sam3_model.segment(pil, segmentation_prompt(object_prompt))
        except Exception as exc:
            raise EnvironmentalError(
                f"SAM 3 failed on frame {frame_idx}: {exc}"
            ) from exc
        # Suppressed concepts leave the pipeline here (decision 0089): only
        # the exclusion union survives, and only inside masks.npz.
        detections, suppressed = partition_detections(detections)
        if suppressed:
            logger.info(
                "privacy: frame %d scene %s suppressed=%d labels=%s",
                frame_idx, scene_id, len(suppressed),
                sorted({d["label"] for d in suppressed}),
            )

        # masks.npz is complete at segmentation time — write it now (the
        # shell + refinement read it; there is no masks-only cache-hit
        # path, so an early write can never short-circuit reprocessing).
        masks_uri = _gcs_upload_for_scene(
            f"gs://{outputs_bucket}/", f"{frame_prefix}/masks.npz",
            masks_npz_bytes(detections, suppressed), "application/octet-stream"
        )

        # Hold masks bit-packed (~8x smaller than bool) for association +
        # pass-2 reconstruction; unpack on demand.
        mask_shape = detections[0]["mask"].shape if detections else (0, 0)
        packed = [np.packbits(d["mask"].astype(bool)) for d in detections]
        det_meta = [
            {k: d[k] for k in ("label", "instance_idx", "bbox", "score")}
            for d in detections
        ]

        def _unpacker(packed_list, shape):
            def unpack(mi: int):
                flat = np.unpackbits(packed_list[mi])[: shape[0] * shape[1]]
                return flat.reshape(shape).astype(bool)
            return unpack

        states[frame_idx] = {
            "frame": frame,
            "pil": pil,
            "rgb_gcs_uri": rgb_uri,
            "masks_uri": masks_uri,
            "detections": det_meta,
            "unpack_mask": _unpacker(packed, mask_shape),
            "entries": {},
            "depth": None,  # fetched lazily at first pass-2 use
        }

    # ---- Plan + Pass 2 ----------------------------------------------------
    plan, plan_meta = _build_reconstruction_plan(
        boxes, states, frames_by_idx, frame_results_by_idx,
        outputs_bucket, scene_id,
    )
    executed: set[tuple[int, int]] = set()
    if not budget_stopped:
        for frame_idx, mask_index, _tier in plan:
            st = states[frame_idx]
            det = st["detections"][mask_index]
            if st["depth"] is None:
                st["depth"] = _fetch_frame_depth(st["frame"], prefix)
            depth_raster, depth_confidence, depth_intrinsics = st["depth"]
            obj = {**det, "mask": st["unpack_mask"](mask_index)}
            entry, stopped = _reconstruct_one_object(
                scene_id=scene_id,
                frame_idx=frame_idx,
                i=mask_index,
                obj=obj,
                pil=st["pil"],
                outputs_bucket=outputs_bucket,
                sam3d_model=sam3d_model,
                budget=budget,
                frame=st["frame"],
                depth_raster=depth_raster,
                depth_confidence=depth_confidence,
                depth_intrinsics=depth_intrinsics,
                objects_done=len(executed),
                objects_detected=len(plan),
            )
            if stopped:
                budget_stopped = True
                break
            st["entries"][mask_index] = entry
            executed.add((frame_idx, mask_index))
            _free_gpu_memory()

    # Policy skips: recorded entries (deterministic — safe to cache).
    for frame_idx, mask_index in plan_meta["skipped"]:
        st = states[frame_idx]
        det = st["detections"][mask_index]
        st["entries"][mask_index] = {
            "label": det["label"],
            "instance_idx": det["instance_idx"],
            "bbox": det["bbox"],
            "score": det["score"],
            "mask_index": mask_index,
            "ok": False,
            "skipped_reason": "box_covered_by_other_view",
        }

    # ---- Finalize frames (in selected order) ------------------------------
    planned_by_frame: dict[int, set[int]] = {}
    for frame_idx, mask_index, _tier in plan:
        planned_by_frame.setdefault(frame_idx, set()).add(mask_index)

    frame_results: list[dict] = []
    for frame in selected:
        frame_idx = frame.frame_index
        if frame_idx in frame_results_by_idx:  # whole-frame cache hit
            frame_results.append(frame_results_by_idx[frame_idx])
            continue
        st = states.get(frame_idx)
        if st is None:
            continue  # pass-1 budget cut before this frame — not attempted
        pending = planned_by_frame.get(frame_idx, set()) - set(st["entries"])
        objects_out = [st["entries"][mi] for mi in sorted(st["entries"])]
        result = {
            "frame_index": frame_idx,
            "rgb_gcs_uri": st["rgb_gcs_uri"],
            "image_size": [st["pil"].width, st["pil"].height],
            "masks_gcs_uri": st["masks_uri"],
            "objects": objects_out,
            "ok": True,
        }
        if pending:
            # Budget cut a planned mask in this frame: the frame is
            # incomplete — never cached (its finished splats keep their
            # per-object caches for the retry).
            result["budget_stopped"] = True
            frame_results.append(result)
            continue
        _gcs_upload_for_scene(
            f"gs://{outputs_bucket}/",
            f"scenes/{scene_id}/frames/{frame_idx:04d}/objects.json",
            json.dumps(result).encode(), "application/json"
        )
        frame_results.append(result)

    return frame_results, budget_stopped, plan_meta["info"]


# ---------------------------------------------------------------------------
# Top-level processing orchestrator
# ---------------------------------------------------------------------------

def run_perception(
    *,
    scene_id: str,
    bundle_uri: str,
    outputs_bucket: str,
    sam3_model: Any,
    sam3d_model: Any,
    object_prompt: str,
    max_frames: Optional[int] = None,
    budget=None,
) -> str:
    """Process a bounded, pose-diverse subset of the bundle's frames.
    Returns the gs:// URI of the manifest.

    max_frames caps how many frames are reconstructed (None → sampling
    module default, env PERCEPTION_MAX_FRAMES). budget is an optional
    budget.BudgetTracker anchored at request entry; when the remaining
    budget can't fit another frame (or another object, mid-frame), the loop
    stops early and the scene ships with what's banked — a degraded-but-
    ready scene beats a request-timeout zombie. If NO frame completed in
    full, raises EnvironmentalError instead: the Cloud Tasks retry starts
    with warm models and per-object splat caches, so it gets strictly
    further than this attempt did.

    Raises PoisonError or EnvironmentalError as appropriate.
    """
    import sampling as sampling_mod  # deferred with the other heavy imports
    from budget import BudgetTracker

    if budget is None:
        budget = BudgetTracker(None)  # unlimited (tests/local callers)

    # Fetch + parse the bundle proto.
    raw = _download_gcs_uri(bundle_uri)
    bundle = CaptureBundle()
    try:
        bundle.ParseFromString(raw)
    except Exception as exc:
        raise PoisonError(f"Bundle proto cannot be parsed: {exc}") from exc

    if not bundle.frames:
        raise PoisonError("Bundle has no frames")

    # CapturedRoom (decision 0077): parsed once, cached to the outputs
    # bucket, threaded into fusion's census pass. Missing/corrupt →
    # LIDAR_ARKIT semantics with a structured log + manifest note — never
    # a failed scene.
    room_plan, roomplan_reason, roomplan_source = _load_scene_room_plan(
        bundle=bundle, bundle_uri=bundle_uri, scene_id=scene_id,
        outputs_bucket=outputs_bucket,
    )
    if roomplan_reason is not None:
        logger.warning(
            "roomplan_parse_failed scene_id=%s reason=%s; degrading to "
            "LIDAR_ARKIT semantics", scene_id, roomplan_reason,
        )
    elif room_plan is not None:
        logger.info(
            "roomplan scene_id=%s source=%s walls=%d objects=%d",
            scene_id, roomplan_source, len(room_plan.walls), len(room_plan.objects),
        )

    frames_total = len(bundle.frames)
    effective_max = max_frames if max_frames is not None else sampling_mod.DEFAULT_MAX_FRAMES
    census_boxes = list(room_plan.objects) if room_plan is not None else []
    census_info = None
    if census_boxes:
        # Census-driven selection (decision 0077): box-visibility set-cover
        # + pose-diverse residue. No census → the 0062 sampler VERBATIM
        # (the degrade lock).
        import census_sampling as census_sampling_mod

        selected, census_info = census_sampling_mod.select_frames_census(
            bundle.frames, census_boxes, effective_max
        )
    else:
        selected = sampling_mod.select_frames(bundle.frames, effective_max)
    selected_indices = [f.frame_index for f in selected]
    logger.info(
        "sampling scene_id=%s frames_total=%d frames_sampled=%d policy=%s indices=%s",
        scene_id, frames_total, len(selected),
        "census_set_cover_v1" if census_boxes else "pose_diverse_fps_v1",
        selected_indices,
    )

    prefix = _bundle_prefix(bundle_uri)
    plan_info = None
    run_started = time.monotonic()

    if census_boxes:
        frame_results, budget_stopped, plan_info = _run_census_two_pass(
            scene_id=scene_id,
            bundle=bundle,
            bundle_uri=bundle_uri,
            selected=selected,
            boxes=census_boxes,
            outputs_bucket=outputs_bucket,
            sam3_model=sam3_model,
            sam3d_model=sam3d_model,
            object_prompt=object_prompt,
            budget=budget,
        )
        logger.info(
            "census two-pass scene_id=%s frames=%d plan=%s budget_stopped=%s "
            "elapsed_s=%.1f",
            scene_id, len(frame_results), plan_info, budget_stopped,
            time.monotonic() - run_started,
        )
        _log_vram(scene_id, "after_census_pass2")
    else:
        frame_results = []
        budget_stopped = False
        for frame in selected:
            if not budget.can_start_frame():
                budget_stopped = True
                logger.info(
                    "budget_stop point=frame scene_id=%s frames_done=%d "
                    "frames_planned=%d %s",
                    scene_id, len(frame_results), len(selected), budget.snapshot(),
                )
                break
            frame_started = time.monotonic()
            rgb_uri = prefix + frame.rgb_gcs_path
            frame_result = _process_frame(
                scene_id=scene_id,
                frame_idx=frame.frame_index,
                rgb_gcs_uri=rgb_uri,
                outputs_bucket=outputs_bucket,
                sam3_model=sam3_model,
                sam3d_model=sam3d_model,
                object_prompt=object_prompt,
                frame=frame,
                bundle_prefix=prefix,
                budget=budget,
            )
            frame_s = time.monotonic() - frame_started
            frame_results.append(frame_result)
            logger.info(
                "scene %s frame %d done (%d objects) frame_s=%.1f elapsed_s=%.1f %s",
                scene_id, frame.frame_index,
                sum(1 for o in frame_result.get("objects", []) if o.get("ok")),
                frame_s, time.monotonic() - run_started, budget.snapshot(),
            )
            if frame_result.get("budget_stopped"):
                # Mid-frame stop: bank this partial frame's objects and finish.
                budget_stopped = True
                break
            budget.note_frame(frame_s)
            _free_gpu_memory()
            _log_vram(scene_id, f"after_frame_{frame.frame_index}")

    complete_frames = [fr for fr in frame_results if not fr.get("budget_stopped")]
    if not complete_frames:
        # Nothing trustworthy banked. 5xx so Cloud Tasks retries: the retry
        # runs against warm models and this attempt's per-object splat
        # caches, so it makes strictly more progress per second.
        raise EnvironmentalError(
            f"budget exhausted before any frame completed "
            f"(frames_planned={len(selected)}); {budget.snapshot()}"
        )

    # Scene-level fusion: one entry per physical object, with a fused world
    # transform — the array the web viewer renders. Frames stay for
    # provenance/debug. See fusion.py.
    import fusion as fusion_mod
    refine_ctx = _build_refinement_context(
        bundle=bundle, scene_id=scene_id, bundle_uri=bundle_uri,
        outputs_bucket=outputs_bucket, budget=budget, room_plan=room_plan,
    )
    scene_objects, fusion_meta = fusion_mod.fuse_scene_objects_with_meta(frame_results, refine_ctx)

    # Scene-level roomplan note — emitted ONLY when the bundle claims a
    # CapturedRoom, so a no-roomplan bundle's manifest stays byte-identical
    # to the pre-0077 shape (the no-CapturedRoom degrade lock).
    roomplan_note: Optional[dict] = None
    if bundle.HasField("room_plan") and bundle.room_plan.json_gcs_path:
        roomplan_note = {
            "present": True,
            "parse_ok": room_plan is not None,
            "wall_count": len(room_plan.walls) if room_plan is not None else None,
            "object_count": len(room_plan.objects) if room_plan is not None else None,
        }
        if roomplan_reason is not None:
            roomplan_note["parse_failed"] = roomplan_reason
        if roomplan_source is not None:
            roomplan_note["source"] = roomplan_source

    manifest = {
        "scene_id": scene_id,
        "bundle_uri": bundle_uri,
        "schema_version": bundle.schema_version,
        "manifest_version": 2,
        "frame_count": frames_total,
        "frames_total": frames_total,
        "frames_sampled": len(selected),
        **({"roomplan": roomplan_note} if roomplan_note is not None else {}),
        "sampling": {
            "policy": (
                "census_set_cover_v1" if census_boxes else "pose_diverse_fps_v1"
            ),
            "max_frames": effective_max,
            "selected_frame_indices": selected_indices,
            "frames_processed": len(frame_results),
            "budget_stopped": budget_stopped,
            "refinement_skipped": fusion_meta["refinement_skipped"],
            **(
                {"census": {**census_info, "plan": plan_info}}
                if census_info is not None else {}
            ),
        },
        "objects": scene_objects,
        "frames": frame_results,
    }
    manifest_blob = f"scenes/{scene_id}/manifest.json"
    manifest_uri = _gcs_upload_for_scene(
        f"gs://{outputs_bucket}/", manifest_blob,
        json.dumps(manifest).encode(), "application/json"
    )
    return manifest_uri


# ---------------------------------------------------------------------------
# /process route handler (imported and registered in server.py)
# ---------------------------------------------------------------------------

async def handle_process(
    request: Request,
    req: ProcessRequest,
    *,
    oidc_verifier,        # OIDCVerifier | None (None disables auth, for tests)
    receiver_repo,        # ReceiverRepository
    fcm_notifier,         # FcmNotifier
    outputs_bucket: str,
    sam3_model: Any,
    sam3d_model: Any,
    object_prompt: str,
    deadline: Optional[float] = None,
) -> JSONResponse:
    """Core handler for POST /process. Injected into the FastAPI route in server.py.

    deadline is a time.monotonic() value captured at REQUEST ENTRY in
    server.py (before the lazy model load), bounding all reconstruction
    work so the handler finishes inside the Cloud Run request window —
    see budget.py for why. None disables budgeting (tests).

    Separating the handler from the route registration makes the logic testable
    without standing up a full FastAPI app or loading the SAM models.
    """
    from oidc import OIDCError

    # 1. OIDC verification.
    if oidc_verifier is not None:
        try:
            oidc_verifier.verify(request.headers.get("Authorization"))
        except OIDCError as exc:
            logger.warning("OIDC rejected: %s %s", exc.code, exc.detail)
            return JSONResponse(
                status_code=401,
                content={"error": exc.code, "detail": exc.detail},
            )

    # Stash the repo so the SIGTERM handler can use it if this worker is
    # killed mid-job during a rolling deploy.
    global _sigterm_repo_ref
    if _sigterm_repo_ref is None:
        _sigterm_repo_ref = receiver_repo

    retry_count = _parse_retry_count(request)
    is_final_attempt = retry_count >= _FINAL_ATTEMPT_INDEX

    scene_id = req.scene_id

    # 2. Claim scene.
    from receiver_repo import ClaimStatus
    claim_result = receiver_repo.claim(
        scene_id, SCENE_LEASE_TTL_SECONDS, holder_id=_WORKER_ID
    )

    if claim_result.status == ClaimStatus.NOT_FOUND:
        logger.warning("process: scene %s not found; draining task", scene_id)
        return JSONResponse({"status": "noop", "reason": "not_found"})

    if claim_result.status == ClaimStatus.WRONG_STATE:
        logger.warning("process: scene %s in wrong state; draining task", scene_id)
        return JSONResponse({"status": "noop", "reason": "wrong_state"})

    if claim_result.status == ClaimStatus.ALREADY_OWNED:
        _log_lease_action("noop_live_lease", scene_id=scene_id)
        return JSONResponse({"status": "noop", "reason": "already_owned"})

    # CLAIMED or RECLAIMED — we own it; proceed.
    fcm_token = claim_result.fcm_token
    action = "claim" if claim_result.status == ClaimStatus.CLAIMED else "reclaim_stale"
    _log_lease_action(action, scene_id=scene_id)
    with _held_scenes_lock:
        _held_scene_ids.add(scene_id)

    # Budget: everything from here runs against the time left in the request
    # window. On a cold start the lazy model load already consumed minutes of
    # it — the snapshot logged here shows exactly how much.
    from budget import BudgetTracker
    budget = BudgetTracker(deadline)
    logger.info("process budget scene_id=%s %s", scene_id, budget.snapshot())

    # 3. Run perception.
    try:
        result_uri = run_perception(
            scene_id=scene_id,
            bundle_uri=req.bundle_uri,
            outputs_bucket=outputs_bucket,
            sam3_model=sam3_model,
            sam3d_model=sam3d_model,
            object_prompt=object_prompt,
            budget=budget,
        )
    except PoisonError as exc:
        logger.error("process: poison failure for scene %s: %s", scene_id, exc)
        with _held_scenes_lock:
            _held_scene_ids.discard(scene_id)
        await _finalize_failed(
            scene_id, str(exc), fcm_token, receiver_repo, fcm_notifier,
            holder_id=_WORKER_ID,
        )
        return JSONResponse({"status": "failed", "reason": str(exc)})
    except EnvironmentalError as exc:
        logger.error("process: environmental failure for scene %s: %s", scene_id, exc)
        # Release the lease before returning 5xx so Cloud Tasks retries find an
        # immediately-reclaimable scene rather than waiting out the full TTL.
        # Status stays processing — Cloud Tasks retry will reclaim and proceed.
        try:
            receiver_repo.release_lease(scene_id, holder_id=_WORKER_ID)
            _log_lease_action("release_error", scene_id=scene_id)
        except Exception as rel_exc:
            logger.error("release_lease failed for scene %s: %s", scene_id, rel_exc)
        with _held_scenes_lock:
            _held_scene_ids.discard(scene_id)
        if is_final_attempt:
            logger.error("process: final attempt exhausted for scene %s; marking failed", scene_id)
            await _finalize_failed(
                scene_id, str(exc), fcm_token, receiver_repo, fcm_notifier,
                holder_id=_WORKER_ID,
            )
        return JSONResponse(
            status_code=500,
            content={"status": "error", "reason": str(exc)},
        )
    except Exception as exc:
        # Unexpected errors are treated as environmental.
        logger.exception("process: unexpected failure for scene %s: %s", scene_id, exc)
        try:
            receiver_repo.release_lease(scene_id, holder_id=_WORKER_ID)
            _log_lease_action("release_error", scene_id=scene_id)
        except Exception as rel_exc:
            logger.error("release_lease failed for scene %s: %s", scene_id, rel_exc)
        with _held_scenes_lock:
            _held_scene_ids.discard(scene_id)
        if is_final_attempt:
            await _finalize_failed(
                scene_id, str(exc), fcm_token, receiver_repo, fcm_notifier,
                holder_id=_WORKER_ID,
            )
        return JSONResponse(
            status_code=500,
            content={"status": "error", "reason": str(exc)},
        )

    # 4. Success path.
    with _held_scenes_lock:
        _held_scene_ids.discard(scene_id)
    try:
        receiver_repo.release_ready(scene_id, result_uri, holder_id=_WORKER_ID)
    except Exception as exc:
        raise EnvironmentalError(f"Failed to mark scene ready: {exc}") from exc

    logger.info("process: scene %s ready result_uri=%s", scene_id, result_uri)

    # Second stage: enqueue the room-shell bake (decision 0066).
    # Fire-and-forget AFTER release_ready — an enqueue failure logs and the
    # scene stays ready; the client's grace window absorbs a missing shell.
    try:
        from shell_enqueue import enqueue_shell_task  # deferred, like the GCS imports

        enqueue_shell_task(scene_id=scene_id, bundle_uri=req.bundle_uri)
    except Exception as exc:
        logger.warning(
            "shell enqueue failed (scene %s stays ready): %s", scene_id, exc
        )

    # Third stage: enqueue the compressed-splat tier (decisions 0125/0126).
    # Same fire-and-forget posture, and independent of the shell enqueue
    # above — one failing must not cost the other. A missing compressed
    # tier is invisible to the client: the room renders from PLY, which is
    # what every room did before the tier existed.
    try:
        from compress_enqueue import enqueue_compress_task  # deferred

        enqueue_compress_task(scene_id=scene_id)
    except Exception as exc:
        logger.warning(
            "compress enqueue failed (scene %s stays ready): %s", scene_id, exc
        )

    if fcm_token:
        try:
            fcm_notifier.notify_ready(fcm_token=fcm_token, scene_id=scene_id)
        except Exception as exc:
            logger.warning("FCM notify_ready failed (continuing): %s", exc)
    else:
        logger.debug("no fcm_token on scene %s; skipping notify_ready", scene_id)

    return JSONResponse({"status": "ready", "scene_id": scene_id, "result_uri": result_uri})


def _parse_retry_count(request: Request) -> int:
    """Extract X-CloudTasks-TaskRetryCount from the request headers.

    0-indexed: 0 = first delivery, 1 = first retry, 2 = second retry (final
    for maxAttempts=3 per 0003).
    """
    header = request.headers.get("X-CloudTasks-TaskRetryCount", "0")
    try:
        return int(header)
    except ValueError:
        return 0


# release_failed retry schedule for _finalize_failed. This call is the last
# opportunity to mark the scene failed on both terminal paths (PoisonError
# drain, EnvironmentalError final attempt); if it never lands, the scene is
# permanently stranded in `processing` with no further automatic retry. A
# short bounded retry absorbs transient Firestore errors; the residual risk
# is logged with a stable discriminator for alerting/manual reconciliation.
# See docs/decisions/0048.
_FINALIZE_FAILED_RETRY_DELAYS_S: tuple[float, ...] = (0.5, 1.0)


async def _finalize_failed(
    scene_id: str,
    error: str,
    fcm_token: str,
    repo,
    fcm_notifier,
    *,
    holder_id: str = "",
) -> None:
    """Mark scene as failed and fire FCM. Both are best-effort: log on failure.

    release_failed is retried on a short bounded schedule because there is no
    later automatic path that can rescue the scene if this write is lost.
    """
    attempts = 1 + len(_FINALIZE_FAILED_RETRY_DELAYS_S)
    for attempt in range(attempts):
        try:
            repo.release_failed(scene_id, error, holder_id=holder_id)
            break
        except ValueError:
            # Wrong state / not found — retrying cannot change this; the scene
            # is not in `processing`, so there is nothing to strand.
            logger.error(
                "release_failed rejected for scene %s (wrong state or missing)",
                scene_id,
            )
            break
        except Exception as exc:
            if attempt + 1 < attempts:
                await asyncio.sleep(_FINALIZE_FAILED_RETRY_DELAYS_S[attempt])
                continue
            logger.error(
                "scene_strand_risk=true scene_id=%s: release_failed failed on "
                "all %d attempts; scene may be stranded in 'processing' with "
                "no automatic retry (manual reconciliation required): %s",
                scene_id, attempts, exc,
            )
    if fcm_token:
        try:
            fcm_notifier.notify_failed(fcm_token=fcm_token, scene_id=scene_id, reason=error)
        except Exception as exc:
            logger.warning("FCM notify_failed failed (continuing): %s", exc)
    else:
        logger.debug("no fcm_token on scene %s; skipping notify_failed", scene_id)
