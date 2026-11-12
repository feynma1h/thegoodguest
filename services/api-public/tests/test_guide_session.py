"""The room guide's product session (guide_session.py): what is kept between
requests comes back exactly, and a turn played against it is the harness's turn.

Covers:
  - needs and the whole kept state survive JSON exactly, so a reloaded room is the
    room that was saved (and a replayed request is the one that was cached)
  - a card's button: ready, shown, stale, ready again after putting back
  - the panel's view of a turn: words joined into paragraphs, cards and notes kept
  - the room's files: scene.json, solids.json when present, whole boxes otherwise
  - needs.json: the rules pass runs once per scene and is kept against the scene's
    hash and the rules prompt's version
  - a turn through GuideSession uses every attribute run_turn reads; the session
    never takes part shapes from a browser
  - run_guide_turn charges what a failed turn cost and lets go of the lease

Synthetic room and scripted model only (tests/guide_fixtures.py): no network, no
credentials, no room data.

Run from repo root:
  pytest services/api-public/tests/test_guide_session.py -v
"""
from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest
from guide_fixtures import (
    STUDY_NEEDS,
    Script,
    StubGateway,
    look_then_offer,
    study_scene,
    text,
    tool,
)
from guide_repo import InMemoryGuideRepository
from guide_session import (
    CardRefused,
    GuideSession,
    GuideState,
    arrangement_key,
    card_status,
    ensure_needs,
    fold_events,
    load_scene,
    needs_from_doc,
    needs_to_doc,
    read_needs,
    run_guide_turn,
    trimmed,
)
from thegoodguest_room_guide.guide import run_turn
from thegoodguest_room_guide.model import Pose, room_from_scene
from thegoodguest_room_guide.needs import parse_needs

DIR = "gs://outputs/scenes/s1"
NOW = datetime(2026, 11, 12, 9, 0, tzinfo=UTC)


class Store(dict):
    """A bucket: fetch_optional and put over a dict."""

    def fetch_optional(self, uri):
        return self.get(uri)

    def put(self, uri, data, content_type="application/json"):
        self[uri] = bytes(data)


def scene_store(scene=None, solids=None) -> Store:
    s = Store()
    s[f"{DIR}/scene.json"] = json.dumps(scene or study_scene()).encode()
    if solids is not None:
        s[f"{DIR}/solids.json"] = solids if isinstance(solids, bytes) else json.dumps(solids).encode()
    return s


def session(steps, tmp_path, state=None) -> tuple[GuideSession, Script]:
    inputs = load_scene(scene_store().fetch_optional, DIR)
    script = Script(steps)
    gw = StubGateway(tmp_path / "llm", mode="stub", stub=script, budget_usd=1.0)
    needs = parse_needs(inputs.room, STUDY_NEEDS)
    return GuideSession(inputs.room, needs, state or GuideState(), model="claude-opus-5-5", gateway=gw), script


def play(s: GuideSession, words: str) -> list[tuple[str, dict]]:
    """One turn, with cards marked offered as run_guide_turn's relay marks them."""
    events = []

    def emit(kind, data):
        if kind == "card" and data["id"] not in s.offered:
            s.offered.append(data["id"])
        events.append((kind, data))

    run_turn(s, words, emit)
    return events


# ---------------------------------------------------------------------------
# What is kept comes back exactly
# ---------------------------------------------------------------------------

class TestKeptExactly:
    def test_needs_survive_json(self):
        room = room_from_scene(study_scene())
        needs = parse_needs(room, STUDY_NEEDS)
        back = needs_from_doc(json.loads(json.dumps(needs_to_doc(needs))))
        assert back == needs
        assert list(back.pieces) == list(needs.pieces), "order decides who follows whom"

    def test_the_whole_state_survives_json_after_a_change(self, tmp_path):
        s, _ = session([*look_then_offer(), text("Want to see it?")], tmp_path)
        play(s, "What would you change?")
        pid = s.offered[0]
        s.show_card(pid)
        kept = s.kept()
        again = GuideState.from_json(kept.to_json())
        assert again.to_json() == kept.to_json()
        assert again.history[-1] == kept.history[-1], "every pose float comes back exactly"
        p0, p1 = kept.proposals[pid], again.proposals[pid]
        assert (p1.words, p1.anchors, p1.arrangement, p1.effort) == (p0.words, p0.anchors, p0.arrangement, p0.effort)
        assert [f.text for f in p1.fixes] == [f.text for f in p0.fixes]

    def test_a_reloaded_session_reads_the_same_room(self, tmp_path):
        s, _ = session([*look_then_offer(), text("Want to see it?")], tmp_path)
        play(s, "What would you change?")
        s.show_card(s.offered[0])
        again, _ = session([], tmp_path, state=GuideState.from_json(s.kept().to_json()))
        assert [f.text for f in again.engine.current_findings] == [f.text for f in s.engine.current_findings]
        assert again.changes == s.changes and again.arrangement == s.arrangement

    def test_numpy_floats_and_python_floats_key_the_same_arrangement(self):
        a = {"desk": Pose(np.float64(1.25), 0.0, np.float64(-0.5), np.float64(1.5707963))}
        b = {"desk": Pose(1.25, 0.0, -0.5, 1.5707963)}
        assert arrangement_key(a) == arrangement_key(b)

    def test_trimming_keeps_the_scanned_room_and_every_offered_card(self):
        state = GuideState(history=[{}] + [{"desk": Pose(i / 100, 0, 0, 0)} for i in range(80)],
                           marks=[1] * 80)
        t = trimmed(state)
        assert t.history[0] == {} and len(t.history) == 60 and len(t.marks) == 59
        assert t.history[-1] == state.history[-1]


# ---------------------------------------------------------------------------
# A card's button
# ---------------------------------------------------------------------------

class TestCards:
    def test_ready_shown_stale_and_ready_again(self, tmp_path):
        s, _ = session([*look_then_offer(), text("Want to see it?")], tmp_path)
        events = play(s, "What would you change?")
        cards = [d for k, d in events if k == "card"]
        assert len(cards) == 1
        pid = cards[0]["id"]
        assert s.offered == [pid]
        assert card_status(pid, s.arrangement, s.proposals, s.bases) == "ready"

        result = s.show_card(pid)
        assert result["plan"]["tracks"] and result["state"]["can_undo"] is True
        assert result["state"]["cards"][pid] == "shown"
        assert s.changes == s.proposals[pid].words, "the guide is told what is on screen"
        with pytest.raises(CardRefused) as refused:
            s.show_card(pid)
        assert refused.value.code == "proposal_shown"

        back = s.put_back()
        assert back["plan"] and back["state"]["can_undo"] is False
        assert back["state"]["cards"][pid] == "ready" and s.changes == []
        with pytest.raises(CardRefused) as refused:
            s.put_back()
        assert refused.value.code == "nothing_to_undo"

    def test_a_card_offered_on_another_arrangement_is_stale(self, tmp_path):
        s, _ = session([*look_then_offer(), text("Want to see it?")], tmp_path)
        play(s, "What would you change?")
        pid = s.offered[0]
        s.bases[pid] = "some-other-room"
        with pytest.raises(CardRefused) as refused:
            s.show_card(pid)
        assert refused.value.code == "proposal_stale"

    def test_an_unoffered_proposal_is_not_a_card(self, tmp_path):
        s, _ = session([], tmp_path)
        with pytest.raises(CardRefused) as refused:
            s.show_card("nope")
        assert refused.value.code == "no_such_proposal"


# ---------------------------------------------------------------------------
# The panel's view of a turn
# ---------------------------------------------------------------------------

def test_a_turn_folds_into_paragraphs_cards_and_notes():
    events = [("note", {"text": "Looking…"}), ("delta", {"text": "The desk "}),
              ("delta", {"text": "faces the wall."}), ("card", {"id": "p1", "words": ["w"], "status": "ready"}),
              ("delta", {"text": "Want to see it?"}), ("play", {}), ("delta", {"text": "Done."}),
              ("focus", {}), ("delta", {"text": " There."})]
    assert fold_events(events) == [
        {"kind": "note", "text": "Looking…"},
        {"kind": "say", "text": "The desk faces the wall."},
        {"kind": "card", "card": {"id": "p1", "words": ["w"]}},
        {"kind": "say", "text": "Want to see it?"},
        {"kind": "say", "text": "Done."},
        {"kind": "say", "text": " There."},
    ]


# ---------------------------------------------------------------------------
# The room's files
# ---------------------------------------------------------------------------

class TestSceneFiles:
    def test_no_scene_json_is_no_guide(self):
        assert load_scene(Store().fetch_optional, DIR) is None

    def test_whole_boxes_without_solids(self):
        inputs = load_scene(scene_store().fetch_optional, DIR)
        assert inputs.solids_from == "boxes"
        assert all(p.parts_from == "box" for p in inputs.room.pieces.values())

    def test_the_pipelines_solids_are_used(self):
        solids = {"desk": [[0, 0.72, 0, 0.6, 0.02, 0.3], [-0.55, 0.35, 0, 0.03, 0.35, 0.28],
                           [0.55, 0.35, 0, 0.03, 0.35, 0.28]]}
        inputs = load_scene(scene_store(solids=solids).fetch_optional, DIR)
        assert inputs.solids_from == "pipeline"
        assert inputs.room.pieces["desk"].parts_from == "builder"

    def test_unreadable_solids_fall_back_to_boxes(self):
        assert load_scene(scene_store(solids=b"not json").fetch_optional, DIR).solids_from == "boxes"
        bad = {"desk": [["x", 1, 2]]}
        assert load_scene(scene_store(solids=bad).fetch_optional, DIR).solids_from == "boxes"

    def test_a_scene_that_is_not_a_diorama_scene_raises(self):
        with pytest.raises(ValueError):
            load_scene(scene_store(scene={"schema": "something/2"}).fetch_optional, DIR)


class TestNeedsJson:
    def test_the_rules_pass_runs_once_per_scene(self, tmp_path):
        store = scene_store()
        inputs = load_scene(store.fetch_optional, DIR)
        script = Script([])
        gw = StubGateway(tmp_path / "a", mode="stub", stub=script, budget_usd=1.0)
        first = ensure_needs(store.fetch_optional, store.put, inputs, gw, "claude-opus-5-5", NOW)
        assert script.rules_calls == 1 and f"{DIR}/needs.json" in store
        kept = json.loads(store[f"{DIR}/needs.json"])
        assert kept["scene_sha256"] == inputs.scene_sha and kept["model"] == "claude-opus-5-5"

        def never(req):
            raise AssertionError("needs.json should have answered")

        second = ensure_needs(store.fetch_optional, store.put, inputs,
                              StubGateway(tmp_path / "b", mode="stub", stub=never), "claude-opus-5-5", NOW)
        assert second == first

    def test_needs_for_another_scene_are_not_used(self, tmp_path):
        store = scene_store()
        inputs = load_scene(store.fetch_optional, DIR)
        gw = StubGateway(tmp_path / "a", mode="stub", stub=Script([]), budget_usd=1.0)
        ensure_needs(store.fetch_optional, store.put, inputs, gw, "claude-opus-5-5", NOW)
        changed = study_scene()
        changed["objects"][2]["size"] = [1.4, 0.74, 0.6]
        store[f"{DIR}/scene.json"] = json.dumps(changed).encode()
        assert read_needs(store.fetch_optional, load_scene(store.fetch_optional, DIR)) is None


# ---------------------------------------------------------------------------
# A turn
# ---------------------------------------------------------------------------

class TestTurns:
    def test_a_turn_runs_against_the_session_and_its_tools_reach_the_room(self, tmp_path):
        s, script = session([
            tool("move", {"piece": "desk", "how": "wall", "target": "wall_-z"}, 1),
            tool("show", lambda req: {"proposal": json.loads(req.messages[-1]["content"][-1]["content"])
                                      ["proposal"]["id"]}, 2),
            text("Done: the desk is against the other wall."),
        ], tmp_path)
        events = play(s, "Put the desk against the other wall.")
        plays = [d for k, d in events if k == "play"]
        assert len(plays) == 1 and "desk" in plays[0]["plan"]["tracks"]
        assert plays[0]["state"]["can_undo"] is True and "desk" in plays[0]["state"]["poses"]
        assert s.marks == [len(s.changes)] and s.changes
        # The next request carries the conversation exactly as it was returned.
        assert len(script.requests) == 3 and script.requests[-1].messages[-1]["role"] == "user"

    def test_the_session_never_takes_shapes_from_a_browser(self, tmp_path):
        s, _ = session([], tmp_path)
        with pytest.raises(NotImplementedError):
            s.take_solids({"desk": [[0, 0, 0, 1, 1, 1]]})
        with pytest.raises(NotImplementedError):
            s.load()

    def test_a_failed_turn_charges_what_it_spent_and_lets_go(self, tmp_path):
        store = scene_store()
        inputs = load_scene(store.fetch_optional, DIR)
        repo = InMemoryGuideRepository()
        accepted = repo.accept_turn("s1", "u1", "m1", opening=False, daily_usd=2.0, ttl_s=150, now=NOW)
        assert accepted.kind == "accepted"

        def broken(req):
            if hasattr(req, "schema"):
                return dict(STUDY_NEEDS)
            raise RuntimeError("the model fell over")

        outcome = run_guide_turn(
            repo=repo, scene_id="s1", user_id="u1", client_msg_id="m1", text="hello", opening=False,
            inputs=inputs, fetch_optional=store.fetch_optional, put=store.put,
            make_gateway=lambda p: StubGateway(p, mode="stub", stub=broken, budget_usd=2.0),
            spend_of=lambda gw: gw.report()["priced_usd"], model="claude-opus-5-5", history_turns=30,
            emit=lambda k, d: None, cancel=threading.Event(), created_at=NOW, now=lambda: NOW)
        assert outcome.error == "turn_failed" and outcome.turn is None
        assert outcome.cost_usd > 0 and repo.spent_today("u1", NOW) == pytest.approx(outcome.cost_usd)
        assert repo.get("s1", "u1").active is None, "the lease is let go"
        assert repo.turns("s1", "u1", 10) == []
        assert not list(Path(tmp_path).glob("guide-*")), "nothing left on disk"
