"""Scene persistence layer.

Defines the SceneRepository interface and two implementations:

  InMemorySceneRepository  — for tests; no external dependencies.
  FirestoreSceneRepository — production; backed by Firestore collection
                             'scenes'. Firestore is imported lazily so the
                             module is safe to import in test environments
                             without GCP credentials or the library installed.

SceneRepository extends roomstudio_api_core.scene_read_repo.SceneReadRepository,
adding write methods (create, update_status). api-public only receives the read
interface; api-internal gets the full read+write interface.

FirestoreSceneRepository extends FirestoreSceneReadRepository from api-core so
the Firestore read logic (_db, _doc_ref, _from_doc, get, get_by_bundle_id) is
not duplicated. It adds create() and update_status().

SceneNotFoundError is defined in api-core and re-exported from here for
callers that prefer importing it from repository.py.

No Firestore types leak beyond FirestoreSceneRepository. The rest of the
codebase works entirely with the Scene dataclass from scene.py.

Consumers: ingest_server.py (Scene persistence + dispatch wiring), tests.
"""
from __future__ import annotations

import copy
import os
from abc import abstractmethod
from datetime import datetime, timedelta, timezone
from typing import Optional

from scene import Scene, SceneStatus, validate_transition
from roomstudio_api_core.scene_read_repo import (
    FirestoreSceneReadRepository,
    InMemorySceneReadRepository,
    SceneNotFoundError,  # re-exported; callers may import from here or api-core
    SceneReadRepository,
)


# ---------------------------------------------------------------------------
# Scene TTL stamping (gap F6, decisions 0018/0086)
# ---------------------------------------------------------------------------

# Retention for terminal-failure scenes. The Firestore TTL policy on
# scenes.expire_at (infra/eventarc_setup.sh --scenes-ttl-only) sweeps any doc
# whose expire_at is past. Read per call so tests can override the env.
_SCENES_FAILED_TTL_ENV = "SCENES_FAILED_TTL_DAYS"
_SCENES_FAILED_TTL_DEFAULT_DAYS = 90

# Statuses that schedule expiry. READY is deliberately absent — ready rooms
# are product data and never age out. QUEUED clears any pending expiry (a
# revived scene is live again). PROCESSING leaves the field untouched.
_EXPIRING_STATUSES = frozenset({
    SceneStatus.FAILED,
    SceneStatus.FAILED_INVALID,
    SceneStatus.FAILED_INCOMPLETE,
})


def _failed_ttl_days() -> int:
    try:
        return max(1, int(os.environ.get(_SCENES_FAILED_TTL_ENV,
                                         _SCENES_FAILED_TTL_DEFAULT_DAYS)))
    except ValueError:
        return _SCENES_FAILED_TTL_DEFAULT_DAYS


def expiry_for_transition(
    new_status: SceneStatus, now: datetime
) -> tuple[bool, Optional[datetime]]:
    """(touch, value) for scene.expire_at on a transition to new_status.

    touch=False → leave the field as it is (processing, ready).
    touch=True, value=datetime → schedule expiry (terminal failures).
    touch=True, value=None → clear a pending expiry (revival to queued).

    Only the transitions api-internal itself performs flow through here.
    perception-obj mirrors these semantics in its own receiver_repo
    (`expiry_for_failed`) — deliberately a duplicate rather than an import,
    because that image installs packages/schemas only, so there is no shared
    module to import from. Its env var name and default days are pinned there
    against this module's constants so the two cannot drift silently.
    """
    if new_status in _EXPIRING_STATUSES:
        return True, now + timedelta(days=_failed_ttl_days())
    if new_status == SceneStatus.QUEUED:
        return True, None
    return False, None


# ---------------------------------------------------------------------------
# Abstract interface (read + write)
# ---------------------------------------------------------------------------

class SceneRepository(SceneReadRepository):
    """Full read+write interface for Scene persistence.

    Extends SceneReadRepository (get, get_by_bundle_id) with write methods.
    Implementations must be thread-safe.

    api-public uses only SceneReadRepository; api-internal uses SceneRepository.
    """

    @abstractmethod
    def create(self, scene: Scene) -> None:
        """Persist a new Scene.

        Raises ValueError if a scene with the same scene_id already exists.
        """

    @abstractmethod
    def update_status(
        self,
        scene_id: str,
        new_status: SceneStatus,
        *,
        result_uri: Optional[str] = None,
        last_error: Optional[str] = None,
        missing_paths: Optional[list] = None,
        invalid_blobs: Optional[list] = None,
    ) -> Scene:
        """Transition scene_id to new_status and return the updated Scene.

        Validates the transition via validate_transition before mutating;
        raises InvalidTransitionError on disallowed moves. Sets updated_at to
        now. Sets result_uri, last_error, missing_paths, and invalid_blobs only
        when explicitly provided.

        Raises SceneNotFoundError if the scene does not exist.
        Raises InvalidTransitionError if the transition is not allowed.
        """


# ---------------------------------------------------------------------------
# In-memory implementation (tests)
# ---------------------------------------------------------------------------

class InMemorySceneRepository(InMemorySceneReadRepository, SceneRepository):
    """In-memory Scene store. Intended for unit tests only; not thread-safe.

    Inherits get() and get_by_bundle_id() (and the _store dict) from
    InMemorySceneReadRepository, mirroring how FirestoreSceneRepository
    extends FirestoreSceneReadRepository. Adds create() and update_status().
    """

    def create(self, scene: Scene) -> None:
        if scene.scene_id in self._store:
            raise ValueError(f"Scene already exists: {scene.scene_id!r}")
        self._store[scene.scene_id] = copy.deepcopy(scene)

    def update_status(
        self,
        scene_id: str,
        new_status: SceneStatus,
        *,
        result_uri: Optional[str] = None,
        last_error: Optional[str] = None,
        missing_paths: Optional[list] = None,
        invalid_blobs: Optional[list] = None,
    ) -> Scene:
        scene = self.get(scene_id)          # raises SceneNotFoundError if missing
        validate_transition(scene.status, new_status)  # raises InvalidTransitionError if bad
        scene.status = new_status
        scene.updated_at = datetime.now(tz=timezone.utc)
        if result_uri is not None:
            scene.result_uri = result_uri
        if last_error is not None:
            scene.last_error = last_error
        if missing_paths is not None:
            scene.missing_paths = missing_paths
        if invalid_blobs is not None:
            scene.invalid_blobs = invalid_blobs
        touch_expiry, expire_at = expiry_for_transition(new_status, scene.updated_at)
        if touch_expiry:
            scene.expire_at = expire_at
        self._store[scene_id] = copy.deepcopy(scene)
        return copy.deepcopy(scene)


# ---------------------------------------------------------------------------
# Firestore implementation (production)
# ---------------------------------------------------------------------------

class FirestoreSceneRepository(FirestoreSceneReadRepository, SceneRepository):
    """Firestore-backed Scene repository.

    Extends FirestoreSceneReadRepository (api-core) to inherit _db, _doc_ref,
    _from_doc, get, and get_by_bundle_id. Adds create() and update_status().

    Construction signature: FirestoreSceneRepository(project=None).
    """

    def __init__(self, project: Optional[str] = None) -> None:
        # FirestoreSceneReadRepository.__init__ initialises self._db.
        super().__init__(project=project)

    def create(self, scene: Scene) -> None:
        from google.api_core.exceptions import AlreadyExists

        ref = self._doc_ref(scene.scene_id)
        try:
            ref.create(self._to_dict(scene))
        except AlreadyExists:
            raise ValueError(f"Scene already exists: {scene.scene_id!r}")

    def update_status(
        self,
        scene_id: str,
        new_status: SceneStatus,
        *,
        result_uri: Optional[str] = None,
        last_error: Optional[str] = None,
        missing_paths: Optional[list] = None,
        invalid_blobs: Optional[list] = None,
    ) -> Scene:
        from google.cloud import firestore as _fs

        ref = self._doc_ref(scene_id)

        @_fs.transactional
        def _run(transaction, ref):
            snap = ref.get(transaction=transaction)
            if not snap.exists:
                raise SceneNotFoundError(f"Scene not found: {scene_id!r}")
            scene = self._from_doc(snap)
            validate_transition(scene.status, new_status)

            now = datetime.now(tz=timezone.utc)
            updates: dict = {"status": new_status.value, "updated_at": now}
            if result_uri is not None:
                updates["result_uri"] = result_uri
            if last_error is not None:
                updates["last_error"] = last_error
            if missing_paths is not None:
                updates["missing_paths"] = missing_paths
            if invalid_blobs is not None:
                updates["invalid_blobs"] = invalid_blobs
            touch_expiry, expire_at = expiry_for_transition(new_status, now)
            if touch_expiry:
                # Clearing uses DELETE_FIELD (not None): the TTL policy on
                # expire_at ignores absent fields, and an explicit null would
                # read as a malformed deadline in the console.
                updates["expire_at"] = (
                    expire_at if expire_at is not None else _fs.DELETE_FIELD
                )
            transaction.update(ref, updates)

            scene.status = new_status
            scene.updated_at = now
            if result_uri is not None:
                scene.result_uri = result_uri
            if last_error is not None:
                scene.last_error = last_error
            if missing_paths is not None:
                scene.missing_paths = missing_paths
            if invalid_blobs is not None:
                scene.invalid_blobs = invalid_blobs
            if touch_expiry:
                scene.expire_at = expire_at
            return scene

        return _run(self._db.transaction(), ref)

    @staticmethod
    def _to_dict(scene: Scene) -> dict:
        """Serialize a Scene to a Firestore-compatible dict.

        scene_id is stored as the document id, not as a field.
        """
        doc = {
            "device_id": scene.device_id,
            "status": scene.status.value,
            "bundle_uri": scene.bundle_uri,
            "created_at": scene.created_at,
            "updated_at": scene.updated_at,
            "result_uri": scene.result_uri,
            "attempt_count": scene.attempt_count,
            "last_error": scene.last_error,
            "bundle_id": scene.bundle_id,
            "user_id": scene.user_id,
            "fcm_token": scene.fcm_token,
            "missing_paths": scene.missing_paths,
            "invalid_blobs": scene.invalid_blobs,
        }
        # expire_at is written only when set: the scenes TTL policy treats an
        # absent field as "no expiry", which is the correct state for every
        # newly created (queued) scene.
        if scene.expire_at is not None:
            doc["expire_at"] = scene.expire_at
        return doc
