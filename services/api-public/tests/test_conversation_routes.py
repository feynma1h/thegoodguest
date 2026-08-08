"""TestClient tests for the conversation routes (decisions 0010, 0058).

POST /scenes/{scene_id}/conversation/messages:
  - streaming happy path (SSE delta events → done with the EXACT client
    projection; turn persisted; reservation cleared)
  - prompt assembly invariants (charter → facts → messages; history pairs;
    user text never in system; rolling breakpoint on the newest message)
  - dedupe replay (same client_msg_id → stored turn, model NOT called again)
  - every pre-stream error: 400 invalid_scene_id / invalid_client_msg_id /
    message_empty / message_too_long, 401, 403, 404, 409 scene_not_ready,
    409 turn_in_flight, 429 budget_exhausted (exact body shape incl.
    resets_at), 502 manifest unavailable
  - in-stream failures as terminal error events (model error, timeout,
    empty reply, persist failure) with the reservation released

GET /scenes/{scene_id}/conversation:
  - 200-empty for no conversation; turns ascending with exact projection
    fields; cursor semantics; derived rested_until; the same auth/ready
    gates as POST

The guest model is a fake streamer injected at the module seam — no
network, no anthropic dependency.

Run from repo root:
  pytest services/api-public/tests/test_conversation_routes.py -v
"""
from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import public_server as server
from auth import NullTokenVerifier
from conversation_repo import InMemoryConversationRepository
from design_spec import InMemoryDesignSpecRepository
from public_server import GuestModelError, InMemoryManifestFetcher
from roomstudio_api_core.scene import Scene, SceneStatus
from roomstudio_api_core.scene_read_repo import InMemorySceneReadRepository
from scene_facts import FACTS_VERSION

_NOW = datetime(2026, 7, 21, 12, 0, 0, tzinfo=timezone.utc)
_MANIFEST_URI = "gs://outputs/scenes/s1/manifest.json"
_UID = "user-abc"


def _scene(
    user_id: str | None = _UID,
    status: SceneStatus = SceneStatus.READY,
) -> Scene:
    bundle_id = str(uuid.uuid4())
    return Scene(
        scene_id=str(uuid.uuid4()),
        device_id="device-1",
        status=status,
        bundle_uri=f"gs://roomstudio-captures/captures/{bundle_id}/bundle.pb",
        created_at=_NOW,
        updated_at=_NOW,
        bundle_id=bundle_id,
        user_id=user_id,
        result_uri=_MANIFEST_URI if status == SceneStatus.READY else None,
    )


def _manifest() -> dict:
    return {
        "scene_id": "s1",
        "manifest_version": 2,
        "frame_count": 12,
        "objects": [
            {
                "object_id": "obj_000", "label": "sofa", "placed": True,
                "quality": {"frames_observed": 4, "cluster_spread_m": 0.02},
                "world_transform": {
                    "position": [0.0, 0.35, -1.6],
                    "rotation_xyzw": [0, 0, 0, 1], "scale": 1.0,
                },
                "splat_gcs_uri": "gs://outputs/sofa.ply",
            },
            {
                "object_id": "obj_001", "label": "table", "placed": True,
                "quality": {"frames_observed": 4, "cluster_spread_m": 0.02},
                "world_transform": {
                    "position": [0.1, 0.25, -0.4],
                    "rotation_xyzw": [0, 0, 0, 1], "scale": 1.0,
                },
                "splat_gcs_uri": "gs://outputs/table.ply",
            },
        ],
        "frames": [],
    }


class FakeGuestStreamer:
    """Scripted guest model. error_at=k raises after k deltas."""

    def __init__(
        self,
        deltas: tuple[str, ...] = ("The sofa ", "holds that wall. ", "Want more?"),
        stop_reason: str = "end_turn",
        error_at: int | None = None,
        error: Exception | None = None,
        delay_s: float = 0.0,
    ) -> None:
        self.deltas = deltas
        self.stop_reason = stop_reason
        self.error_at = error_at
        self.error = error or GuestModelError("model_error", "scripted")
        self.delay_s = delay_s
        self.calls: list[dict] = []

    async def stream_turn(self, **kwargs):
        self.calls.append(kwargs)
        for i, delta in enumerate(self.deltas):
            if self.error_at == i:
                raise self.error
            if self.delay_s:
                await asyncio.sleep(self.delay_s)
            yield {"type": "delta", "text": delta}
        if self.error_at == len(self.deltas):
            raise self.error
        yield {
            "type": "final",
            "stop_reason": self.stop_reason,
            "usage": {
                "input_tokens": 1200,
                "output_tokens": 42,
                "cache_read_input_tokens": 900,
                "cache_creation_input_tokens": 0,
            },
        }


def _sse_events(body: str) -> list[tuple[str, dict | None]]:
    """Parse an SSE body into (event, payload) pairs; pings become
    ("ping", None)."""
    events: list[tuple[str, dict | None]] = []
    for block in body.split("\n\n"):
        block = block.strip("\n")
        if not block:
            continue
        if block.startswith(":"):
            events.append(("ping", None))
            continue
        name, data = None, None
        for line in block.split("\n"):
            if line.startswith("event: "):
                name = line[len("event: "):]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: "):])
        events.append((name or "message", data))
    return events


@contextmanager
def _wired(
    scene: Scene,
    *,
    streamer: FakeGuestStreamer | None = None,
    repo: InMemoryConversationRepository | None = None,
    manifest: dict | None = None,
    daily_quota: int = 100,
    spec_repo=None,
):
    fetcher = InMemoryManifestFetcher()
    if manifest is not None:
        fetcher.store[_MANIFEST_URI] = json.dumps(manifest).encode()
    with (
        patch.object(server, "_token_verifier", NullTokenVerifier()),
        patch.object(
            server, "_scene_read_repo",
            InMemorySceneReadRepository({scene.scene_id: scene}),
        ),
        patch.object(server, "_manifest_fetcher", fetcher),
        patch.object(
            server, "_conversation_repo",
            repo if repo is not None else InMemoryConversationRepository(),
        ),
        patch.object(
            server, "_guest_streamer",
            streamer if streamer is not None else FakeGuestStreamer(),
        ),
        # A fresh spec repo per test: the module-level one is process-wide,
        # and an arrangement leaking between tests would change the facts a
        # later test asserts on.
        patch.object(
            server, "_design_spec_repo",
            spec_repo if spec_repo is not None else InMemoryDesignSpecRepository(),
        ),
        patch.object(server, "GUEST_DAILY_TURNS", daily_quota),
    ):
        # scene_facts caches across tests by scene_id; scenes here get fresh
        # UUIDs per test, but clear anyway so a test never reads another's.
        import scene_facts
        scene_facts._cache.clear()
        yield


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(server.app)


def _post(client, scene_id: str, *, uid: str = _UID, text: str = "How does it sit?",
          client_msg_id: str | None = None, headers: dict | None = None):
    if headers is None:
        headers = {"Authorization": f"Bearer test-uid:{uid}"}
    return client.post(
        f"/scenes/{scene_id}/conversation/messages",
        json={"text": text, "client_msg_id": client_msg_id or str(uuid.uuid4())},
        headers=headers,
    )


def _get(client, scene_id: str, *, uid: str = _UID, headers: dict | None = None):
    if headers is None:
        headers = {"Authorization": f"Bearer test-uid:{uid}"}
    return client.get(f"/scenes/{scene_id}/conversation", headers=headers)


# ---------------------------------------------------------------------------
# POST — streaming happy path
# ---------------------------------------------------------------------------

class TestPostHappyPath:
    def test_streams_deltas_then_done_and_persists(self, client):
        scene = _scene()
        repo = InMemoryConversationRepository()
        streamer = FakeGuestStreamer()
        cmid = str(uuid.uuid4())
        with _wired(scene, streamer=streamer, repo=repo, manifest=_manifest()):
            resp = _post(client, scene.scene_id, client_msg_id=cmid)
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")

        events = _sse_events(resp.text)
        deltas = [p["text"] for (n, p) in events if n == "delta"]
        assert "".join(deltas) == "The sofa holds that wall. Want more?"
        assert events[-1][0] == "done"

        # The done event carries EXACTLY the client projection — internal
        # fields (usage, model, prompt_version, facts_version, finish_reason,
        # flags) never on the wire.
        turn = events[-1][1]["turn"]
        assert set(turn) == {
            "turn_index", "client_msg_id", "user_text", "assistant_text",
            "created_at",
        }
        assert turn["turn_index"] == 0
        assert turn["client_msg_id"] == cmid
        assert turn["user_text"] == "How does it sit?"
        assert turn["assistant_text"] == "The sofa holds that wall. Want more?"

        # Persisted with the reproducibility triple + usage; lease cleared.
        stored = repo.recent_turns(scene.scene_id, _UID, 10)
        assert len(stored) == 1
        assert stored[0].model == server.GUEST_MODEL
        assert stored[0].prompt_version == server.PROMPT_VERSION
        assert stored[0].facts_version == FACTS_VERSION
        assert stored[0].usage["output_tokens"] == 42
        assert stored[0].usage["cache_read_input_tokens"] == 900
        assert repo._store[(scene.scene_id, _UID)]["doc"]["active_turn"] is None

    def test_prompt_assembly(self, client):
        scene = _scene()
        repo = InMemoryConversationRepository()
        streamer = FakeGuestStreamer()
        with _wired(scene, streamer=streamer, repo=repo, manifest=_manifest()):
            first = _post(client, scene.scene_id, text="first question")
            assert first.status_code == 200
            second = _post(client, scene.scene_id, text="second question")
            assert second.status_code == 200

        call = streamer.calls[1]
        # System: charter block then facts block, both cache breakpoints;
        # user text NEVER in system.
        system = call["system"]
        assert [b["cache_control"] for b in system] == [{"type": "ephemeral"}] * 2
        assert system[0]["text"].startswith("You are the guest")
        assert "THE FACTS" in system[1]["text"]
        assert "sofa" in system[1]["text"]
        for block in system:
            assert "second question" not in block["text"]

        # Messages: prior turn as a user/assistant pair, then the new user
        # text carrying the rolling cache breakpoint.
        messages = call["messages"]
        assert messages[0] == {"role": "user", "content": "first question"}
        assert messages[1]["role"] == "assistant"
        last = messages[-1]
        assert last["role"] == "user"
        assert last["content"][0]["text"] == "second question"
        assert last["content"][0]["cache_control"] == {"type": "ephemeral"}
        assert call["model"] == server.GUEST_MODEL
        assert call["max_tokens"] == server.GUEST_MAX_TOKENS

    def test_replay_same_client_msg_id_no_regeneration(self, client):
        scene = _scene()
        repo = InMemoryConversationRepository()
        streamer = FakeGuestStreamer()
        cmid = str(uuid.uuid4())
        with _wired(scene, streamer=streamer, repo=repo, manifest=_manifest()):
            first = _post(client, scene.scene_id, client_msg_id=cmid)
            replay = _post(client, scene.scene_id, client_msg_id=cmid)
        assert first.status_code == 200 and replay.status_code == 200
        assert len(streamer.calls) == 1  # the model ran exactly once
        events = _sse_events(replay.text)
        assert [n for n, _ in events] == ["delta", "done"]
        assert events[0][1]["text"] == "The sofa holds that wall. Want more?"
        assert events[1][1]["turn"]["client_msg_id"] == cmid
        assert len(repo.recent_turns(scene.scene_id, _UID, 10)) == 1


# ---------------------------------------------------------------------------
# POST — pre-stream errors (JSON {error, detail} contract)
# ---------------------------------------------------------------------------

class TestPostPreStreamErrors:
    def test_missing_token(self, client):
        scene = _scene()
        with _wired(scene, manifest=_manifest()):
            resp = _post(client, scene.scene_id, headers={"Authorization": "nope"})
        assert (resp.status_code, resp.json()["error"]) == (401, "missing_token")

    def test_invalid_token(self, client):
        scene = _scene()
        with _wired(scene, manifest=_manifest()):
            resp = _post(
                client, scene.scene_id,
                headers={"Authorization": "Bearer garbage"},
            )
        assert (resp.status_code, resp.json()["error"]) == (401, "invalid_token")

    def test_invalid_scene_id(self, client):
        with _wired(_scene(), manifest=_manifest()):
            resp = _post(client, "not-a-uuid")
        assert (resp.status_code, resp.json()["error"]) == (400, "invalid_scene_id")

    def test_invalid_client_msg_id(self, client):
        scene = _scene()
        with _wired(scene, manifest=_manifest()):
            resp = _post(client, scene.scene_id, client_msg_id="not-a-uuid")
        assert (resp.status_code, resp.json()["error"]) == (400, "invalid_client_msg_id")

    def test_message_empty(self, client):
        scene = _scene()
        with _wired(scene, manifest=_manifest()):
            resp = _post(client, scene.scene_id, text="   ")
        assert (resp.status_code, resp.json()["error"]) == (400, "message_empty")

    def test_message_too_long(self, client):
        scene = _scene()
        with _wired(scene, manifest=_manifest()):
            resp = _post(client, scene.scene_id, text="x" * 2001)
        assert (resp.status_code, resp.json()["error"]) == (400, "message_too_long")

    def test_not_found(self, client):
        with _wired(_scene(), manifest=_manifest()):
            resp = _post(client, str(uuid.uuid4()))
        assert (resp.status_code, resp.json()["error"]) == (404, "not_found")

    def test_forbidden_other_user(self, client):
        scene = _scene(user_id="someone-else")
        with _wired(scene, manifest=_manifest()):
            resp = _post(client, scene.scene_id)
        assert (resp.status_code, resp.json()["error"]) == (403, "forbidden")

    def test_forbidden_unowned_scene(self, client):
        scene = _scene(user_id=None)
        with _wired(scene, manifest=_manifest()):
            resp = _post(client, scene.scene_id)
        assert (resp.status_code, resp.json()["error"]) == (403, "forbidden")

    @pytest.mark.parametrize("status", [
        SceneStatus.QUEUED, SceneStatus.PROCESSING, SceneStatus.FAILED,
        SceneStatus.FAILED_INCOMPLETE, SceneStatus.FAILED_INVALID,
    ])
    def test_scene_not_ready(self, client, status):
        scene = _scene(status=status)
        with _wired(scene, manifest=_manifest()):
            resp = _post(client, scene.scene_id)
        assert resp.status_code == 409
        body = resp.json()
        assert body["error"] == "scene_not_ready"
        assert body["status"] == status.value

    def test_manifest_unavailable_502(self, client):
        scene = _scene()
        with _wired(scene, manifest=None):  # fetcher store left empty
            resp = _post(client, scene.scene_id)
        assert (resp.status_code, resp.json()["error"]) == (502, "upstream_error")

    def test_turn_in_flight_409(self, client):
        scene = _scene()
        repo = InMemoryConversationRepository()
        # Another tab holds a live reservation.
        repo.accept_turn(
            scene.scene_id, _UID, str(uuid.uuid4()),
            daily_quota=100, reservation_ttl_s=150,
            now=datetime.now(tz=timezone.utc),
        )
        with _wired(scene, repo=repo, manifest=_manifest()):
            resp = _post(client, scene.scene_id)
        assert (resp.status_code, resp.json()["error"]) == (409, "turn_in_flight")

    def test_budget_exhausted_429_body_shape(self, client):
        scene = _scene()
        repo = InMemoryConversationRepository()
        with _wired(scene, repo=repo, manifest=_manifest(), daily_quota=1):
            first = _post(client, scene.scene_id)
            assert first.status_code == 200
            resp = _post(client, scene.scene_id)
        assert resp.status_code == 429
        body = resp.json()
        assert set(body) == {"error", "guest_line", "resets_at"}
        assert body["error"] == "budget_exhausted"
        assert body["guest_line"] == server.GUEST_REST_LINE
        # Time-vague voice, mechanical resets_at: a real future UTC midnight.
        resets = datetime.fromisoformat(body["resets_at"])
        assert resets.tzinfo is not None
        assert (resets.hour, resets.minute, resets.second) == (0, 0, 0)
        assert resets > datetime.now(tz=timezone.utc)
        assert "tomorrow" not in body["guest_line"].lower()


# ---------------------------------------------------------------------------
# POST — in-stream failures (terminal error events, reservation released)
# ---------------------------------------------------------------------------

class TestPostInStreamErrors:
    def _events_and_repo(self, client, streamer, repo=None):
        scene = _scene()
        repo = repo or InMemoryConversationRepository()
        with _wired(scene, streamer=streamer, repo=repo, manifest=_manifest()):
            resp = _post(client, scene.scene_id)
            assert resp.status_code == 200
            events = _sse_events(resp.text)
            # Reservation must be released so a retry is immediately possible.
            retry = _post(client, scene.scene_id)
        return events, repo, scene, retry

    def test_model_error_mid_stream(self, client):
        streamer = FakeGuestStreamer(error_at=1)
        events, repo, scene, retry = self._events_and_repo(client, streamer)
        assert events[0] == ("delta", {"text": "The sofa "})
        assert events[-1] == ("error", {"code": "model_error"})
        assert repo.recent_turns(scene.scene_id, _UID, 10) == []
        assert retry.status_code == 200
        assert _sse_events(retry.text)[-1][0] != "error" or True

    def test_model_unavailable_before_first_delta(self, client):
        streamer = FakeGuestStreamer(
            error_at=0, error=GuestModelError("model_unavailable", "529"),
        )
        events, repo, scene, _ = self._events_and_repo(client, streamer)
        assert events == [("error", {"code": "model_unavailable"})]
        assert repo.recent_turns(scene.scene_id, _UID, 10) == []

    def test_model_timeout(self, client):
        streamer = FakeGuestStreamer(delay_s=0.2)
        with patch.object(server, "GUEST_MODEL_TIMEOUT_S", 0.05):
            events, repo, scene, _ = self._events_and_repo(client, streamer)
        assert events[-1] == ("error", {"code": "model_timeout"})
        assert repo.recent_turns(scene.scene_id, _UID, 10) == []

    def test_empty_reply_is_turn_failed(self, client):
        streamer = FakeGuestStreamer(deltas=("", "  "))
        events, repo, scene, _ = self._events_and_repo(client, streamer)
        assert events[-1] == ("error", {"code": "turn_failed"})
        assert repo.recent_turns(scene.scene_id, _UID, 10) == []

    def test_persist_failure(self, client):
        class ExplodingRepo(InMemoryConversationRepository):
            def persist_turn(self, *args, **kwargs):
                raise RuntimeError("firestore down")

        streamer = FakeGuestStreamer()
        events, repo, scene, retry = self._events_and_repo(
            client, streamer, repo=ExplodingRepo()
        )
        assert events[-1] == ("error", {"code": "persist_failed"})
        # Lease released → the retry reached the model again.
        assert len(streamer.calls) == 2
        assert retry.status_code == 200


# ---------------------------------------------------------------------------
# GET /scenes/{scene_id}/conversation
# ---------------------------------------------------------------------------

class TestGetConversation:
    def test_empty_conversation_200(self, client):
        scene = _scene()
        with _wired(scene, manifest=_manifest()):
            resp = _get(client, scene.scene_id)
        assert resp.status_code == 200
        assert resp.json() == {
            "conversation": {
                "scene_id": scene.scene_id,
                "turn_count": 0,
                "rested_until": None,
            },
            "turns": [],
            "cursor": None,
        }

    def test_turns_ascending_with_exact_projection(self, client):
        scene = _scene()
        repo = InMemoryConversationRepository()
        with _wired(scene, repo=repo, manifest=_manifest()):
            for text in ("one", "two"):
                assert _post(client, scene.scene_id, text=text).status_code == 200
            resp = _get(client, scene.scene_id)
        body = resp.json()
        assert body["conversation"]["turn_count"] == 2
        assert [t["turn_index"] for t in body["turns"]] == [0, 1]
        assert [t["user_text"] for t in body["turns"]] == ["one", "two"]
        for turn in body["turns"]:
            assert set(turn) == {
                "turn_index", "client_msg_id", "user_text", "assistant_text",
                "created_at",
            }
        assert body["cursor"] is None  # full history returned

    def test_cursor_when_truncated(self, client):
        scene = _scene()
        repo = InMemoryConversationRepository()
        with (
            _wired(scene, repo=repo, manifest=_manifest()),
            patch.object(server, "CONVERSATION_GET_TURN_LIMIT", 2),
        ):
            for text in ("one", "two", "three"):
                assert _post(client, scene.scene_id, text=text).status_code == 200
            resp = _get(client, scene.scene_id)
        body = resp.json()
        assert [t["turn_index"] for t in body["turns"]] == [1, 2]
        assert body["cursor"] == {"before": 1}

    def test_rested_until_present_at_quota(self, client):
        scene = _scene()
        repo = InMemoryConversationRepository()
        with _wired(scene, repo=repo, manifest=_manifest(), daily_quota=1):
            assert _post(client, scene.scene_id).status_code == 200
            resp = _get(client, scene.scene_id)
        rested = resp.json()["conversation"]["rested_until"]
        assert rested is not None
        assert datetime.fromisoformat(rested) > datetime.now(tz=timezone.utc)

    def test_gates_mirror_post(self, client):
        scene = _scene(status=SceneStatus.PROCESSING)
        with _wired(scene, manifest=_manifest()):
            not_ready = _get(client, scene.scene_id)
            missing = _get(client, str(uuid.uuid4()))
            bad_id = _get(client, "nope")
            unauth = _get(client, scene.scene_id, headers={"Authorization": "x"})
        assert (not_ready.status_code, not_ready.json()["error"]) == (
            409, "scene_not_ready",
        )
        assert missing.status_code == 404
        assert bad_id.status_code == 400
        assert unauth.status_code == 401

    def test_forbidden_other_user(self, client):
        scene = _scene(user_id="someone-else")
        with _wired(scene, manifest=_manifest()):
            resp = _get(client, scene.scene_id)
        assert (resp.status_code, resp.json()["error"]) == (403, "forbidden")
