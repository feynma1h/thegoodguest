"""Tests for GET /scenes (list the caller's scenes).

Covers:
  - 200 with the per-scene shape shared with /scenes/by-bundle
  - newest-first ordering
  - only the caller's scenes appear (isolation)
  - empty list is 200 {"scenes": []}, not 404
  - limit: applied, and 400 invalid_limit outside 1..100
  - 401 missing_token / invalid_token

NullTokenVerifier is used for all tests (accepts "test-uid:<uid>" tokens).
InMemorySceneReadRepository is injected directly — no Firestore.

Run from repo root:
  pytest services/api-public/tests/test_scenes_list.py -v
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import public_server as server
from auth import NullTokenVerifier  # noqa: E402
from thegoodguest_api_core.scene import Scene, SceneStatus  # noqa: E402
from thegoodguest_api_core.scene_read_repo import InMemorySceneReadRepository  # noqa: E402

_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _make_scene(user_id: str = "user-abc", minute: int = 0,
                status: SceneStatus = SceneStatus.QUEUED) -> Scene:
    bundle_id = str(uuid.uuid4())
    return Scene(
        scene_id=str(uuid.uuid4()),
        device_id="device-1",
        status=status,
        bundle_uri=f"gs://roomstudio-captures/captures/{bundle_id}/bundle.pb",
        created_at=_NOW.replace(minute=minute),
        updated_at=_NOW.replace(minute=minute),
        bundle_id=bundle_id,
        user_id=user_id,
    )


def _list(client: TestClient, scenes: list[Scene] = (), uid: str = "user-abc",
          query: str = "", headers: dict | None = None):
    repo = InMemorySceneReadRepository({s.scene_id: s for s in scenes})
    if headers is None:
        headers = {"Authorization": f"Bearer test-uid:{uid}"}
    with (
        patch.object(server, "_token_verifier", NullTokenVerifier()),
        patch.object(server, "_scene_read_repo", repo),
    ):
        return client.get(f"/scenes{query}", headers=headers)


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(server.app)


class TestListScenesHappyPath:
    def test_returns_owned_scenes_with_shared_shape(self, client) -> None:
        scene = _make_scene(minute=5, status=SceneStatus.READY)
        scene.result_uri = "gs://outputs/scenes/x/manifest.json"
        resp = _list(client, [scene])
        assert resp.status_code == 200
        body = resp.json()
        assert list(body.keys()) == ["scenes"]
        (entry,) = body["scenes"]
        assert entry == {
            "scene_id": scene.scene_id,
            "bundle_id": scene.bundle_id,
            "status": "ready",
            "result_uri": scene.result_uri,
            "missing_paths": None,
            "created_at": scene.created_at.isoformat(),
            "updated_at": scene.updated_at.isoformat(),
        }

    def test_newest_first(self, client) -> None:
        scenes = [_make_scene(minute=m) for m in (10, 40, 25)]
        resp = _list(client, scenes)
        minutes = [e["created_at"][14:16] for e in resp.json()["scenes"]]
        assert minutes == ["40", "25", "10"]

    def test_other_users_scenes_excluded(self, client) -> None:
        mine = _make_scene(user_id="user-abc")
        theirs = _make_scene(user_id="someone-else", minute=30)
        resp = _list(client, [mine, theirs])
        assert [e["scene_id"] for e in resp.json()["scenes"]] == [mine.scene_id]

    def test_no_scenes_is_empty_200(self, client) -> None:
        resp = _list(client, [])
        assert resp.status_code == 200
        assert resp.json() == {"scenes": []}


class TestListScenesLimit:
    def test_limit_applied(self, client) -> None:
        scenes = [_make_scene(minute=m) for m in range(10)]
        resp = _list(client, scenes, query="?limit=4")
        assert len(resp.json()["scenes"]) == 4

    @pytest.mark.parametrize("bad", ["0", "101", "-3"])
    def test_limit_out_of_range_is_400(self, client, bad) -> None:
        resp = _list(client, [], query=f"?limit={bad}")
        assert resp.status_code == 400
        assert resp.json()["error"] == "invalid_limit"


class TestListScenesAuth:
    def test_missing_header_is_422_from_fastapi(self, client) -> None:
        # Header(...) is required; FastAPI rejects before the handler runs.
        with patch.object(server, "_token_verifier", NullTokenVerifier()):
            resp = client.get("/scenes")
        assert resp.status_code == 422

    def test_non_bearer_header_is_401(self, client) -> None:
        resp = _list(client, [], headers={"Authorization": "Basic xyz"})
        assert resp.status_code == 401
        assert resp.json()["error"] == "missing_token"

    def test_invalid_token_is_401(self, client) -> None:
        resp = _list(client, [], headers={"Authorization": "Bearer garbage"})
        assert resp.status_code == 401
        assert resp.json()["error"] == "invalid_token"
