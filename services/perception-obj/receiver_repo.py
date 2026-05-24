"""ReceiverRepository: Scene claim/release for the perception-obj /process endpoint.

Manages the lease lifecycle that the ingester's SceneRepository does not need:
  - claim()        — atomically transition queued→processing and write
                     lease_expires_at; or reclaim a PROCESSING scene whose
                     lease has gone stale (crash recovery per 0004).
  - release_ready() — mark the scene READY, set result_uri, clear lease.
  - release_failed() — mark the scene FAILED, set last_error, clear lease.

`lease_expires_at` is an implementation detail of the receiver. It lives in the
Firestore document alongside the standard Scene fields (written by the ingester)
but is not part of the Scene domain model in services/api/scene.py.

The receiver drives the queued→processing→ready|failed arc.
The ingester owns failed→queued (manual retry). The receiver treats `failed`
on entry as a bug (per 0004) and 200-exits without clobbering state.

Status strings match the SceneStatus enum values in services/api/scene.py:
  "queued" / "processing" / "ready" / "failed"

Consumers: process_receiver.py (POST /process orchestration).
"""
from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Claim result types
# ---------------------------------------------------------------------------

class ClaimStatus(str, Enum):
    """Outcome of a claim() call."""
    CLAIMED       = "claimed"       # was queued, now processing; caller should proceed
    RECLAIMED     = "reclaimed"     # was processing with stale lease; reclaimed; proceed
    ALREADY_OWNED = "already_owned" # processing with fresh lease; another worker owns it; 200-exit
    WRONG_STATE   = "wrong_state"   # scene is failed or ready; 200-exit (bug per 0004)
    NOT_FOUND     = "not_found"     # no scene with this id; 200-exit


@dataclass
class ClaimResult:
    """Result of a claim() call.

    device_id is non-empty only when status is CLAIMED or RECLAIMED — the
    caller needs it to send FCM notifications on terminal transitions.
    """
    status: ClaimStatus
    device_id: str = ""


# ---------------------------------------------------------------------------
# Abstract interface
# ---------------------------------------------------------------------------

class ReceiverRepository(ABC):
    """Interface for Scene claim/release from the perception receiver's perspective."""

    @abstractmethod
    def claim(self, scene_id: str, lease_ttl_seconds: int, *, holder_id: str = "") -> ClaimResult:
        """Atomically attempt to claim scene_id for processing.

        holder_id identifies the calling worker (written to lease_holder_id for
        observability). Pass the module-level _WORKER_ID from process_receiver.

        Behaviour by current scene status:
          queued      → transition to processing, write lease_expires_at +
                        lease_holder_id. Returns CLAIMED.
          processing  → if lease is stale (expired), reclaim atomically in a
                        single transaction: verify still expired, write new
                        lease_expires_at + lease_holder_id. Returns RECLAIMED.
                        If lease is fresh, another worker owns it.
                        Returns ALREADY_OWNED.
          failed      → bug per 0004; receiver should 200-exit.
                        Returns WRONG_STATE.
          ready       → already done; receiver should 200-exit.
                        Returns WRONG_STATE.
          not found   → idempotency or stale task; receiver should 200-exit.
                        Returns NOT_FOUND.
        """

    @abstractmethod
    def release_lease(self, scene_id: str, *, holder_id: str = "") -> None:
        """Clear lease fields, leave status=processing.

        Called by the EnvironmentalError handler before returning 500 so Cloud
        Tasks retries arrive at an immediately-reclaimable state instead of
        waiting for the full lease TTL. Best-effort: no-op if the scene is not
        found, not in processing state, or if the doc's lease_holder_id does
        not match holder_id (guards against clearing another worker's lease
        when the OOM-on-cold-start race crosses the TTL boundary).
        """

    @abstractmethod
    def release_queued(self, scene_id: str, *, holder_id: str = "") -> None:
        """Atomically clear lease and set status=queued; increment shutdown_release_count.

        Called by the SIGTERM handler for each held scene so that Cloud Tasks
        retries after a rolling deploy find a clean state. No-op if the scene is
        not in processing state or if the doc's lease_holder_id does not match
        holder_id (guards against worker A releasing worker B's live lease when
        B reclaimed the scene while A was draining). Single transaction —
        non-negotiable (a two-step clear-then-update is unsafe under SIGKILL
        between the steps).
        """

    @abstractmethod
    def release_ready(self, scene_id: str, result_uri: str) -> None:
        """Transition scene_id from processing to ready and set result_uri.

        Clears lease_expires_at. Raises ValueError if scene is not processing.
        """

    @abstractmethod
    def release_failed(self, scene_id: str, last_error: str) -> None:
        """Transition scene_id from processing to failed and set last_error.

        Clears lease_expires_at. Raises ValueError if scene is not processing.
        """


# ---------------------------------------------------------------------------
# In-memory implementation (tests / local dev)
# ---------------------------------------------------------------------------

class InMemoryReceiverRepository(ReceiverRepository):
    """Thread-safe in-memory implementation. For tests.

    seed() pre-populates scenes so tests can start from any state.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # Each entry: {"status": str, "device_id": str, "bundle_uri": str,
        #              "result_uri": str|None, "last_error": str|None,
        #              "lease_expires_at": datetime|None}
        self._scenes: dict[str, dict] = {}

    def seed(
        self,
        scene_id: str,
        *,
        status: str,
        device_id: str = "device-1",
        bundle_uri: str = "gs://bucket/captures/test/bundle.pb",
        result_uri: Optional[str] = None,
        last_error: Optional[str] = None,
        lease_expires_at: Optional[datetime] = None,
        lease_holder_id: str = "",
        shutdown_release_count: int = 0,
    ) -> None:
        """Pre-populate a scene for testing. Not part of the production interface."""
        with self._lock:
            self._scenes[scene_id] = {
                "status": status,
                "device_id": device_id,
                "bundle_uri": bundle_uri,
                "result_uri": result_uri,
                "last_error": last_error,
                "lease_expires_at": lease_expires_at,
                "lease_holder_id": lease_holder_id,
                "shutdown_release_count": shutdown_release_count,
            }

    def get_raw(self, scene_id: str) -> Optional[dict]:
        """Return a copy of the raw scene dict for test assertions."""
        with self._lock:
            entry = self._scenes.get(scene_id)
            return dict(entry) if entry is not None else None

    def claim(self, scene_id: str, lease_ttl_seconds: int, *, holder_id: str = "") -> ClaimResult:
        with self._lock:
            entry = self._scenes.get(scene_id)
            if entry is None:
                return ClaimResult(ClaimStatus.NOT_FOUND)

            status = entry["status"]
            now = datetime.now(tz=timezone.utc)
            new_lease = now + timedelta(seconds=lease_ttl_seconds)

            if status in ("failed", "ready"):
                return ClaimResult(ClaimStatus.WRONG_STATE)

            if status == "processing":
                existing_lease = entry.get("lease_expires_at")
                if existing_lease is not None and existing_lease > now:
                    return ClaimResult(ClaimStatus.ALREADY_OWNED)
                # Stale lease — reclaim atomically under the lock.
                entry["lease_expires_at"] = new_lease
                entry["lease_holder_id"] = holder_id
                return ClaimResult(ClaimStatus.RECLAIMED, device_id=entry["device_id"])

            if status == "queued":
                entry["status"] = "processing"
                entry["lease_expires_at"] = new_lease
                entry["lease_holder_id"] = holder_id
                return ClaimResult(ClaimStatus.CLAIMED, device_id=entry["device_id"])

            # Unknown status — treat as bug.
            return ClaimResult(ClaimStatus.WRONG_STATE)

    def release_lease(self, scene_id: str, *, holder_id: str = "") -> None:
        with self._lock:
            entry = self._scenes.get(scene_id)
            if entry is None or entry["status"] != "processing":
                return
            if entry.get("lease_holder_id") != holder_id:
                return
            entry["lease_expires_at"] = None
            entry["lease_holder_id"] = ""

    def release_queued(self, scene_id: str, *, holder_id: str = "") -> None:
        with self._lock:
            entry = self._scenes.get(scene_id)
            if entry is None or entry["status"] != "processing":
                return
            if entry.get("lease_holder_id") != holder_id:
                return
            entry["status"] = "queued"
            entry["lease_expires_at"] = None
            entry["lease_holder_id"] = ""
            entry["shutdown_release_count"] = entry.get("shutdown_release_count", 0) + 1

    def release_ready(self, scene_id: str, result_uri: str) -> None:
        with self._lock:
            entry = self._scenes.get(scene_id)
            if entry is None:
                raise ValueError(f"Scene not found: {scene_id!r}")
            if entry["status"] != "processing":
                raise ValueError(
                    f"Cannot release_ready scene {scene_id!r}: "
                    f"current status is {entry['status']!r}"
                )
            entry["status"] = "ready"
            entry["result_uri"] = result_uri
            entry["lease_expires_at"] = None

    def release_failed(self, scene_id: str, last_error: str) -> None:
        with self._lock:
            entry = self._scenes.get(scene_id)
            if entry is None:
                raise ValueError(f"Scene not found: {scene_id!r}")
            if entry["status"] != "processing":
                raise ValueError(
                    f"Cannot release_failed scene {scene_id!r}: "
                    f"current status is {entry['status']!r}"
                )
            entry["status"] = "failed"
            entry["last_error"] = last_error
            entry["lease_expires_at"] = None


# ---------------------------------------------------------------------------
# Firestore implementation (production)
# ---------------------------------------------------------------------------

class FirestoreReceiverRepository(ReceiverRepository):
    """Firestore-backed implementation.

    Reads and writes the 'scenes' collection — the same collection the ingester
    uses. The receiver adds one extra field (`lease_expires_at`) the ingester
    does not write.

    google.cloud.firestore is imported lazily so this module is safe to import
    in test environments without GCP credentials or the library installed.

    Collection: 'scenes'. Document id = scene_id.
    """

    COLLECTION = "scenes"

    def __init__(self, project: Optional[str] = None) -> None:
        from google.cloud import firestore as _fs  # deferred

        self._db = _fs.Client(project=project)

    def claim(self, scene_id: str, lease_ttl_seconds: int, *, holder_id: str = "") -> ClaimResult:
        from google.cloud import firestore as _fs  # deferred

        ref = self._db.collection(self.COLLECTION).document(scene_id)
        now = datetime.now(tz=timezone.utc)
        new_lease = now + timedelta(seconds=lease_ttl_seconds)

        result: ClaimResult = ClaimResult(ClaimStatus.NOT_FOUND)

        @_fs.transactional
        def _txn(transaction, ref):
            nonlocal result
            snap = ref.get(transaction=transaction)
            if not snap.exists:
                result = ClaimResult(ClaimStatus.NOT_FOUND)
                return

            data = snap.to_dict()
            status = data.get("status", "")
            device_id = data.get("device_id", "")

            if status in ("failed", "ready"):
                result = ClaimResult(ClaimStatus.WRONG_STATE)
                return

            if status == "processing":
                existing_lease = data.get("lease_expires_at")
                if existing_lease is not None and existing_lease > now:
                    result = ClaimResult(ClaimStatus.ALREADY_OWNED)
                    return
                # Stale lease — reclaim atomically within this transaction.
                # Re-reading the lease inside the transaction closes the TOCTOU
                # window between two workers both observing an expired lease.
                transaction.update(ref, {
                    "lease_expires_at": new_lease,
                    "lease_holder_id": holder_id,
                    "updated_at": now,
                })
                result = ClaimResult(ClaimStatus.RECLAIMED, device_id=device_id)
                return

            if status == "queued":
                transaction.update(ref, {
                    "status": "processing",
                    "lease_expires_at": new_lease,
                    "lease_holder_id": holder_id,
                    "updated_at": now,
                })
                result = ClaimResult(ClaimStatus.CLAIMED, device_id=device_id)
                return

            result = ClaimResult(ClaimStatus.WRONG_STATE)

        _txn(self._db.transaction(), ref)
        return result

    def release_lease(self, scene_id: str, *, holder_id: str = "") -> None:
        from google.cloud import firestore as _fs  # deferred

        ref = self._db.collection(self.COLLECTION).document(scene_id)
        now = datetime.now(tz=timezone.utc)

        @_fs.transactional
        def _txn(transaction, ref):
            snap = ref.get(transaction=transaction)
            if not snap.exists:
                return
            data = snap.to_dict()
            if data.get("status") != "processing":
                return
            if data.get("lease_holder_id") != holder_id:
                return
            transaction.update(ref, {
                "lease_expires_at": None,
                "lease_holder_id": "",
                "updated_at": now,
            })

        _txn(self._db.transaction(), ref)

    def release_queued(self, scene_id: str, *, holder_id: str = "") -> None:
        from google.cloud import firestore as _fs  # deferred

        ref = self._db.collection(self.COLLECTION).document(scene_id)
        now = datetime.now(tz=timezone.utc)

        @_fs.transactional
        def _txn(transaction, ref):
            snap = ref.get(transaction=transaction)
            if not snap.exists:
                return
            data = snap.to_dict()
            if data.get("status") != "processing":
                return
            if data.get("lease_holder_id") != holder_id:
                return
            transaction.update(ref, {
                "status": "queued",
                "lease_expires_at": None,
                "lease_holder_id": "",
                "shutdown_release_count": _fs.Increment(1),
                "updated_at": now,
            })

        _txn(self._db.transaction(), ref)

    def release_ready(self, scene_id: str, result_uri: str) -> None:
        from google.cloud import firestore as _fs  # deferred

        ref = self._db.collection(self.COLLECTION).document(scene_id)

        @_fs.transactional
        def _txn(transaction, ref):
            snap = ref.get(transaction=transaction)
            if not snap.exists:
                raise ValueError(f"Scene not found: {scene_id!r}")
            data = snap.to_dict()
            if data.get("status") != "processing":
                raise ValueError(
                    f"Cannot release_ready scene {scene_id!r}: "
                    f"current status is {data.get('status')!r}"
                )
            transaction.update(ref, {
                "status": "ready",
                "result_uri": result_uri,
                "lease_expires_at": None,
                "updated_at": datetime.now(tz=timezone.utc),
            })

        _txn(self._db.transaction(), ref)

    def release_failed(self, scene_id: str, last_error: str) -> None:
        from google.cloud import firestore as _fs  # deferred

        ref = self._db.collection(self.COLLECTION).document(scene_id)

        @_fs.transactional
        def _txn(transaction, ref):
            snap = ref.get(transaction=transaction)
            if not snap.exists:
                raise ValueError(f"Scene not found: {scene_id!r}")
            data = snap.to_dict()
            if data.get("status") != "processing":
                raise ValueError(
                    f"Cannot release_failed scene {scene_id!r}: "
                    f"current status is {data.get('status')!r}"
                )
            transaction.update(ref, {
                "status": "failed",
                "last_error": last_error,
                "lease_expires_at": None,
                "updated_at": datetime.now(tz=timezone.utc),
            })

        _txn(self._db.transaction(), ref)
