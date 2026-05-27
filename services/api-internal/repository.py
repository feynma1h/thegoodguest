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

SceneNotFoundError is defined in api-core and re-exported from here so that
existing `from repository import SceneNotFoundError` imports continue to work.

No Firestore types leak beyond FirestoreSceneRepository. The rest of the
codebase works entirely with the Scene dataclass from scene.py.

Consumers: server.py (step 3 dispatch wiring), tests.
"""
from __future__ import annotations

import copy
from abc import abstractmethod
from datetime import datetime, timezone
from typing import Optional

from roomstudio_api_core.scene import InvalidTransitionError, Scene, SceneStatus, validate_transition
from roomstudio_api_core.scene_read_repo import (
    FirestoreSceneReadRepository,
    InMemorySceneReadRepository,
    SceneNotFoundError,  # re-exported; callers may import from here or api-core
    SceneReadRepository,
)

# Re-export SceneNotFoundError so existing `from repository import SceneNotFoundError`
# continues to work without changes in test files.
__all__ = [
    "SceneNotFoundError",
    "SceneRepository",
    "InMemorySceneRepository",
    "FirestoreSceneRepository",
]


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
    def create(self, scene: Scene) -> Scene:
        """Persist a new Scene and return the stored copy.

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
    ) -> Scene:
        """Transition scene_id to new_status and return the updated Scene.

        Validates the transition via validate_transition before mutating;
        raises InvalidTransitionError on disallowed moves. Sets updated_at to
        now. Sets result_uri, last_error, and missing_paths only when
        explicitly provided.

        Raises SceneNotFoundError if the scene does not exist.
        Raises InvalidTransitionError if the transition is not allowed.
        """


# ---------------------------------------------------------------------------
# In-memory implementation (tests)
# ---------------------------------------------------------------------------

class InMemorySceneRepository(SceneRepository):
    """In-memory Scene store. Intended for unit tests only; not thread-safe."""

    def __init__(self) -> None:
        self._store: dict[str, Scene] = {}

    def get(self, scene_id: str) -> Scene:
        if scene_id not in self._store:
            raise SceneNotFoundError(f"Scene not found: {scene_id!r}")
        return copy.deepcopy(self._store[scene_id])

    def create(self, scene: Scene) -> Scene:
        if scene.scene_id in self._store:
            raise ValueError(f"Scene already exists: {scene.scene_id!r}")
        stored = copy.deepcopy(scene)
        self._store[scene.scene_id] = stored
        return copy.deepcopy(stored)

    def update_status(
        self,
        scene_id: str,
        new_status: SceneStatus,
        *,
        result_uri: Optional[str] = None,
        last_error: Optional[str] = None,
        missing_paths: Optional[list] = None,
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
        self._store[scene_id] = copy.deepcopy(scene)
        return copy.deepcopy(scene)

    def get_by_bundle_id(self, bundle_id: str) -> Optional[Scene]:
        for scene in self._store.values():
            if scene.bundle_id == bundle_id:
                return copy.deepcopy(scene)
        return None


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

    def create(self, scene: Scene) -> Scene:
        from google.api_core.exceptions import AlreadyExists

        ref = self._doc_ref(scene.scene_id)
        try:
            ref.create(self._to_dict(scene))
        except AlreadyExists:
            raise ValueError(f"Scene already exists: {scene.scene_id!r}")
        return scene

    def update_status(
        self,
        scene_id: str,
        new_status: SceneStatus,
        *,
        result_uri: Optional[str] = None,
        last_error: Optional[str] = None,
        missing_paths: Optional[list] = None,
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
            transaction.update(ref, updates)

            scene.status = new_status
            scene.updated_at = now
            if result_uri is not None:
                scene.result_uri = result_uri
            if last_error is not None:
                scene.last_error = last_error
            if missing_paths is not None:
                scene.missing_paths = missing_paths
            return scene

        return _run(self._db.transaction(), ref)

    @staticmethod
    def _to_dict(scene: Scene) -> dict:
        """Serialize a Scene to a Firestore-compatible dict.

        scene_id is stored as the document id, not as a field.
        """
        return {
            "device_id": scene.device_id,
            "device_id_source": scene.device_id_source.value,
            "status": scene.status.value,
            "bundle_uri": scene.bundle_uri,
            "created_at": scene.created_at,
            "updated_at": scene.updated_at,
            "result_uri": scene.result_uri,
            "attempt_count": scene.attempt_count,
            "last_error": scene.last_error,
            "bundle_id": scene.bundle_id,
            "user_id": scene.user_id,
            "missing_paths": scene.missing_paths,
        }
