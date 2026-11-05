"""POST /process receiver for Cloud Tasks-dispatched perception jobs.

Implements the contract from docs/decisions/0004-perception-receiver-semantics.md:

  1. Verify OIDC token (Cloud Tasks attaches it when oidc_token is set on the
     task — see the OIDC verification in services/api-internal/dispatcher.py).
  2. Claim the scene atomically via ReceiverRepository (lease-TTL crash
     recovery). Exit 200 without processing on ALREADY_OWNED, WRONG_STATE,
     NOT_FOUND.
  3. Fetch the CaptureBundle proto from GCS.
  4. Write the person's boxes (boxes.json), then for each selected frame:
     download RGB, run SAM 3, write the masks to GCS. Nothing is reconstructed
     (decision 0323).
  5. Write a top-level manifest to GCS; update scene→ready; fire FCM.
  On PoisonError: update scene→failed, fire FCM, return 200 (drain queue).
  On EnvironmentalError: return 5xx (Cloud Tasks retries). On the final
  attempt (X-CloudTasks-TaskRetryCount >= maxAttempts-1 = 2): update
  scene→failed, fire FCM before returning 5xx.

Output structure (keyed by scene_id):
  gs://{PERCEPTION_OUTPUTS_BUCKET}/scenes/{scene_id}/manifest.json
  gs://{PERCEPTION_OUTPUTS_BUCKET}/scenes/{scene_id}/boxes.json
  gs://{PERCEPTION_OUTPUTS_BUCKET}/scenes/{scene_id}/frames/{idx:04d}/objects.json
  gs://{PERCEPTION_OUTPUTS_BUCKET}/scenes/{scene_id}/frames/{idx:04d}/masks.npz

The scene manifest URI is stored in Scene.result_uri on success.

Manifest contract (manifest_version 2):
  {scene_id, bundle_uri, schema_version, manifest_version: 2, frame_count,
   frames_total, frames_sampled, sampling: {...}, objects: [], frames: [...]}
  "sampling" records the frame-selection policy, the selected indices and
  whether the budget stopped the run (see sampling.py / census_sampling.py /
  budget.py). "objects" is always empty: scans made before decision 0323 carry
  reconstructed objects there, and every reader tolerates both. "frames"
  carries each segmented frame's masks (masks_gcs_uri, mask_count) for the
  shell. The room's objects are in boxes.json, written by this route alone.

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
from thegoodguest_schemas import CaptureBundle

logger = logging.getLogger(__name__)

# The segmentation vocabulary: what SAM 3 is asked to find, so the shell can
# leave furniture out of its wall and floor readings. It lives here rather than
# in server.py because SAM 3 returns the PROMPT TERM verbatim as a detection's
# label. It no longer has to agree with box_placement's label families (which
# associated masks with RoomPlan boxes); nothing is associated now.
DEFAULT_OBJECT_PROMPT = (
    "sofa,armchair,chair,dining chair,dining table,coffee table,side table,desk,"
    "cabinet,bookshelf,bed,nightstand,rug,curtain,floor lamp,table lamp,pendant light,"
    "ceiling fan,plant,artwork,painting,mirror,window,door,doorway,fireplace,"
    "tv,monitor,speaker,clock"
)

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


def _process_frame(
    *,
    scene_id: str,
    frame_idx: int,
    rgb_gcs_uri: str,
    outputs_bucket: str,
    sam3_model: Any,
    object_prompt: str,
) -> dict:
    """Segment one frame with SAM 3 and bank its masks. Returns the frame entry.

    Per frame: fetch the RGB image from GCS, segment it with SAM 3 and upload a
    packed masks.npz (the kept masks plus the suppressed-concept union, when
    any) and a per-frame objects.json under
    scenes/{scene_id}/frames/{frame_idx}/. Nothing is reconstructed: the
    objects in a room are the boxes the person made (decision 0322), and the
    masks here serve the shell (what to exclude from wall and floor
    observation) and the privacy filter (decision 0089). A frame already
    present in GCS is reused as a cache (partial-run recovery on retry).

    Raises PoisonError if the image can't be fetched or decoded. Raises
    EnvironmentalError on model or GCS failures.
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
    # exclusion union the shell reads.
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

    masks_uri = _gcs_upload_for_scene(
        f"gs://{outputs_bucket}/", f"{frame_prefix}/masks.npz",
        masks_npz_bytes(detections, suppressed), "application/octet-stream"
    )

    frame_result = {
        "frame_index": frame_idx,
        "rgb_gcs_uri": rgb_gcs_uri,
        "image_size": [pil.width, pil.height],
        "masks_gcs_uri": masks_uri,
        "mask_count": len(detections),
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
    object_prompt: str,
    max_frames: Optional[int] = None,
    budget=None,
) -> str:
    """Segment a bounded, box-aware subset of the bundle's frames and write
    the scene's manifest and boxes.json. Returns the gs:// URI of the manifest.

    The objects in a room are the boxes the person made on the phone
    (decision 0322): they are read from the bundle, written as boxes.json, and
    decide which frames are worth segmenting (census set-cover over the boxes;
    no boxes → the pose-diverse sampler). No object is reconstructed; the
    manifest's `objects` array stays, empty, for the readers that expect it.

    max_frames caps how many frames are segmented (None → sampling module
    default, env PERCEPTION_MAX_FRAMES). budget is an optional
    budget.BudgetTracker anchored at request entry; when the remaining budget
    can't fit another frame the loop stops early and the scene ships with
    what's banked. If NO frame completed, raises EnvironmentalError instead:
    the Cloud Tasks retry starts with warm models and the per-frame cache, so
    it gets strictly further than this attempt did.

    Raises PoisonError or EnvironmentalError as appropriate.
    """
    import boxes_json as boxes_json_mod  # deferred with the other heavy imports
    import sampling as sampling_mod
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

    # The person's boxes: written first, whole and idempotent (one blob PUT of
    # canonical bytes), even when empty, so a missing file always means "not
    # yet" and never "no boxes".
    boxes = boxes_json_mod.boxes_from_bundle(bundle)
    _gcs_upload_for_scene(
        f"gs://{outputs_bucket}/", f"scenes/{scene_id}/boxes.json",
        boxes_json_mod.boxes_json_bytes(scene_id, boxes), "application/json",
    )
    if len(boxes) < len(bundle.person_boxes):
        logger.warning(
            "boxes scene_id=%s kept=%d dropped=%d (unusable, repeated or past the limit)",
            scene_id, len(boxes), len(bundle.person_boxes) - len(boxes),
        )
    logger.info("boxes scene_id=%s count=%d", scene_id, len(boxes))

    frames_total = len(bundle.frames)
    effective_max = max_frames if max_frames is not None else sampling_mod.DEFAULT_MAX_FRAMES
    census_boxes = boxes_json_mod.census_boxes(boxes)
    census_info = None
    if census_boxes:
        # Census-driven selection (decision 0077): box-visibility set-cover +
        # pose-diverse residue. No boxes → the 0062 sampler VERBATIM (the
        # degrade lock).
        import census_sampling as census_sampling_mod

        # The vetoes (decision 0234) need pixels and depth, which only this
        # layer can fetch. Both accessors are lazy and are asked only about a
        # frame the cover pass is about to take, so a default run fetches
        # nothing extra and a veto run fetches a handful of blobs.
        _prefix = _bundle_prefix(bundle_uri)
        _by_idx = {f.frame_index: f for f in bundle.frames}

        def _veto_depth(frame_index: int):
            frame = _by_idx.get(frame_index)
            if frame is None:
                return None
            try:
                return _fetch_frame_depth(frame, _prefix)
            except Exception:
                return None

        def _veto_rgb(frame_index: int):
            frame = _by_idx.get(frame_index)
            if frame is None or not frame.rgb_gcs_path:
                return None
            try:
                import numpy as np  # deferred with the other heavy imports
                from PIL import Image

                raw = _download_gcs_uri(_prefix + frame.rgb_gcs_path)
                return np.asarray(Image.open(io.BytesIO(raw)).convert("L"))
            except Exception:
                return None

        _veto_on = census_sampling_mod.VISIBILITY_VETO
        selected, census_info = census_sampling_mod.select_frames_census(
            bundle.frames, census_boxes, effective_max,
            room=None,
            get_depth=_veto_depth if _veto_on else None,
            get_rgb=_veto_rgb if _veto_on else None,
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
    run_started = time.monotonic()
    frame_results: list[dict] = []
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
        frame_result = _process_frame(
            scene_id=scene_id,
            frame_idx=frame.frame_index,
            rgb_gcs_uri=prefix + frame.rgb_gcs_path,
            outputs_bucket=outputs_bucket,
            sam3_model=sam3_model,
            object_prompt=object_prompt,
        )
        frame_s = time.monotonic() - frame_started
        frame_results.append(frame_result)
        logger.info(
            "scene %s frame %d done (%d masks) frame_s=%.1f elapsed_s=%.1f %s",
            scene_id, frame.frame_index, frame_result.get("mask_count", 0),
            frame_s, time.monotonic() - run_started, budget.snapshot(),
        )
        budget.note_frame(frame_s)
        _free_gpu_memory()
        _log_vram(scene_id, f"after_frame_{frame.frame_index}")

    if not frame_results:
        # Nothing banked. 5xx so Cloud Tasks retries against warm models and
        # this attempt's per-frame cache.
        raise EnvironmentalError(
            f"budget exhausted before any frame completed "
            f"(frames_planned={len(selected)}); {budget.snapshot()}"
        )

    manifest = {
        "scene_id": scene_id,
        "bundle_uri": bundle_uri,
        "schema_version": bundle.schema_version,
        "manifest_version": 2,
        "frame_count": frames_total,
        "frames_total": frames_total,
        "frames_sampled": len(selected),
        "sampling": {
            "policy": (
                "census_set_cover_v1" if census_boxes else "pose_diverse_fps_v1"
            ),
            "max_frames": effective_max,
            "selected_frame_indices": selected_indices,
            "frames_processed": len(frame_results),
            "budget_stopped": budget_stopped,
            **({"census": census_info} if census_info is not None else {}),
        },
        # No object is reconstructed (decision 0323): the room's objects are the
        # boxes in boxes.json. The key stays so readers that ask for it get [].
        "objects": [],
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
