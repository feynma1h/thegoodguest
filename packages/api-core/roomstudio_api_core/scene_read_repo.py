"""Read-only Scene repository for public API consumers.

api-public uses this module to look up scenes by bundle_id without
needing access to api-internal's write-capable SceneRepository. The
interface is intentionally minimal: the write path stays in api-internal.

Exports:
  SceneNotFoundError            — raised by get() when scene_id is absent
  SceneReadRepository           — ABC: get(scene_id), get_by_bundle_id(bundle_id)
  InMemorySceneReadRepository   — dict-backed implementation for tests
  FirestoreSceneReadRepository  — Firestore-backed production implementation

api-internal's SceneRepository extends SceneReadRepository so that
InMemorySceneRepository and FirestoreSceneRepository satisfy both interfaces.

Consumers: services/api-public (GET /scenes/by-bundle/{bundle_id}),
           services/api-internal (extends SceneReadRepository via SceneRepository).
"""
from __future__ import annotations

import copy
from abc import ABC, abstractmethod
from typing import Optional

from roomstudio_api_core.scene import Scene


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class SceneNotFoundError(Exception):
    """Raised when a requested scene_id does not exist in the store."""


# ---------------------------------------------------------------------------
# Abstract interface
# ---------------------------------------------------------------------------

class SceneReadRepository(ABC):
    """Read-only interface for Scene retrieval. Implementations must be thread-safe."""

    @abstractmethod
    def get(self, scene_id: str) -> Scene:
        """Return the Scene with the given scene_id.

        Raises SceneNotFoundError if not found.
        """

    @abstractmethod
    def get_by_bundle_id(self, bundle_id: str) -> Optional[Scene]:
        """Return the Scene whose bundle_id matches, or None if not found.

        bundle_id is the iOS-generated UUIDv4 stored on the Scene at ingest
        time. Different from scene_id (the ingester's UUID for the job).
        """


# ---------------------------------------------------------------------------
# In-memory implementation (tests and local development)
# ---------------------------------------------------------------------------

class InMemorySceneReadRepository(SceneReadRepository):
    """In-memory read-only Scene repository.

    Accepts an optional pre-populated dict so test fixtures can inject scenes
    without going through a write path:

        repo = InMemorySceneReadRepository({scene.scene_id: scene})

    Not thread-safe; intended for tests only.
    """

    def __init__(self, scenes: Optional[dict[str, Scene]] = None) -> None:
        self._store: dict[str, Scene] = dict(scenes or {})

    def get(self, scene_id: str) -> Scene:
        if scene_id not in self._store:
            raise SceneNotFoundError(f"Scene not found: {scene_id!r}")
        return copy.deepcopy(self._store[scene_id])

    def get_by_bundle_id(self, bundle_id: str) -> Optional[Scene]:
        for scene in self._store.values():
            if scene.bundle_id == bundle_id:
                return copy.deepcopy(scene)
        return None


# ---------------------------------------------------------------------------
# Firestore implementation (production)
# ---------------------------------------------------------------------------

class FirestoreSceneReadRepository(SceneReadRepository):
    """Firestore-backed read-only Scene repository.

    Collection: 'scenes'. Document id = scene_id.

    Firestore is imported lazily so this module is safe to import in test
    environments without GCP credentials or the library installed — provided
    FirestoreSceneReadRepository is never instantiated.

    Used directly by api-public. api-internal's FirestoreSceneRepository
    extends this class to share the read logic and _db handle.
    """

    COLLECTION = "scenes"

    def __init__(self, project: Optional[str] = None) -> None:
        from google.cloud import firestore as _fs  # deferred

        self._db = _fs.Client(project=project)

    def _doc_ref(self, scene_id: str):
        return self._db.collection(self.COLLECTION).document(scene_id)

    @staticmethod
    def _from_doc(doc) -> Scene:
        """Deserialize a Firestore DocumentSnapshot into a Scene."""
        from roomstudio_api_core.scene import DeviceIdSource, SceneStatus

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
            bundle_id=data.get("bundle_id"),
            user_id=data.get("user_id"),
            missing_paths=data.get("missing_paths"),
        )

    def get(self, scene_id: str) -> Scene:
        doc = self._doc_ref(scene_id).get()
        if not doc.exists:
            raise SceneNotFoundError(f"Scene not found: {scene_id!r}")
        return self._from_doc(doc)

    def get_by_bundle_id(self, bundle_id: str) -> Optional[Scene]:
        docs = (
            self._db.collection(self.COLLECTION)
            .where("bundle_id", "==", bundle_id)
            .limit(1)
            .stream()
        )
        for doc in docs:
            return self._from_doc(doc)
        return None
