"""TestClient tests for the room guide's routes (decision 0376).

GET  /scenes/{scene_id}/guide         the conversation and the room as it stands
POST /scenes/{scene_id}/guide/turns   one streamed turn (SSE)
POST /scenes/{scene_id}/guide/show    "Show me" on a card
POST /scenes/{scene_id}/guide/undo    "Put it back"

Covers:
  - a room without scene.json has no guide (404 no_guide), and every gate the
    guest's routes have: auth, ownership, readiness, ids
  - the opening: streamed, kept, the rules pass run once and kept as needs.json
  - the next turn carries the kept conversation exactly as it was returned
  - cards: "Show me" plays a checked plan, the guide hears what is on screen,
    "Put it back" is one step, stale and repeated presses are refused
  - the guide playing a move itself
  - the guarantees: one turn at a time (buttons included), the daily budget,
    a repeated client_msg_id replays, an opening happens once
  - failures reach the panel as an error event, release the lease and keep
    nothing; a turn past its time is told to stop and lets go when it does
  - only the two allowed models

The model is the gateway's stub mode playing a script (tests/guide_fixtures.py):
no network, no credentials, no room data.

Run from repo root:
  pytest services/api-public/tests/test_guide_routes.py -v
"""
from __future__ import annotations

import json
import time
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from unittest.mock import patch

import public_server as server
import pytest
from auth import NullTokenVerifier
from fastapi.testclient import TestClient
from guide_fixtures import Script, StubGateway, look_then_offer, study_scene, text, tool
from guide_repo import InMemoryGuideRepository
from public_server import InMemoryManifestFetcher
from thegoodguest_api_core.scene import Scene, SceneStatus
from thegoodguest_api_core.scene_read_repo import InMemorySceneReadRepository

UID = "user-abc"
DIR = "gs://outputs/scenes/s1"
NOW = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)


def make_scene(user_id: str | None = UID, status: SceneStatus = SceneStatus.READY) -> Scene:
    bundle_id = str(uuid.uuid4())
    return Scene(scene_id=str(uuid.uuid4()), device_id="device-1", status=status,
                 bundle_uri=f"gs://thegoodguest-captures/captures/{bundle_id}/bundle.pb",
                 created_at=NOW, updated_at=NOW, bundle_id=bundle_id, user_id=user_id,
                 result_uri=f"{DIR}/manifest.json" if status == SceneStatus.READY else None)


@contextmanager
def wired(scene: Scene, script: Script | None = None, *, repo=None, with_scene=True, daily=2.0,
          model="claude-opus-5-5", timeout=None):
    fetcher = InMemoryManifestFetcher({f"{DIR}/manifest.json": b'{"objects": []}'})
    if with_scene:
        fetcher.store[f"{DIR}/scene.json"] = json.dumps(study_scene()).encode()
    script = script if script is not None else Script([])
    patches = [
        patch.object(server, "_token_verifier", NullTokenVerifier()),
        patch.object(server, "_scene_read_repo", InMemorySceneReadRepository({scene.scene_id: scene})),
        patch.object(server, "_manifest_fetcher", fetcher),
        patch.object(server, "_guide_repo", repo if repo is not None else InMemoryGuideRepository()),
        patch.object(server, "GUIDE_LLM", "stub"),
        patch.object(server, "_guide_gateway", lambda work, remaining: StubGateway(
            work, mode="stub", stub=script, budget_usd=max(0.0, remaining))),
        patch.object(server, "GUIDE_DAILY_USD", daily),
        patch.object(server, "GUIDE_MODEL", model),
    ]
    if timeout is not None:
        patches.append(patch.object(server, "GUIDE_TURN_TIMEOUT_S", timeout))
    for p in patches:
        p.start()
    try:
        yield fetcher
    finally:
        for p in reversed(patches):
            p.stop()


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(server.app)


def auth(uid: str = UID) -> dict:
    return {"Authorization": f"Bearer test-uid:{uid}"}


def events_of(body: str) -> list[tuple[str, dict | None]]:
    out = []
    for block in body.split("\n\n"):
        block = block.strip("\n")
        if not block or block.startswith(":"):
            continue
        name = data = None
        for line in block.split("\n"):
            if line.startswith("event: "):
                name = line[len("event: "):]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: "):])
        out.append((name, data))
    return out


def turn(client, scene, *, text_="", opening=False, cmid=None, uid=UID):
    body = {"client_msg_id": cmid or str(uuid.uuid4()), "text": text_, "opening": opening}
    return client.post(f"/scenes/{scene.scene_id}/guide/turns", json=body, headers=auth(uid))


def opening_with_a_card(i: int = 1) -> list:
    return [*look_then_offer(i), text("The desk faces the wall, so the window is behind you. Want to see it turned?")]


def open_room(client, scene) -> tuple[list, dict]:
    resp = turn(client, scene, opening=True)
    assert resp.status_code == 200, resp.text
    events = events_of(resp.text)
    card = next(d for k, d in events if k == "card")
    return events, card


# ---------------------------------------------------------------------------
# Which rooms have a guide, and who may reach it
# ---------------------------------------------------------------------------

class TestGates:
    def test_a_room_without_a_scene_has_no_guide(self, client):
        scene = make_scene()
        with wired(scene, with_scene=False):
            assert client.get(f"/scenes/{scene.scene_id}/guide", headers=auth()).json()["error"] == "no_guide"
            resp = turn(client, scene, opening=True)
            assert resp.status_code == 404 and resp.json()["error"] == "no_guide"

    def test_before_any_turn(self, client):
        scene = make_scene()
        with wired(scene):
            body = client.get(f"/scenes/{scene.scene_id}/guide", headers=auth()).json()
        assert body["turn_count"] == 0 and body["transcript"] == []
        assert body["state"] == {"poses": {}, "can_undo": False, "cards": {}}
        assert body["rested_until"] is None and body["busy"] is False
        assert body["room"].startswith("Study, ")
        assert body["floor_m2"] == 14.4

    @pytest.mark.parametrize("path,method", [("/guide", "get"), ("/guide/turns", "post"),
                                             ("/guide/show", "post"), ("/guide/undo", "post")])
    def test_the_guests_gates(self, client, path, method):
        scene = make_scene()
        body = {"client_msg_id": str(uuid.uuid4()), "opening": True, "proposal_id": "x"}

        def call(sid=scene.scene_id, headers=None):
            return getattr(client, method)(f"/scenes/{sid}{path}", headers=headers or auth(),
                                           **({"json": body} if method == "post" else {}))

        with wired(scene):
            assert call(headers={"Authorization": "Bearer nope"}).status_code == 401
            assert call(sid="not-a-uuid").json()["error"] == "invalid_scene_id"
            assert call(sid=str(uuid.uuid4())).status_code == 404
            assert call(headers=auth("someone-else")).status_code == 403
        processing = make_scene(status=SceneStatus.PROCESSING)
        with wired(processing):
            resp = call(sid=processing.scene_id)
            assert resp.status_code == 409 and resp.json()["error"] == "scene_not_ready"

    def test_turn_bodies_are_checked(self, client):
        scene = make_scene()
        with wired(scene):
            assert turn(client, scene, opening=True, text_="hi").json()["error"] == "invalid_turn"
            assert turn(client, scene, text_="   ").json()["error"] == "message_empty"
            assert turn(client, scene, text_="x" * 2001).json()["error"] == "message_too_long"
            assert turn(client, scene, opening=True, cmid="nope").json()["error"] == "invalid_client_msg_id"

    def test_an_unreadable_scene_is_an_upstream_error(self, client):
        scene = make_scene()
        with wired(scene) as fetcher:
            fetcher.store[f"{DIR}/scene.json"] = b"{ not json"
            resp = client.get(f"/scenes/{scene.scene_id}/guide", headers=auth())
        assert resp.status_code == 502 and resp.json()["error"] == "upstream_error"


# ---------------------------------------------------------------------------
# Turns
# ---------------------------------------------------------------------------

class TestTurns:
    def test_the_opening_is_streamed_and_kept(self, client):
        scene = make_scene()
        script = Script(opening_with_a_card())
        with wired(scene, script) as fetcher:
            events, card = open_room(client, scene)
            body = client.get(f"/scenes/{scene.scene_id}/guide", headers=auth()).json()
        kinds = [k for k, _ in events]
        assert kinds[0] == "note" and "delta" in kinds and kinds[-1] == "done"
        assert card["status"] == "ready" and card["words"]
        done = events[-1][1]
        assert done["turn"]["turn_index"] == 0 and done["state"]["cards"] == {card["id"]: "ready"}

        assert script.rules_calls == 1 and f"{DIR}/needs.json" in fetcher.store
        first = script.requests[0].messages[0]["content"]
        assert first[0]["type"] == "image", "the first turn shows the guide the plan"

        assert body["turn_count"] == 1
        t0 = body["transcript"][0]
        assert t0["opening"] is True and t0["person"] is None
        assert [i["kind"] for i in t0["items"]] == ["note", "card", "say"]
        assert t0["items"][1]["card"]["status"] == "ready"
        assert t0["items"][2]["text"].startswith("The desk faces the wall")

    def test_the_next_turn_carries_the_conversation_exactly(self, client):
        scene = make_scene()
        repo = InMemoryGuideRepository()
        script = Script([*opening_with_a_card(), text("It's the window behind you that bothers me.")])
        with wired(scene, script, repo=repo):
            open_room(client, scene)
            kept = json.loads(repo.turns(scene.scene_id, UID, 10)[0].messages_json)
            resp = turn(client, scene, text_="Why?")
        assert resp.status_code == 200 and events_of(resp.text)[-1][0] == "done"
        sent = script.requests[-1].messages
        assert sent[:len(kept)] == kept, "every block goes back exactly as it was kept"
        assert sent[len(kept)] == {"role": "user", "content": [{"type": "text", "text": "Why?"}]}
        assert script.rules_calls == 1, "needs.json answers every turn after the first"

    def test_the_guide_plays_a_move_itself(self, client):
        scene = make_scene()
        script = Script([
            tool("move", {"piece": "desk", "how": "wall", "target": "wall_-z"}, 1),
            tool("show", lambda req: {"proposal": json.loads(
                req.messages[-1]["content"][-1]["content"])["proposal"]["id"]}, 2),
            text("I've moved the desk against the other wall."),
        ])
        with wired(scene, script):
            resp = turn(client, scene, opening=True)
            body = client.get(f"/scenes/{scene.scene_id}/guide", headers=auth()).json()
        play = next(d for k, d in events_of(resp.text) if k == "play")
        assert play["plan"]["easing"] == "smoothstep" and "desk" in play["plan"]["tracks"]
        assert play["state"]["can_undo"] is True
        assert "desk" in body["state"]["poses"] and body["state"]["can_undo"] is True

    def test_a_repeated_client_msg_id_replays(self, client):
        scene = make_scene()
        script = Script(opening_with_a_card())
        cmid = str(uuid.uuid4())
        with wired(scene, script):
            first = events_of(turn(client, scene, opening=True, cmid=cmid).text)
            asked = len(script.requests)
            again = events_of(turn(client, scene, opening=True, cmid=cmid).text)
        assert len(script.requests) == asked, "a replay never asks again"
        said = lambda evs: "".join(d["text"] for k, d in evs if k == "delta")  # noqa: E731
        assert said(again) == said(first) and again[-1][0] == "done"
        assert [d["id"] for k, d in again if k == "card"] == [d["id"] for k, d in first if k == "card"]

    def test_an_opening_happens_once(self, client):
        scene = make_scene()
        with wired(scene, Script(opening_with_a_card())):
            open_room(client, scene)
            resp = turn(client, scene, opening=True)
        assert resp.status_code == 409 and resp.json()["error"] == "already_open"


# ---------------------------------------------------------------------------
# The panel's two buttons
# ---------------------------------------------------------------------------

class TestButtons:
    def test_show_me_and_put_it_back(self, client):
        scene = make_scene()
        sid = scene.scene_id
        with wired(scene, Script(opening_with_a_card())):
            _, card = open_room(client, scene)
            shown = client.post(f"/scenes/{sid}/guide/show", json={"proposal_id": card["id"]}, headers=auth())
            assert shown.status_code == 200, shown.text
            plan, state = shown.json()["plan"], shown.json()["state"]
            assert plan["plan_version"] == 1 and plan["tracks"] and plan["footprints"]
            assert state["cards"][card["id"]] == "shown" and state["can_undo"] is True
            assert client.get(f"/scenes/{sid}/guide", headers=auth()).json()["state"]["poses"]

            again = client.post(f"/scenes/{sid}/guide/show", json={"proposal_id": card["id"]}, headers=auth())
            assert again.status_code == 409 and again.json()["error"] == "proposal_shown"

            back = client.post(f"/scenes/{sid}/guide/undo", headers=auth())
            assert back.status_code == 200 and back.json()["plan"]["tracks"]
            assert back.json()["state"] == {"poses": {}, "can_undo": False, "cards": {card["id"]: "ready"}}
            nothing = client.post(f"/scenes/{sid}/guide/undo", headers=auth())
            assert nothing.status_code == 409 and nothing.json()["error"] == "nothing_to_undo"

            unknown = client.post(f"/scenes/{sid}/guide/show", json={"proposal_id": "nope"}, headers=auth())
            assert unknown.status_code == 404 and unknown.json()["error"] == "no_such_proposal"

    def test_the_guide_hears_what_the_button_put_on_screen(self, client):
        scene = make_scene()
        script = Script([*opening_with_a_card(), text("That reads better.")])
        with wired(scene, script):
            _, card = open_room(client, scene)
            client.post(f"/scenes/{scene.scene_id}/guide/show", json={"proposal_id": card["id"]}, headers=auth())
            turn(client, scene, text_="What do you think?")
        brief = script.requests[-1].system[1]["text"]
        on_screen = brief.split("ON THEIR SCREEN NOW", 1)[1]
        assert card["words"][0] in on_screen


# ---------------------------------------------------------------------------
# The guest's guarantees
# ---------------------------------------------------------------------------

class TestGuarantees:
    def test_one_turn_at_a_time_buttons_included(self, client):
        scene = make_scene()
        repo = InMemoryGuideRepository()
        repo.take_lease(scene.scene_id, UID, "someone", ttl_s=150, now=datetime.now(tz=UTC))
        with wired(scene, repo=repo):
            assert turn(client, scene, opening=True).json()["error"] == "turn_in_flight"
            assert client.post(f"/scenes/{scene.scene_id}/guide/show", json={"proposal_id": "x"},
                               headers=auth()).json()["error"] == "turn_in_flight"
            assert client.post(f"/scenes/{scene.scene_id}/guide/undo",
                               headers=auth()).json()["error"] == "turn_in_flight"
            assert client.get(f"/scenes/{scene.scene_id}/guide", headers=auth()).json()["busy"] is True

    def test_a_spent_day_rests(self, client):
        scene = make_scene()
        repo = InMemoryGuideRepository()
        repo.charge(UID, 2.0, datetime.now(tz=UTC))
        with wired(scene, repo=repo, daily=2.0):
            resp = turn(client, scene, opening=True)
            body = client.get(f"/scenes/{scene.scene_id}/guide", headers=auth()).json()
        assert resp.status_code == 429
        assert resp.json()["error"] == "budget_exhausted"
        assert resp.json()["guest_line"] == server.GUEST_REST_LINE and resp.json()["resets_at"]
        assert body["rested_until"] == resp.json()["resets_at"]

    def test_a_turn_is_charged_to_the_persons_day(self, client):
        scene = make_scene()
        repo = InMemoryGuideRepository()
        with wired(scene, Script(opening_with_a_card()), repo=repo):
            open_room(client, scene)
        assert repo.spent_today(UID, datetime.now(tz=UTC)) > 0

    def test_a_failed_turn_says_so_keeps_nothing_and_lets_go(self, client):
        scene = make_scene()
        repo = InMemoryGuideRepository()

        def boom(req):
            raise RuntimeError("the model fell over")

        with wired(scene, Script([boom, text("Second time lucky.")]), repo=repo):
            resp = turn(client, scene, opening=True)
            assert events_of(resp.text)[-1] == ("error", {"code": "turn_failed"})
            assert repo.get(scene.scene_id, UID).active is None and repo.turns(scene.scene_id, UID, 5) == []
            again = turn(client, scene, opening=True)
        assert events_of(again.text)[-1][0] == "done"

    def test_only_the_two_allowed_models(self, client):
        scene = make_scene()
        with wired(scene, Script([text("hello")]), model="claude-haiku-5-5"):
            resp = turn(client, scene, opening=True)
        assert events_of(resp.text)[-1] == ("error", {"code": "model_not_allowed"})

    def test_a_turn_past_its_time_stops_and_lets_go(self, client):
        scene = make_scene()
        repo = InMemoryGuideRepository()

        def slow(req):
            time.sleep(0.8)
            return [{"type": "text", "text": "Sorry, I was miles away."}]

        with wired(scene, Script([slow]), repo=repo, timeout=0.2):
            resp = turn(client, scene, opening=True)
            assert events_of(resp.text)[-1] == ("error", {"code": "model_timeout"})
            deadline = time.monotonic() + 5
            while repo.get(scene.scene_id, UID).active is not None and time.monotonic() < deadline:
                time.sleep(0.05)
        assert repo.get(scene.scene_id, UID).active is None, "the worker lets go when it stops"
        assert repo.turns(scene.scene_id, UID, 5) == [], "a turn the panel was told failed is not kept"
