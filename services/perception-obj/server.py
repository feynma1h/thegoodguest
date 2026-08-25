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
  POST /shell     — Cloud Tasks receiver, second stage (decision 0066).
                    Bakes the room shell from plane anchors + cached masks.
                    Never loads the SAM models; never touches Firestore.
                    See shell_receiver.py.

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

# Request models must be imported before the @app.post registrations that use them.
# FastAPI resolves type annotations at decoration time; if ProcessRequest is not
# in the module namespace then, FastAPI silently treats `req` as a query param
# instead of a body model, producing 422 on every Cloud Tasks delivery.
# See docs/decisions/0010.
from compress_receiver import CompressRequest  # noqa: E402  (same 0010 rule)
from process_receiver import (  # noqa: E402
    DEFAULT_OBJECT_PROMPT,
    ProcessRequest,
)
from segment_receiver import SegmentRequest  # noqa: E402  (same 0010 rule for /segment)
from shell_receiver import ShellRequest  # noqa: E402  (same 0010 rule for /shell)

# Model classes are NOT imported at module level. Importing models.sam3 or
# models.sam3d would immediately run the SAM 3 / SAM 3D CUDA initialisation
# (hundreds of seconds), blocking uvicorn from binding before the startup
# probe fires. Imports are deferred to the accessor functions below so that
# the process survives the startup probe and pays the load cost on first use.


# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

# GCS bucket for perception outputs. /process (process_receiver.py) writes
# per-scene splats and manifests under scenes/{scene_id}/ in this bucket.
PERCEPTION_OUTPUTS_BUCKET = os.environ.get(
    "PERCEPTION_OUTPUTS_BUCKET", "roomstudio-perception-outputs"
)

# Wall-clock budget for one /process request. Must mirror the Cloud Run
# request timeout (infra/deploy_perception.sh --timeout=900): the receiver
# uses it to stop reconstruction early and finish INSIDE the request instead
# of computing past the platform cutoff as an unreachable zombie (see
# budget.py). Deliberately a mirror, not gospel — if the deploy flag changes,
# set this env var to match.
PROCESS_REQUEST_BUDGET_SECONDS = float(
    os.environ.get("PROCESS_REQUEST_BUDGET_SECONDS", "900")
)

# Same mirror for /shell (decision 0066): the shell bake shares the service's
# Cloud Run request timeout; its handler stops with an environmental error
# (Cloud Tasks retries) rather than computing past the platform cutoff.
SHELL_REQUEST_BUDGET_SECONDS = float(
    os.environ.get("SHELL_REQUEST_BUDGET_SECONDS", "900")
)

# Same mirror for /compress (decisions 0125/0126). Running out of budget is
# not an error there: the stage writes the index with what it banked and the
# rest of the room falls back to PLY, so the next re-drive finishes the job.
COMPRESS_REQUEST_BUDGET_SECONDS = float(
    os.environ.get("COMPRESS_REQUEST_BUDGET_SECONDS", "900")
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
_shell_oidc_verifier = None
_compress_oidc_verifier = None


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


def _get_shell_oidc_verifier():
    """Separate verifier for /shell: same invoker SA, but the OIDC audience
    is RECEIVER_URL + "/shell" — a /process token must not replay here."""
    global _shell_oidc_verifier
    if _shell_oidc_verifier is None:
        from oidc import OIDCVerifier
        from process_receiver import CLOUD_TASKS_INVOKER_SA, RECEIVER_URL
        if CLOUD_TASKS_INVOKER_SA:
            _shell_oidc_verifier = OIDCVerifier(
                audience=RECEIVER_URL + "/shell",
                allowed_email=CLOUD_TASKS_INVOKER_SA,
            )
    return _shell_oidc_verifier


def _get_compress_oidc_verifier():
    """Separate verifier for /compress: same invoker SA, but the OIDC
    audience is RECEIVER_URL + "/compress" — a /process or /shell token
    must not replay here."""
    global _compress_oidc_verifier
    if _compress_oidc_verifier is None:
        from oidc import OIDCVerifier
        from process_receiver import CLOUD_TASKS_INVOKER_SA, RECEIVER_URL
        if CLOUD_TASKS_INVOKER_SA:
            _compress_oidc_verifier = OIDCVerifier(
                audience=RECEIVER_URL + "/compress",
                allowed_email=CLOUD_TASKS_INVOKER_SA,
            )
    return _compress_oidc_verifier


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

    # Deadline anchors at REQUEST ENTRY — the lazy model load below spends
    # minutes of the same request window, and the budget must know that.
    deadline = time.monotonic() + PROCESS_REQUEST_BUDGET_SECONDS

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
        deadline=deadline,
    )


@app.post(
    "/shell",
    summary="Cloud Tasks room-shell receiver (decision 0066)",
    responses={
        200: {"description": "Shell written, unavailable written, or noop (drained)"},
        401: {"description": "OIDC token missing or invalid"},
        422: {"description": "Malformed payload (natural poison drain)"},
        500: {"description": "Environmental failure; Cloud Tasks will retry"},
    },
)
async def shell(
    request: Request,
    req: ShellRequest,
) -> JSONResponse:
    """Room-shell second stage. Enqueued by /process's success path.

    Deliberately NEVER touches the SAM accessors — no model load on this
    path, so a cold /shell start costs seconds. No scene lease, no
    Firestore writes; shell.json is a single idempotent blob PUT
    (see shell_receiver.py).
    """
    from shell_receiver import handle_shell

    deadline = time.monotonic() + SHELL_REQUEST_BUDGET_SECONDS
    return await handle_shell(
        request,
        req,
        oidc_verifier=_get_shell_oidc_verifier(),
        outputs_bucket=PERCEPTION_OUTPUTS_BUCKET,
        deadline=deadline,
    )




@app.post(
    "/segment",
    summary="Segmentation-only probe: SAM 3 on named frames, no reconstruction",
    responses={
        200: {"description": "Segmented (per-frame errors reported in the body)"},
        401: {"description": "OIDC token missing or invalid"},
        422: {"description": "Malformed payload"},
        503: {"description": "SAM 3 not yet loaded; retry"},
    },
)
async def segment(
    request: Request,
    req: SegmentRequest,
) -> JSONResponse:
    """Run pass 1 only on an explicit frame list and return what SAM 3 saw.

    Exists because the cheap half of "would another frame reconstruct better"
    is answerable without reconstructing: the mask IS SAM 3D's input, so a
    truncated mask settles it for ~4s of GPU instead of ~25s an object.
    /process cannot answer it — its payload names no frames and it always
    reconstructs.

    Loads SAM 3 ONLY. SAM 3D is never touched here, which also skips its
    ~124s cold load. Writes exclusively under scenes/{id}/segment_probe/ and
    never to Firestore, so a probe cannot become pipeline state or regress a
    ready room (see segment_receiver's module docstring).
    """
    from segment_receiver import handle_segment

    sam3_model = await asyncio.to_thread(get_sam3)

    return await handle_segment(
        request,
        req,
        oidc_verifier=_get_oidc_verifier(),
        outputs_bucket=PERCEPTION_OUTPUTS_BUCKET,
        sam3_model=sam3_model,
        object_prompt=DEFAULT_OBJECT_PROMPT,
    )


@app.post(
    "/compress",
    summary="Cloud Tasks compressed-splat receiver (decisions 0125/0126)",
    responses={
        200: {"description": "Tier written, noop (already current), or drained"},
        401: {"description": "OIDC token missing or invalid"},
        422: {"description": "Malformed payload (natural poison drain)"},
        500: {"description": "Environmental failure; Cloud Tasks will retry"},
    },
)
async def compress(
    request: Request,
    req: CompressRequest,
) -> JSONResponse:
    """Compressed-splat third stage. Enqueued by /process's success path.

    Like /shell, NEVER touches the SAM accessors — no model load, so a cold
    start costs seconds. No scene lease, no Firestore, and never
    manifest.json: it writes .spz siblings plus scenes/{id}/compressed.json
    (see compress_receiver.py). A room with no compressed tier renders from
    PLY exactly as it always has, so failure here is invisible.
    """
    from compress_receiver import handle_compress

    deadline = time.monotonic() + COMPRESS_REQUEST_BUDGET_SECONDS
    return await handle_compress(
        request,
        req,
        oidc_verifier=_get_compress_oidc_verifier(),
        outputs_bucket=PERCEPTION_OUTPUTS_BUCKET,
        deadline=deadline,
    )
