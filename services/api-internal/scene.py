"""Scene domain model and state machine for the roomstudio perception pipeline.

A Scene represents one capture-to-splat job: from bundle upload through
perception to a finished splat. The Scene record is the durable source of truth
for job status; it lives in Firestore (collection: scenes, doc id: scene_id)
and is read by the ingester, perception services, and eventually the iOS client.

State machine:
  queued → processing → ready              (happy path)
                      → failed             (perception error; Cloud Tasks exhausted retries)
         → failed                          (dispatch error; task never enqueued)
         → failed_incomplete               (existence check: some blobs absent at ingest time)
  failed → queued                          (manual retry only, via POST /scenes/{id}/retry)
  failed_incomplete → queued               (re-upload + Eventarc re-fires → ingest retries)

Any other transition is a programming error and raises InvalidTransitionError.

last_error is server-side only: never serialized in client-facing responses.

Consumers: repository.py (persistence), server.py (dispatch wiring in step 3).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class SceneStatus(str, Enum):
    """Lifecycle state of a Scene.

    String-valued so Firestore stores a human-readable string rather than an
    integer, and so equality with raw strings works in logs and test output.
    """
    QUEUED = "queued"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"
    FAILED_INCOMPLETE = "failed_incomplete"  # upload incomplete; recoverable via re-upload


class DeviceIdSource(str, Enum):
    """How the Scene's device_id was determined at ingest time.

    provided:
        bundle.device.device_id was non-empty; used directly.

    fallback_hardware_id:
        bundle.device.device_id was empty; device_id was set from
        bundle.device.hardware_id instead. This is a model string (e.g.
        "iPhone15,3"), not a unique device identifier — two phones of the same
        model produce the same value. Use this field to query for scenes still
        on the fallback path.

        Remove this enum variant (and the fallback logic in server.py) once iOS
        bundles populate device_id for ≥99% of captures over a 7-day window.
    """
    PROVIDED = "provided"
    FALLBACK_HARDWARE_ID = "fallback_hardware_id"


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------

# Allowed state transitions. Values are frozensets of legal target states.
_ALLOWED_TRANSITIONS: dict[SceneStatus, frozenset[SceneStatus]] = {
    SceneStatus.QUEUED:            frozenset({SceneStatus.PROCESSING, SceneStatus.FAILED, SceneStatus.FAILED_INCOMPLETE}),
    SceneStatus.PROCESSING:        frozenset({SceneStatus.READY, SceneStatus.FAILED}),
    SceneStatus.FAILED:            frozenset({SceneStatus.QUEUED}),           # manual retry only
    SceneStatus.FAILED_INCOMPLETE: frozenset({SceneStatus.QUEUED}),           # re-upload → Eventarc re-fires → ingest retries
    SceneStatus.READY:             frozenset(),                                # terminal
}


class InvalidTransitionError(Exception):
    """Raised when a state transition is not permitted by the state machine."""


def allowed_transitions(status: SceneStatus) -> frozenset[SceneStatus]:
    """Return the set of valid next states from the given status."""
    return _ALLOWED_TRANSITIONS[status]


def validate_transition(current: SceneStatus, next_status: SceneStatus) -> None:
    """Raise InvalidTransitionError if current → next_status is not allowed.

    This is the single enforcement point for the state machine. The repository's
    update_status calls this before every mutation; callers outside the repository
    should not need to call it directly.
    """
    allowed = _ALLOWED_TRANSITIONS[current]
    if next_status not in allowed:
        allowed_str = (
            ", ".join(f"'{s.value}'" for s in sorted(allowed, key=lambda s: s.value))
            or "none (terminal state)"
        )
        raise InvalidTransitionError(
            f"Cannot transition from '{current.value}' to '{next_status.value}'. "
            f"Allowed from '{current.value}': {allowed_str}."
        )


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------

@dataclass
class Scene:
    """A single capture-to-splat job.

    Fields
    ------
    scene_id:
        Stable identifier (UUIDv4). Also used as the Firestore doc id and as
        the Cloud Tasks task name for deduplication.
    device_id:
        Identifies the originating device. Non-empty; see device_id_source for
        how it was determined.
    device_id_source:
        Whether device_id came from bundle.device.device_id (preferred) or
        fell back to bundle.device.hardware_id (placeholder, not unique).
    status:
        Current lifecycle state.
    bundle_uri:
        Absolute GCS URI of the serialized CaptureBundle proto
        (e.g. gs://bucket/captures/{bundle_id}/bundle.pb). Unlike the paths
        inside the bundle itself, this IS absolute — the Scene record needs a
        self-contained pointer to the source data.
    created_at:
        UTC timestamp of record creation (when the bundle was ingested).
    updated_at:
        UTC timestamp of the most recent status change.
    result_uri:
        Absolute GCS URI of the finished splat output. None until status==READY.
    attempt_count:
        Number of times this scene has been dispatched to perception. Incremented
        at dispatch time (step 3), not during model construction.
    last_error:
        Last error message received from perception. Server-side only —
        never included in client-facing API responses.
    """
    scene_id: str
    device_id: str
    device_id_source: DeviceIdSource
    status: SceneStatus
    bundle_uri: str
    created_at: datetime
    updated_at: datetime
    result_uri: Optional[str] = None
    attempt_count: int = 0
    last_error: Optional[str] = None      # server-side only; never serialized to clients
    bundle_id: Optional[str] = None       # iOS bundle UUIDv4; stored for lookup by bundle_id
    user_id: Optional[str] = None         # Firebase UID from the upload JWT
    missing_paths: Optional[list] = None  # relative paths absent at existence-check time

    def __post_init__(self) -> None:
        if not self.scene_id:
            raise ValueError("scene_id must not be empty")
        if not self.device_id:
            raise ValueError("device_id must not be empty")
        if not isinstance(self.device_id_source, DeviceIdSource):
            raise ValueError(
                f"device_id_source must be a DeviceIdSource, got: {type(self.device_id_source)}"
            )
        if not isinstance(self.status, SceneStatus):
            raise ValueError(
                f"status must be a SceneStatus, got: {type(self.status)}"
            )
        if not self.bundle_uri.startswith("gs://"):
            raise ValueError(
                f"bundle_uri must be an absolute gs:// URI, got: {self.bundle_uri!r}"
            )
        if self.attempt_count < 0:
            raise ValueError(
                f"attempt_count must be >= 0, got: {self.attempt_count}"
            )
        if self.created_at.tzinfo is None or self.updated_at.tzinfo is None:
            raise ValueError("created_at and updated_at must be timezone-aware datetimes")


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------

def new_scene(
    *,
    scene_id: Optional[str] = None,
    device_id: str,
    device_id_source: DeviceIdSource,
    bundle_uri: str,
) -> Scene:
    """Construct a new Scene in the initial QUEUED state.

    scene_id defaults to a fresh UUIDv4. Callers that need idempotency (e.g.
    Cloud Tasks task-name dedup in step 3) should generate and pass their own.
    """
    now = datetime.now(tz=timezone.utc)
    return Scene(
        scene_id=scene_id or str(uuid.uuid4()),
        device_id=device_id,
        device_id_source=device_id_source,
        status=SceneStatus.QUEUED,
        bundle_uri=bundle_uri,
        created_at=now,
        updated_at=now,
    )
