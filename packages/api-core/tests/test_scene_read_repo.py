"""Unit tests for thegoodguest_api_core.scene_read_repo.

Tests the module directly — no FastAPI, no HTTP, no GCP credentials.

Covers:
  SceneNotFoundError:
    - raised by InMemorySceneReadRepository.get() when scene is absent

  InMemorySceneReadRepository:
    - get: raises SceneNotFoundError for unknown scene_id
    - get: returns deep copy of stored scene
    - get_by_bundle_id: returns None for unknown bundle_id
    - get_by_bundle_id: returns matching scene by bundle_id
    - get_by_bundle_id: returns None after all scenes have different bundle_ids
    - pre-population: constructor dict is copied into the store
    - isolation: mutating a returned scene does not affect stored state
    - list_by_user: newest-first ordering, limit cap, other-user isolation,
      empty result, deep-copy isolation

Run from repo root:
  pytest packages/api-core/tests/test_scene_read_repo.py -v
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from thegoodguest_api_core.scene import Scene, SceneStatus
from thegoodguest_api_core.scene_read_repo import InMemorySceneReadRepository, SceneNotFoundError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _scene(bundle_id: str | None = None, user_id: str | None = "u1") -> Scene:
    sid = str(uuid.uuid4())
    return Scene(
        scene_id=sid,
        device_id="dev-1",
        status=SceneStatus.QUEUED,
        bundle_uri=f"gs://bucket/captures/{sid}/bundle.pb",
        created_at=_NOW,
        updated_at=_NOW,
        bundle_id=bundle_id or str(uuid.uuid4()),
        user_id=user_id,
    )


# ---------------------------------------------------------------------------
# SceneNotFoundError
# ---------------------------------------------------------------------------

class TestSceneNotFoundError:
    def test_get_raises_for_unknown_scene_id(self) -> None:
        repo = InMemorySceneReadRepository()
        with pytest.raises(SceneNotFoundError):
            repo.get("nonexistent-id")


# ---------------------------------------------------------------------------
# InMemorySceneReadRepository
# ---------------------------------------------------------------------------

class TestInMemorySceneReadRepository:
    def test_get_returns_stored_scene(self) -> None:
        scene = _scene()
        repo = InMemorySceneReadRepository({scene.scene_id: scene})
        result = repo.get(scene.scene_id)
        assert result.scene_id == scene.scene_id
        assert result.bundle_id == scene.bundle_id

    def test_get_returns_deep_copy(self) -> None:
        scene = _scene()
        repo = InMemorySceneReadRepository({scene.scene_id: scene})
        copy1 = repo.get(scene.scene_id)
        copy1.device_id = "mutated"
        copy2 = repo.get(scene.scene_id)
        assert copy2.device_id == "dev-1"

    def test_get_by_bundle_id_returns_none_when_absent(self) -> None:
        repo = InMemorySceneReadRepository()
        assert repo.get_by_bundle_id(str(uuid.uuid4())) is None

    def test_get_by_bundle_id_finds_matching_scene(self) -> None:
        bundle_id = str(uuid.uuid4())
        scene = _scene(bundle_id=bundle_id)
        repo = InMemorySceneReadRepository({scene.scene_id: scene})
        result = repo.get_by_bundle_id(bundle_id)
        assert result is not None
        assert result.scene_id == scene.scene_id

    def test_get_by_bundle_id_returns_none_when_no_match(self) -> None:
        scene = _scene(bundle_id=str(uuid.uuid4()))
        repo = InMemorySceneReadRepository({scene.scene_id: scene})
        assert repo.get_by_bundle_id(str(uuid.uuid4())) is None

    def test_empty_constructor_works(self) -> None:
        repo = InMemorySceneReadRepository()
        with pytest.raises(SceneNotFoundError):
            repo.get("any-id")

    def test_mutation_of_returned_scene_does_not_affect_store(self) -> None:
        bundle_id = str(uuid.uuid4())
        scene = _scene(bundle_id=bundle_id)
        repo = InMemorySceneReadRepository({scene.scene_id: scene})
        retrieved = repo.get_by_bundle_id(bundle_id)
        assert retrieved is not None
        retrieved.bundle_id = "mutated"
        again = repo.get_by_bundle_id(bundle_id)
        assert again is not None
        assert again.bundle_id == bundle_id


# ---------------------------------------------------------------------------
# list_by_user
# ---------------------------------------------------------------------------

class TestListByUser:
    def _scene_at(self, user_id: str, minute: int) -> Scene:
        s = _scene(user_id=user_id)
        s.created_at = _NOW.replace(minute=minute)
        return s

    def test_empty_for_unknown_user(self) -> None:
        repo = InMemorySceneReadRepository()
        assert repo.list_by_user("nobody") == []

    def test_newest_first_ordering(self) -> None:
        scenes = [self._scene_at("u1", m) for m in (5, 30, 15)]
        repo = InMemorySceneReadRepository({s.scene_id: s for s in scenes})
        out = repo.list_by_user("u1")
        minutes = [s.created_at.minute for s in out]
        assert minutes == [30, 15, 5]

    def test_limit_caps_results(self) -> None:
        scenes = [self._scene_at("u1", m) for m in range(10)]
        repo = InMemorySceneReadRepository({s.scene_id: s for s in scenes})
        out = repo.list_by_user("u1", limit=3)
        assert len(out) == 3
        # The cap keeps the NEWEST three, not an arbitrary three.
        assert [s.created_at.minute for s in out] == [9, 8, 7]

    def test_other_users_scenes_excluded(self) -> None:
        mine = self._scene_at("u1", 10)
        theirs = self._scene_at("u2", 20)
        repo = InMemorySceneReadRepository({
            mine.scene_id: mine, theirs.scene_id: theirs,
        })
        out = repo.list_by_user("u1")
        assert [s.scene_id for s in out] == [mine.scene_id]

    def test_returns_deep_copies(self) -> None:
        scene = self._scene_at("u1", 10)
        repo = InMemorySceneReadRepository({scene.scene_id: scene})
        repo.list_by_user("u1")[0].device_id = "mutated"
        assert repo.list_by_user("u1")[0].device_id == "dev-1"
