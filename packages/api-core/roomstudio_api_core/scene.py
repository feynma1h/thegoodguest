"""Scene domain model and state machine.

Canonical location for the Scene type, shared by api-public and api-internal
without a cross-service import. services/api-internal/scene.py re-exports this
module for the shorter `from scene import ...` path.

Consumers: packages/api-core (SceneReadRepository), services/api-internal (all
scene persistence and dispatch logic), services/api-public (read endpoint).
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
    FAILED_INVALID = "failed_invalid"        # blobs present but content is non-decodable


class InvalidBlobReason:
    """Fixed reason codes for invalid_blobs entries on FAILED_INVALID scenes.

    Defined in api-core alongside FAILED_INVALID so api-public can surface them
    to clients (e.g. the web app) without importing api-internal.

    Values are stable strings — treat as a versioned API contract. Do not
    rename without a migration: the web app will map these to user-facing
    messages (e.g. "too_small" → "Photo could not be read — try again").
    """
    TOO_SMALL = "too_small"                    # blob < MIN_IMAGE_SIZE_BYTES; catches zero-byte,
                                               # truncated, and tiny synthetic test fixtures
    BAD_MAGIC = "bad_magic"                    # first bytes don't match the extension's format
    UNRECOGNIZED_FORMAT = "unrecognized_format" # extension not in the known image format set


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------

# Allowed state transitions. Values are frozensets of legal target states.
_ALLOWED_TRANSITIONS: dict[SceneStatus, frozenset[SceneStatus]] = {
    SceneStatus.QUEUED: frozenset({
        SceneStatus.PROCESSING,
        SceneStatus.FAILED,           # dispatch-time failure (task never enqueued)
        SceneStatus.FAILED_INCOMPLETE, # existence-check failure (missing blobs)
        SceneStatus.FAILED_INVALID,   # validity-check failure (present but non-decodable blobs)
    }),
    SceneStatus.PROCESSING:        frozenset({SceneStatus.READY, SceneStatus.FAILED}),
    SceneStatus.FAILED:            frozenset({SceneStatus.QUEUED}),           # manual retry only
    SceneStatus.FAILED_INCOMPLETE: frozenset({SceneStatus.QUEUED}),           # re-upload → Eventarc re-fires → ingest retries
    SceneStatus.FAILED_INVALID:    frozenset(),                                # terminal — corrupted blobs cannot be fixed by re-upload
    SceneStatus.READY:             frozenset(),                                # terminal
}


class InvalidTransitionError(Exception):
    """Raised when a state transition is not permitted by the state machine."""


def allowed_transitions(status: SceneStatus) -> frozenset[SceneStatus]:
    """Return the set of valid next states from the given status."""
    return _ALLOWED_TRANSITIONS[status]


def validate_transition(current: SceneStatus, next_status: SceneStatus) -> None:
    """Raise InvalidTransitionError if current → next_status is not allowed."""
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
        Identifies the originating device: the iOS app's Keychain-persisted
        per-device UUID (bundle.device.device_id). Non-empty. The literal
        sentinel "unknown" is used for rejection Scenes created from bundles
        that carried no device identity (see ingest_server.py).
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
        by the ingest handler's dispatch step, not during model construction.
    last_error:
        Last error message received from perception. Server-side only —
        never included in client-facing API responses.
    """
    scene_id: str
    device_id: str
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
    invalid_blobs: Optional[list] = None  # [{relative_path, reason}] for FAILED_INVALID scenes

    def __post_init__(self) -> None:
        if not self.scene_id:
            raise ValueError("scene_id must not be empty")
        if not self.device_id:
            raise ValueError("device_id must not be empty")
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
    bundle_uri: str,
) -> Scene:
    """Construct a new Scene in the initial QUEUED state.

    scene_id defaults to a fresh UUIDv4. A caller may pass an explicit id
    (e.g. to reuse the id of an existing Scene record when re-running ingest);
    note the ingest handler's idempotency comes from looking up existing
    scenes by bundle_id, not from deterministic scene_ids.
    """
    now = datetime.now(tz=timezone.utc)
    return Scene(
        scene_id=scene_id or str(uuid.uuid4()),
        device_id=device_id,
        status=SceneStatus.QUEUED,
        bundle_uri=bundle_uri,
        created_at=now,
        updated_at=now,
    )
