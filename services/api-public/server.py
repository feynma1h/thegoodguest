"""roomstudio public API — Firebase-authenticated client endpoints.

Hosts endpoints for iOS client traffic. Auth is Firebase ID token verified
in-app; Cloud Run is configured --allow-unauthenticated so the platform
does not reject Firebase JWTs before the in-app verifier sees them.

Endpoints:
  GET  /health
      Liveness probe; always returns {"status": "ok"} with HTTP 200.

  POST /captures/{bundle_id}/upload_session
      Mint GCS resumable session URIs for each entry in the manifest. Auth:
      Firebase ID token via Authorization: Bearer header. Returns
      [{relative_path, session_uri}] for the iOS client to upload against.

  GET  /scenes/by-bundle/{bundle_id}
      Read scene state for a bundle the caller owns. Auth: Firebase ID token.
      Returns scene status, result_uri, missing_paths, and timestamps. The
      smoke tool polls this endpoint after upload to observe state transitions.

Run locally (from services/api-public/):
  uvicorn server:app --reload --port 8080

Environment variables:
  ENVIRONMENT         — set to "production" to enable startup env-var
                        validation. Unset or any other value → silent
                        in-memory fallbacks (local dev / tests).
  FIRESTORE_PROJECT   — GCP project for Firestore upload_sessions and scenes
                        collections; absent → in-memory repositories
  GCS_CAPTURES_BUCKET — bucket name for capture blobs; used when minting
                        GCS resumable session URIs

Consumed by: the iOS capture app and integration tests.
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

from fastapi import FastAPI, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# Ensure local packages are importable in dev without a virtualenv install.
_repo_root = Path(__file__).resolve().parents[2]
for _pkg in ("packages/schemas", "packages/api-core"):
    _p = str(_repo_root / _pkg)
    if _p not in sys.path:
        sys.path.insert(0, _p)

from auth import TokenVerifier, NullTokenVerifier, TokenVerificationError  # noqa: E402
from roomstudio_api_core.upload_session_repo import (  # noqa: E402
    UploadSessionRepository,
    InMemoryUploadSessionRepository,
    validate_manifest_path,
    gcs_mint_resumable_uri,
)
from roomstudio_api_core.scene_read_repo import (  # noqa: E402
    SceneReadRepository,
    InMemorySceneReadRepository,
    SceneNotFoundError,
)


# ---------------------------------------------------------------------------
# Startup validation
# ---------------------------------------------------------------------------

_PRODUCTION_REQUIRED_VARS: tuple[str, ...] = (
    "FIRESTORE_PROJECT",
    "GCS_CAPTURES_BUCKET",
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
    title="roomstudio-api-public",
    description="Public client-facing API. Firebase-authenticated. Hosts upload_session and future client endpoints.",
    version="0.1.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class UploadSessionRequest(BaseModel):
    """Body for POST /captures/{bundle_id}/upload_session."""
    manifest: list[dict]         # [{relative_path, expected_size_bytes}]
    fcm_token: Optional[str] = None


class UploadSessionEntry(BaseModel):
    """One entry in the upload_session response."""
    relative_path: str
    session_uri: str


# ---------------------------------------------------------------------------
# Dependency instances — lazy-initialized from env vars on first use.
# ---------------------------------------------------------------------------

_token_verifier: Optional[TokenVerifier] = None
_upload_session_repo: Optional[UploadSessionRepository] = None
_scene_read_repo: Optional[SceneReadRepository] = None

_GCS_CAPTURES_BUCKET: str = os.environ.get("GCS_CAPTURES_BUCKET", "roomstudio-captures")


def _get_token_verifier() -> TokenVerifier:
    global _token_verifier
    if _token_verifier is None:
        if os.environ.get("ENVIRONMENT") == "production":
            from auth import FirebaseTokenVerifier
            _token_verifier = FirebaseTokenVerifier()
            logger.info("Using FirebaseTokenVerifier")
        else:
            _token_verifier = NullTokenVerifier()
            logger.info("ENVIRONMENT != production — using NullTokenVerifier")
    return _token_verifier


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


def _get_scene_read_repo() -> SceneReadRepository:
    global _scene_read_repo
    if _scene_read_repo is None:
        project = os.environ.get("FIRESTORE_PROJECT")
        if project:
            from roomstudio_api_core.scene_read_repo import FirestoreSceneReadRepository
            _scene_read_repo = FirestoreSceneReadRepository(project=project)
            logger.info("Using Firestore SceneReadRepository")
        else:
            _scene_read_repo = InMemorySceneReadRepository()
            logger.info("FIRESTORE_PROJECT unset — using in-memory SceneReadRepository")
    return _scene_read_repo


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health", summary="Liveness probe")
def health() -> JSONResponse:
    """Always returns {"status": "ok"} with HTTP 200."""
    return JSONResponse(status_code=200, content={"status": "ok"})


@app.post(
    "/captures/{bundle_id}/upload_session",
    summary="Mint GCS resumable session URIs for an iOS capture upload",
)
async def create_upload_session(
    bundle_id: str,
    req: UploadSessionRequest,
    authorization: str = Header(...),
) -> JSONResponse:
    """Mint GCS resumable session URIs for each entry in the client manifest.

    Auth: Firebase ID token in Authorization: Bearer <token>.

    Request body:
      manifest: [{relative_path: str, expected_size_bytes: int}]
      fcm_token: str | null   (FCM registration token for upload-incomplete push)

    Response (200): [{relative_path, session_uri}]

    Idempotent: repeated calls with the same {bundle_id, manifest paths}
    return the stored URIs without minting new ones.

    Errors:
      400 invalid_bundle_id   — bundle_id is not a UUIDv4
      400 invalid_manifest    — a manifest entry has a bad path
      400 manifest_empty      — manifest has no entries
      401 missing_token       — Authorization header absent or malformed
      403 forbidden           — JWT uid does not match the stored user_id for
                                this bundle_id (another user's upload)
    """
    # 1. Verify Firebase ID token.
    if not authorization.startswith("Bearer "):
        return JSONResponse(
            status_code=401,
            content={"error": "missing_token", "detail": "Authorization: Bearer <token> required"},
        )
    token = authorization[len("Bearer "):]
    try:
        user_id = _get_token_verifier().verify(token)
    except TokenVerificationError as exc:
        return JSONResponse(
            status_code=401,
            content={"error": "invalid_token", "detail": str(exc)},
        )

    # 2. Validate bundle_id is a UUIDv4.
    try:
        val = uuid.UUID(bundle_id, version=4)
        if str(val) != bundle_id:
            raise ValueError("not canonical form")
    except ValueError:
        return JSONResponse(
            status_code=400,
            content={"error": "invalid_bundle_id", "detail": f"{bundle_id!r} is not a UUIDv4"},
        )

    # 3. Validate manifest.
    if not req.manifest:
        return JSONResponse(
            status_code=400,
            content={"error": "manifest_empty", "detail": "manifest must have at least one entry"},
        )
    for entry in req.manifest:
        path = entry.get("relative_path", "")
        err = validate_manifest_path(path)
        if err:
            return JSONResponse(
                status_code=400,
                content={"error": "invalid_manifest", "detail": err},
            )

    # 4. Check user_id ownership — 403 if another user already claimed this bundle_id.
    upload_repo = _get_upload_session_repo()
    stored_uid = upload_repo.get_user_id(bundle_id)
    if stored_uid is not None and stored_uid != user_id:
        return JSONResponse(
            status_code=403,
            content={
                "error": "forbidden",
                "detail": "bundle_id is owned by a different user",
            },
        )

    # 5. Mint (or retrieve stored) session URIs.
    try:
        bucket = os.environ.get("GCS_CAPTURES_BUCKET", _GCS_CAPTURES_BUCKET)
        session_entries = upload_repo.create_or_get(
            bundle_id=bundle_id,
            user_id=user_id,
            manifest=req.manifest,
            fcm_token=req.fcm_token,
            mint_uri_fn=gcs_mint_resumable_uri,
            bucket=bucket,
        )
    except Exception as exc:
        logger.exception("Failed to mint upload session for bundle_id=%s", bundle_id)
        return JSONResponse(
            status_code=500,
            content={"error": "session_mint_failed", "detail": str(exc)},
        )

    return JSONResponse(status_code=200, content=session_entries)


@app.get(
    "/scenes/by-bundle/{bundle_id}",
    summary="Read scene state for a bundle the caller owns",
)
async def get_scene_by_bundle(
    bundle_id: str,
    authorization: str = Header(...),
) -> JSONResponse:
    """Return the Scene record for bundle_id.

    Auth: Firebase ID token in Authorization: Bearer <token>. The requesting
    UID must match scene.user_id (ownership check).

    Response (200):
      {scene_id, bundle_id, status, result_uri, missing_paths, created_at, updated_at}

    status is body-only — a scene in 'failed' or 'failed_incomplete' returns
    HTTP 200. 404 is reserved for "no scene exists for this bundle_id."

    Errors:
      400 invalid_bundle_id   — bundle_id is not a UUIDv4
      401 missing_token       — Authorization header absent or malformed
      401 invalid_token       — JWT failed verification
      403 forbidden           — JWT uid does not match scene.user_id
      403 forbidden           — scene.user_id is None (scene has no owner)
      404 not_found           — no scene exists for this bundle_id
    """
    # 1. Verify Firebase ID token.
    if not authorization.startswith("Bearer "):
        return JSONResponse(
            status_code=401,
            content={"error": "missing_token", "detail": "Authorization: Bearer <token> required"},
        )
    token = authorization[len("Bearer "):]
    try:
        user_id = _get_token_verifier().verify(token)
    except TokenVerificationError as exc:
        return JSONResponse(
            status_code=401,
            content={"error": "invalid_token", "detail": str(exc)},
        )

    # 2. Validate bundle_id is a UUIDv4.
    try:
        val = uuid.UUID(bundle_id, version=4)
        if str(val) != bundle_id:
            raise ValueError("not canonical form")
    except ValueError:
        return JSONResponse(
            status_code=400,
            content={"error": "invalid_bundle_id", "detail": f"{bundle_id!r} is not a UUIDv4"},
        )

    # 3. Look up the scene.
    scene_repo = _get_scene_read_repo()
    scene = scene_repo.get_by_bundle_id(bundle_id)
    if scene is None:
        return JSONResponse(
            status_code=404,
            content={"error": "not_found", "detail": f"No scene found for bundle_id {bundle_id!r}"},
        )

    # 4. Authorization: caller must own the scene.
    if scene.user_id is None:
        logger.warning(
            "Scene %s for bundle_id %s has no user_id — possible ingest bug",
            scene.scene_id,
            bundle_id,
        )
        return JSONResponse(
            status_code=403,
            content={"error": "forbidden", "detail": "scene has no owner"},
        )
    if scene.user_id != user_id:
        return JSONResponse(
            status_code=403,
            content={"error": "forbidden", "detail": "bundle_id is owned by a different user"},
        )

    # 5. Return scene state. last_error is server-side only — excluded per decision 0019.
    return JSONResponse(
        status_code=200,
        content={
            "scene_id": scene.scene_id,
            "bundle_id": scene.bundle_id,
            "status": scene.status.value,
            "result_uri": scene.result_uri,
            "missing_paths": scene.missing_paths,
            "created_at": scene.created_at.isoformat(),
            "updated_at": scene.updated_at.isoformat(),
        },
    )
