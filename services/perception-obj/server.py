"""
perception-obj server.

Runs SAM 3 (open-vocabulary segmentation) and SAM 3D Objects (per-object Gaussian
splat reconstruction). Endpoints:

  POST /segment   — SAM 3 only. Returns object metadata + packed masks as .npz.
  POST /objects   — Full SAM 3 + SAM 3D. Returns a zip archive: manifest.json +
                    per-object splat PLYs + packed masks.
  POST /process   — Cloud Tasks receiver. Accepts {scene_id, bundle_uri}, runs
                    the full pipeline, updates Firestore Scene state, fires FCM.
                    See process_receiver.py and docs/decisions/0004.

This service does NOT know about VGGT. Splat placement into the scene's
coordinate frame is the client's job (see tools/call_perception.py), using
VGGT's pointmap from perception-geom.
"""
from __future__ import annotations

import io
import json
import os
import gc
import hashlib
import tempfile
import threading
import time
import zipfile
from contextlib import asynccontextmanager
from typing import Any

import numpy as np
import torch
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, Response, StreamingResponse
from PIL import Image

try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:
    pass

from models.sam3 import SAM3Model
from models.sam3d import SAM3DModel


# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

DEFAULT_OBJECT_PROMPT = (
    "sofa,armchair,chair,dining chair,dining table,coffee table,side table,desk,"
    "cabinet,bookshelf,bed,nightstand,rug,curtain,floor lamp,table lamp,pendant light,"
    "ceiling fan,plant,artwork,painting,mirror,window,door,doorway,fireplace,"
    "tv,monitor,speaker,clock"
)

# GCS-backed output cache. Server writes splats to GCS and returns gs:// URIs
# in the JSON response, sidestepping Cloud Run's 32 MiB response cap and
# connection fragility on large streaming payloads. Setting this env var to ""
# (empty) disables GCS entirely; in that case /objects falls back to the
# in-memory zip path (kept around for local testing).
PERCEPTION_OUTPUTS_BUCKET = os.environ.get(
    "PERCEPTION_OUTPUTS_BUCKET", "roomstudio-perception-outputs"
)

# Lazily import + construct the GCS client so the server can boot without GCS
# (e.g. unit tests, local dev without network).
_gcs_bucket = None
_gcs_lock = threading.Lock()


def _bucket():
    """Return a cached GCS bucket handle, or None if GCS is disabled."""
    global _gcs_bucket
    if not PERCEPTION_OUTPUTS_BUCKET:
        return None
    if _gcs_bucket is not None:
        return _gcs_bucket
    with _gcs_lock:
        if _gcs_bucket is not None:
            return _gcs_bucket
        from google.cloud import storage  # noqa: PLC0415
        _gcs_bucket = storage.Client().bucket(PERCEPTION_OUTPUTS_BUCKET)
    return _gcs_bucket


def _gcs_upload(blob_path: str, data: bytes, content_type: str) -> str:
    """Upload bytes to gs://bucket/blob_path. Returns the gs:// URI."""
    bucket = _bucket()
    if bucket is None:
        raise RuntimeError("PERCEPTION_OUTPUTS_BUCKET is unset; GCS uploads disabled")
    blob = bucket.blob(blob_path)
    blob.upload_from_string(data, content_type=content_type)
    return f"gs://{PERCEPTION_OUTPUTS_BUCKET}/{blob_path}"


def _gcs_get_bytes(blob_path: str) -> bytes | None:
    """Download bytes from gs://bucket/blob_path. Returns None if not found."""
    bucket = _bucket()
    if bucket is None:
        return None
    blob = bucket.blob(blob_path)
    if not blob.exists():
        return None
    return blob.download_as_bytes()


def _gcs_blob_size(blob_path: str) -> int | None:
    """Return blob size in bytes, or None if not found."""
    bucket = _bucket()
    if bucket is None:
        return None
    blob = bucket.blob(blob_path)
    # blob.reload() raises NotFound (404) on missing blobs rather than
    # returning a blob with size=None, so we catch instead of pre-checking
    # with .exists() (which would double the API calls).
    from google.cloud.exceptions import NotFound  # noqa: PLC0415
    try:
        blob.reload()
    except NotFound:
        return None
    return blob.size

# -----------------------------------------------------------------------------
# Model initialization (background thread, see lifespan below)
# -----------------------------------------------------------------------------
sam3: SAM3Model | None = None
sam3d: SAM3DModel | None = None
_models_ready = False
_startup_error: str | None = None
_startup_started_at: float | None = None
_startup_finished_at: float | None = None


def _load_models() -> None:
    """Load SAM 3 + SAM 3D in a background thread. Sets module-level globals
    and flips `_models_ready` on success, or captures the error in
    `_startup_error` on failure."""
    global sam3, sam3d, _models_ready, _startup_error, _startup_finished_at
    try:
        print(f"[startup] Initializing on {DEVICE}", flush=True)
        t_total = time.time()

        print("[startup] Loading SAM 3...", flush=True)
        t = time.time()
        sam3 = SAM3Model()
        print(f"[startup] SAM 3 loaded in {time.time() - t:.1f}s", flush=True)

        print("[startup] Loading SAM 3D Objects...", flush=True)
        t = time.time()
        sam3d = SAM3DModel()
        print(f"[startup] SAM 3D loaded in {time.time() - t:.1f}s", flush=True)

        print(f"[startup] All models ready in {time.time() - t_total:.1f}s", flush=True)
        _models_ready = True
    except Exception as e:
        _startup_error = f"{type(e).__name__}: {e}"
        print(f"[startup] FAILED: {_startup_error}", flush=True)
    finally:
        _startup_finished_at = time.time()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Fire model loading in a background thread so uvicorn can bind to
    the port immediately. Cloud Run's startup probe passes as soon as we're
    listening; meanwhile, the client polls /ready to know when to send
    real work."""
    global _startup_started_at
    _startup_started_at = time.time()
    thread = threading.Thread(target=_load_models, name="model-loader", daemon=True)
    thread.start()
    yield
    # No shutdown work needed; daemon thread dies with the process.


# -----------------------------------------------------------------------------
# FastAPI app
# -----------------------------------------------------------------------------
app = FastAPI(title="roomstudio-perception-obj", lifespan=lifespan)

# Lazy-initialized singletons for the /process endpoint. In tests, replace via
# patch.object(server, "_receiver_repo", ...) etc.
_receiver_repo = None
_fcm_notifier = None
_oidc_verifier = None


def _get_receiver_repo():
    global _receiver_repo
    if _receiver_repo is None:
        from process_receiver import RECEIVER_URL, CLOUD_TASKS_INVOKER_SA
        from receiver_repo import FirestoreReceiverRepository, InMemoryReceiverRepository
        project = os.environ.get("FIRESTORE_PROJECT")
        if project:
            _receiver_repo = FirestoreReceiverRepository(project=project)
        else:
            _receiver_repo = InMemoryReceiverRepository()
    return _receiver_repo


def _get_fcm_notifier():
    global _fcm_notifier
    if _fcm_notifier is None:
        from fcm import FirebaseFcmNotifier, NullFcmNotifier
        if os.environ.get("FIRESTORE_PROJECT"):
            _fcm_notifier = FirebaseFcmNotifier()
        else:
            _fcm_notifier = NullFcmNotifier()
    return _fcm_notifier


def _get_oidc_verifier():
    global _oidc_verifier
    if _oidc_verifier is None:
        from process_receiver import RECEIVER_URL, CLOUD_TASKS_INVOKER_SA
        from oidc import OIDCVerifier
        if CLOUD_TASKS_INVOKER_SA:
            _oidc_verifier = OIDCVerifier(
                audience=RECEIVER_URL + "/process",
                allowed_email=CLOUD_TASKS_INVOKER_SA,
            )
        # If CLOUD_TASKS_INVOKER_SA is unset (local dev), verifier stays None
        # and the endpoint skips auth (see handle_process oidc_verifier=None path).
    return _oidc_verifier


@app.get("/")
def health() -> dict[str, Any]:
    return {"status": "ok", "device": DEVICE, "models": ["sam3", "sam-3d-objects"]}


@app.get("/ready")
def ready() -> JSONResponse:
    """Readiness check. Returns 200 when models are loaded, 503 while loading,
    500 if the loader thread crashed. Clients should poll this before posting
    to /segment or /objects."""
    elapsed = (
        (_startup_finished_at or time.time()) - _startup_started_at
        if _startup_started_at is not None
        else 0.0
    )
    if _startup_error is not None:
        return JSONResponse(
            {"ready": False, "error": _startup_error, "elapsed_seconds": elapsed},
            status_code=500,
        )
    if _models_ready:
        return JSONResponse({"ready": True, "elapsed_seconds": elapsed})
    return JSONResponse(
        {"ready": False, "elapsed_seconds": elapsed},
        status_code=503,
    )


def _require_ready() -> None:
    """Endpoint guard. Raises 503 if models aren't loaded yet."""
    if _startup_error is not None:
        raise HTTPException(status_code=500, detail=f"startup failed: {_startup_error}")
    if not _models_ready:
        raise HTTPException(status_code=503, detail="models still loading; poll /ready")


@app.post("/segment")
async def segment(
    image: UploadFile = File(...),
    prompt: str = Form(DEFAULT_OBJECT_PROMPT),
) -> JSONResponse:
    """SAM 3 only. Returns object metadata. Masks are NOT included in this
    endpoint (too large for JSON). Use /segment-raw to get masks back."""
    _require_ready()
    t0 = time.time()
    img_bytes = await image.read()
    pil = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    objects = sam3.segment(pil, prompt)
    print(f"[segment] {len(objects)} objects in {time.time() - t0:.1f}s", flush=True)

    slim = [{k: v for k, v in o.items() if k != "mask"} for o in objects]
    return JSONResponse({"objects": slim, "image_size": [pil.width, pil.height]})


@app.post("/segment-raw")
async def segment_raw(
    image: UploadFile = File(...),
    prompt: str = Form(DEFAULT_OBJECT_PROMPT),
) -> Response:
    """SAM 3 only. Returns a zip containing manifest.json + masks.npz."""
    _require_ready()
    t0 = time.time()
    img_bytes = await image.read()
    pil = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    objects = sam3.segment(pil, prompt)
    print(f"[segment-raw] {len(objects)} objects in {time.time() - t0:.1f}s", flush=True)

    # Stream the response: with 40+ masks at full-image resolution this can
    # exceed Cloud Run's 32 MiB non-chunked response cap. See /objects below.
    payload = _pack_segments(objects, pil.size)

    def _iter_payload(buf: bytes, chunk: int = 1 << 20):
        for i in range(0, len(buf), chunk):
            yield buf[i : i + chunk]

    return StreamingResponse(_iter_payload(payload), media_type="application/zip")


@app.post("/objects")
async def objects(
    image: UploadFile = File(...),
    prompt: str = Form(DEFAULT_OBJECT_PROMPT),
    max_objects: int = Form(20),
) -> JSONResponse:
    """Full SAM 3 + SAM 3D pipeline. Writes each splat to GCS keyed by the
    SHA-256 of the uploaded image bytes, and returns a JSON manifest with
    gs:// URIs per object.

    Cache semantics:
      - If `{photo_sha256}/objects.json` already exists, return it. Skips
        SAM 3 + SAM 3D entirely.
      - Per-object: if the splat blob already exists, skip SAM 3D for that
        object and reuse the cached PLY. This handles partial-success from
        previous OOM-aborted runs.

    `max_objects` caps how many of SAM 3's top-scoring detections we feed to
    SAM 3D. SAM 3D is the expensive step (per-object inference); capping
    protects runtime.
    """
    _require_ready()
    t0 = time.time()
    img_bytes = await image.read()
    photo_sha256 = hashlib.sha256(img_bytes).hexdigest()
    manifest_path = f"{photo_sha256}/objects.json"

    # Whole-run cache hit: return the previous manifest verbatim.
    cached = _gcs_get_bytes(manifest_path)
    if cached is not None:
        manifest = json.loads(cached)
        manifest["cached"] = True
        manifest["total_seconds"] = time.time() - t0
        print(
            f"[objects] cache HIT {photo_sha256[:12]}, "
            f"{sum(1 for o in manifest['objects'] if o['ok'])}/"
            f"{len(manifest['objects'])} objects",
            flush=True,
        )
        return JSONResponse(manifest)

    pil = Image.open(io.BytesIO(img_bytes)).convert("RGB")

    detections = sam3.segment(pil, prompt)
    print(
        f"[objects] SAM 3 found {len(detections)} objects in {time.time() - t0:.1f}s",
        flush=True,
    )
    detections = detections[:max_objects]

    # Run SAM 3D per object. Upload each successful splat to GCS immediately
    # so a partial run is recoverable on retry.
    # CRITICAL: SAM 3D allocates large intermediates per call and PyTorch holds
    # them in its caching allocator until explicitly released. Without
    # gc.collect() + torch.cuda.empty_cache() between calls, the L4's 22 GiB
    # fragments and fills, causing OOM partway through a 20-object batch.
    objects_out: list[dict[str, Any]] = []
    for i, obj in enumerate(detections):
        result = None
        ply_bytes = None
        safe = _safe_label(obj["label"])
        splat_blob = f"{photo_sha256}/splats/{i:02d}_{safe}.ply"

        meta = {
            "label": obj["label"],
            "instance_idx": obj["instance_idx"],
            "bbox": obj["bbox"],
            "score": obj["score"],
            "mask_index": i,
        }

        # Per-object cache hit: previous run already wrote this splat.
        existing_size = _gcs_blob_size(splat_blob)
        if existing_size is not None:
            print(
                f"[objects]   {i:02d} {obj['label']:18s} cached "
                f"({existing_size//1024} KB)",
                flush=True,
            )
            objects_out.append({
                **meta,
                "ok": True,
                "cached": True,
                "splat_gcs_uri": f"gs://{PERCEPTION_OUTPUTS_BUCKET}/{splat_blob}",
                "splat_size_bytes": existing_size,
            })
            continue

        try:
            t_obj = time.time()
            try:
                result = sam3d.reconstruct(pil, obj["mask"], seed=42 + i)
            except torch.cuda.OutOfMemoryError as oom:
                result = None
                gc.collect()
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                print(f"[objects]   {i:02d} {obj['label']} OOM, retrying: {oom}", flush=True)
                result = sam3d.reconstruct(pil, obj["mask"], seed=42 + i)
            ply_bytes = _splat_to_ply_bytes(result)

            # Upload immediately so this object survives a later OOM in the loop.
            uri = _gcs_upload(splat_blob, ply_bytes, "application/octet-stream")
            objects_out.append({
                **meta,
                "ok": True,
                "cached": False,
                "splat_gcs_uri": uri,
                "splat_size_bytes": len(ply_bytes),
            })
            print(
                f"[objects]   {i:02d} {obj['label']:18s} {time.time() - t_obj:.1f}s "
                f"({len(ply_bytes)//1024} KB) -> gs",
                flush=True,
            )
        except Exception as e:
            objects_out.append({**meta, "ok": False, "error": str(e)})
            print(f"[objects]   {i:02d} {obj['label']} FAILED: {e}", flush=True)
        finally:
            del result
            del ply_bytes
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

    # Pack and upload masks.npz so the scene pipeline can rehydrate them
    # without a separate /segment-raw call. Only the masks that correspond
    # to detections we processed (post max_objects cap) are included; this
    # matches what the old zip-based flow stored.
    masks_buf = io.BytesIO()
    if detections:
        np.savez_compressed(
            masks_buf, masks=np.stack([d["mask"] for d in detections])
        )
    else:
        np.savez_compressed(masks_buf, masks=np.zeros((0,), dtype=bool))
    masks_blob = f"{photo_sha256}/masks.npz"
    masks_uri = _gcs_upload(masks_blob, masks_buf.getvalue(), "application/octet-stream")

    manifest = {
        "photo_sha256": photo_sha256,
        "image_size": [pil.width, pil.height],
        "total_seconds": time.time() - t0,
        "masks_gcs_uri": masks_uri,
        "objects": objects_out,
        "cached": False,
    }
    # Cache the manifest itself so future identical requests skip everything.
    # Only cache if at least one object succeeded; an all-failure manifest is
    # not worth poisoning the cache with.
    n_ok = sum(1 for o in objects_out if o["ok"])
    if n_ok > 0:
        _gcs_upload(manifest_path, json.dumps(manifest).encode("utf-8"), "application/json")

    print(
        f"[objects] done in {time.time() - t0:.1f}s, "
        f"{n_ok}/{len(objects_out)} reconstructed, manifest cached={n_ok > 0}",
        flush=True,
    )
    return JSONResponse(manifest)


# -----------------------------------------------------------------------------
# Cloud Tasks receiver
# -----------------------------------------------------------------------------

@app.post(
    "/process",
    summary="Cloud Tasks perception receiver",
    responses={
        200: {"description": "Processing complete (ready or poison-drained)"},
        401: {"description": "OIDC token missing or invalid"},
        422: {"description": "Malformed payload (natural poison drain)"},
        500: {"description": "Environmental failure; Cloud Tasks will retry"},
        503: {"description": "Models not yet loaded; Cloud Tasks will retry"},
    },
)
async def process(
    request: Request,
    req: "ProcessRequest",
) -> JSONResponse:
    """Cloud Tasks perception receiver.

    Accepts {scene_id, bundle_uri}, claims the scene atomically (with
    lease-TTL crash recovery), runs SAM 3 + SAM 3D Objects on all frames,
    writes outputs to GCS, and updates Scene state in Firestore.

    Cloud Run config: concurrency=1, request-timeout=600s.
    Returns 5xx on environmental failures so Cloud Tasks retries. Returns 2xx
    on all success and poison paths so the task is drained from the queue.
    """
    from process_receiver import ProcessRequest, handle_process

    _require_ready()

    return await handle_process(
        request,
        req,
        oidc_verifier=_get_oidc_verifier(),
        receiver_repo=_get_receiver_repo(),
        fcm_notifier=_get_fcm_notifier(),
        outputs_bucket=PERCEPTION_OUTPUTS_BUCKET,
        sam3_model=sam3,
        sam3d_model=sam3d,
        object_prompt=DEFAULT_OBJECT_PROMPT,
    )


# Import here so FastAPI can resolve the ProcessRequest type annotation above
# without a circular import (server imports process_receiver, not vice versa).
from process_receiver import ProcessRequest  # noqa: E402


# -----------------------------------------------------------------------------
# Packers
# -----------------------------------------------------------------------------

def _pack_segments(objects: list[dict[str, Any]], image_size: tuple[int, int]) -> bytes:
    """Pack SAM 3 results as a zip: manifest + masks.npz."""
    masks = [o["mask"] for o in objects]
    manifest = {
        "image_size": list(image_size),
        "objects": [
            {
                "label": o["label"],
                "instance_idx": o["instance_idx"],
                "bbox": o["bbox"],
                "score": o["score"],
                "mask_index": i,
            }
            for i, o in enumerate(objects)
        ],
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))
        masks_buf = io.BytesIO()
        if masks:
            np.savez_compressed(masks_buf, masks=np.stack(masks))
        else:
            np.savez_compressed(masks_buf, masks=np.zeros((0,), dtype=bool))
        zf.writestr("masks.npz", masks_buf.getvalue())
    return buf.getvalue()


def _pack_objects(
    results: list[dict[str, Any]],
    image_size: tuple[int, int],
    total_seconds: float,
) -> bytes:
    """Pack /objects results: manifest + masks.npz + per-object PLYs."""
    masks = [r["mask"] for r in results]
    manifest_objects = []
    for i, r in enumerate(results):
        entry = {
            "label": r["label"],
            "instance_idx": r["instance_idx"],
            "bbox": r["bbox"],
            "score": r["score"],
            "mask_index": i,
            "ok": r["ok"],
        }
        if r["ok"]:
            entry["splat_filename"] = f"obj_{i:02d}_{_safe_label(r['label'])}.ply"
        else:
            entry["error"] = r.get("error", "unknown")
        manifest_objects.append(entry)

    manifest = {
        "image_size": list(image_size),
        "total_seconds": total_seconds,
        "objects": manifest_objects,
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))

        masks_buf = io.BytesIO()
        if masks:
            np.savez_compressed(masks_buf, masks=np.stack(masks))
        else:
            np.savez_compressed(masks_buf, masks=np.zeros((0,), dtype=bool))
        zf.writestr("masks.npz", masks_buf.getvalue())

        for i, r in enumerate(results):
            if r["ok"] and r["ply_bytes"]:
                zf.writestr(
                    f"obj_{i:02d}_{_safe_label(r['label'])}.ply",
                    r["ply_bytes"],
                )
    return buf.getvalue()


def _splat_to_ply_bytes(result: dict[str, Any]) -> bytes:
    """Convert SAM 3D's Inference result to PLY bytes."""
    gs = result.get("gs")
    if gs is None:
        raise RuntimeError("No 'gs' output in SAM 3D result")
    with tempfile.NamedTemporaryFile(suffix=".ply", delete=True) as tmp:
        gs.save_ply(tmp.name)
        tmp.flush()
        with open(tmp.name, "rb") as f:
            return f.read()


def _safe_label(label: str) -> str:
    """Make a label safe for use in a filename."""
    return "".join(c if c.isalnum() else "_" for c in label)[:32]
