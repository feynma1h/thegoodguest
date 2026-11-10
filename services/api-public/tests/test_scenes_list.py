"""Tests for GET /scenes (list the caller's scenes).

Covers:
  - 200 with the per-scene shape shared with /scenes/by-bundle
  - still_url / still_night_url from the scene's marker alone (decision 0363):
    signed when present, null otherwise, never a bucket call
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
        bundle_uri=f"gs://thegoodguest-captures/captures/{bundle_id}/bundle.pb",
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
            "still_url": None,
            "still_night_url": None,
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


class _Signer:
    """Records what it signed; `fail` makes every signature raise."""

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[str] = []

    def sign(self, gs_uri: str, ttl_seconds: int) -> str:
        if self.fail:
            raise RuntimeError("signblob unavailable")
        assert ttl_seconds == server._ASSET_URL_TTL_SECONDS
        self.calls.append(gs_uri)
        return "https://signed.example/" + gs_uri[5:] + "?sig=1"


class _NoBucket:
    """Listing rooms must not ask the bucket anything about stills."""

    def __getattr__(self, name):
        raise AssertionError(f"the bucket was asked: {name}")


def _ready(minute: int = 0, still: dict | None = None) -> Scene:
    scene = _make_scene(minute=minute, status=SceneStatus.READY)
    scene.result_uri = f"gs://outputs/scenes/{scene.scene_id}/manifest.json"
    scene.still = still
    return scene


def _list_signed(client, scenes, signer):
    with patch.object(server, "_url_signer", signer), patch.object(server, "_manifest_fetcher", _NoBucket()):
        return _list(client, scenes)


class TestListScenesStills:
    def test_a_room_with_a_day_still_gets_one_link_and_no_night(self, client) -> None:
        scene = _ready(still={"night": False, "rendered_at": _NOW})
        signer = _Signer()
        (entry,) = _list_signed(client, [scene], signer).json()["scenes"]
        assert entry["still_url"] == f"https://signed.example/outputs/scenes/{scene.scene_id}/still.jpg?sig=1"
        assert entry["still_night_url"] is None
        assert signer.calls == [f"gs://outputs/scenes/{scene.scene_id}/still.jpg"]

    def test_a_room_with_twins_gets_day_and_night(self, client) -> None:
        scene = _ready(still={"night": True, "rendered_at": _NOW})
        (entry,) = _list_signed(client, [scene], _Signer()).json()["scenes"]
        assert entry["still_url"].endswith(f"/scenes/{scene.scene_id}/still.jpg?sig=1")
        assert entry["still_night_url"].endswith(f"/scenes/{scene.scene_id}/still-night.jpg?sig=1")

    def test_rooms_without_a_marker_are_null_and_cost_no_signature(self, client) -> None:
        drawn = _ready(minute=30, still={"night": False, "rendered_at": _NOW})
        waiting = _ready(minute=20)
        queued = _make_scene(minute=10)
        signer = _Signer()
        entries = _list_signed(client, [drawn, waiting, queued], signer).json()["scenes"]
        assert [e["still_url"] is not None for e in entries] == [True, False, False]
        assert all(e["still_night_url"] is None for e in entries)
        assert signer.calls == [f"gs://outputs/scenes/{drawn.scene_id}/still.jpg"]

    def test_a_signing_failure_is_a_null_link_not_an_error(self, client) -> None:
        scene = _ready(still={"night": True, "rendered_at": _NOW})
        resp = _list_signed(client, [scene], _Signer(fail=True))
        assert resp.status_code == 200
        (entry,) = resp.json()["scenes"]
        assert (entry["still_url"], entry["still_night_url"]) == (None, None)

    def test_every_room_in_a_list_is_signed(self, client) -> None:
        scenes = [_ready(minute=m, still={"night": m % 2 == 0, "rendered_at": _NOW}) for m in range(12)]
        signer = _Signer()
        entries = _list_signed(client, scenes, signer).json()["scenes"]
        assert all(e["still_url"] for e in entries)
        assert sum(1 for e in entries if e["still_night_url"]) == 6
        assert len(signer.calls) == 18
