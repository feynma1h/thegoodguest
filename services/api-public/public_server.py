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
      Returns scene status, result_uri, missing_paths, and timestamps.
      Consumers: the iOS app's ScenePoller (production polling loop) and the
      smoke tool (tools/upload_test_bundle.py) after upload.

  GET  /scenes?limit=N
      List the caller's scenes, newest first. Auth: Firebase ID token.
      Returns {"scenes": [<same shape as /scenes/by-bundle>]}.
      Consumer: the web app's scene browser.

  GET  /scenes/{scene_id}/assets
      The ready scene's perception manifest plus V4-signed HTTPS URLs for
      its fused objects' splat files (a browser cannot fetch gs:// URIs).
      409 scene_not_ready until the scene reaches `ready`. Auth: Firebase
      ID token + ownership. Consumer: the web app's scene viewer.
      Production prerequisites: the runtime SA needs storage.objectViewer
      on the perception-outputs bucket and iam.serviceAccountTokenCreator
      on itself (V4 signing runs through IAM signBlob — Cloud Run has no
      private key on disk).

Run locally (from services/api-public/):
  uvicorn public_server:app --reload --port 8080

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

import json
import logging
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
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
# original fix; this was missing here.
logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
logger = logging.getLogger(__name__)

from fastapi import FastAPI, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from auth import TokenVerifier, NullTokenVerifier, TokenVerificationError

# Ensure local packages are importable in dev without a virtualenv install.
# Gated off in production, where the packages are pip-installed by the
# Dockerfile and patching sys.path would be redundant.
if os.environ.get("ENVIRONMENT") != "production":
    _repo_root = Path(__file__).resolve().parents[2]
    for _pkg in ("packages/schemas", "packages/api-core"):
        _p = str(_repo_root / _pkg)
        if _p not in sys.path:
            sys.path.insert(0, _p)

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
# Scene-assets dependencies (manifest fetch + URL signing)
# ---------------------------------------------------------------------------

# Signed-URL lifetime. Long enough to load a scene's splats without a
# re-fetch dance; short enough that a leaked URL goes stale within the hour.
_ASSET_URL_TTL_SECONDS = 3600


class ManifestFetchError(Exception):
    """Raised when the perception manifest cannot be fetched from GCS."""


def _split_gs_uri(gs_uri: str) -> tuple[str, str]:
    if not gs_uri.startswith("gs://"):
        raise ValueError(f"expected gs:// URI, got {gs_uri!r}")
    bucket, _, path = gs_uri[5:].partition("/")
    if not bucket or not path:
        raise ValueError(f"malformed gs:// URI {gs_uri!r}")
    return bucket, path


class GcsManifestFetcher:
    """Production manifest fetcher: reads the manifest object from GCS with
    the service's own credentials."""

    def fetch(self, gs_uri: str) -> bytes:
        from google.cloud import storage  # deferred

        try:
            bucket, path = _split_gs_uri(gs_uri)
            return storage.Client().bucket(bucket).blob(path).download_as_bytes()
        except Exception as exc:
            raise ManifestFetchError(f"manifest fetch failed for {gs_uri}: {exc}") from exc


class InMemoryManifestFetcher:
    """Test/dev fetcher: serves from a settable {gs_uri: bytes} store."""

    def __init__(self, store: Optional[dict] = None) -> None:
        self.store: dict[str, bytes] = dict(store or {})

    def fetch(self, gs_uri: str) -> bytes:
        if gs_uri not in self.store:
            raise ManifestFetchError(f"no such manifest in store: {gs_uri}")
        return self.store[gs_uri]


class IamV4UrlSigner:
    """Production signer: V4 signed URLs via IAM signBlob.

    Cloud Run service accounts have no private key on disk, so
    generate_signed_url is given the runtime SA's email + access token,
    which routes signing through the IAM Credentials API. Requires
    roles/iam.serviceAccountTokenCreator granted to the runtime SA on
    itself (deploy-time prerequisite, recorded in CLAUDE.md).
    """

    def __init__(self) -> None:
        import google.auth
        from google.auth.transport import requests as ga_requests
        from google.cloud import storage  # deferred

        self._credentials, _ = google.auth.default()
        self._auth_request = ga_requests.Request()
        self._client = storage.Client()

    def sign(self, gs_uri: str, ttl_seconds: int) -> str:
        from datetime import timedelta

        bucket, path = _split_gs_uri(gs_uri)
        if not self._credentials.valid:
            self._credentials.refresh(self._auth_request)
        return self._client.bucket(bucket).blob(path).generate_signed_url(
            version="v4",
            expiration=timedelta(seconds=ttl_seconds),
            method="GET",
            service_account_email=self._credentials.service_account_email,
            access_token=self._credentials.token,
        )


class UnsignedDevUrlSigner:
    """Test/dev signer: emits the public GCS HTTPS form without a signature.

    Only usable against objects that are actually readable by the caller
    (dev buckets); exists so local dev exercises the full response shape.
    """

    def sign(self, gs_uri: str, ttl_seconds: int) -> str:  # noqa: ARG002
        bucket, path = _split_gs_uri(gs_uri)
        return f"https://storage.googleapis.com/{bucket}/{path}"


_manifest_fetcher = None
_url_signer = None


def _get_manifest_fetcher():
    global _manifest_fetcher
    if _manifest_fetcher is None:
        if os.environ.get("ENVIRONMENT") == "production":
            _manifest_fetcher = GcsManifestFetcher()
            logger.info("Using GcsManifestFetcher")
        else:
            _manifest_fetcher = InMemoryManifestFetcher()
            logger.info("ENVIRONMENT != production — using InMemoryManifestFetcher")
    return _manifest_fetcher


def _get_url_signer():
    global _url_signer
    if _url_signer is None:
        if os.environ.get("ENVIRONMENT") == "production":
            _url_signer = IamV4UrlSigner()
            logger.info("Using IamV4UrlSigner")
        else:
            _url_signer = UnsignedDevUrlSigner()
            logger.info("ENVIRONMENT != production — using UnsignedDevUrlSigner")
    return _url_signer


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

def _scene_to_client_dict(scene) -> dict:
    """Client-facing Scene shape, shared by /scenes/by-bundle and /scenes.

    last_error and invalid_blobs are server-side only — excluded per
    decision 0019."""
    return {
        "scene_id": scene.scene_id,
        "bundle_id": scene.bundle_id,
        "status": scene.status.value,
        "result_uri": scene.result_uri,
        "missing_paths": scene.missing_paths,
        "created_at": scene.created_at.isoformat(),
        "updated_at": scene.updated_at.isoformat(),
    }


def _verify_bearer(authorization: str):
    """Common Bearer-token verification. Returns (user_id, None) on success
    or (None, JSONResponse) with the 401 to return."""
    if not authorization.startswith("Bearer "):
        return None, JSONResponse(
            status_code=401,
            content={"error": "missing_token", "detail": "Authorization: Bearer <token> required"},
        )
    token = authorization[len("Bearer "):]
    try:
        return _get_token_verifier().verify(token), None
    except TokenVerificationError as exc:
        return None, JSONResponse(
            status_code=401,
            content={"error": "invalid_token", "detail": str(exc)},
        )


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
# Plain def (not async): the whole call chain — Firebase verify, Firestore
# reads/writes, GCS session minting — is synchronous/blocking. FastAPI runs
# sync handlers on its threadpool, keeping the event loop free; as async def
# this handler blocked the loop for its full round-trip latency.
def create_upload_session(
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
    user_id, err = _verify_bearer(authorization)
    if err is not None:
        return err

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
        bucket = _GCS_CAPTURES_BUCKET
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
# Plain def for the same event-loop reason as create_upload_session above.
def get_scene_by_bundle(
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
    user_id, err = _verify_bearer(authorization)
    if err is not None:
        return err

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

    # 5. Return scene state.
    return JSONResponse(status_code=200, content=_scene_to_client_dict(scene))


@app.get(
    "/scenes",
    summary="List the caller's scenes, newest first",
)
# Plain def for the same event-loop reason as create_upload_session above.
def list_scenes(
    authorization: str = Header(...),
    limit: int = 50,
) -> JSONResponse:
    """List scenes owned by the authenticated user, newest first.

    Auth: Firebase ID token in Authorization: Bearer <token>. Scoped to
    the token's UID — there is no cross-user listing.

    Query params:
      limit — max scenes returned; default 50, valid range 1..100.

    Response (200): {"scenes": [<same per-scene shape as /scenes/by-bundle>]}
    An authenticated user with no scenes gets 200 {"scenes": []}, not 404.

    Errors:
      400 invalid_limit       — limit outside 1..100
      401 missing_token       — Authorization header absent or malformed
      401 invalid_token       — JWT failed verification

    Consumer: the web app's scene browser.
    """
    user_id, err = _verify_bearer(authorization)
    if err is not None:
        return err

    if not 1 <= limit <= 100:
        return JSONResponse(
            status_code=400,
            content={"error": "invalid_limit", "detail": f"limit must be 1..100, got {limit}"},
        )

    scenes = _get_scene_read_repo().list_by_user(user_id, limit=limit)
    return JSONResponse(
        status_code=200,
        content={"scenes": [_scene_to_client_dict(s) for s in scenes]},
    )


@app.get(
    "/scenes/{scene_id}/assets",
    summary="Perception manifest + signed asset URLs for a ready scene",
)
# Plain def for the same event-loop reason as create_upload_session above.
def get_scene_assets(
    scene_id: str,
    authorization: str = Header(...),
) -> JSONResponse:
    """Return the scene's perception manifest with browser-fetchable URLs.

    The manifest references splat files by gs:// URI, which a browser
    cannot fetch. This endpoint fetches the manifest server-side and signs
    a V4 HTTPS URL (TTL 1h) for each splat referenced by the scene-level
    fused "objects" array (manifest_version 2 — see perception-obj's
    process_receiver docstring for the contract).

    Auth: Firebase ID token; the caller must own the scene.

    Response (200):
      {scene_id, manifest: <verbatim manifest.json>,
       asset_urls: {<gs_uri>: <signed https url>}, expires_at: <ISO 8601>}

    Errors:
      400 invalid_scene_id — scene_id is not a UUIDv4
      401 missing_token / invalid_token
      403 forbidden        — caller does not own the scene / scene unowned
      404 not_found        — no such scene
      409 scene_not_ready  — status != ready (body carries {status});
                             clients poll /scenes/by-bundle until ready
      502 upstream_error   — manifest unreachable/unparseable or signing
                             failed (server-side dependency, retryable)

    Consumer: the web app's scene viewer.
    """
    user_id, err = _verify_bearer(authorization)
    if err is not None:
        return err

    try:
        val = uuid.UUID(scene_id, version=4)
        if str(val) != scene_id:
            raise ValueError("not canonical form")
    except ValueError:
        return JSONResponse(
            status_code=400,
            content={"error": "invalid_scene_id", "detail": f"{scene_id!r} is not a UUIDv4"},
        )

    try:
        scene = _get_scene_read_repo().get(scene_id)
    except SceneNotFoundError:
        return JSONResponse(
            status_code=404,
            content={"error": "not_found", "detail": f"No scene {scene_id!r}"},
        )

    if scene.user_id is None:
        logger.warning("Scene %s has no user_id — possible ingest bug", scene_id)
        return JSONResponse(
            status_code=403,
            content={"error": "forbidden", "detail": "scene has no owner"},
        )
    if scene.user_id != user_id:
        return JSONResponse(
            status_code=403,
            content={"error": "forbidden", "detail": "scene is owned by a different user"},
        )

    from roomstudio_api_core.scene import SceneStatus
    if scene.status != SceneStatus.READY or not scene.result_uri:
        return JSONResponse(
            status_code=409,
            content={"error": "scene_not_ready", "status": scene.status.value},
        )

    try:
        manifest = json.loads(_get_manifest_fetcher().fetch(scene.result_uri))
    except (ManifestFetchError, ValueError) as exc:
        logger.error("assets: manifest unavailable for scene %s: %s", scene_id, exc)
        return JSONResponse(
            status_code=502,
            content={"error": "upstream_error", "detail": "manifest unavailable"},
        )

    # Sign the splats the viewer renders: the scene-level fused objects.
    # (Pre-v2 manifests have no "objects" array and yield no URLs; no such
    # scenes exist with real users, so no compatibility shim.)
    splat_uris = {
        obj["splat_gcs_uri"]
        for obj in manifest.get("objects", [])
        if isinstance(obj, dict) and obj.get("splat_gcs_uri")
    }
    signer = _get_url_signer()
    asset_urls = {}
    try:
        for uri in sorted(splat_uris):
            asset_urls[uri] = signer.sign(uri, _ASSET_URL_TTL_SECONDS)
    except Exception as exc:
        logger.exception("assets: signing failed for scene %s: %s", scene_id, exc)
        return JSONResponse(
            status_code=502,
            content={"error": "upstream_error", "detail": "asset URL signing failed"},
        )

    expires_at = datetime.now(tz=timezone.utc) + timedelta(seconds=_ASSET_URL_TTL_SECONDS)
    return JSONResponse(
        status_code=200,
        content={
            "scene_id": scene_id,
            "manifest": manifest,
            "asset_urls": asset_urls,
            "expires_at": expires_at.isoformat(),
        },
    )
