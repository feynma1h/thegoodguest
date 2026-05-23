"""roomstudio bundle ingester — FastAPI service.

Accepts a serialized CaptureBundle by GCS URI, validates it, creates a Scene
record, enqueues a Cloud Tasks job targeting perception-obj, and returns an
acknowledgement with the scene_id and status="queued".

Endpoints:
  GET  /health  — liveness probe; always returns {"status": "ok"} with HTTP 200.
  POST /ingest  — validate bundle, create Scene, enqueue perception task.

Run locally (from services/api/):
  uvicorn server:app --reload --port 8080

Environment variables:
  ENVIRONMENT                — set to "production" to enable startup env-var
                               validation (see _check_production_env). Unset
                               or any other value → silent in-memory fallbacks
                               (appropriate for local dev / tests).
  FIRESTORE_PROJECT          — GCP project for Firestore; absent → in-memory repo
  CLOUD_TASKS_PROJECT        — GCP project for Cloud Tasks  ┐
  CLOUD_TASKS_LOCATION       — Cloud Tasks region           ├ all three required
  CLOUD_TASKS_QUEUE          — Cloud Tasks queue name       ┘ for real dispatch
  CLOUD_TASKS_INVOKER_SA     — service account email for OIDC token on tasks
  PERCEPTION_OBJ_PROCESS_URL — full URL of the perception-obj /process endpoint

See also: infra/cloud-tasks-queue.md for queue setup and SA configuration.

Consumed by: the iOS capture app (future) and integration tests.
"""
from __future__ import annotations

import logging
import os
import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# Ensure roomstudio_schemas is importable in local dev without a virtualenv
# having it installed. In production it is a declared dependency and will be
# installed. The sys.path guard avoids double-adding it if already present.
_schemas_path = Path(__file__).resolve().parents[2] / "packages/schemas"
if str(_schemas_path) not in sys.path:
    sys.path.insert(0, str(_schemas_path))

from roomstudio_schemas import CaptureBundle, CaptureTier  # noqa: E402
from validation import validate_bundle  # noqa: E402
from scene import DeviceIdSource, SceneStatus, new_scene  # noqa: E402
from repository import SceneRepository, InMemorySceneRepository  # noqa: E402
from dispatcher import TaskDispatcher, InMemoryTaskDispatcher  # noqa: E402


# ---------------------------------------------------------------------------
# Startup validation
# ---------------------------------------------------------------------------

#: Env vars that must be non-empty when ENVIRONMENT=production.
_PRODUCTION_REQUIRED_VARS: tuple[str, ...] = (
    "FIRESTORE_PROJECT",
    "CLOUD_TASKS_PROJECT",
    "CLOUD_TASKS_LOCATION",
    "CLOUD_TASKS_QUEUE",
    "CLOUD_TASKS_INVOKER_SA",
    "PERCEPTION_OBJ_PROCESS_URL",
)


def _check_production_env() -> None:
    """Raise RuntimeError if ENVIRONMENT=production and any required var is absent.

    Called from the lifespan handler at process startup. Has no effect when
    ENVIRONMENT is unset or set to any value other than "production" —
    preserving the silent in-memory fallback for local dev and tests.

    This turns misconfiguration into an immediate, noisy startup failure so
    Cloud Run's startup probe catches it and the deploy rolls back, rather
    than serving traffic with a broken (in-memory) backend silently.
    """
    if os.environ.get("ENVIRONMENT") != "production":
        return
    missing = [v for v in _PRODUCTION_REQUIRED_VARS if not os.environ.get(v)]
    if missing:
        raise RuntimeError(
            f"ENVIRONMENT=production but the following required env vars are "
            f"missing or empty: {', '.join(missing)}"
        )


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001
    """FastAPI lifespan: validate config on startup, nothing on shutdown."""
    _check_production_env()
    yield


app = FastAPI(
    title="roomstudio-api",
    description="Capture-bundle ingester. Validates bundles and dispatches perception work.",
    version="0.1.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class IngestRequest(BaseModel):
    """Body for POST /ingest."""
    bundle_gcs_uri: str


class IngestAck(BaseModel):
    """Returned on successful ingest (HTTP 200).

    The Scene has been created with status=queued and a perception task has
    been enqueued. Poll GET /scenes/{scene_id} (not yet implemented) to track
    progress.
    """
    scene_id: str
    status: str  # always "queued" on 200


class IngestError(BaseModel):
    """Returned on failure (HTTP 400 or 500).

    error:  machine-readable code, stable across versions.
    detail: human-readable explanation with enough context to act on.
    """
    error: str
    detail: str


# ---------------------------------------------------------------------------
# device_id resolution — prefer bundle.device.device_id, fall back to
# hardware_id while the iOS app is not yet built and device_id is always "".
#
# Remove the fallback_hardware_id path once iOS bundles populate device_id
# for ≥99% of captures over a 7-day window. The DeviceIdSource field on Scene
# lets you run that query in Firestore: count docs where device_id_source ==
# "fallback_hardware_id" over the target window.
# ---------------------------------------------------------------------------

def resolve_device_id(bundle, bundle_gcs_uri: str) -> tuple[str, DeviceIdSource]:
    """Return (device_id, source) from the parsed CaptureBundle.

    Preference order:
      1. bundle.device.device_id  — the stable Keychain UUID (preferred).
      2. bundle.device.hardware_id — model string fallback; not unique across
         devices of the same model. Logs a WARNING so the fallback is visible
         in Cloud Logging.

    Raises ValueError if both fields are empty, surfaced as a 400 to the client.
    """
    if bundle.device.device_id:
        return bundle.device.device_id, DeviceIdSource.PROVIDED

    if bundle.device.hardware_id:
        logger.warning(
            "device_id absent in bundle; falling back to hardware_id %r "
            "(not unique per device). bundle_uri=%s",
            bundle.device.hardware_id,
            bundle_gcs_uri,
        )
        return bundle.device.hardware_id, DeviceIdSource.FALLBACK_HARDWARE_ID

    raise ValueError(
        "bundle.device.device_id and bundle.device.hardware_id are both empty; "
        "cannot determine device identity"
    )


# ---------------------------------------------------------------------------
# GCS fetch — isolated so tests can patch without google-cloud-storage
# ---------------------------------------------------------------------------

MAX_BUNDLE_BYTES: int = 10 * 1024 * 1024  # 10 MiB — proto metadata only, no pixel data


def _fetch_bundle_bytes(gcs_uri: str) -> bytes:
    """Download bundle bytes from GCS.

    Checks blob.size before downloading and rejects anything over
    MAX_BUNDLE_BYTES. The bundle is metadata only (no pixel data); anything
    larger than 10 MiB is almost certainly a mis-upload.

    Wrapped in its own function so integration tests can patch it without
    needing google-cloud-storage installed. The deferred import of
    google.cloud.storage means importing this module in tests is also safe.

    Raises ValueError for a malformed URI or an oversized blob; raises
    google.cloud.exceptions.* for GCS errors (NotFound, Forbidden, etc.) —
    callers should handle both.
    """
    from google.cloud import storage  # deferred: not installed in tests

    if not gcs_uri.startswith("gs://"):
        raise ValueError(f"Expected gs:// URI, got: {gcs_uri!r}")
    # Strip scheme and split on the first slash: gs://bucket/path/to/blob
    without_scheme = gcs_uri[5:]
    bucket_name, blob_path = without_scheme.split("/", 1)
    client = storage.Client()
    blob = client.bucket(bucket_name).blob(blob_path)
    blob.reload()  # fetches blob metadata (size, content-type, etc.)
    if blob.size is not None and blob.size > MAX_BUNDLE_BYTES:
        raise ValueError(
            f"Bundle blob is {blob.size} bytes, exceeds limit of "
            f"{MAX_BUNDLE_BYTES} bytes ({MAX_BUNDLE_BYTES // (1024 * 1024)} MiB). "
            "The bundle proto must not contain pixel data inline."
        )
    return blob.download_as_bytes()


# ---------------------------------------------------------------------------
# Dependency instances — lazy-initialized from env vars on first use.
# In tests, replace via patch.object(server, "_scene_repo", fake) etc.
# ---------------------------------------------------------------------------

_scene_repo: Optional[SceneRepository] = None
_task_dispatcher: Optional[TaskDispatcher] = None

# Perception-obj endpoint to target with Cloud Tasks. The /process receiver
# does not exist yet; it is the next session's work.
_PERCEPTION_OBJ_PROCESS_URL: str = os.environ.get(
    "PERCEPTION_OBJ_PROCESS_URL", "http://localhost:8081/process"
)


def _get_scene_repo() -> SceneRepository:
    """Return the module-level SceneRepository, initialising from env if needed.

    Falls back to InMemorySceneRepository when FIRESTORE_PROJECT is unset
    (local dev / tests). In tests, patch server._scene_repo directly to inject
    a controlled instance.
    """
    global _scene_repo
    if _scene_repo is None:
        project = os.environ.get("FIRESTORE_PROJECT")
        if project:
            from repository import FirestoreSceneRepository
            _scene_repo = FirestoreSceneRepository(project=project)
            logger.info("Using Firestore SceneRepository (project=%s)", project)
        else:
            _scene_repo = InMemorySceneRepository()
            logger.info("FIRESTORE_PROJECT unset — using in-memory SceneRepository")
    return _scene_repo


def _get_task_dispatcher() -> TaskDispatcher:
    """Return the module-level TaskDispatcher, initialising from env if needed.

    Falls back to InMemoryTaskDispatcher when Cloud Tasks env vars are unset
    (local dev / tests). In tests, patch server._task_dispatcher directly to
    inject a controlled instance.
    """
    global _task_dispatcher
    if _task_dispatcher is None:
        project = os.environ.get("CLOUD_TASKS_PROJECT")
        location = os.environ.get("CLOUD_TASKS_LOCATION")
        queue = os.environ.get("CLOUD_TASKS_QUEUE")
        if project and location and queue:
            from dispatcher import CloudTasksDispatcher
            _task_dispatcher = CloudTasksDispatcher(
                project=project, location=location, queue=queue
            )
            logger.info(
                "Using CloudTasksDispatcher (project=%s, location=%s, queue=%s)",
                project, location, queue,
            )
        else:
            _task_dispatcher = InMemoryTaskDispatcher()
            logger.info(
                "Cloud Tasks env vars unset — using in-memory TaskDispatcher"
            )
    return _task_dispatcher


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health", summary="Liveness probe")
def health() -> JSONResponse:
    """Always returns {"status": "ok"} with HTTP 200.

    Used by Cloud Run startup/liveness probes and external monitoring.
    Does not exercise Firestore or Cloud Tasks — this is intentional.
    A healthy response means the process is alive and routing; it says
    nothing about backend connectivity.
    """
    return JSONResponse(status_code=200, content={"status": "ok"})


@app.post(
    "/ingest",
    response_model=IngestAck,
    responses={
        400: {"model": IngestError},
        500: {"model": IngestError},
    },
    summary="Validate a CaptureBundle and enqueue perception work",
)
def ingest(req: IngestRequest) -> JSONResponse:
    """Accept a serialized CaptureBundle by GCS URI.

    On success (200): the bundle is valid, a Scene record has been created
    with status=queued, and a Cloud Task has been enqueued targeting
    perception-obj. Response body: {scene_id, status: "queued"}.

    On validation failure (400): bundle did not pass contract checks; nothing
    was written to Firestore or Cloud Tasks.

    On dispatch failure (500): bundle was valid and the Scene record was
    created, but the Cloud Task could not be enqueued. The Scene is marked
    failed so there are no orphaned queued records.

    Validation checks (see validation.py):
      - schema_version is a supported version
      - all camera_pose quaternions are unit-norm within 1e-3
      - depth fields only appear with a LIDAR_* tier
      - all GCS paths are relative (not full gs:// URIs)
    """
    repo = _get_scene_repo()
    dispatcher = _get_task_dispatcher()

    # 1. Fetch from GCS.
    try:
        raw = _fetch_bundle_bytes(req.bundle_gcs_uri)
    except Exception as exc:
        logger.exception("Failed to fetch bundle from GCS: %s", req.bundle_gcs_uri)
        return JSONResponse(
            status_code=400,
            content=IngestError(error="bundle_fetch_failed", detail=str(exc)).model_dump(),
        )

    # 2. Parse proto.
    bundle = CaptureBundle()
    try:
        bundle.ParseFromString(raw)
    except Exception as exc:
        logger.exception(
            "Failed to parse bundle proto from %s (%d bytes)",
            req.bundle_gcs_uri, len(raw),
        )
        return JSONResponse(
            status_code=400,
            content=IngestError(error="bundle_parse_failed", detail=str(exc)).model_dump(),
        )

    # 3. Validate contract.
    err = validate_bundle(bundle)
    if err:
        error_code, detail = err
        return JSONResponse(
            status_code=400,
            content=IngestError(error=error_code, detail=detail).model_dump(),
        )

    # 4. Resolve device_id.
    try:
        device_id, device_id_source = resolve_device_id(bundle, req.bundle_gcs_uri)
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content=IngestError(error="device_id_missing", detail=str(exc)).model_dump(),
        )

    # 5. Create Scene record with status=queued.
    scene_id = str(uuid.uuid4())
    scene = new_scene(
        scene_id=scene_id,
        device_id=device_id,
        device_id_source=device_id_source,
        bundle_uri=req.bundle_gcs_uri,
    )
    repo.create(scene)
    logger.info(
        "Scene created: scene_id=%s device_id_source=%s bundle_uri=%s",
        scene_id, device_id_source.value, req.bundle_gcs_uri,
    )

    # 6. Enqueue Cloud Task targeting perception-obj.
    # Task name = scene_id for Cloud Tasks dedup within 1-hour window.
    try:
        dispatcher.enqueue(
            task_name=scene_id,
            payload={"scene_id": scene_id, "bundle_uri": req.bundle_gcs_uri},
            target_url=_PERCEPTION_OBJ_PROCESS_URL,
        )
        logger.info("Task enqueued: scene_id=%s target=%s", scene_id, _PERCEPTION_OBJ_PROCESS_URL)
    except Exception as exc:
        # Enqueue failed — mark the Scene as failed so there are no orphaned
        # queued records. The iOS client will see status=failed and offer retry.
        logger.exception("Failed to enqueue task for scene_id=%s: %s", scene_id, exc)
        try:
            repo.update_status(
                scene_id,
                SceneStatus.FAILED,
                last_error=f"dispatch_failed: {exc}",
            )
        except Exception:
            logger.exception(
                "Also failed to mark scene %s as failed after dispatch error", scene_id
            )
        return JSONResponse(
            status_code=500,
            content=IngestError(
                error="dispatch_failed",
                detail=f"Scene created but task could not be enqueued: {exc}",
            ).model_dump(),
        )

    # 7. Acknowledge.
    return JSONResponse(
        status_code=200,
        content=IngestAck(scene_id=scene_id, status="queued").model_dump(),
    )
