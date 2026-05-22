"""Scene persistence layer.

Defines the SceneRepository interface and two implementations:

  InMemorySceneRepository  — for tests; no external dependencies.
  FirestoreSceneRepository — production; backed by Firestore collection
                             'scenes'. Firestore is imported lazily so the
                             module is safe to import in test environments
                             without GCP credentials or the library installed.

The abstract base enforces the interface contract. Callers program to
SceneRepository, not to an implementation.

No Firestore types leak beyond FirestoreSceneRepository. The rest of the
codebase works entirely with the Scene dataclass from scene.py.

Consumers: server.py (step 3 dispatch wiring), tests.
"""
from __future__ import annotations

import copy
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Optional

from scene import InvalidTransitionError, Scene, SceneStatus, validate_transition


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class SceneNotFoundError(Exception):
    """Raised when a requested scene_id does not exist in the store."""


# ---------------------------------------------------------------------------
# Abstract interface
# ---------------------------------------------------------------------------

class SceneRepository(ABC):
    """Interface for Scene persistence. Implementations must be thread-safe."""

    @abstractmethod
    def get(self, scene_id: str) -> Scene:
        """Return the Scene with the given scene_id.

        Raises SceneNotFoundError if not found.
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
    ) -> Scene:
        """Transition scene_id to new_status and return the updated Scene.

        Validates the transition via validate_transition before mutating;
        raises InvalidTransitionError on disallowed moves. Sets updated_at to
        now. Sets result_uri and last_error only when explicitly provided.

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
        # Return a deep copy so callers can't mutate stored state by accident.
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
    ) -> Scene:
        scene = self.get(scene_id)          # raises SceneNotFoundError if missing
        validate_transition(scene.status, new_status)  # raises InvalidTransitionError if bad
        scene.status = new_status
        scene.updated_at = datetime.now(tz=timezone.utc)
        if result_uri is not None:
            scene.result_uri = result_uri
        if last_error is not None:
            scene.last_error = last_error
        self._store[scene_id] = copy.deepcopy(scene)
        return copy.deepcopy(scene)


# ---------------------------------------------------------------------------
# Firestore implementation (production)
# ---------------------------------------------------------------------------

class FirestoreSceneRepository(SceneRepository):
    """Firestore-backed Scene repository.

    Collection: 'scenes'. Document id = scene_id.

    All Firestore types are fully encapsulated here. The rest of the codebase
    never sees a Firestore DocumentSnapshot, DocumentReference, or Transaction.

    google.cloud.firestore is imported lazily so that importing this module in
    a test environment (no GCP credentials, library may not be installed) is
    safe — provided FirestoreSceneRepository is never instantiated.
    """

    COLLECTION = "scenes"

    def __init__(self, project: Optional[str] = None) -> None:
        from google.cloud import firestore as _fs  # deferred

        self._db = _fs.Client(project=project)

    # ------------------------------------------------------------------
    # Serialization helpers
    # ------------------------------------------------------------------

    def _doc_ref(self, scene_id: str):
        return self._db.collection(self.COLLECTION).document(scene_id)

    @staticmethod
    def _from_doc(doc) -> Scene:
        """Deserialize a Firestore DocumentSnapshot into a Scene."""
        from scene import DeviceIdSource, SceneStatus

        data = doc.to_dict()
        return Scene(
            scene_id=doc.id,
            device_id=data["device_id"],
            device_id_source=DeviceIdSource(data["device_id_source"]),
            status=SceneStatus(data["status"]),
            bundle_uri=data["bundle_uri"],
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            result_uri=data.get("result_uri"),
            attempt_count=data.get("attempt_count", 0),
            last_error=data.get("last_error"),
        )

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
        }

    # ------------------------------------------------------------------
    # SceneRepository interface
    # ------------------------------------------------------------------

    def get(self, scene_id: str) -> Scene:
        doc = self._doc_ref(scene_id).get()
        if not doc.exists:
            raise SceneNotFoundError(f"Scene not found: {scene_id!r}")
        return self._from_doc(doc)

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
            transaction.update(ref, updates)

            # Return the updated Scene without a second read.
            scene.status = new_status
            scene.updated_at = now
            if result_uri is not None:
                scene.result_uri = result_uri
            if last_error is not None:
                scene.last_error = last_error
            return scene

        return _run(self._db.transaction(), ref)
