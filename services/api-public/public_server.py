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

  GET  /scenes/{scene_id}/conversation
      Conversation meta + the last ~50 turns for the caller's conversation
      on a ready scene (decision 0058). 200-empty when no conversation
      exists; 409 scene_not_ready until ready. Consumer: the web app.

  DELETE /account
      Erase the caller's account: every scene, conversation, upload session,
      mint-quota record, GCS capture and perception artifact, and finally
      the Firebase user itself (decision 0095). Auth: Firebase ID token; the
      token's uid IS the target — there is no way to delete anyone else.
      Idempotent and resumable; 202 means "call again", not "corrupt".
      Consumers: the web account menu, and the iOS app when it grows one.

  POST /scenes/{scene_id}/conversation/messages
      One conversation turn. Body {text, client_msg_id}; the response IS
      the stream: text/event-stream with events delta/done/error and
      ": ping" comments during model silence. Everything checkable
      pre-generation returns the JSON {error, detail} contract; once
      streaming starts, failures travel as a terminal `error` event.
      Consumer: the web app's composer.

Run locally (from services/api-public/):
  uvicorn public_server:app --reload --port 8080

Environment variables:
  ENVIRONMENT         — set to "production" to enable startup env-var
                        validation. Unset or any other value → silent
                        in-memory fallbacks (local dev / tests).
  FIRESTORE_PROJECT   — GCP project for Firestore upload_sessions, scenes,
                        and conversations collections; absent → in-memory
                        repositories
  GCS_CAPTURES_BUCKET — bucket name for capture blobs; used when minting
                        GCS resumable session URIs, and swept by DELETE
                        /account
  PERCEPTION_OUTPUTS_BUCKET
                      — bucket holding scenes/{id}/** perception artifacts.
                        Read only by DELETE /account (the assets route uses
                        each scene's recorded result_uri instead). Required
                        in production: without it, deletion would silently
                        leave every reconstruction behind.
  ANTHROPIC_API_KEY   — Anthropic API key for the conversation guest model
                        (production: Secret Manager via Cloud Run
                        --set-secrets). Absent in dev → the conversation
                        route degrades to an in-stream model_unavailable
                        error; everything else works.
  GUEST_MODEL         — guest model id (default claude-sonnet-5)
  GUEST_DAILY_TURNS   — per-conversation daily turn quota (default 100)

Consumed by: the iOS capture app, the web app, and integration tests.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, Optional

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
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from auth import TokenVerifier, NullTokenVerifier, TokenVerificationError
from conversation_repo import (
    ConversationRepository,
    InMemoryConversationRepository,
    TurnRecord,
)
from guest_prompt import PROMPT_VERSION, build_system_prompt, telemetry_flags
from scene_facts import cached_scene_facts, render_facts_block

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
    ForeignBundleError,
    MintRateLimitedError,
    gcs_mint_resumable_uri,
)
from roomstudio_api_core.manifest_validation import validate_manifest  # noqa: E402
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
    "ANTHROPIC_API_KEY",  # conversation guest model (Secret Manager-mounted)
    # Required, not defaulted: a wrong-or-absent outputs bucket makes DELETE
    # /account report success while every reconstruction survives (0095).
    # Fail at startup instead.
    "PERCEPTION_OUTPUTS_BUCKET",
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

# CORS for browser clients (the web app). Off unless CORS_ALLOWED_ORIGINS is
# set — a comma-separated origin list (see infra/api-public.env.yaml). Native
# clients (iOS) don't send Origin and are unaffected. No credentials mode:
# auth is the Bearer header, not cookies.
_cors_origins = [
    o.strip()
    for o in os.environ.get("CORS_ALLOWED_ORIGINS", "").split(",")
    if o.strip()
]
if _cors_origins:
    from fastapi.middleware.cors import CORSMiddleware

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
        allow_credentials=False,
    )
    logger.info("CORS enabled for origins: %s", _cors_origins)


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


class AccountDeleteRequest(BaseModel):
    """Body for DELETE /account.

    confirm_user_id must equal the token's uid. It is not a security control
    — the verified token already is one — it is an ACCIDENT control: an
    irreversible whole-account erase should be impossible to trigger by a
    client bug that fires the wrong request, and echoing your own uid back is
    something only deliberate code does.
    """
    confirm_user_id: str


# ---------------------------------------------------------------------------
# Dependency instances — lazy-initialized from env vars on first use.
# ---------------------------------------------------------------------------

_token_verifier: Optional[TokenVerifier] = None
_upload_session_repo: Optional[UploadSessionRepository] = None
_scene_read_repo: Optional[SceneReadRepository] = None

_GCS_CAPTURES_BUCKET: str = os.environ.get("GCS_CAPTURES_BUCKET", "roomstudio-captures")

# Per-UID daily mint quota for /upload_session (gap b, decisions 0015/0018).
# One unit = one call that actually mints GCS session URIs; idempotent
# replays are free. Sizing: the heaviest observed developer day (full smoke
# run + several real captures + retries) stays under ~25 mints; 50 bounds a
# runaway client or a single hostile UID without ever touching real use.
# Module-level so tests can patch it, mirroring GUEST_DAILY_TURNS.
UPLOAD_DAILY_MINTS = int(os.environ.get("UPLOAD_SESSION_DAILY_MINTS", "50"))


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


_account_deleter = None


def _get_account_deleter():
    """AccountDeleter over live Firestore/GCS/Firebase Auth, or None when the
    service is running without Firestore (local dev, tests). The route turns
    None into a 503 rather than pretending to delete anything."""
    global _account_deleter
    if _account_deleter is None:
        project = os.environ.get("FIRESTORE_PROJECT")
        if not project:
            return None
        from google.cloud import firestore as _fs  # deferred
        from google.cloud import storage as _storage  # deferred
        import firebase_admin  # deferred
        from firebase_admin import auth as _fb_auth  # deferred

        try:
            firebase_admin.get_app()
        except ValueError:
            firebase_admin.initialize_app()

        from account_deletion import AccountDeleter

        _account_deleter = AccountDeleter(
            firestore_client=_fs.Client(project=project),
            storage_client=_storage.Client(project=project),
            auth_client=_fb_auth,
            captures_bucket=_GCS_CAPTURES_BUCKET,
            outputs_bucket=os.environ["PERCEPTION_OUTPUTS_BUCKET"],
        )
        logger.info("AccountDeleter ready")
    return _account_deleter


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

    def fetch_optional(self, gs_uri: str) -> bytes | None:
        """fetch(), except a missing object returns None instead of raising.

        Exists for blobs whose ABSENCE is a meaningful state — shell.json
        (decision 0066: absent = not yet; the client keeps its grace
        window). Non-404 failures still raise ManifestFetchError."""
        from google.cloud import storage  # deferred
        from google.cloud.exceptions import NotFound

        try:
            bucket, path = _split_gs_uri(gs_uri)
            return storage.Client().bucket(bucket).blob(path).download_as_bytes()
        except NotFound:
            return None
        except Exception as exc:
            raise ManifestFetchError(f"fetch failed for {gs_uri}: {exc}") from exc


class InMemoryManifestFetcher:
    """Test/dev fetcher: serves from a settable {gs_uri: bytes} store."""

    def __init__(self, store: Optional[dict] = None) -> None:
        self.store: dict[str, bytes] = dict(store or {})

    def fetch(self, gs_uri: str) -> bytes:
        if gs_uri not in self.store:
            raise ManifestFetchError(f"no such manifest in store: {gs_uri}")
        return self.store[gs_uri]

    def fetch_optional(self, gs_uri: str) -> bytes | None:
        return self.store.get(gs_uri)


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
# Conversation stage 1 (decision 0058): config + guest model seam
# ---------------------------------------------------------------------------

# Env-configured knobs. Module-level so tests can patch them.
GUEST_MODEL = os.environ.get("GUEST_MODEL", "claude-sonnet-5")
GUEST_DAILY_TURNS = int(os.environ.get("GUEST_DAILY_TURNS", "100"))

# Cost bounds (decision 0058 "Cost" — worst-case per-scene-daily spend is
# closed-form from these):
GUEST_MESSAGE_MAX_CHARS = 2000     # request body text ceiling
GUEST_HISTORY_TURNS = 20           # model context window: last N turns verbatim
GUEST_MAX_TOKENS = 250             # generous backstop — truncating the guest
                                   # mid-sentence is worse than a long beat
GUEST_MODEL_TIMEOUT_S = 60.0       # model call wall-clock cap
# The reservation TTL MUST exceed the full 120 s request envelope (60 s model
# cap + shield drain + persist margin): a lease expiring under a legitimate
# in-flight turn re-admits parallel generation through the mechanism that
# closed it (decision 0058; lease-expiry-vs-live-holder history: 0011/0012).
CONVERSATION_RESERVATION_TTL_S = 150
SSE_PING_INTERVAL_S = 15.0         # ": ping" comment cadence during silence
CONVERSATION_GET_TURN_LIMIT = 50

# The 429 budget_exhausted guest line: server-authored, fixed, in voice, and
# time-vague on purpose — "later", never "tomorrow", so voice never promises
# a boundary the mechanism doesn't keep (resets_at carries the mechanism).
GUEST_REST_LINE = (
    "We've talked a lot today, and I want to keep doing right by this room — "
    "let's pick it up again a little later."
)


class GuestModelError(Exception):
    """A guest model call failed. `code` is OUR error vocabulary — the SSE
    error event carries it; upstream provider details stay in logs."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(detail or code)
        self.code = code


class AnthropicGuestStreamer:
    """Production guest streamer: Claude via the Anthropic SDK.

    Yields {"type": "delta", "text": ...} chunks, then one
    {"type": "final", "stop_reason": ..., "usage": {...}}.

    ZERO tools on the call — read-only is architectural, not charter
    (decision 0058). Thinking is explicitly disabled: claude-sonnet-5 runs
    adaptive thinking by default when the field is omitted, and max_tokens
    caps thinking + speech together — an invisible thought would spend the
    guest's 250-token beat budget and truncate the reply. No sampling params
    (rejected by the model family).
    """

    def __init__(self) -> None:
        self._client = None

    def _get_client(self):
        if self._client is None:
            import anthropic  # deferred: not needed by tests

            self._client = anthropic.AsyncAnthropic()
        return self._client

    async def stream_turn(
        self,
        *,
        model: str,
        max_tokens: int,
        system: list[dict],
        messages: list[dict],
    ) -> AsyncIterator[dict]:
        import anthropic  # deferred

        try:
            async with self._get_client().messages.stream(
                model=model,
                max_tokens=max_tokens,
                thinking={"type": "disabled"},
                system=system,
                messages=messages,
            ) as stream:
                async for text in stream.text_stream:
                    yield {"type": "delta", "text": text}
                final = await stream.get_final_message()
            usage = final.usage
            yield {
                "type": "final",
                "stop_reason": final.stop_reason or "end_turn",
                "usage": {
                    "input_tokens": usage.input_tokens,
                    "output_tokens": usage.output_tokens,
                    "cache_read_input_tokens": getattr(
                        usage, "cache_read_input_tokens", 0
                    ) or 0,
                    "cache_creation_input_tokens": getattr(
                        usage, "cache_creation_input_tokens", 0
                    ) or 0,
                },
            }
        except anthropic.APIStatusError as exc:
            code = (
                "model_unavailable"
                if exc.status_code == 429 or exc.status_code >= 500
                else "model_error"
            )
            raise GuestModelError(code, str(exc)) from exc
        except anthropic.APIConnectionError as exc:
            raise GuestModelError("model_unavailable", str(exc)) from exc


class NullGuestStreamer:
    """Dev fallback when no ANTHROPIC_API_KEY is configured: fails honestly
    as an in-stream model_unavailable — never a fake guest voice."""

    async def stream_turn(self, **kwargs) -> AsyncIterator[dict]:
        raise GuestModelError(
            "model_unavailable", "no ANTHROPIC_API_KEY configured"
        )
        yield  # pragma: no cover — makes this an async generator

_conversation_repo: Optional[ConversationRepository] = None
_guest_streamer = None

# asyncio keeps only weak references to tasks; the turn task must survive the
# SSE generator being torn down on client disconnect (the shield), so hold a
# strong reference until each task completes.
_conversation_turn_tasks: set[asyncio.Task] = set()


def _get_conversation_repo() -> ConversationRepository:
    global _conversation_repo
    if _conversation_repo is None:
        project = os.environ.get("FIRESTORE_PROJECT")
        if project:
            from conversation_repo import FirestoreConversationRepository

            _conversation_repo = FirestoreConversationRepository(project=project)
            logger.info("Using Firestore ConversationRepository")
        else:
            _conversation_repo = InMemoryConversationRepository()
            logger.info(
                "FIRESTORE_PROJECT unset — using in-memory ConversationRepository"
            )
    return _conversation_repo


def _get_guest_streamer():
    global _guest_streamer
    if _guest_streamer is None:
        if os.environ.get("ANTHROPIC_API_KEY"):
            _guest_streamer = AnthropicGuestStreamer()
            logger.info("Using AnthropicGuestStreamer (model=%s)", GUEST_MODEL)
        else:
            _guest_streamer = NullGuestStreamer()
            logger.info("ANTHROPIC_API_KEY unset — using NullGuestStreamer")
    return _guest_streamer


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


def _turn_to_client_dict(turn: TurnRecord) -> dict:
    """Client-facing turn projection, shared by the conversation GET and the
    stream's `done` event (mirrors _scene_to_client_dict). Internal fields —
    usage, model, prompt_version, facts_version, finish_reason, flags — never
    enter the wire contract."""
    return {
        "turn_index": turn.turn_index,
        "client_msg_id": turn.client_msg_id,
        "user_text": turn.user_text,
        "assistant_text": turn.assistant_text,
        "created_at": turn.created_at.isoformat(),
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


def _validate_uuid4(value: str, error_code: str):
    """400 JSONResponse if value is not canonical UUIDv4, else None."""
    try:
        val = uuid.UUID(value, version=4)
        if str(val) != value:
            raise ValueError("not canonical form")
    except ValueError:
        return JSONResponse(
            status_code=400,
            content={"error": error_code, "detail": f"{value!r} is not a UUIDv4"},
        )
    return None


def _load_owned_ready_scene(scene_id: str, user_id: str):
    """Shared gate for the ready-scene routes (assets + conversation, both
    verbs): fetch → 404, ownership → 403, readiness → 409 scene_not_ready.
    Returns (scene, None) or (None, JSONResponse)."""
    try:
        scene = _get_scene_read_repo().get(scene_id)
    except SceneNotFoundError:
        return None, JSONResponse(
            status_code=404,
            content={"error": "not_found", "detail": f"No scene {scene_id!r}"},
        )

    if scene.user_id is None:
        logger.warning("Scene %s has no user_id — possible ingest bug", scene_id)
        return None, JSONResponse(
            status_code=403,
            content={"error": "forbidden", "detail": "scene has no owner"},
        )
    if scene.user_id != user_id:
        return None, JSONResponse(
            status_code=403,
            content={"error": "forbidden", "detail": "scene is owned by a different user"},
        )

    from roomstudio_api_core.scene import SceneStatus
    if scene.status != SceneStatus.READY or not scene.result_uri:
        return None, JSONResponse(
            status_code=409,
            content={"error": "scene_not_ready", "status": scene.status.value},
        )
    return scene, None


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
    return the stored URIs without minting new ones (and without consuming
    rate-limit quota).

    Manifest rules (gaps c + F3, decisions 0015/0018): every entry carries a
    real expected_size_bytes (>= 1, capped), paths match the capture clients'
    known shapes, exactly one bundle.pb — see
    roomstudio_api_core.manifest_validation for the grammar and caps.

    Errors:
      400 invalid_bundle_id   — bundle_id is not a UUIDv4
      400 invalid_manifest    — a manifest entry has a bad path, a missing/
                                invalid/oversized expected_size_bytes, a
                                duplicate path, or bundle.pb is absent
      400 manifest_empty      — manifest has no entries
      401 missing_token       — Authorization header absent or malformed
      403 forbidden           — JWT uid does not match the stored user_id for
                                this bundle_id (another user's upload); the
                                claim is transactional (gap a), so two
                                concurrent first-mints can never both own it
      429 rate_limited        — the caller's UTC-day mint quota is exhausted
                                (gap b); body carries resets_at, and the
                                Retry-After header the seconds until then
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

    # 3. Validate manifest (structure, sizes, path grammar, caps).
    if not req.manifest:
        return JSONResponse(
            status_code=400,
            content={"error": "manifest_empty", "detail": "manifest must have at least one entry"},
        )
    manifest_err = validate_manifest(req.manifest)
    if manifest_err:
        return JSONResponse(
            status_code=400,
            content={"error": "invalid_manifest", "detail": manifest_err},
        )

    # 4. Mint (or retrieve stored) session URIs. Ownership and the per-UID
    # daily quota are enforced atomically inside the repository (gaps a + b).
    try:
        session_entries = _get_upload_session_repo().create_or_get(
            bundle_id=bundle_id,
            user_id=user_id,
            manifest=req.manifest,
            fcm_token=req.fcm_token,
            mint_uri_fn=gcs_mint_resumable_uri,
            bucket=_GCS_CAPTURES_BUCKET,
            daily_mint_quota=UPLOAD_DAILY_MINTS,
        )
    except ForeignBundleError:
        return JSONResponse(
            status_code=403,
            content={
                "error": "forbidden",
                "detail": "bundle_id is owned by a different user",
            },
        )
    except MintRateLimitedError as exc:
        retry_after_s = max(
            1, int((exc.resets_at - datetime.now(tz=timezone.utc)).total_seconds())
        )
        logger.warning(
            "rate_limited: uid=%s bundle_id=%s daily_mints=%d",
            user_id, bundle_id, UPLOAD_DAILY_MINTS,
        )
        return JSONResponse(
            status_code=429,
            content={
                "error": "rate_limited",
                "detail": (
                    f"daily upload-session mint quota ({UPLOAD_DAILY_MINTS}) "
                    "exhausted for this account"
                ),
                "resets_at": exc.resets_at.isoformat(),
            },
            headers={"Retry-After": str(retry_after_s)},
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


@app.delete("/account", summary="Erase the caller's account and everything in it")
# Plain def for the same event-loop reason as create_upload_session above —
# Firestore queries, GCS deletes and the Firebase Auth call all block.
def delete_account(
    req: AccountDeleteRequest,
    authorization: str = Header(...),
) -> JSONResponse:
    """Delete the authenticated user's account in full (decision 0095).

    THE TOKEN IS THE TARGET. There is no uid path or query parameter, so this
    route cannot be pointed at another account — the worst a stolen token can
    do is what its owner could already do.

    Removes, in this order: GCS capture blobs and perception artifacts →
    conversations (with their turns subcollection, which Firestore does NOT
    cascade) → scenes → upload sessions → the mint-quota record → the
    Firebase Auth user. See account_deletion.py for why that order and not
    the faster-looking one.

    Idempotent and resumable: a second call on an already-deleted account
    finds nothing left and returns 200 with zero counts.

    Request body: {confirm_user_id: <the caller's own uid>} — an accident
    control, not a security one (see AccountDeleteRequest).

    Response (200) — the pass completed, the identity is gone:
      {deleted: true, identity_deleted: true,
       counts: {rooms, conversations, conversation_messages,
                upload_sessions, files}}

    Response (202) — partial; storage errors stopped the pass before any
    Firestore record was touched, so nothing is stranded and the same call
    repeated resumes it:
      {deleted: false, identity_deleted: false, counts: {...},
       detail: "..."}

    Errors:
      400 confirmation_mismatch — confirm_user_id != the token's uid
      401 missing_token / invalid_token
      503 deletion_unavailable  — the service has no Firestore configured
                                  (local dev); never returned in production
    """
    user_id, err = _verify_bearer(authorization)
    if err is not None:
        return err

    if req.confirm_user_id != user_id:
        return JSONResponse(
            status_code=400,
            content={
                "error": "confirmation_mismatch",
                "detail": "confirm_user_id must equal the authenticated uid",
            },
        )

    deleter = _get_account_deleter()
    if deleter is None:
        return JSONResponse(
            status_code=503,
            content={
                "error": "deletion_unavailable",
                "detail": "account deletion requires a configured datastore",
            },
        )

    try:
        report = deleter.delete(user_id)
    except Exception as exc:
        # The user is still signed in and every record they own still exists —
        # a retry re-derives the same plan. Say so rather than implying loss.
        logger.exception("account_deletion failed for uid=%s", user_id)
        return JSONResponse(
            status_code=500,
            content={
                "error": "deletion_failed",
                "detail": f"nothing was left in a partial state; try again ({exc})",
            },
        )

    if not report.complete:
        # errors[] can carry object paths — logged above, never shipped.
        logger.error(
            "account_deletion incomplete uid=%s errors=%s", user_id, report.errors
        )
        return JSONResponse(
            status_code=202,
            content={
                "deleted": False,
                "identity_deleted": False,
                "counts": report.counts(),
                "detail": "some files could not be removed; call again to resume",
            },
        )

    return JSONResponse(
        status_code=200,
        content={
            "deleted": True,
            "identity_deleted": report.identity_deleted,
            "counts": report.counts(),
        },
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
       shell: <verbatim shell.json> | null,
       asset_urls: {<gs_uri>: <signed https url>}, expires_at: <ISO 8601>}

    shell (decisions 0066/0069) is a SIBLING of the manifest, read from
    scenes/{id}/shell.json beside the manifest: null means the shell
    stage hasn't landed yet (the room-shell task runs a beat after ready
    — clients keep a brief grace window); a present document with
    status "unavailable" means it is never coming (keep the grid). The
    shell is passed through VERBATIM and contributes nothing to
    asset_urls — shell_version 2 carries parametric materials, no
    fetchable blobs (0069 removed the texture bake from serving). A
    shell fetch ERROR degrades to null with a log — the optional shell
    never 502s the room.

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

    err = _validate_uuid4(scene_id, "invalid_scene_id")
    if err is not None:
        return err

    scene, err = _load_owned_ready_scene(scene_id, user_id)
    if err is not None:
        return err

    try:
        manifest = json.loads(_get_manifest_fetcher().fetch(scene.result_uri))
    except (ManifestFetchError, ValueError) as exc:
        logger.error("assets: manifest unavailable for scene %s: %s", scene_id, exc)
        return JSONResponse(
            status_code=502,
            content={"error": "upstream_error", "detail": "manifest unavailable"},
        )

    # The room shell (decision 0066): a sibling blob beside the manifest.
    # Absent (None) = the shell stage hasn't landed; a fetch ERROR also
    # degrades to null with a log — the shell is optional and must never
    # take the room down with it.
    shell = None
    shell_uri = scene.result_uri.rsplit("/", 1)[0] + "/shell.json"
    try:
        shell_bytes = _get_manifest_fetcher().fetch_optional(shell_uri)
        if shell_bytes is not None:
            shell = json.loads(shell_bytes)
    except (ManifestFetchError, ValueError) as exc:
        logger.warning("assets: shell fetch degraded to null for scene %s: %s",
                       scene_id, exc)
        shell = None

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
            "shell": shell,
            "asset_urls": asset_urls,
            "expires_at": expires_at.isoformat(),
        },
    )


# ---------------------------------------------------------------------------
# Conversation routes (decision 0058)
# ---------------------------------------------------------------------------

class ConversationMessageRequest(BaseModel):
    """Body for POST /scenes/{scene_id}/conversation/messages."""
    text: str
    client_msg_id: str


def _scene_facts_for(scene):
    """SceneFacts for a ready scene, via the (scene_id, FACTS_VERSION) cache.
    The manifest fetch runs only on a cache miss. Blocking — call off-loop."""
    def _load() -> dict:
        return json.loads(_get_manifest_fetcher().fetch(scene.result_uri))

    return cached_scene_facts(scene.scene_id, _load)


@app.get(
    "/scenes/{scene_id}/conversation",
    summary="Conversation meta + recent turns for a ready scene",
)
# Plain def for the same event-loop reason as create_upload_session above —
# only the streaming POST below needs the async posture.
def get_conversation(
    scene_id: str,
    authorization: str = Header(...),
) -> JSONResponse:
    """Return the caller's conversation on this scene: meta + last ~50 turns.

    Response (200):
      {conversation: {scene_id, turn_count, rested_until|null},
       turns: [{turn_index, client_msg_id, user_text, assistant_text,
                created_at}...]  (ascending, last <=50),
       cursor: {before: <lowest returned turn_index>} | null}

    A scene+user pair with no conversation yet returns 200 with
    turn_count 0 and no turns — not 404. The cursor is defined now for
    pagination; the v1 client may ignore it.

    Errors mirror /scenes/{scene_id}/assets:
      400 invalid_scene_id / 401 / 403 forbidden / 404 not_found /
      409 scene_not_ready (until the scene reaches `ready`)
    """
    user_id, err = _verify_bearer(authorization)
    if err is not None:
        return err
    err = _validate_uuid4(scene_id, "invalid_scene_id")
    if err is not None:
        return err
    scene, err = _load_owned_ready_scene(scene_id, user_id)
    if err is not None:
        return err

    snapshot = _get_conversation_repo().get_conversation(
        scene_id,
        user_id,
        turn_limit=CONVERSATION_GET_TURN_LIMIT,
        daily_quota=GUEST_DAILY_TURNS,
        now=datetime.now(tz=timezone.utc),
    )
    turns = [_turn_to_client_dict(t) for t in snapshot.turns]
    cursor = (
        {"before": snapshot.turns[0].turn_index}
        if snapshot.turns and snapshot.turns[0].turn_index > 0
        else None
    )
    return JSONResponse(
        status_code=200,
        content={
            "conversation": {
                "scene_id": scene_id,
                "turn_count": snapshot.turn_count,
                "rested_until": (
                    snapshot.rested_until.isoformat()
                    if snapshot.rested_until
                    else None
                ),
            },
            "turns": turns,
            "cursor": cursor,
        },
    )


def _sse(event: str, payload: dict) -> bytes:
    return f"event: {event}\ndata: {json.dumps(payload)}\n\n".encode()


_SSE_HEADERS = {
    # SSE must never be buffered or cached between us and the browser.
    "Cache-Control": "no-store",
    "X-Accel-Buffering": "no",
}


async def _replay_stream(turn: TurnRecord) -> AsyncIterator[bytes]:
    """Dedupe replay: the stored turn, never regeneration (decision 0058).
    One full-text delta then done keeps the client's stream path uniform."""
    yield _sse("delta", {"text": turn.assistant_text})
    yield _sse("done", {"turn": _turn_to_client_dict(turn)})


async def _run_guest_turn(
    *,
    queue: asyncio.Queue,
    scene,
    user_id: str,
    client_msg_id: str,
    user_text: str,
    facts,
    history: list[TurnRecord],
) -> None:
    """Drain the model stream, persist the completed turn, feed the SSE
    queue. Runs as an independent task so a client disconnect cannot stop
    generation or persistence (the 0058 shield) — turns exist only
    completed, and a disconnected client refetches by client_msg_id."""
    repo = _get_conversation_repo()
    created_at = datetime.now(tz=timezone.utc)
    parts: list[str] = []
    usage: dict = {}
    stop_reason = "end_turn"

    async def _fail(code: str) -> None:
        # Error path: the turn never happened — release our lease so the
        # composer isn't locked out for the remaining TTL.
        try:
            await asyncio.to_thread(
                repo.release_reservation, scene.scene_id, user_id, client_msg_id
            )
        except Exception:
            logger.exception(
                "conversation: reservation release failed for scene %s",
                scene.scene_id,
            )
        await queue.put(("error", code))

    try:
        messages = []
        for t in history:
            messages.append({"role": "user", "content": t.user_text})
            messages.append({"role": "assistant", "content": t.assistant_text})
        # Third (rolling) cache breakpoint on the newest user message: the
        # cached prefix then covers charter + facts + prior history, so each
        # turn re-reads the whole conversation at cache-read rates
        # (decision 0058 lists this one as a tunable; measured worth it).
        messages.append({
            "role": "user",
            "content": [{
                "type": "text",
                "text": user_text,
                "cache_control": {"type": "ephemeral"},
            }],
        })

        async with asyncio.timeout(GUEST_MODEL_TIMEOUT_S):
            async for event in _get_guest_streamer().stream_turn(
                model=GUEST_MODEL,
                max_tokens=GUEST_MAX_TOKENS,
                system=build_system_prompt(facts),
                messages=messages,
            ):
                if event["type"] == "delta":
                    parts.append(event["text"])
                    await queue.put(("delta", event["text"]))
                elif event["type"] == "final":
                    usage = event["usage"]
                    stop_reason = event["stop_reason"]
    except TimeoutError:
        logger.warning(
            "conversation: model call exceeded %.0fs for scene %s",
            GUEST_MODEL_TIMEOUT_S,
            scene.scene_id,
        )
        await _fail("model_timeout")
        return
    except GuestModelError as exc:
        logger.warning(
            "conversation: guest model failed for scene %s: %s",
            scene.scene_id,
            exc,
        )
        await _fail(exc.code)
        return
    except Exception:
        logger.exception(
            "conversation: unexpected turn failure for scene %s", scene.scene_id
        )
        await _fail("turn_failed")
        return

    assistant_text = "".join(parts)
    if not assistant_text.strip():
        # A stream that produced no speech is a failed turn, not an empty one.
        await _fail("turn_failed")
        return

    # Observe-only telemetry (decision 0058): flags + structured log, never
    # blocking, never failing the turn.
    try:
        flags = telemetry_flags(
            assistant_text,
            render_facts_block(facts),
            [t.user_text for t in history] + [user_text],
        )
    except Exception:
        logger.exception("conversation: telemetry failed (observe-only)")
        flags = []

    try:
        turn = await asyncio.to_thread(
            repo.persist_turn,
            scene.scene_id,
            user_id,
            client_msg_id=client_msg_id,
            user_text=user_text,
            assistant_text=assistant_text,
            created_at=created_at,
            completed_at=datetime.now(tz=timezone.utc),
            facts_version=facts.facts_version,
            prompt_version=PROMPT_VERSION,
            model=GUEST_MODEL,
            usage=usage,
            finish_reason=stop_reason,
            flags=flags,
        )
    except Exception:
        logger.exception(
            "conversation: persist failed for scene %s", scene.scene_id
        )
        await _fail("persist_failed")
        return

    logger.info(
        "conversation_turn scene_id=%s turn_index=%d model=%s prompt_version=%d "
        "facts_version=%d finish_reason=%s output_tokens=%s "
        "cache_read_input_tokens=%s flags=%s",
        scene.scene_id,
        turn.turn_index,
        GUEST_MODEL,
        PROMPT_VERSION,
        facts.facts_version,
        stop_reason,
        usage.get("output_tokens"),
        usage.get("cache_read_input_tokens"),
        ",".join(flags) or "-",
    )
    await queue.put(("done", _turn_to_client_dict(turn)))


async def _turn_stream(
    *,
    scene,
    user_id: str,
    client_msg_id: str,
    user_text: str,
    facts,
    history: list[TurnRecord],
) -> AsyncIterator[bytes]:
    """SSE body: forwards the turn task's events; emits ": ping" during
    model silence. The vocabulary here is OURS (delta/done/error) — a
    transform of the model stream, never a passthrough."""
    queue: asyncio.Queue = asyncio.Queue()
    task = asyncio.create_task(_run_guest_turn(
        queue=queue,
        scene=scene,
        user_id=user_id,
        client_msg_id=client_msg_id,
        user_text=user_text,
        facts=facts,
        history=history,
    ))
    _conversation_turn_tasks.add(task)
    task.add_done_callback(_conversation_turn_tasks.discard)
    try:
        while True:
            try:
                kind, payload = await asyncio.wait_for(
                    queue.get(), timeout=SSE_PING_INTERVAL_S
                )
            except TimeoutError:
                yield b": ping\n\n"
                continue
            if kind == "delta":
                yield _sse("delta", {"text": payload})
            elif kind == "done":
                yield _sse("done", {"turn": payload})
                return
            else:
                yield _sse("error", {"code": payload})
                return
    finally:
        # The shield (decision 0058): on client disconnect the framework
        # tears this generator down (cancellation or GeneratorExit); the turn
        # task above keeps generating and persists on its own. Hold the
        # request open until it finishes — the open request is the only place
        # Cloud Run guarantees CPU. Cancellation may be re-delivered at every
        # await while the enclosing scope unwinds, so swallow it in a bounded
        # loop; the task itself is bounded by the model cap + persist.
        if not task.done():
            deadline = asyncio.get_running_loop().time() + GUEST_MODEL_TIMEOUT_S + 30.0
            while not task.done():
                if asyncio.get_running_loop().time() > deadline:
                    logger.error(
                        "conversation: shield deadline exceeded for scene %s",
                        scene.scene_id,
                    )
                    break
                try:
                    await asyncio.wait_for(asyncio.shield(task), timeout=0.25)
                except (TimeoutError, asyncio.CancelledError):
                    continue
                except Exception:
                    break  # task error already handled inside _run_guest_turn


@app.post(
    "/scenes/{scene_id}/conversation/messages",
    summary="One conversation turn: streamed guest reply (SSE)",
)
# async def — the service's FIRST async route, diverging from the sync-def
# posture recorded on create_upload_session above. A sync handler would hold
# a threadpool slot for the whole streamed turn (up to ~120 s); async holds
# none. The discipline that makes this safe: every blocking call — auth,
# scene fetch, manifest fetch, accept/persist transactions — runs via
# asyncio.to_thread or before the generator starts, so the event loop this
# service was just un-async'd to protect stays unblocked.
async def post_conversation_message(
    scene_id: str,
    req: ConversationMessageRequest,
    authorization: str = Header(...),
):
    """One turn of the read-only room conversation (decision 0058).

    Body: {text: <=2000 chars, client_msg_id: UUID}

    Everything checkable pre-generation returns the JSON {error, detail}
    contract; once streaming starts, failures travel as a terminal `error`
    event. Success: 200 text/event-stream with events
      delta {text} / done {turn} / error {code}
    and ": ping" comments during model silence. `done` carries the same
    client projection as GET (internal fields never on the wire).

    Pre-stream errors:
      400 invalid_scene_id / invalid_client_msg_id / message_empty /
          message_too_long
      401 missing_token / invalid_token
      403 forbidden
      404 not_found
      409 scene_not_ready — scene isn't ready
      409 turn_in_flight  — a live turn holds the reservation (second tab)
      429 budget_exhausted — body {error, guest_line, resets_at}
      502 upstream_error  — manifest unavailable (facts underivable)

    A repeated client_msg_id replays the stored turn verbatim — never
    regeneration; the id is also the client's refetch-confirmation key.
    """
    user_id, err = await asyncio.to_thread(_verify_bearer, authorization)
    if err is not None:
        return err
    err = _validate_uuid4(scene_id, "invalid_scene_id")
    if err is not None:
        return err

    try:
        uuid.UUID(req.client_msg_id)
    except ValueError:
        return JSONResponse(
            status_code=400,
            content={
                "error": "invalid_client_msg_id",
                "detail": f"{req.client_msg_id!r} is not a UUID",
            },
        )
    if not req.text.strip():
        return JSONResponse(
            status_code=400,
            content={"error": "message_empty", "detail": "text must not be empty"},
        )
    if len(req.text) > GUEST_MESSAGE_MAX_CHARS:
        return JSONResponse(
            status_code=400,
            content={
                "error": "message_too_long",
                "detail": f"text exceeds {GUEST_MESSAGE_MAX_CHARS} characters",
            },
        )

    scene, err = await asyncio.to_thread(_load_owned_ready_scene, scene_id, user_id)
    if err is not None:
        return err

    try:
        facts = await asyncio.to_thread(_scene_facts_for, scene)
    except (ManifestFetchError, ValueError) as exc:
        logger.error(
            "conversation: manifest unavailable for scene %s: %s", scene_id, exc
        )
        return JSONResponse(
            status_code=502,
            content={"error": "upstream_error", "detail": "manifest unavailable"},
        )

    repo = _get_conversation_repo()
    outcome = await asyncio.to_thread(
        repo.accept_turn,
        scene_id,
        user_id,
        req.client_msg_id,
        daily_quota=GUEST_DAILY_TURNS,
        reservation_ttl_s=CONVERSATION_RESERVATION_TTL_S,
        now=datetime.now(tz=timezone.utc),
    )

    if outcome.kind == "rested":
        return JSONResponse(
            status_code=429,
            content={
                "error": "budget_exhausted",
                "guest_line": GUEST_REST_LINE,
                "resets_at": outcome.resets_at.isoformat(),
            },
        )
    if outcome.kind == "busy":
        return JSONResponse(
            status_code=409,
            content={
                "error": "turn_in_flight",
                "detail": "a turn is already being answered for this conversation",
            },
        )
    if outcome.kind == "replay":
        return StreamingResponse(
            _replay_stream(outcome.replay_turn),
            media_type="text/event-stream",
            headers=_SSE_HEADERS,
        )

    history = await asyncio.to_thread(
        repo.recent_turns, scene_id, user_id, GUEST_HISTORY_TURNS
    )
    return StreamingResponse(
        _turn_stream(
            scene=scene,
            user_id=user_id,
            client_msg_id=req.client_msg_id,
            user_text=req.text,
            facts=facts,
            history=history,
        ),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )
