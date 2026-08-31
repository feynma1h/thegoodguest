"""TestClient tests for stage 2's routes and the tool loop (0131/0132/0133).

Three things get exercised here that no unit test can:

  - GET/DELETE /scenes/{id}/design_spec — including `orphaned`, the field
    that stops a re-drive from silently re-pointing an arrangement at the
    wrong furniture.
  - The TOOL LOOP through the real streaming turn: a scripted model emits
    tool_use, the server runs it, the room actually changes, and an
    `arrangement` SSE event tells the client to refetch.
  - That the guest reads the room AS IT NOW STANDS — facts re-derived from
    the proposed arrangement, with the block that makes rule 10 actionable.

The guest model is a fake streamer at the module seam: no network, no
anthropic dependency. It mimics the SDK shape the real streamer consumes
(content blocks with .type/.name/.input/.id).

Run from repo root:
  pytest services/api-public/tests/test_design_spec_routes.py -v
"""
from __future__ import annotations

import json
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import public_server as server
from auth import NullTokenVerifier
from conversation_repo import InMemoryConversationRepository
from design_spec import (
    DesignSpec,
    Footprint,
    InMemoryDesignSpecRepository,
    SolverTrace,
    SpecEntry,
    Transform,
)
from public_server import InMemoryManifestFetcher
from thegoodguest_api_core.scene import Scene, SceneStatus
from thegoodguest_api_core.scene_read_repo import InMemorySceneReadRepository

_NOW = datetime(2026, 8, 9, 12, 0, 0, tzinfo=timezone.utc)
_MANIFEST_URI = "gs://outputs/scenes/s1/manifest.json"
_SHELL_URI = "gs://outputs/scenes/s1/shell.json"
_UID = "user-abc"


def _scene(user_id: str | None = _UID, status=SceneStatus.READY) -> Scene:
    bundle_id = str(uuid.uuid4())
    return Scene(
        scene_id=str(uuid.uuid4()), device_id="d1", status=status,
        bundle_uri=f"gs://roomstudio-captures/captures/{bundle_id}/bundle.pb",
        created_at=_NOW, updated_at=_NOW, bundle_id=bundle_id, user_id=user_id,
        result_uri=_MANIFEST_URI if status == SceneStatus.READY else None,
    )


def _obj(oid, label, x, z, ident=None, w=1.0, d=1.0):
    """One placed, box-measured object at (x, 0.5, z)."""
    out = {
        "object_id": oid, "label": label, "placed": True,
        "quality": {"frames_observed": 4, "cluster_spread_m": 0.02},
        "world_transform": {
            "position": [x, 0.5, z], "rotation_xyzw": [0, 0, 0, 1], "scale": 1.0,
        },
        "splat_gcs_uri": f"gs://outputs/{oid}.ply",
    }
    if ident:
        out["roomplan_box"] = {
            "identifier": ident, "category": label, "confidence": "high",
            "dims": [w, 1.0, d], "yaw_rad": 0.0, "center_world": [x, 0.5, z],
        }
    return out


def _manifest() -> dict:
    return {
        "scene_id": "s1", "manifest_version": 2, "frame_count": 12,
        "objects": [
            _obj("obj_000", "sofa", 2.0, 2.0, "IDENT-SOFA", w=2.0, d=1.0),
            _obj("obj_001", "table", 3.0, 3.0, "IDENT-TABLE"),
        ],
        "frames": [],
    }


def _shell() -> dict:
    """A 4x4 m room with one wall along z=0 fronting +z, carrying one window."""
    return {
        "scene_id": "s1", "shell_version": 3, "status": "ready", "method": "roomplan",
        "reason": None,
        "floor": {
            "polygon": [[0, 0, 0], [4, 0, 0], [4, 0, 4], [0, 0, 4]],
            "y": 0.0, "provenance": {"source": "roomplan"},
            "material": {"albedo_hex": "#c8c1b7", "render": {"roughness": 0.9}},
        },
        "walls": [{
            "wall_id": "wall_00",
            "polygon": [[0, 0, 0], [4, 0, 0], [4, 2.5, 0], [0, 2.5, 0]],
            "classification": "wall", "confidence": "high",
            "openings": [{"classification": "window",
                          "rect_uv": [[0.4, 0.4], [0.6, 0.8]]}],
            "provenance": {"source": "roomplan"},
            "material": {"albedo_hex": "#aab9c3", "render": {"roughness": 0.9}},
        }],
    }


# --- A fake model that can call tools -------------------------------------

@dataclass
class _Block:
    type: str
    text: str = ""
    name: str = ""
    input: dict = None  # type: ignore[assignment]
    id: str = "tu_1"


@dataclass
class _Final:
    content: list
    stop_reason: str = "end_turn"
    usage: Any = None


class _Usage:
    input_tokens = 100
    output_tokens = 20
    cache_read_input_tokens = 0
    cache_creation_input_tokens = 0


class ToolCallingStreamer:
    """Scripted rounds. Each round is (deltas, tool_calls) — tool_calls is a
    list of (name, input); an empty list ends the turn.

    This mirrors AnthropicGuestStreamer's own loop rather than reimplementing
    it, so the test exercises the contract the real streamer offers the
    server: deltas, `tool_result` events, one `final`.
    """

    def __init__(self, rounds):
        self.rounds = rounds
        self.calls: list[dict] = []
        self.tool_inputs: list[tuple[str, dict]] = []

    async def stream_turn(self, *, model, max_tokens, system, messages,
                          tools=None, run_tool=None):
        self.calls.append({"system": system, "messages": messages, "tools": tools})
        for deltas, tool_calls in self.rounds:
            for text in deltas:
                yield {"type": "delta", "text": text}
            if not tool_calls or run_tool is None:
                break
            for name, payload in tool_calls:
                self.tool_inputs.append((name, payload))
                result = await run_tool(name, payload)
                yield {"type": "tool_result", "name": name, "result": result}
        yield {"type": "final", "stop_reason": "end_turn",
               "usage": {"input_tokens": 1, "output_tokens": 1,
                         "cache_read_input_tokens": 0,
                         "cache_creation_input_tokens": 0}}


@contextmanager
def _wired(scene, *, streamer=None, spec_repo=None, manifest=None, shell=None,
           with_shell=True):
    fetcher = InMemoryManifestFetcher()
    fetcher.store[_MANIFEST_URI] = json.dumps(
        manifest if manifest is not None else _manifest()
    ).encode()
    if with_shell:
        fetcher.store[_SHELL_URI] = json.dumps(
            shell if shell is not None else _shell()
        ).encode()
    with (
        patch.object(server, "_token_verifier", NullTokenVerifier()),
        patch.object(server, "_scene_read_repo",
                     InMemorySceneReadRepository({scene.scene_id: scene})),
        patch.object(server, "_manifest_fetcher", fetcher),
        patch.object(server, "_conversation_repo", InMemoryConversationRepository()),
        patch.object(server, "_design_spec_repo",
                     spec_repo if spec_repo is not None
                     else InMemoryDesignSpecRepository()),
        patch.object(server, "_guest_streamer",
                     streamer if streamer is not None
                     else ToolCallingStreamer([(["ok"], [])])),
    ):
        import scene_facts
        scene_facts._cache.clear()
        yield


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(server.app)


def _auth(uid=_UID):
    return {"Authorization": f"Bearer test-uid:{uid}"}


def _sse(body: str):
    out = []
    for block in body.split("\n\n"):
        block = block.strip("\n")
        if not block or block.startswith(":"):
            continue
        name = data = None
        for line in block.split("\n"):
            if line.startswith("event: "):
                name = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
        out.append((name, data))
    return out


def _entry(key="box:IDENT-SOFA", action="move", pos=(3.5, 0.5, 0.5)):
    return SpecEntry(
        key=key, action=action, label="sofa",
        measured_transform=Transform((2.0, 0.5, 2.0), (0, 0, 0, 1), 1.0),
        proposed_transform=Transform(pos, (0, 0, 0, 1), 1.0)
        if action == "move" else None,
        measured_footprint=Footprint((2.0, 0.5, 2.0), (1.0, 0.5, 0.5), 0.0),
        solver=SolverTrace("against_wall", "wall_00", ("keeps_height",), "why"),
        description="the sofa is against the wall",
        turn_index=0, client_msg_id="c1",
    )


# ---------------------------------------------------------------------------
# GET / DELETE
# ---------------------------------------------------------------------------

class TestSpecRoutes:
    def test_empty_is_200_not_404(self, client):
        scene = _scene()
        with _wired(scene):
            r = client.get(f"/scenes/{scene.scene_id}/design_spec", headers=_auth())
        assert r.status_code == 200
        assert r.json() == {"spec_version": 1, "scene_id": scene.scene_id,
                            "entries": [], "updated_at": None}

    def test_entries_carry_both_transforms_on_the_wire(self, client):
        scene, repo = _scene(), InMemoryDesignSpecRepository()
        repo.put(DesignSpec(scene.scene_id, _UID).with_entry(_entry()), now=_NOW)
        with _wired(scene, spec_repo=repo):
            body = client.get(f"/scenes/{scene.scene_id}/design_spec",
                              headers=_auth()).json()
        entry = body["entries"][0]
        assert entry["measured_transform"]["position"] == [2.0, 0.5, 2.0]
        assert entry["proposed_transform"]["position"] == [3.5, 0.5, 0.5]
        assert entry["measured_footprint"]["yaw_rad"] == 0.0
        assert entry["solver"]["reasoning"] == "why"
        assert entry["orphaned"] is False
        assert body["updated_at"] == _NOW.isoformat()

    def test_an_entry_whose_object_left_the_manifest_is_reported(self, client):
        scene, repo = _scene(), InMemoryDesignSpecRepository()
        repo.put(DesignSpec(scene.scene_id, _UID).with_entry(
            _entry(key="box:IDENT-GONE")), now=_NOW)
        with _wired(scene, spec_repo=repo):
            body = client.get(f"/scenes/{scene.scene_id}/design_spec",
                              headers=_auth()).json()
        assert len(body["entries"]) == 1, "orphans are reported, never dropped"
        assert body["entries"][0]["orphaned"] is True

    def test_an_unreadable_manifest_does_not_orphan_everything(self, client):
        """Otherwise the client would offer to clear a perfectly good
        arrangement because a GCS read blipped."""
        scene, repo = _scene(), InMemoryDesignSpecRepository()
        repo.put(DesignSpec(scene.scene_id, _UID).with_entry(_entry()), now=_NOW)
        empty = InMemoryManifestFetcher()
        with _wired(scene, spec_repo=repo), \
                patch.object(server, "_manifest_fetcher", empty):
            body = client.get(f"/scenes/{scene.scene_id}/design_spec",
                              headers=_auth()).json()
        assert body["entries"][0]["orphaned"] is False

    def test_delete_is_one_action_and_idempotent(self, client):
        scene, repo = _scene(), InMemoryDesignSpecRepository()
        repo.put(DesignSpec(scene.scene_id, _UID)
                 .with_entry(_entry())
                 .with_entry(_entry(key="box:IDENT-TABLE")), now=_NOW)
        with _wired(scene, spec_repo=repo):
            r1 = client.delete(f"/scenes/{scene.scene_id}/design_spec",
                               headers=_auth())
            r2 = client.delete(f"/scenes/{scene.scene_id}/design_spec",
                               headers=_auth())
            after = client.get(f"/scenes/{scene.scene_id}/design_spec",
                               headers=_auth()).json()
        assert r1.json() == {"cleared": 2}
        assert r2.json() == {"cleared": 0}
        assert after["entries"] == []

    @pytest.mark.parametrize("method", ["get", "delete"])
    def test_the_same_gates_as_every_other_ready_scene_route(self, client, method):
        call = getattr(client, method)
        scene = _scene()
        with _wired(scene):
            assert call(f"/scenes/{scene.scene_id}/design_spec").status_code == 422
            assert call(f"/scenes/{scene.scene_id}/design_spec",
                        headers={"Authorization": "Bearer bad"}).status_code == 401
            assert call("/scenes/not-a-uuid/design_spec",
                        headers=_auth()).status_code == 400
            assert call(f"/scenes/{scene.scene_id}/design_spec",
                        headers=_auth("someone-else")).status_code == 403
            assert call(f"/scenes/{uuid.uuid4()}/design_spec",
                        headers=_auth()).status_code == 404
        pending = _scene(status=SceneStatus.PROCESSING)
        with _wired(pending):
            assert call(f"/scenes/{pending.scene_id}/design_spec",
                        headers=_auth()).status_code == 409


# ---------------------------------------------------------------------------
# The tool loop
# ---------------------------------------------------------------------------

def _turn(client, scene, text="move the sofa against the wall"):
    return client.post(
        f"/scenes/{scene.scene_id}/conversation/messages",
        json={"text": text, "client_msg_id": str(uuid.uuid4())},
        headers=_auth(),
    )


class TestToolLoop:
    def test_a_tool_call_changes_the_room_and_announces_it(self, client):
        scene, repo = _scene(), InMemoryDesignSpecRepository()
        streamer = ToolCallingStreamer([
            (["Let me try that. "], [("propose", {"changes": [
                {"object_id": "obj_000", "action": "move",
                 "relation": "against_wall"}]})]),
            (["Done — it's against the wall now. Shall we look?"], []),
        ])
        with _wired(scene, streamer=streamer, spec_repo=repo):
            r = _turn(client, scene)
            body = client.get(f"/scenes/{scene.scene_id}/design_spec",
                              headers=_auth()).json()
        assert r.status_code == 200
        events = _sse(r.text)
        assert ("arrangement", {}) in events, "the client is never told to refetch"
        assert events[-1][0] == "done"
        # ...and the room really changed, with its measurement beside it.
        assert len(body["entries"]) == 1
        entry = body["entries"][0]
        assert entry["key"] == "box:IDENT-SOFA"
        assert entry["measured_transform"]["position"] == [2.0, 0.5, 2.0]
        assert entry["proposed_transform"]["position"] != [2.0, 0.5, 2.0]
        assert entry["proposed_transform"]["position"][1] == 0.5
        assert entry["solver"]["relation"] == "against_wall"
        assert entry["solver"]["constraints_applied"]

    def test_the_model_is_offered_the_tools(self, client):
        scene = _scene()
        streamer = ToolCallingStreamer([(["hello"], [])])
        with _wired(scene, streamer=streamer):
            _turn(client, scene)
        names = {t["name"] for t in streamer.calls[0]["tools"]}
        assert names == {"propose", "revert"}

    def test_a_refused_change_writes_nothing_and_emits_no_arrangement(self, client):
        scene = _scene()
        streamer = ToolCallingStreamer([
            ([""], [("propose", {"changes": [
                {"object_id": "obj_000", "action": "move",
                 "relation": "beside", "anchor": "the piano"}]})]),
            (["I couldn't find a piano in here. Want to point me at it?"], []),
        ])
        with _wired(scene, streamer=streamer):
            r = _turn(client, scene)
            body = client.get(f"/scenes/{scene.scene_id}/design_spec",
                              headers=_auth()).json()
        assert body["entries"] == []
        assert ("arrangement", {}) not in _sse(r.text)

    def test_remove_hides_a_piece_and_revert_brings_it_back(self, client):
        scene, repo = _scene(), InMemoryDesignSpecRepository()
        with _wired(scene, spec_repo=repo, streamer=ToolCallingStreamer([
            ([""], [("propose", {"changes": [
                {"object_id": "obj_001", "action": "remove"}]})]),
            (["Taken out. Say the word and it's back."], []),
        ])):
            _turn(client, scene, "take the table out")
            mid = client.get(f"/scenes/{scene.scene_id}/design_spec",
                             headers=_auth()).json()
        assert mid["entries"][0]["action"] == "remove"
        assert mid["entries"][0]["proposed_transform"] is None
        assert mid["entries"][0]["measured_transform"] is not None

        with _wired(scene, spec_repo=repo, streamer=ToolCallingStreamer([
            ([""], [("revert", {"keys": ["all"]})]),
            (["Back as measured. Want to try something else?"], []),
        ])):
            _turn(client, scene, "put it back")
            after = client.get(f"/scenes/{scene.scene_id}/design_spec",
                               headers=_auth()).json()
        assert after["entries"] == []

    def test_a_tool_that_blows_up_becomes_a_refusal_not_a_dead_turn(self, client):
        scene = _scene()
        streamer = ToolCallingStreamer([
            ([""], [("propose", {"changes": [
                {"object_id": "obj_000", "action": "move"}]})]),
            (["I couldn't manage that one, I'm afraid. Shall we try another?"], []),
        ])
        with _wired(scene, streamer=streamer), \
                patch.object(server, "run_guest_tool", side_effect=RuntimeError("boom")):
            r = _turn(client, scene)
        events = _sse(r.text)
        assert events[-1][0] == "done", "a broken tool must not kill the turn"

    def test_an_arrangement_survives_the_turn_that_made_it(self, client):
        """The 0058 shield covers the spec: writes happen per tool round, not
        at the end, so a client that disconnects still finds its room moved."""
        scene, repo = _scene(), InMemoryDesignSpecRepository()
        with _wired(scene, spec_repo=repo, streamer=ToolCallingStreamer([
            ([""], [("propose", {"changes": [
                {"object_id": "obj_000", "action": "move",
                 "relation": "against_wall"}]})]),
            (["done"], []),
        ])):
            _turn(client, scene)
        assert len(repo.get(scene.scene_id, _UID).entries) == 1


class TestTheGuestSeesTheProposedRoom:
    def test_facts_are_re_derived_and_the_arrangement_block_appears(self, client):
        scene, repo = _scene(), InMemoryDesignSpecRepository()
        repo.put(DesignSpec(scene.scene_id, _UID).with_entry(_entry()), now=_NOW)
        streamer = ToolCallingStreamer([(["ok"], [])])
        with _wired(scene, spec_repo=repo, streamer=streamer):
            _turn(client, scene, "how does it sit now?")
        system = streamer.calls[0]["system"]
        assert len(system) == 3, "charter, facts, arrangement"
        assert "THE ARRANGEMENT" in system[2]["text"]
        assert "the sofa is against the wall" in system[2]["text"]
        assert "cache_control" not in system[2]
        # The facts describe the MOVED room: the sofa/table distance changed.
        assert "about 1.6 m" not in system[1]["text"]

    def test_the_facts_stop_calling_a_moved_piece_measured(self, client):
        """Decision 0214, end to end through the real turn. The facts block's
        own provenance line is the only place the guest is told where its
        numbers came from, and it used to say "measured" over a room the
        scan never saw — corrected downstream by the arrangement block, which
        made that block load-bearing rather than belt-and-braces.
        """
        scene, repo = _scene(), InMemoryDesignSpecRepository()
        repo.put(DesignSpec(scene.scene_id, _UID).with_entry(_entry()), now=_NOW)
        streamer = ToolCallingStreamer([(["ok"], [])])
        with _wired(scene, spec_repo=repo, streamer=streamer):
            _turn(client, scene, "how does it sit now?")
        facts = streamer.calls[0]["system"][1]["text"]
        assert "These facts were measured from" not in facts
        assert "the sofa has been moved since" in facts
        assert "nothing measured it where it now stands" in facts

    def test_a_removal_alone_leaves_the_provenance_measured(self, client):
        """A remove takes the piece out of the derived facts entirely, so
        every fact that survives is still one the scan measured. Naming it as
        unmeasured would hedge facts nothing touched — the regression 0174
        recorded when it made the same distinction for rule 10's grammar.
        """
        scene, repo = _scene(), InMemoryDesignSpecRepository()
        repo.put(
            DesignSpec(scene.scene_id, _UID).with_entry(_entry(action="remove")),
            now=_NOW,
        )
        streamer = ToolCallingStreamer([(["ok"], [])])
        with _wired(scene, spec_repo=repo, streamer=streamer):
            _turn(client, scene, "how does it sit now?")
        facts = streamer.calls[0]["system"][1]["text"]
        assert "These facts were measured from" in facts
        assert "has been moved since" not in facts

    def test_no_arrangement_costs_exactly_what_stage_one_cost(self, client):
        scene = _scene()
        streamer = ToolCallingStreamer([(["ok"], [])])
        with _wired(scene, streamer=streamer):
            _turn(client, scene, "how does it sit?")
        assert len(streamer.calls[0]["system"]) == 2

    def test_a_missing_shell_still_answers_and_refuses_wall_relations(self, client):
        scene = _scene()
        streamer = ToolCallingStreamer([
            ([""], [("propose", {"changes": [
                {"object_id": "obj_000", "action": "move",
                 "relation": "against_wall"}]})]),
            (["I can't see any walls in what reached me."], []),
        ])
        with _wired(scene, streamer=streamer, with_shell=False):
            r = _turn(client, scene)
            body = client.get(f"/scenes/{scene.scene_id}/design_spec",
                              headers=_auth()).json()
        assert _sse(r.text)[-1][0] == "done"
        assert body["entries"] == []
