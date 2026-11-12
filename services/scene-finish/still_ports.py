"""Where /still reads a room and leaves its picture (decision 0363).

  StillStore    the outputs bucket under scenes/<scene_id>/: read shell.json,
                finish.json and furniture.json; write and delete the stills.
  StillMarker   the scene's Firestore document: does the room still exist, and
                the one field that tells api-public a still is there
                (`still: {night, rendered_at}`), so listing rooms never asks the
                bucket. Written with update(), so it can never create a scene,
                and it touches no other field (status above all).

Each has a production implementation (deferred google imports, so tests need
no cloud libraries or credentials) and an in-memory one for tests.

Read by: routes_still.py; finish_server.py builds the production pair.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Protocol

log = logging.getLogger("scene-finish")

STILL_DAY = "still.jpg"
STILL_NIGHT = "still-night.jpg"
SCENES_COLLECTION = "scenes"
# Signed links to these are minted per API call (1 h), so a long private cache
# never serves a stale picture under a fresh link.
STILL_CACHE_CONTROL = "private, max-age=3600"


class StillStore(Protocol):
    def read_json(self, scene_id: str, name: str) -> dict | None: ...
    def put(self, scene_id: str, name: str, data: bytes, content_type: str) -> None: ...
    def delete(self, scene_id: str, name: str) -> None: ...


class StillMarker(Protocol):
    def scene_exists(self, scene_id: str) -> bool: ...
    def mark(self, scene_id: str, *, night: bool) -> bool:
        """Record the still; False when the scene document is gone."""
        ...


class GcsStillStore:
    def __init__(self, bucket_name: str):
        from google.cloud import storage

        self._bucket = storage.Client().bucket(bucket_name)

    def _blob(self, scene_id: str, name: str):
        return self._bucket.blob(f"scenes/{scene_id}/{name}")

    def read_json(self, scene_id: str, name: str) -> dict | None:
        from google.cloud.exceptions import NotFound

        try:
            return json.loads(self._blob(scene_id, name).download_as_bytes())
        except NotFound:
            return None

    def put(self, scene_id: str, name: str, data: bytes, content_type: str) -> None:
        blob = self._blob(scene_id, name)
        blob.cache_control = STILL_CACHE_CONTROL
        blob.upload_from_string(data, content_type=content_type)

    def delete(self, scene_id: str, name: str) -> None:
        from google.cloud.exceptions import NotFound

        try:
            self._blob(scene_id, name).delete()
        except NotFound:
            pass


class FirestoreStillMarker:
    def __init__(self, project: str | None = None):
        from google.cloud import firestore

        self._db = firestore.Client(project=project)

    def _doc(self, scene_id: str):
        return self._db.collection(SCENES_COLLECTION).document(scene_id)

    def scene_exists(self, scene_id: str) -> bool:
        return self._doc(scene_id).get(field_paths=["status"]).exists

    def mark(self, scene_id: str, *, night: bool) -> bool:
        from google.api_core.exceptions import NotFound

        try:
            self._doc(scene_id).update({"still": {"night": night, "rendered_at": datetime.now(timezone.utc)}})
        except NotFound:
            return False
        return True


class InMemoryStillStore:
    """{(scene_id, name): bytes}. JSON documents are stored as their bytes too."""

    def __init__(self, blobs: dict[tuple[str, str], bytes] | None = None):
        self.blobs = dict(blobs or {})
        self.content_types: dict[tuple[str, str], str] = {}

    def read_json(self, scene_id: str, name: str) -> dict | None:
        raw = self.blobs.get((scene_id, name))
        return None if raw is None else json.loads(raw)

    def put(self, scene_id: str, name: str, data: bytes, content_type: str) -> None:
        self.blobs[(scene_id, name)] = data
        self.content_types[(scene_id, name)] = content_type

    def delete(self, scene_id: str, name: str) -> None:
        self.blobs.pop((scene_id, name), None)


class InMemoryStillMarker:
    """{scene_id: document dict}; `delete_on_mark` simulates the room being
    deleted while it was being drawn."""

    def __init__(self, scenes: dict[str, dict] | None = None, *, delete_on_mark: bool = False):
        self.scenes = {k: dict(v) for k, v in (scenes or {}).items()}
        self.delete_on_mark = delete_on_mark

    def scene_exists(self, scene_id: str) -> bool:
        return scene_id in self.scenes

    def mark(self, scene_id: str, *, night: bool) -> bool:
        if self.delete_on_mark:
            self.scenes.pop(scene_id, None)
        if scene_id not in self.scenes:
            return False
        self.scenes[scene_id]["still"] = {"night": night, "rendered_at": datetime.now(timezone.utc)}
        return True
