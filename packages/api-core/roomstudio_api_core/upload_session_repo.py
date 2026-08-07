"""Upload session storage and GCS resumable URI minting.

When an iOS client calls POST /captures/{bundle_id}/upload_session, the
server mints one GCS resumable session URI per manifest entry and stores
the record in Firestore (or in-memory for tests). The client uses these
URIs directly with URLSession background upload tasks.

Resumable session URIs are valid for 7 days per GCS docs. The Firestore
record carries a TTL on created_at (Firestore sweeps promptly once the
timestamp is past — the record only needs to outlive the upload window).

Ownership and admission (pre-launch gaps a + b, decisions 0015/0018):
create_or_get runs a single transaction over the session record AND the
caller's mint-quota document before any GCS mint happens:

  - bundle_id ownership is claimed atomically. The FIRST caller to reach the
    transaction owns the bundle_id forever; a different UID — concurrent or
    later — gets ForeignBundleError (403 at the endpoint). The old
    read-then-write pair allowed two UIDs to interleave and the loser's
    blobs to land under the winner's scene.
  - Idempotent replay (same UID, same path set, entries already stored)
    returns the stored URIs WITHOUT consuming quota — a client retrying a
    timed-out POST must never be rate-limited into a corner.
  - A call that will actually mint charges one unit against the caller's
    UTC-day quota inside the same transaction (the conversation repo's
    day-roll pattern, decision 0058). At the cap it raises
    MintRateLimitedError (429 at the endpoint) before any claim or mint.
    Quota is charged at admission, so a subsequent GCS mint failure burns
    the slot — accepted: mint failures are rare and the cap is generous.
  - Same-UID concurrent mints for one bundle_id remain last-write-wins on
    the stored record (both responses' URIs are real GCS sessions and both
    work); serializing them would need a lease with client-visible 409s the
    deployed iOS retry policy (0038) does not know. Cross-UID exclusion is
    the security property; same-UID overlap is benign duplication.

UploadSessionRepository interface:
  create_or_get(bundle_id, user_id, manifest, fcm_token, *, mint_uri_fn,
                bucket, daily_mint_quota=None, now=None)
    → list[{relative_path, session_uri}]
    Raises ForeignBundleError / MintRateLimitedError per above.

  get_user_id(bundle_id) → str | None
    Returns the stored user_id for a bundle_id, or None if no record exists.
    (Ownership enforcement lives inside create_or_get; this read remains for
    api-internal's ingest-time owner lookup.)

Implementations:
  InMemoryUploadSessionRepository — tests; the semantics oracle
  FirestoreUploadSessionRepository — production; mirrors the in-memory
  semantics inside Firestore transactions

The GCS resumable URI minting is injectable (mint_uri_fn) so tests can
substitute a fake without google-cloud-storage installed.

Consumers: services/api-public (POST /captures/{bundle_id}/upload_session),
           services/api-internal (_handle_failed_incomplete FCM token lookup).
"""
from __future__ import annotations

import logging
import os
import threading
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time as _dt_time, timedelta, timezone
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


class ForeignBundleError(Exception):
    """The bundle_id is already owned by a different UID (403 at the endpoint)."""


class MintRateLimitedError(Exception):
    """The caller's UTC-day mint quota is exhausted (429 at the endpoint).

    resets_at is the next UTC midnight — the moment the day-roll admits the
    caller again."""

    def __init__(self, resets_at: datetime) -> None:
        super().__init__(f"mint quota exhausted; resets at {resets_at.isoformat()}")
        self.resets_at = resets_at


def _utc_day(now: datetime) -> str:
    """UTC calendar day key, mirroring the conversation repo's quota roll."""
    return now.astimezone(timezone.utc).strftime("%Y-%m-%d")


def _next_utc_midnight(now: datetime) -> datetime:
    day_after = now.astimezone(timezone.utc).date() + timedelta(days=1)
    return datetime.combine(day_after, _dt_time.min, tzinfo=timezone.utc)


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
        daily_mint_quota: Optional[int] = None,
        now: Optional[datetime] = None,
    ) -> list[SessionEntry]:
        """Return session URIs for each manifest entry.

        Admission runs atomically over the session record and the caller's
        mint-quota document (module docstring has the full semantics):

          - existing record owned by another UID → ForeignBundleError
          - same UID + same path set + stored entries → replay (no quota)
          - otherwise, with daily_mint_quota set: at the UTC-day cap →
            MintRateLimitedError; else the quota is charged and new session
            URIs are minted via mint_uri_fn and stored.

        daily_mint_quota=None disables quota accounting (dev/tests).
        now is injectable for tests; defaults to the current UTC time.
        """


# ---------------------------------------------------------------------------
# In-memory implementation (tests)
# ---------------------------------------------------------------------------

class InMemoryUploadSessionRepository(UploadSessionRepository):
    """In-memory upload session store. For tests only.

    The semantics oracle for FirestoreUploadSessionRepository: the lock-held
    admission section mirrors the Firestore transaction exactly. Minting runs
    OUTSIDE the lock (like outside the transaction) so the bounded-pool
    overlap invariants stay observable."""

    def __init__(self) -> None:
        # bundle_id → {user_id, fcm_token, manifest, session_entries, created_at}
        self._store: dict[str, dict] = {}
        # user_id → {"day": "YYYY-MM-DD", "count": int}
        self._quota: dict[str, dict] = {}
        self._lock = threading.Lock()

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
        daily_mint_quota: Optional[int] = None,
        now: Optional[datetime] = None,
    ) -> list[SessionEntry]:
        now = now or datetime.now(tz=timezone.utc)
        new_paths = {e["relative_path"] for e in manifest}

        # Admission (mirrors the Firestore transaction).
        with self._lock:
            existing = self._store.get(bundle_id)
            if existing:
                if existing["user_id"] != user_id:
                    raise ForeignBundleError(
                        f"bundle_id {bundle_id!r} is owned by a different user"
                    )
                existing_paths = {e["relative_path"] for e in existing["manifest"]}
                if existing_paths == new_paths and existing["session_entries"]:
                    return existing["session_entries"]

            if daily_mint_quota is not None:
                q = self._quota.get(user_id)
                count = q["count"] if q and q["day"] == _utc_day(now) else 0
                if count >= daily_mint_quota:
                    raise MintRateLimitedError(_next_utc_midnight(now))
                self._quota[user_id] = {"day": _utc_day(now), "count": count + 1}

            if not existing:
                # Claim ownership before minting: a concurrent foreign caller
                # must observe the claim, and a crash mid-mint leaves a record
                # whose empty session_entries routes the retry back here.
                self._store[bundle_id] = {
                    "user_id": user_id,
                    "fcm_token": fcm_token,
                    "manifest": manifest,
                    "session_entries": [],
                    "created_at": now,
                }

        session_entries = _mint_all(bundle_id, manifest, bucket, mint_uri_fn)

        with self._lock:
            record = self._store.get(bundle_id)
            if record and record["user_id"] != user_id:
                raise ForeignBundleError(  # unreachable: ownership never reassigns
                    f"bundle_id {bundle_id!r} is owned by a different user"
                )
            self._store[bundle_id] = {
                "user_id": user_id,
                "fcm_token": fcm_token,
                "manifest": manifest,
                "session_entries": session_entries,
                "created_at": now,
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

    Collections:
      'upload_sessions'    — document id = bundle_id. TTL policy on the
                             'created_at' field (infra/eventarc_setup.sh).
      'upload_mint_quotas' — document id = user_id; {day, count, updated_at}.
                             The UTC-day mint quota (gap b). No TTL needed:
                             one small doc per active user, overwritten on
                             each day roll.

    Admission (ownership claim + quota) runs in ONE transaction spanning
    both documents — see the module docstring. The GCS mints happen outside
    the transaction; a second transaction stores the entries.

    google.cloud.firestore is imported lazily.
    """

    COLLECTION = "upload_sessions"
    QUOTA_COLLECTION = "upload_mint_quotas"

    def __init__(self, project: Optional[str] = None) -> None:
        from google.cloud import firestore as _fs  # deferred

        self._fs = _fs
        self._db = _fs.Client(project=project)

    def _doc_ref(self, bundle_id: str):
        return self._db.collection(self.COLLECTION).document(bundle_id)

    def _quota_ref(self, user_id: str):
        return self._db.collection(self.QUOTA_COLLECTION).document(user_id)

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
        daily_mint_quota: Optional[int] = None,
        now: Optional[datetime] = None,
    ) -> list[SessionEntry]:
        now = now or datetime.now(tz=timezone.utc)
        ref = self._doc_ref(bundle_id)
        quota_ref = self._quota_ref(user_id)
        new_paths = {e["relative_path"] for e in manifest}

        @self._fs.transactional
        def _admit(txn):
            # All reads before any write (Firestore transaction rule).
            snap = ref.get(transaction=txn)
            quota_snap = (
                quota_ref.get(transaction=txn)
                if daily_mint_quota is not None
                else None
            )

            if snap.exists:
                data = snap.to_dict()
                if data.get("user_id") != user_id:
                    return ("foreign", None)
                stored_paths = {
                    e["relative_path"] for e in data.get("manifest", [])
                }
                if stored_paths == new_paths and data.get("session_entries"):
                    return ("replay", data["session_entries"])

            if daily_mint_quota is not None:
                qdoc = quota_snap.to_dict() if quota_snap.exists else None
                count = (
                    int(qdoc.get("count", 0))
                    if qdoc and qdoc.get("day") == _utc_day(now)
                    else 0
                )
                if count >= daily_mint_quota:
                    return ("rate_limited", _next_utc_midnight(now))
                txn.set(quota_ref, {
                    "day": _utc_day(now),
                    "count": count + 1,
                    "updated_at": now,
                })

            if not snap.exists:
                # Atomic ownership claim before any mint. create() fails the
                # transaction if a concurrent caller won the race; the retry
                # re-reads and lands in the owned/replay branches above.
                txn.create(ref, {
                    "user_id": user_id,
                    "fcm_token": fcm_token,
                    "manifest": manifest,
                    "session_entries": [],
                    "created_at": now,
                })
            return ("admitted", None)

        kind, payload = _admit(self._db.transaction())
        if kind == "foreign":
            raise ForeignBundleError(
                f"bundle_id {bundle_id!r} is owned by a different user"
            )
        if kind == "rate_limited":
            raise MintRateLimitedError(payload)
        if kind == "replay":
            return payload

        session_entries = _mint_all(bundle_id, manifest, bucket, mint_uri_fn)

        @self._fs.transactional
        def _store(txn):
            snap = ref.get(transaction=txn)
            if snap.exists and snap.to_dict().get("user_id") != user_id:
                # Unreachable in practice — ownership never reassigns — kept
                # as the mirror of the in-memory oracle's paranoia guard.
                raise ForeignBundleError(
                    f"bundle_id {bundle_id!r} is owned by a different user"
                )
            txn.set(ref, {
                "user_id": user_id,
                "fcm_token": fcm_token,
                "manifest": manifest,
                "session_entries": session_entries,
                "created_at": now,
            })

        _store(self._db.transaction())
        return session_entries


# ---------------------------------------------------------------------------
# GCS resumable session URI minter (production)
# ---------------------------------------------------------------------------

# Per-thread AuthorizedSession cache for gcs_mint_resumable_uri — the
# services/api-internal/gcs_client.py idiom. Before this cache every mint
# call resolved ADC credentials and built a fresh AuthorizedSession (a new
# requests.Session + connection pool + token fetch): a 2,170-path LiDAR
# manifest at UPLOAD_SESSION_MINT_CONCURRENCY=64 OOM-killed the 512 MiB
# api-public instance mid-mint (measured live, RP-8 2026-08-06) and burned
# most of its wall clock on per-call TLS + auth. Per-thread rather than one
# shared session for the same reason as the ingest cache: cross-thread
# safety of the underlying requests.Session is not documented. Bounded by
# the mint pool size; sessions live for the process lifetime.
_mint_thread_local = threading.local()


def _mint_session():
    """Return this thread's cached AuthorizedSession, constructing on first use."""
    session = getattr(_mint_thread_local, "session", None)
    if session is None:
        import google.auth  # deferred
        import google.auth.transport.requests  # deferred

        credentials, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/devstorage.read_write"]
        )
        session = google.auth.transport.requests.AuthorizedSession(credentials)
        _mint_thread_local.session = session
    return session


def gcs_mint_resumable_uri(bucket: str, blob_path: str, size_bytes: int) -> str:
    """Initiate a GCS resumable upload session and return the session URI.

    The URI is valid for 7 days per GCS docs. The iOS client uses it directly
    with URLSession background tasks (PUT requests with the resumable URI).

    X-Upload-Content-Length is ALWAYS set (gap c, decision 0015): GCS then
    rejects any upload whose byte count differs from the declared size, which
    is what makes the manifest's expected_size_bytes an enforced cap rather
    than a hint. Manifest validation guarantees size_bytes >= 1 upstream; the
    raise below is the defense-in-depth backstop for any future caller that
    skips validation.

    google.auth and google.auth.transport.requests are imported lazily (in
    _mint_session, once per worker thread).
    """
    if size_bytes < 1:
        raise ValueError(
            f"size_bytes must be >= 1 for {blob_path!r} (got {size_bytes}); "
            "expected_size_bytes is required and enforced as of gap (c)"
        )
    authed_session = _mint_session()

    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "X-Upload-Content-Type": "application/octet-stream",
        "X-Upload-Content-Length": str(size_bytes),
    }

    resp = authed_session.post(
        f"https://storage.googleapis.com/upload/storage/v1/b/{bucket}/o"
        f"?uploadType=resumable&name={blob_path}",
        headers=headers,
        json={"name": blob_path, "contentType": "application/octet-stream"},
    )
    resp.raise_for_status()
    return resp.headers["Location"]
