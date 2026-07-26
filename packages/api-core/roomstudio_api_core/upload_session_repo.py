"""Upload session storage and GCS resumable URI minting.

When an iOS client calls POST /captures/{bundle_id}/upload_session, the
server mints one GCS resumable session URI per manifest entry and stores
the record in Firestore (or in-memory for tests). The client uses these
URIs directly with URLSession background upload tasks.

Resumable session URIs are valid for 7 days per GCS docs. The Firestore
record has a matching 7-day TTL (Firestore TTL policy on created_at field).

UploadSessionRepository interface:
  create_or_get(bundle_id, user_id, manifest, fcm_token, *, mint_uri_fn)
    → list[{relative_path, session_uri}]

  get_user_id(bundle_id) → str | None
    Returns the stored user_id for a bundle_id, or None if no record exists.
    Used by the endpoint to 403 on user_id mismatch before minting new URIs.

Implementations:
  InMemoryUploadSessionRepository — tests; no external dependencies
  FirestoreUploadSessionRepository — production

The GCS resumable URI minting is injectable (mint_uri_fn) so tests can
substitute a fake without google-cloud-storage installed.

Consumers: services/api-public (POST /captures/{bundle_id}/upload_session),
           services/api-internal (_handle_failed_incomplete FCM token lookup).
"""
from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# Upper bound on concurrent mint_uri_fn calls in _mint_all. Each mint is one
# small HTTP POST to GCS; the bound keeps a large manifest from monopolising
# the service's worker threads. Read per call so tests can override the env.
_MINT_CONCURRENCY_ENV = "UPLOAD_SESSION_MINT_CONCURRENCY"
_MINT_CONCURRENCY_DEFAULT = 16

# Each manifest entry from the client.
ManifestEntry = dict  # {"relative_path": str, "expected_size_bytes": int}
# Each element of the response list.
SessionEntry = dict   # {"relative_path": str, "session_uri": str}

# Type for the GCS URI minter: (bucket, blob_path, size_bytes) → session_uri
UriMintFn = Callable[[str, str, int], str]


# ---------------------------------------------------------------------------
# Path validation
# ---------------------------------------------------------------------------

def validate_manifest_path(path: str) -> str | None:
    """Return an error message if path is not a valid relative blob path, else None.

    Valid: non-empty, no leading slash, no gs:// prefix, no .. traversal.
    """
    if not path:
        return "path must not be empty"
    if path.startswith("/"):
        return f"path must be relative (no leading slash): {path!r}"
    if path.startswith("gs://"):
        return f"path must be relative (not a gs:// URI): {path!r}"
    parts = path.split("/")
    if ".." in parts:
        return f"path must not contain '..': {path!r}"
    return None


# ---------------------------------------------------------------------------
# Minting
# ---------------------------------------------------------------------------

def _mint_concurrency() -> int:
    """Current mint concurrency bound (>= 1)."""
    try:
        return max(1, int(os.environ.get(_MINT_CONCURRENCY_ENV,
                                         _MINT_CONCURRENCY_DEFAULT)))
    except ValueError:
        return _MINT_CONCURRENCY_DEFAULT


def _mint_all(
    bundle_id: str,
    manifest: list[ManifestEntry],
    bucket: str,
    mint_uri_fn: UriMintFn,
) -> list[SessionEntry]:
    """Mint one session URI per manifest entry, in manifest order.

    Minting runs on a bounded thread pool: each mint is an independent HTTP
    round trip to GCS, and a serial loop scales linearly with manifest size —
    a real 878-path LiDAR manifest took ~80 s serial, past the iOS client's
    60 s request timeout, so the client re-POSTed and the server ran the full
    mint twice (2026-07-26). The pool keeps the largest realistic manifest
    inside a few seconds.

    Error semantics match the old serial loop: the first mint failure aborts
    the call (remaining mints are cancelled where possible) and nothing is
    stored by the caller. Already-minted resumable sessions are simply
    abandoned — GCS expires them after 7 days; they grant nothing by
    themselves.
    """
    if not manifest:
        return []

    def mint(entry: ManifestEntry) -> SessionEntry:
        return {
            "relative_path": entry["relative_path"],
            "session_uri": mint_uri_fn(
                bucket,
                f"captures/{bundle_id}/{entry['relative_path']}",
                entry.get("expected_size_bytes", 0),
            ),
        }

    workers = min(_mint_concurrency(), len(manifest))
    if workers == 1:
        return [mint(entry) for entry in manifest]

    executor = ThreadPoolExecutor(max_workers=workers)
    try:
        futures = [executor.submit(mint, entry) for entry in manifest]
        try:
            return [f.result() for f in futures]
        except BaseException:
            executor.shutdown(wait=False, cancel_futures=True)
            raise
    finally:
        executor.shutdown(wait=True)


# ---------------------------------------------------------------------------
# Abstract interface
# ---------------------------------------------------------------------------

class UploadSessionRepository(ABC):
    """Interface for upload session persistence and URI minting."""

    @abstractmethod
    def get_user_id(self, bundle_id: str) -> Optional[str]:
        """Return the stored Firebase UID for bundle_id, or None if no record."""

    @abstractmethod
    def create_or_get(
        self,
        bundle_id: str,
        user_id: str,
        manifest: list[ManifestEntry],
        fcm_token: Optional[str],
        *,
        mint_uri_fn: UriMintFn,
        bucket: str,
    ) -> list[SessionEntry]:
        """Return session URIs for each manifest entry.

        If a record already exists for bundle_id with the same manifest paths,
        return the stored URIs (idempotent). If no record exists, mint new
        session URIs via mint_uri_fn, store the record, and return.

        Caller must verify user_id before calling (403 on mismatch).
        """


# ---------------------------------------------------------------------------
# In-memory implementation (tests)
# ---------------------------------------------------------------------------

class InMemoryUploadSessionRepository(UploadSessionRepository):
    """In-memory upload session store. For tests only."""

    def __init__(self) -> None:
        # bundle_id → {user_id, fcm_token, manifest, session_entries, created_at}
        self._store: dict[str, dict] = {}

    def get_user_id(self, bundle_id: str) -> Optional[str]:
        record = self._store.get(bundle_id)
        return record["user_id"] if record else None

    def create_or_get(
        self,
        bundle_id: str,
        user_id: str,
        manifest: list[ManifestEntry],
        fcm_token: Optional[str],
        *,
        mint_uri_fn: UriMintFn,
        bucket: str,
    ) -> list[SessionEntry]:
        existing = self._store.get(bundle_id)
        if existing:
            existing_paths = {e["relative_path"] for e in existing["manifest"]}
            new_paths = {e["relative_path"] for e in manifest}
            if existing_paths == new_paths:
                return existing["session_entries"]

        session_entries = _mint_all(bundle_id, manifest, bucket, mint_uri_fn)
        self._store[bundle_id] = {
            "user_id": user_id,
            "fcm_token": fcm_token,
            "manifest": manifest,
            "session_entries": session_entries,
            "created_at": datetime.now(tz=timezone.utc),
        }
        return session_entries

    def get_fcm_token(self, bundle_id: str) -> Optional[str]:
        """Return the stored FCM token for bundle_id, or None."""
        record = self._store.get(bundle_id)
        return record.get("fcm_token") if record else None


# ---------------------------------------------------------------------------
# Firestore implementation (production)
# ---------------------------------------------------------------------------

class FirestoreUploadSessionRepository(UploadSessionRepository):
    """Firestore-backed upload session repository.

    Collection: 'upload_sessions'. Document id = bundle_id.
    TTL policy must be set on the 'created_at' field (7-day TTL) in the
    GCP console or via infra/eventarc_setup.sh.

    google.cloud.firestore is imported lazily.
    """

    COLLECTION = "upload_sessions"

    def __init__(self, project: Optional[str] = None) -> None:
        from google.cloud import firestore as _fs  # deferred

        self._db = _fs.Client(project=project)

    def _doc_ref(self, bundle_id: str):
        return self._db.collection(self.COLLECTION).document(bundle_id)

    def get_user_id(self, bundle_id: str) -> Optional[str]:
        doc = self._doc_ref(bundle_id).get()
        if not doc.exists:
            return None
        return doc.to_dict().get("user_id")

    def get_fcm_token(self, bundle_id: str) -> Optional[str]:
        doc = self._doc_ref(bundle_id).get()
        if not doc.exists:
            return None
        return doc.to_dict().get("fcm_token")

    def create_or_get(
        self,
        bundle_id: str,
        user_id: str,
        manifest: list[ManifestEntry],
        fcm_token: Optional[str],
        *,
        mint_uri_fn: UriMintFn,
        bucket: str,
    ) -> list[SessionEntry]:
        ref = self._doc_ref(bundle_id)
        doc = ref.get()
        if doc.exists:
            data = doc.to_dict()
            stored_paths = {e["relative_path"] for e in data.get("manifest", [])}
            new_paths = {e["relative_path"] for e in manifest}
            if stored_paths == new_paths:
                return data["session_entries"]

        session_entries = _mint_all(bundle_id, manifest, bucket, mint_uri_fn)
        ref.set({
            "user_id": user_id,
            "fcm_token": fcm_token,
            "manifest": manifest,
            "session_entries": session_entries,
            "created_at": datetime.now(tz=timezone.utc),
        })
        return session_entries


# ---------------------------------------------------------------------------
# GCS resumable session URI minter (production)
# ---------------------------------------------------------------------------

def gcs_mint_resumable_uri(bucket: str, blob_path: str, size_bytes: int) -> str:
    """Initiate a GCS resumable upload session and return the session URI.

    The URI is valid for 7 days per GCS docs. The iOS client uses it directly
    with URLSession background tasks (PUT requests with the resumable URI).

    google.auth and google.auth.transport.requests are imported lazily.
    """
    import google.auth  # deferred
    import google.auth.transport.requests  # deferred

    credentials, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/devstorage.read_write"]
    )
    authed_session = google.auth.transport.requests.AuthorizedSession(credentials)

    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "X-Upload-Content-Type": "application/octet-stream",
    }
    if size_bytes:
        headers["X-Upload-Content-Length"] = str(size_bytes)

    resp = authed_session.post(
        f"https://storage.googleapis.com/upload/storage/v1/b/{bucket}/o"
        f"?uploadType=resumable&name={blob_path}",
        headers=headers,
        json={"name": blob_path, "contentType": "application/octet-stream"},
    )
    resp.raise_for_status()
    return resp.headers["Location"]
