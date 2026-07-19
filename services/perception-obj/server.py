"""
perception-obj server.

Runs SAM 3 (open-vocabulary segmentation) and SAM 3D Objects (per-object Gaussian
splat reconstruction). Endpoints:

  GET  /health    — Startup probe target. Always 200 as soon as uvicorn is up.
                    No model interaction. Fast timeout is intentional.
  GET  /ready     — Readiness check. Reports model load state: not_loaded /
                    loading / loaded / failed. Intended for Cloud Tasks to poll
                    before sending work (or for debugging cold-start timing).
  POST /process   — Cloud Tasks receiver. Accepts {scene_id, bundle_uri}, runs
                    the full pipeline, updates Firestore Scene state, fires FCM.
                    See process_receiver.py and docs/decisions/0004.

Models are loaded lazily: the first /process call triggers construction.
Startup cost (~195s) is paid by that first request, not at container boot.
See docs/decisions/0007.
"""
from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from typing import Any

import torch
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

# Configure root logger so application logger.info() calls reach Cloud Logging.
# By default uvicorn leaves the root logger with no handlers, falling back to
# Python's lastResort handler which only outputs WARNING+. basicConfig adds a
# StreamHandler at INFO level to the root logger; uvicorn's subsequent
# dictConfig (disable_existing_loggers=False, no "root" key) preserves it.
# This is a no-op if handlers are already configured (e.g. in test environments
# that call basicConfig themselves).
logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
logger = logging.getLogger(__name__)

# ProcessRequest must be imported before any @app.post("/process") registration.
# FastAPI resolves type annotations at decoration time; if ProcessRequest is not
# in the module namespace then, FastAPI silently treats `req` as a query param
# instead of a body model, producing 422 on every Cloud Tasks delivery.
# See docs/decisions/0010.
from process_receiver import ProcessRequest  # noqa: E402

# Model classes are NOT imported at module level. Importing models.sam3 or
# models.sam3d would immediately run the SAM 3 / SAM 3D CUDA initialisation
# (hundreds of seconds), blocking uvicorn from binding before the startup
# probe fires. Imports are deferred to the accessor functions below so that
# the process survives the startup probe and pays the load cost on first use.


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

# GCS bucket for perception outputs. /process (process_receiver.py) writes
# per-scene splats and manifests under scenes/{scene_id}/ in this bucket.
PERCEPTION_OUTPUTS_BUCKET = os.environ.get(
    "PERCEPTION_OUTPUTS_BUCKET", "roomstudio-perception-outputs"
)

# -----------------------------------------------------------------------------
# Lazy model registry
# -----------------------------------------------------------------------------
# Models are None until first use. Accessors (get_sam3 / get_sam3d) load on
# demand with double-checked locking. Cloud Run runs concurrency=1, so the
# pre-lock error/instance checks cannot race with a concurrent in-flight load;
# the locking is defensive for the day concurrency is raised.
# See docs/decisions/0007.

_sam3 = None  # SAM3Model instance or None
_sam3d = None  # SAM3DModel instance or None
_sam3_error: str | None = None
_sam3d_error: str | None = None
_sam3_loading: bool = False
_sam3d_loading: bool = False
_sam3_lock = threading.Lock()
_sam3d_lock = threading.Lock()


def get_sam3():
    """Return the SAM3Model singleton, loading it on first call.

    Raises HTTPException(500) on load failure (cached — won't retry a broken
    model). Blocks the calling thread while loading (~100s on first cold call);
    call via asyncio.to_thread from async handlers so the event loop stays
    responsive. The pre-lock fast paths are race-free under concurrency=1;
    the double-checked locking keeps them correct if concurrency is raised.
    """
    global _sam3, _sam3_error, _sam3_loading
    # Pre-lock fast paths — safe under concurrency=1.
    if _sam3_error is not None:
        raise HTTPException(status_code=500, detail=f"SAM 3 failed to load: {_sam3_error}")
    if _sam3 is not None:
        return _sam3
    with _sam3_lock:
        if _sam3 is not None:
            return _sam3
        if _sam3_error is not None:
            raise HTTPException(status_code=500, detail=f"SAM 3 failed to load: {_sam3_error}")
        _sam3_loading = True
        try:
            from models.sam3 import SAM3Model  # noqa: PLC0415
            logger.info("[model] Loading SAM 3 on %s...", DEVICE)
            t = time.time()
            _sam3 = SAM3Model()
            logger.info("[model] SAM 3 loaded in %.1fs", time.time() - t)
        except Exception as e:
            _sam3_error = f"{type(e).__name__}: {e}"
            logger.error("[model] SAM 3 FAILED: %s", _sam3_error)
            raise HTTPException(status_code=500, detail=f"SAM 3 failed to load: {_sam3_error}")
        finally:
            _sam3_loading = False
    return _sam3


def get_sam3d():
    """Return the SAM3DModel singleton, loading it on first call.

    Raises HTTPException(500) on load failure (cached — won't retry a broken
    model). Blocks the calling thread while loading (~95s on first cold call,
    including DINOv2 init from baked TORCH_HOME cache); call via
    asyncio.to_thread from async handlers so the event loop stays responsive.
    The pre-lock fast paths are race-free under concurrency=1; the
    double-checked locking keeps them correct if concurrency is raised.
    """
    global _sam3d, _sam3d_error, _sam3d_loading
    # Pre-lock fast paths — safe under concurrency=1.
    if _sam3d_error is not None:
        raise HTTPException(status_code=500, detail=f"SAM 3D failed to load: {_sam3d_error}")
    if _sam3d is not None:
        return _sam3d
    with _sam3d_lock:
        if _sam3d is not None:
            return _sam3d
        if _sam3d_error is not None:
            raise HTTPException(status_code=500, detail=f"SAM 3D failed to load: {_sam3d_error}")
        _sam3d_loading = True
        try:
            from models.sam3d import SAM3DModel  # noqa: PLC0415
            logger.info("[model] Loading SAM 3D Objects...")
            t = time.time()
            _sam3d = SAM3DModel()
            logger.info("[model] SAM 3D loaded in %.1fs", time.time() - t)
        except Exception as e:
            _sam3d_error = f"{type(e).__name__}: {e}"
            logger.error("[model] SAM 3D FAILED: %s", _sam3d_error)
            raise HTTPException(status_code=500, detail=f"SAM 3D failed to load: {_sam3d_error}")
        finally:
            _sam3d_loading = False
    return _sam3d


# -----------------------------------------------------------------------------
# FastAPI app
# -----------------------------------------------------------------------------
app = FastAPI(title="roomstudio-perception-obj")

# Lazy-initialized singletons for the /process endpoint. In tests, replace via
# patch.object(server, "_receiver_repo", ...) etc.
_receiver_repo = None
_fcm_notifier = None
_oidc_verifier = None


def _get_receiver_repo():
    global _receiver_repo
    if _receiver_repo is None:
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
def root() -> dict[str, Any]:
    return {"status": "ok", "device": DEVICE, "models": ["sam3", "sam-3d-objects"]}


@app.get("/health")
def health() -> dict[str, str]:
    """Startup probe target. Always returns 200 as soon as uvicorn is up.
    No model interaction — this endpoint must never block. The startup probe
    in infra/deploy_perception.sh points here so Cloud Run marks the container
    healthy in seconds, decoupling container liveness from the ~195s model load.
    See docs/decisions/0007.

    Note: /healthz is intercepted by Google's Frontend (GFE) and never reaches
    the container on public Cloud Run URLs. /health is not intercepted.
    See docs/decisions/0009."""
    return {"status": "ok"}


@app.get("/ready")
def ready() -> JSONResponse:
    """Model readiness check. Reports load state per model.

    status values: not_loaded | loading | loaded | failed

    Returns 200 when both models are loaded, 503 while loading or not yet
    triggered, 500 if either model failed. Intended for observability and for
    clients that want to know whether the next /process call will block.
    """
    def _model_status(instance, error, loading) -> str:
        if error is not None:
            return "failed"
        if instance is not None:
            return "loaded"
        if loading:
            return "loading"
        return "not_loaded"

    sam3_status = _model_status(_sam3, _sam3_error, _sam3_loading)
    sam3d_status = _model_status(_sam3d, _sam3d_error, _sam3d_loading)

    body: dict[str, Any] = {
        "sam3": sam3_status,
        "sam3d": sam3d_status,
    }
    if _sam3_error:
        body["sam3_error"] = _sam3_error
    if _sam3d_error:
        body["sam3d_error"] = _sam3d_error

    if sam3_status == "failed" or sam3d_status == "failed":
        return JSONResponse(body, status_code=500)
    if sam3_status == "loaded" and sam3d_status == "loaded":
        return JSONResponse(body, status_code=200)
    return JSONResponse(body, status_code=503)


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
    req: ProcessRequest,
) -> JSONResponse:
    """Cloud Tasks perception receiver.

    Accepts {scene_id, bundle_uri}, claims the scene atomically (with
    lease-TTL crash recovery), runs SAM 3 + SAM 3D Objects on all frames,
    writes outputs to GCS, and updates Scene state in Firestore.

    Cloud Run config: concurrency=1, request-timeout=900s
    (infra/deploy_perception.sh). The dispatching side sets a Cloud Tasks
    dispatch_deadline of 930s (api-internal dispatcher.py,
    DISPATCH_DEADLINE_SECONDS) — deliberately ≥ this service's request
    timeout so Cloud Tasks never retries an attempt that is still running.
    Returns 5xx on environmental failures so Cloud Tasks retries. Returns 2xx
    on all success and poison paths so the task is drained from the queue.
    """
    from process_receiver import handle_process

    # Accessors load models on first call (~195s combined on a cold container);
    # run them off the event-loop thread so /health and /ready stay responsive
    # during the load. The accessors' locking already serializes concurrent
    # loads. Raises 500 (HTTPException) on cached load failure.
    sam3_model = await asyncio.to_thread(get_sam3)
    sam3d_model = await asyncio.to_thread(get_sam3d)

    return await handle_process(
        request,
        req,
        oidc_verifier=_get_oidc_verifier(),
        receiver_repo=_get_receiver_repo(),
        fcm_notifier=_get_fcm_notifier(),
        outputs_bucket=PERCEPTION_OUTPUTS_BUCKET,
        sam3_model=sam3_model,
        sam3d_model=sam3d_model,
        object_prompt=DEFAULT_OBJECT_PROMPT,
    )


