"""roomstudio internal API — IAM-gated Eventarc handler and legacy ingest endpoint.

This service runs --no-allow-unauthenticated. Cloud Run IAM validates the
caller's OIDC token at the platform boundary before any request reaches
application code. No in-app caller verification is needed or implemented here.

Endpoints:
  GET  /health
      Liveness probe; always returns {"status": "ok"} with HTTP 200.

  POST /ingest
      Validate bundle by GCS URI, run existence check, create Scene, enqueue
      perception task. Legacy entry-point; kept for compatibility.

  POST /ingest/eventarc
      Eventarc CloudEvent handler for google.cloud.storage.object.v1.finalized
      on the captures bucket (bucket-wide filter — GCS Eventarc does not support
      object-path suffix filters; see decision 0023). Discriminates bundle.pb from
      pixel-blob events in-handler: non-matching paths return HTTP 200 with a
      structured ignore-log so Pub/Sub acknowledges rather than retrying. Matching
      paths run the same ingest logic as /ingest. Handles idempotency
      (already-queued scenes) and the retry path (failed_incomplete → queued on
      successful re-upload).

Run locally (from services/api-internal/):
  uvicorn server:app --reload --port 8081

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
"""
from __future__ import annotations

import concurrent.futures
import logging
import os
import re
import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

# Configure root logger so application logger.info() calls reach Cloud Logging.
# By default uvicorn leaves the root logger with no handlers, falling back to
# Python's lastResort handler which only outputs WARNING+. basicConfig adds a
# StreamHandler at INFO level to the root logger; uvicorn's subsequent
# dictConfig (disable_existing_loggers=False, no "root" key) preserves it.
# This is a no-op if handlers are already configured (e.g. in test environments
# that call basicConfig themselves). See perception-obj/server.py for the
# original fix; this was missing here (decision 0023's "observable via log
# query" claim for eventarc_ignored was not actually true in production).
logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
logger = logging.getLogger(__name__)

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# Ensure local packages are importable in dev without a virtualenv install.
_repo_root = Path(__file__).resolve().parents[2]
for _pkg in ("packages/schemas", "packages/api-core"):
    _p = str(_repo_root / _pkg)
    if _p not in sys.path:
        sys.path.insert(0, _p)

from roomstudio_schemas import CaptureBundle, CaptureTier  # noqa: E402
from validation import validate_bundle  # noqa: E402
from scene import DeviceIdSource, SceneStatus, new_scene  # noqa: E402
from repository import SceneRepository, InMemorySceneRepository  # noqa: E402
import blob_validator  # noqa: E402
from dispatcher import TaskDispatcher, InMemoryTaskDispatcher  # noqa: E402
from fcm import FcmNotifier, NullFcmNotifier  # noqa: E402
from roomstudio_api_core.upload_session_repo import (  # noqa: E402
    UploadSessionRepository,
    InMemoryUploadSessionRepository,
)


# ---------------------------------------------------------------------------
# Startup validation
# ---------------------------------------------------------------------------

_PRODUCTION_REQUIRED_VARS: tuple[str, ...] = (
    "FIRESTORE_PROJECT",
    "CLOUD_TASKS_PROJECT",
    "CLOUD_TASKS_LOCATION",
    "CLOUD_TASKS_QUEUE",
    "CLOUD_TASKS_INVOKER_SA",
    "PERCEPTION_OBJ_PROCESS_URL",
)


def _check_production_env() -> None:
    """Raise RuntimeError if ENVIRONMENT=production and any required var is absent."""
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
    _check_production_env()
    yield


app = FastAPI(
    title="roomstudio-api-internal",
    description="Internal IAM-gated API. Hosts /ingest/eventarc (Eventarc trigger) and legacy /ingest.",
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
    """Returned on successful ingest (HTTP 200)."""
    scene_id: str
    status: str


class IngestError(BaseModel):
    """Returned on failure (HTTP 400 or 500)."""
    error: str
    detail: str


# ---------------------------------------------------------------------------
# Dependency instances — lazy-initialized from env vars on first use.
# ---------------------------------------------------------------------------

_scene_repo: Optional[SceneRepository] = None
_task_dispatcher: Optional[TaskDispatcher] = None
_fcm_notifier: Optional[FcmNotifier] = None
_upload_session_repo: Optional[UploadSessionRepository] = None

_PERCEPTION_OBJ_PROCESS_URL: str = os.environ.get(
    "PERCEPTION_OBJ_PROCESS_URL", "http://localhost:8081/process"
)


def _get_scene_repo() -> SceneRepository:
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
                "Using CloudTasksDispatcher (project=%s location=%s queue=%s)",
                project, location, queue,
            )
        else:
            _task_dispatcher = InMemoryTaskDispatcher()
            logger.info("Cloud Tasks env vars unset — using in-memory TaskDispatcher")
    return _task_dispatcher


def _get_fcm_notifier() -> FcmNotifier:
    global _fcm_notifier
    if _fcm_notifier is None:
        if os.environ.get("ENVIRONMENT") == "production":
            from fcm import FirebaseFcmNotifier
            _fcm_notifier = FirebaseFcmNotifier()
            logger.info("Using FirebaseFcmNotifier")
        else:
            _fcm_notifier = NullFcmNotifier()
            logger.info("ENVIRONMENT != production — using NullFcmNotifier")
    return _fcm_notifier


def _get_upload_session_repo() -> UploadSessionRepository:
    # Each service defines its own factory. The factory reads FIRESTORE_PROJECT
    # from this service's bootstrap context; putting it in api-core would couple
    # core to each service's env-var conventions, defeating the isolation.
    global _upload_session_repo
    if _upload_session_repo is None:
        project = os.environ.get("FIRESTORE_PROJECT")
        if project:
            from roomstudio_api_core.upload_session_repo import FirestoreUploadSessionRepository
            _upload_session_repo = FirestoreUploadSessionRepository(project=project)
            logger.info("Using Firestore UploadSessionRepository")
        else:
            _upload_session_repo = InMemoryUploadSessionRepository()
            logger.info("FIRESTORE_PROJECT unset — using in-memory UploadSessionRepository")
    return _upload_session_repo


# ---------------------------------------------------------------------------
# device_id resolution
# ---------------------------------------------------------------------------

def resolve_device_id(bundle, bundle_gcs_uri: str) -> tuple[str, DeviceIdSource]:
    """Return (device_id, source) from the parsed CaptureBundle."""
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
# GCS fetch
# ---------------------------------------------------------------------------

MAX_BUNDLE_BYTES: int = 10 * 1024 * 1024  # 10 MiB — proto metadata only


def _fetch_bundle_bytes(gcs_uri: str) -> bytes:
    """Download bundle bytes from GCS. Patched out in tests."""
    from google.cloud import storage  # deferred

    if not gcs_uri.startswith("gs://"):
        raise ValueError(f"Expected gs:// URI, got: {gcs_uri!r}")
    without_scheme = gcs_uri[5:]
    bucket_name, blob_path = without_scheme.split("/", 1)
    client = storage.Client()
    blob = client.bucket(bucket_name).blob(blob_path)
    blob.reload()
    if blob.size is not None and blob.size > MAX_BUNDLE_BYTES:
        raise ValueError(
            f"Bundle blob is {blob.size} bytes, exceeds limit of "
            f"{MAX_BUNDLE_BYTES} bytes ({MAX_BUNDLE_BYTES // (1024 * 1024)} MiB). "
            "The bundle proto must not contain pixel data inline."
        )
    return blob.download_as_bytes()


# ---------------------------------------------------------------------------
# Existence check helpers
# ---------------------------------------------------------------------------

def _blob_exists(bucket_name: str, blob_path: str) -> bool:
    """Return True if the GCS blob exists. Patched in tests."""
    from google.cloud import storage  # deferred

    return storage.Client().bucket(bucket_name).blob(blob_path).exists()


def _collect_bundle_blob_paths(bundle) -> list[str]:
    """Return all relative blob paths referenced in the bundle."""
    paths: list[str] = []
    for frame in bundle.frames:
        if frame.rgb_gcs_path:
            paths.append(frame.rgb_gcs_path)
        if frame.HasField("depth"):
            if frame.depth.depth_gcs_path:
                paths.append(frame.depth.depth_gcs_path)
            if frame.depth.HasField("confidence_gcs_path"):
                if frame.depth.confidence_gcs_path:
                    paths.append(frame.depth.confidence_gcs_path)
    if bundle.HasField("room_plan"):
        if bundle.room_plan.usdz_gcs_path:
            paths.append(bundle.room_plan.usdz_gcs_path)
    return paths


def _check_bundle_blobs_exist(
    bundle, bucket: str, bundle_id: str
) -> list[str]:
    """Return list of relative paths absent in GCS. Empty list = all present.

    Checks all blob paths referenced in the bundle in parallel using
    ThreadPoolExecutor. The blob paths are relative to captures/{bundle_id}/.
    """
    relative_paths = _collect_bundle_blob_paths(bundle)
    if not relative_paths:
        return []

    def _check(rel_path: str) -> str | None:
        blob_path = f"captures/{bundle_id}/{rel_path}"
        return rel_path if not _blob_exists(bucket, blob_path) else None

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, len(relative_paths))) as pool:
        results = list(pool.map(_check, relative_paths))

    return [r for r in results if r is not None]


# ---------------------------------------------------------------------------
# bundle_id extraction from GCS URI
# ---------------------------------------------------------------------------

# Expected pattern: gs://<bucket>/captures/<bundle_id>/bundle.pb
_BUNDLE_URI_RE = re.compile(r"^gs://[^/]+/captures/([^/]+)/bundle\.pb$")


def _extract_bundle_id(bundle_gcs_uri: str) -> str | None:
    """Extract bundle_id from a gs://…/captures/{bundle_id}/bundle.pb URI."""
    m = _BUNDLE_URI_RE.match(bundle_gcs_uri)
    return m.group(1) if m else None


def _extract_bucket(bundle_gcs_uri: str) -> str:
    """Extract bucket name from a gs://bucket/... URI."""
    return bundle_gcs_uri[5:].split("/", 1)[0]


# ---------------------------------------------------------------------------
# Core ingest logic (shared by /ingest and /ingest/eventarc)
# ---------------------------------------------------------------------------

def _run_ingest(
    bundle_gcs_uri: str,
    repo: SceneRepository,
    dispatcher: TaskDispatcher,
    *,
    existing_scene_id: str | None = None,
) -> JSONResponse:
    """Fetch, parse, validate, existence-check, and enqueue a bundle.

    existing_scene_id: if set, the Scene already exists (retry after
    failed_incomplete) and will be transitioned to QUEUED rather than
    creating a new record.
    """
    bundle_id = _extract_bundle_id(bundle_gcs_uri)
    bucket = _extract_bucket(bundle_gcs_uri)

    # 1. Fetch from GCS.
    try:
        raw = _fetch_bundle_bytes(bundle_gcs_uri)
    except Exception as exc:
        logger.exception("Failed to fetch bundle from GCS: %s", bundle_gcs_uri)
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
            "Failed to parse bundle proto from %s (%d bytes)", bundle_gcs_uri, len(raw)
        )
        return JSONResponse(
            status_code=400,
            content=IngestError(error="bundle_parse_failed", detail=str(exc)).model_dump(),
        )

    # 3. Validate contract.
    err = validate_bundle(bundle)
    if err:
        error_code, detail = err
        # Create a FAILED_INVALID Scene so the iOS client can observe the rejection
        # via GET /scenes/by-bundle/{bundle_id} polling. The iOS path never calls
        # /ingest directly — it uploads bundle.pb to GCS and polls; without a Scene
        # the client polls into the void with no terminal state.
        #
        # Returning 200 (not 400) prevents Pub/Sub retry storms on the Eventarc path:
        # a non-2xx from /ingest/eventarc triggers redelivery, so a stale cohort
        # sending "1.0.0" bundles at a schema bump would spin forever otherwise.
        #
        # Fallback to 400 only when we can't create a pollable Scene (no bundle_id
        # extractable from the URI, or bundle carries no device identity).
        if bundle_id:
            try:
                _rej_device_id, _rej_source = resolve_device_id(bundle, bundle_gcs_uri)
            except ValueError:
                _rej_device_id = None
            if _rej_device_id is not None:
                _handle_failed_invalid(
                    bundle_gcs_uri=bundle_gcs_uri,
                    bundle_id=bundle_id,
                    device_id=_rej_device_id,
                    device_id_source=_rej_source,
                    invalid_blobs=[],
                    repo=repo,
                    existing_scene_id=existing_scene_id,
                    rejection_kind=error_code,
                    rejection_detail=detail,
                )
                return JSONResponse(
                    status_code=200,
                    content={"status": "failed_invalid", "error": error_code},
                )
        # Fallback: no bundle_id in the URI or bundle has no device identity.
        # 400 is acceptable here — the client can't poll either way (no bundle_id)
        # or the bundle is so malformed it's not worth a Scene. Retry behaviour on
        # the Eventarc path is bounded: _extract_bundle_id returns None only for
        # paths that don't match captures/*/bundle.pb, which the trigger's bucket-wide
        # filter makes rare steady-state traffic rather than a stale-cohort storm.
        return JSONResponse(
            status_code=400,
            content=IngestError(error=error_code, detail=detail).model_dump(),
        )

    # 4. Resolve device_id.
    try:
        device_id, device_id_source = resolve_device_id(bundle, bundle_gcs_uri)
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content=IngestError(error="device_id_missing", detail=str(exc)).model_dump(),
        )

    # 5. Existence check — verify all referenced blobs are present in GCS.
    if bundle_id:
        missing = _check_bundle_blobs_exist(bundle, bucket, bundle_id)
        if missing:
            _handle_failed_incomplete(
                bundle_gcs_uri=bundle_gcs_uri,
                bundle_id=bundle_id,
                device_id=device_id,
                device_id_source=device_id_source,
                missing=missing,
                repo=repo,
                existing_scene_id=existing_scene_id,
            )
            return JSONResponse(
                status_code=200,
                content={"status": "failed_incomplete", "missing_paths": missing},
            )

    # 5b. Image-blob validation gate — check RGB frames before dispatching to GPU.
    # Fast-fails bundles with non-decodable image data (too small, wrong format,
    # or bad magic bytes) before they reach the perception pipeline. FAILED_INVALID
    # is terminal: corrupted blobs cannot be fixed by re-uploading the same data.
    if bundle_id:
        invalid_blobs = _validate_image_blobs(bundle, bucket, bundle_id)
        if invalid_blobs:
            _handle_failed_invalid(
                bundle_gcs_uri=bundle_gcs_uri,
                bundle_id=bundle_id,
                device_id=device_id,
                device_id_source=device_id_source,
                invalid_blobs=invalid_blobs,
                repo=repo,
                existing_scene_id=existing_scene_id,
            )
            return JSONResponse(
                status_code=200,
                content={"status": "failed_invalid", "invalid_blobs": invalid_blobs},
            )

    # 6. Create or transition Scene to QUEUED.
    if existing_scene_id:
        scene = repo.update_status(existing_scene_id, SceneStatus.QUEUED)
        scene_id = existing_scene_id
        logger.info(
            "Scene retried: scene_id=%s bundle_uri=%s", scene_id, bundle_gcs_uri
        )
    else:
        scene_id = str(uuid.uuid4())
        scene = new_scene(
            scene_id=scene_id,
            device_id=device_id,
            device_id_source=device_id_source,
            bundle_uri=bundle_gcs_uri,
        )
        # Store bundle_id on the scene for later lookup by /ingest/eventarc.
        scene.bundle_id = bundle_id
        scene.user_id = bundle.user_id or None
        repo.create(scene)
        logger.info(
            "Scene created: scene_id=%s device_id_source=%s bundle_uri=%s",
            scene_id,
            device_id_source.value,
            bundle_gcs_uri,
        )

    # 7. Enqueue Cloud Task targeting perception-obj.
    try:
        dispatcher.enqueue(
            task_name=scene_id,
            payload={"scene_id": scene_id, "bundle_uri": bundle_gcs_uri},
            target_url=_PERCEPTION_OBJ_PROCESS_URL,
        )
        logger.info("Task enqueued: scene_id=%s target=%s", scene_id, _PERCEPTION_OBJ_PROCESS_URL)
    except Exception as exc:
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

    return JSONResponse(
        status_code=200,
        content=IngestAck(scene_id=scene_id, status="queued").model_dump(),
    )


def _validate_image_blobs(bundle, bucket: str, bundle_id: str) -> list[dict]:
    """Thin wrapper around blob_validator.validate_image_blobs.

    Exists as a module-level function so tests can patch it on the server
    module (patch.object(server, "_validate_image_blobs", ...)) without
    affecting the blob_validator module directly. All existing tests that
    exercise the happy path patch this wrapper to return [] (no invalid blobs),
    keeping them independent of GCS I/O.
    """
    return blob_validator.validate_image_blobs(bundle, bucket, bundle_id)


def _handle_failed_incomplete(
    *,
    bundle_gcs_uri: str,
    bundle_id: str,
    device_id: str,
    device_id_source: DeviceIdSource,
    missing: list[str],
    repo: SceneRepository,
    existing_scene_id: str | None,
) -> None:
    """Create or update the Scene to FAILED_INCOMPLETE and fire FCM."""
    if existing_scene_id:
        scene_id = existing_scene_id
        repo.update_status(
            scene_id,
            SceneStatus.FAILED_INCOMPLETE,
            missing_paths=missing,
            last_error=f"missing blobs: {missing}",
        )
    else:
        scene_id = str(uuid.uuid4())
        scene = new_scene(
            scene_id=scene_id,
            device_id=device_id,
            device_id_source=device_id_source,
            bundle_uri=bundle_gcs_uri,
        )
        scene.bundle_id = bundle_id
        scene.user_id = _get_upload_session_repo().get_user_id(bundle_id)
        repo.create(scene)
        repo.update_status(
            scene_id,
            SceneStatus.FAILED_INCOMPLETE,
            missing_paths=missing,
            last_error=f"missing blobs: {missing}",
        )
    logger.warning(
        "Scene %s failed_incomplete: bundle_id=%s missing=%s",
        scene_id,
        bundle_id,
        missing,
    )

    # FCM: look up the FCM token from the upload_session record.
    try:
        upload_repo = _get_upload_session_repo()
        # Both concrete implementations expose get_fcm_token; the abstract
        # base does not require it, so we call defensively.
        get_fcm_token = getattr(upload_repo, "get_fcm_token", None)
        if get_fcm_token:
            fcm_token = get_fcm_token(bundle_id)
            if fcm_token:
                _get_fcm_notifier().notify_upload_incomplete(
                    fcm_token=fcm_token,
                    scene_id=scene_id,
                    missing_paths=missing,
                )
    except Exception:
        logger.exception("FCM notification failed for scene %s (continuing)", scene_id)


def _handle_failed_invalid(
    *,
    bundle_gcs_uri: str,
    bundle_id: str,
    device_id: str,
    device_id_source: DeviceIdSource,
    invalid_blobs: list[dict],
    repo: SceneRepository,
    existing_scene_id: str | None,
    rejection_kind: str = "invalid_blobs",
    rejection_detail: str = "",
) -> None:
    """Create (or update) a Scene to FAILED_INVALID and emit a structured log.

    FAILED_INVALID is terminal — the bundle cannot be fixed by re-uploading.
    The Scene is created but never dispatched to the GPU pipeline.

    rejection_kind controls the log discriminator and last_error format:
      "invalid_blobs"  — image-decode failure; invalid_blobs list is populated
      anything else    — contract validation failure (e.g. "unsupported_schema_version");
                         rejection_detail carries the human-readable reason
    """
    if rejection_kind == "invalid_blobs":
        last_error = f"invalid blobs: {[b['relative_path'] for b in invalid_blobs]}"
        stored_blobs: list[dict] | None = invalid_blobs
    else:
        last_error = f"{rejection_kind}: {rejection_detail}"
        stored_blobs = None

    if existing_scene_id:
        # existing_scene_id is only set when retrying a FAILED_INCOMPLETE scene,
        # which means blobs were previously absent but are now present. If they
        # turn out to be invalid, transition to FAILED_INVALID directly.
        scene_id = existing_scene_id
        repo.update_status(
            scene_id,
            SceneStatus.FAILED_INVALID,
            invalid_blobs=stored_blobs,
            last_error=last_error,
        )
    else:
        scene_id = str(uuid.uuid4())
        scene = new_scene(
            scene_id=scene_id,
            device_id=device_id,
            device_id_source=device_id_source,
            bundle_uri=bundle_gcs_uri,
        )
        scene.bundle_id = bundle_id
        scene.user_id = _get_upload_session_repo().get_user_id(bundle_id)
        repo.create(scene)
        repo.update_status(
            scene_id,
            SceneStatus.FAILED_INVALID,
            invalid_blobs=stored_blobs,
            last_error=last_error,
        )

    if rejection_kind == "invalid_blobs":
        logger.warning(
            "Scene %s failed_invalid: bundle_id=%s invalid_blobs=%s",
            scene_id,
            bundle_id,
            invalid_blobs,
        )
    else:
        logger.warning(
            "Scene %s failed_invalid: bundle_id=%s reason=%s detail=%s",
            scene_id,
            bundle_id,
            rejection_kind,
            rejection_detail,
        )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health", summary="Liveness probe")
def health() -> JSONResponse:
    """Always returns {"status": "ok"} with HTTP 200."""
    return JSONResponse(status_code=200, content={"status": "ok"})


@app.post(
    "/ingest",
    response_model=IngestAck,
    responses={400: {"model": IngestError}, 500: {"model": IngestError}},
    summary="Validate a CaptureBundle and enqueue perception work",
)
def ingest(req: IngestRequest) -> JSONResponse:
    """Accept a serialized CaptureBundle by GCS URI.

    On success (200): bundle is valid, all blobs exist, Scene is queued.
    On validation failure (400): bundle did not pass contract checks.
    On existence failure (200, status=failed_incomplete): some blobs absent.
    On dispatch failure (500): valid bundle but task could not be enqueued.
    """
    return _run_ingest(
        req.bundle_gcs_uri,
        _get_scene_repo(),
        _get_task_dispatcher(),
    )


@app.post(
    "/ingest/eventarc",
    summary="Eventarc CloudEvent handler for captures/*/bundle.pb finalize",
)
async def ingest_eventarc(request: Request) -> JSONResponse:
    """Handle a GCS finalize event from Eventarc.

    The Eventarc trigger is bucket-wide on roomstudio-captures (GCS Eventarc does
    not support object-path suffix filters on object.v1.finalized events — see
    decision 0023). Every finalize event arrives here, including pixel-blob uploads.

    Non-bundle.pb paths: return HTTP 200 with a structured INFO log so Pub/Sub
    acknowledges the message. No work is done; the 200 closes the delivery loop.

    bundle.pb paths: run the full ingest pipeline.

    Eventarc delivers the GCS StorageObjectData as the request body (JSON).
    Called by Eventarc; Cloud Run requires roles/run.invoker on the caller.
    The Eventarc SA is granted that role in infra/eventarc_setup.sh before
    the trigger is created.

    Idempotency (bundle.pb path only):
    - If a Scene for this bundle_id is already QUEUED, PROCESSING, or READY,
      return 200 immediately without re-processing.
    - If FAILED_INCOMPLETE, re-run the existence check with the same scene_id
      (transition to QUEUED if blobs are now present).
    - Otherwise, run a fresh ingest.
    """
    try:
        body = await request.json()
    except Exception as exc:
        logger.warning("Failed to parse Eventarc body: %s", exc)
        return JSONResponse(status_code=400, content={"error": "bad_event", "detail": str(exc)})

    bucket = body.get("bucket", "")
    name = body.get("name", "")  # e.g. "captures/<bundle_id>/bundle.pb"

    if not bucket or not name:
        logger.warning("Eventarc event missing bucket or name: %s", body)
        return JSONResponse(
            status_code=400,
            content={"error": "bad_event", "detail": "missing 'bucket' or 'name' in event body"},
        )

    bundle_gcs_uri = f"gs://{bucket}/{name}"
    bundle_id = _extract_bundle_id(bundle_gcs_uri)
    if not bundle_id:
        # Pixel-blob upload or other non-bundle.pb finalize event. The trigger is
        # bucket-wide (GCS Eventarc cannot filter by object path suffix — see
        # decision 0023), so these are expected steady-state traffic. Return 200
        # so Pub/Sub acknowledges the message rather than entering the retry loop.
        logger.info(
            "event=eventarc_ignored object_name=%s reason=not_bundle_pb",
            name,
        )
        return JSONResponse(
            status_code=200,
            content={"event": "eventarc_ignored", "object_name": name, "reason": "not_bundle_pb"},
        )

    repo = _get_scene_repo()
    dispatcher = _get_task_dispatcher()

    # Idempotency: check for an existing Scene for this bundle_id.
    existing = repo.get_by_bundle_id(bundle_id)
    if existing:
        if existing.status in (SceneStatus.QUEUED, SceneStatus.PROCESSING, SceneStatus.READY):
            logger.info(
                "Eventarc: bundle_id=%s already has scene %s in status %s — skipping",
                bundle_id,
                existing.scene_id,
                existing.status,
            )
            return JSONResponse(
                status_code=200,
                content=IngestAck(
                    scene_id=existing.scene_id, status=existing.status.value
                ).model_dump(),
            )
        if existing.status == SceneStatus.FAILED_INVALID:
            # Terminal state: corrupted blobs cannot be fixed by re-uploading
            # the same data. Unlike FAILED_INCOMPLETE (missing blobs that a
            # re-upload can supply), FAILED_INVALID means the bytes were present
            # but non-decodable. A second finalize event for the same bundle_id
            # cannot change that — skip without re-processing.
            logger.info(
                "Eventarc: bundle_id=%s scene %s is FAILED_INVALID (terminal) — skipping",
                bundle_id,
                existing.scene_id,
            )
            return JSONResponse(
                status_code=200,
                content=IngestAck(
                    scene_id=existing.scene_id, status=existing.status.value
                ).model_dump(),
            )
        if existing.status == SceneStatus.FAILED_INCOMPLETE:
            logger.info(
                "Eventarc: retrying failed_incomplete scene %s for bundle_id=%s",
                existing.scene_id,
                bundle_id,
            )
            return _run_ingest(
                bundle_gcs_uri,
                repo,
                dispatcher,
                existing_scene_id=existing.scene_id,
            )

    return _run_ingest(bundle_gcs_uri, repo, dispatcher)
