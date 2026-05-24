"""POST /process receiver for Cloud Tasks-dispatched perception jobs.

Implements the contract from docs/decisions/0004-perception-receiver-semantics.md:

  1. Verify OIDC token (Cloud Tasks attaches it when oidc_token is set on the
     task — see the ingester OIDC patch in services/api/dispatcher.py).
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

Output structure (mirrors /objects keyed by scene_id instead of photo_sha256):
  gs://{PERCEPTION_OUTPUTS_BUCKET}/scenes/{scene_id}/manifest.json
  gs://{PERCEPTION_OUTPUTS_BUCKET}/scenes/{scene_id}/frames/{idx:04d}/objects.json
  gs://{PERCEPTION_OUTPUTS_BUCKET}/scenes/{scene_id}/frames/{idx:04d}/masks.npz
  gs://{PERCEPTION_OUTPUTS_BUCKET}/scenes/{scene_id}/frames/{idx:04d}/splats/{i:02d}_{label}.ply

The scene manifest URI is stored in Scene.result_uri on success.

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

import gc
import io
import json
import logging
import os
import signal
import threading
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
    """Return the gs:// prefix for paths relative to bundle_uri.

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


# ---------------------------------------------------------------------------
# Per-frame perception
# ---------------------------------------------------------------------------

def _safe_label(label: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in label)[:32]


def _process_frame(
    *,
    scene_id: str,
    frame_idx: int,
    rgb_gcs_uri: str,
    outputs_bucket: str,
    sam3_model: Any,
    sam3d_model: Any,
    object_prompt: str,
) -> dict:
    """Run SAM 3 + SAM 3D on one frame. Returns a dict with per-object results.

    Mirrors the per-object loop in /objects but keyed by scene_id/frame.
    Raises PoisonError if the image can't be fetched/opened.
    Raises EnvironmentalError on model or GCS failures.
    """
    import torch
    from PIL import Image

    frame_prefix = f"scenes/{scene_id}/frames/{frame_idx:04d}"
    objects_blob = f"{frame_prefix}/objects.json"

    # Whole-frame cache hit: a previous run already processed this frame.
    if _gcs_blob_exists(outputs_bucket, objects_blob):
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

    # SAM 3 segmentation.
    try:
        detections = sam3_model.segment(pil, object_prompt)
    except Exception as exc:
        raise EnvironmentalError(f"SAM 3 failed on frame {frame_idx}: {exc}") from exc

    # SAM 3D per object.
    objects_out: list[dict] = []
    for i, obj in enumerate(detections):
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

        # Per-object cache: reuse if already uploaded.
        if _gcs_blob_exists(outputs_bucket, splat_blob):
            objects_out.append({
                **meta,
                "ok": True,
                "cached": True,
                "splat_gcs_uri": f"gs://{outputs_bucket}/{splat_blob}",
            })
            continue

        try:
            try:
                result = sam3d_model.reconstruct(pil, obj["mask"], seed=42 + i)
            except Exception as oom:
                gc.collect()
                try:
                    import torch as _torch
                    if _torch.cuda.is_available():
                        _torch.cuda.empty_cache()
                except ImportError:
                    pass
                result = sam3d_model.reconstruct(pil, obj["mask"], seed=42 + i)

            # Convert to PLY bytes.
            gs = result.get("gs")
            if gs is None:
                raise RuntimeError("No 'gs' output in SAM 3D result")
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".ply", delete=True) as tmp:
                gs.save_ply(tmp.name)
                tmp.flush()
                with open(tmp.name, "rb") as f:
                    ply_bytes = f.read()

            splat_uri = _gcs_upload_for_scene(
                f"gs://{outputs_bucket}/", splat_blob, ply_bytes,
                "application/octet-stream"
            )
            objects_out.append({
                **meta,
                "ok": True,
                "cached": False,
                "splat_gcs_uri": splat_uri,
                "splat_size_bytes": len(ply_bytes),
            })
        except (PoisonError, EnvironmentalError):
            raise
        except Exception as exc:
            raise EnvironmentalError(
                f"SAM 3D failed on frame {frame_idx} object {i}: {exc}"
            ) from exc
        finally:
            del result
            del ply_bytes
            gc.collect()
            try:
                import torch as _torch
                if _torch.cuda.is_available():
                    _torch.cuda.empty_cache()
            except ImportError:
                pass

    # Upload masks.npz.
    import numpy as np  # deferred: heavy dep, only needed during actual processing
    masks_buf = io.BytesIO()
    if detections:
        np.savez_compressed(masks_buf, masks=np.stack([d["mask"] for d in detections]))
    else:
        np.savez_compressed(masks_buf, masks=np.zeros((0,), dtype=bool))
    masks_uri = _gcs_upload_for_scene(
        f"gs://{outputs_bucket}/", f"{frame_prefix}/masks.npz",
        masks_buf.getvalue(), "application/octet-stream"
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
) -> str:
    """Process all frames in the bundle. Returns the gs:// URI of the manifest.

    Raises PoisonError or EnvironmentalError as appropriate.
    """
    # Fetch + parse the bundle proto.
    raw = _download_gcs_uri(bundle_uri)
    bundle = CaptureBundle()
    try:
        bundle.ParseFromString(raw)
    except Exception as exc:
        raise PoisonError(f"Bundle proto cannot be parsed: {exc}") from exc

    if not bundle.frames:
        raise PoisonError("Bundle has no frames")

    prefix = _bundle_prefix(bundle_uri)
    frame_results: list[dict] = []

    for frame in bundle.frames:
        rgb_uri = prefix + frame.rgb_gcs_path
        frame_result = _process_frame(
            scene_id=scene_id,
            frame_idx=frame.frame_index,
            rgb_gcs_uri=rgb_uri,
            outputs_bucket=outputs_bucket,
            sam3_model=sam3_model,
            sam3d_model=sam3d_model,
            object_prompt=object_prompt,
        )
        frame_results.append(frame_result)
        logger.info(
            "scene %s frame %d done (%d objects)",
            scene_id, frame.frame_index,
            sum(1 for o in frame_result.get("objects", []) if o.get("ok")),
        )

    manifest = {
        "scene_id": scene_id,
        "bundle_uri": bundle_uri,
        "schema_version": bundle.schema_version,
        "frame_count": len(bundle.frames),
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
) -> JSONResponse:
    """Core handler for POST /process. Injected into the FastAPI route in server.py.

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
    device_id = claim_result.device_id
    action = "claim" if claim_result.status == ClaimStatus.CLAIMED else "reclaim_stale"
    _log_lease_action(action, scene_id=scene_id)
    with _held_scenes_lock:
        _held_scene_ids.add(scene_id)

    # 3. Run perception.
    try:
        result_uri = run_perception(
            scene_id=scene_id,
            bundle_uri=req.bundle_uri,
            outputs_bucket=outputs_bucket,
            sam3_model=sam3_model,
            sam3d_model=sam3d_model,
            object_prompt=object_prompt,
        )
    except PoisonError as exc:
        logger.error("process: poison failure for scene %s: %s", scene_id, exc)
        with _held_scenes_lock:
            _held_scene_ids.discard(scene_id)
        _finalize_failed(scene_id, str(exc), device_id, receiver_repo, fcm_notifier)
        return JSONResponse({"status": "failed", "reason": str(exc)})
    except EnvironmentalError as exc:
        logger.error("process: environmental failure for scene %s: %s", scene_id, exc)
        # Release the lease before returning 5xx so Cloud Tasks retries find an
        # immediately-reclaimable scene rather than waiting out the full TTL.
        # Status stays processing — Cloud Tasks retry will reclaim and proceed.
        try:
            receiver_repo.release_lease(scene_id)
            _log_lease_action("release_error", scene_id=scene_id)
        except Exception as rel_exc:
            logger.error("release_lease failed for scene %s: %s", scene_id, rel_exc)
        with _held_scenes_lock:
            _held_scene_ids.discard(scene_id)
        if is_final_attempt:
            logger.error("process: final attempt exhausted for scene %s; marking failed", scene_id)
            _finalize_failed(scene_id, str(exc), device_id, receiver_repo, fcm_notifier)
        return JSONResponse(
            status_code=500,
            content={"status": "error", "reason": str(exc)},
        )
    except Exception as exc:
        # Unexpected errors are treated as environmental.
        logger.exception("process: unexpected failure for scene %s: %s", scene_id, exc)
        try:
            receiver_repo.release_lease(scene_id)
            _log_lease_action("release_error", scene_id=scene_id)
        except Exception as rel_exc:
            logger.error("release_lease failed for scene %s: %s", scene_id, rel_exc)
        with _held_scenes_lock:
            _held_scene_ids.discard(scene_id)
        if is_final_attempt:
            _finalize_failed(scene_id, str(exc), device_id, receiver_repo, fcm_notifier)
        return JSONResponse(
            status_code=500,
            content={"status": "error", "reason": str(exc)},
        )

    # 4. Success path.
    with _held_scenes_lock:
        _held_scene_ids.discard(scene_id)
    try:
        receiver_repo.release_ready(scene_id, result_uri)
    except Exception as exc:
        raise EnvironmentalError(f"Failed to mark scene ready: {exc}") from exc

    logger.info("process: scene %s ready result_uri=%s", scene_id, result_uri)

    try:
        fcm_notifier.notify_ready(device_id=device_id, scene_id=scene_id)
    except Exception as exc:
        logger.warning("FCM notify_ready failed (continuing): %s", exc)

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


def _finalize_failed(
    scene_id: str,
    error: str,
    device_id: str,
    repo,
    fcm_notifier,
) -> None:
    """Mark scene as failed and fire FCM. Both are best-effort: log on failure."""
    try:
        repo.release_failed(scene_id, error)
    except Exception as exc:
        logger.error(
            "Failed to mark scene %s as failed (state may be inconsistent): %s",
            scene_id, exc,
        )
    try:
        fcm_notifier.notify_failed(device_id=device_id, scene_id=scene_id, reason=error)
    except Exception as exc:
        logger.warning("FCM notify_failed failed (continuing): %s", exc)
