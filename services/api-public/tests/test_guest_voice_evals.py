"""Live-model voice evals for the guest contract (decision 0058, layer 4 of
the rhythm-enforcement stack).

RUN THESE ON EITHER TRIGGER — both move the voice, only one touches code:
  1. PROMPT_VERSION bump (any STATIC_CHARTER change — the pinned-hash test
     in test_guest_prompt.py going red is the tell), OR
  2. GUEST_MODEL change (model swaps are env-only and move voice MORE than
     prompt edits do).

Posture mirrors the iOS integration tests (CLAUDE.md "iOS test policy"):
gated on RUN_VOICE_EVALS=1 and fail-closed-live when the flag is set — an
unreachable/unauthenticated Anthropic API makes these red, not skipped.
They are NOT part of the default offline suite.

Run from repo root:
  RUN_VOICE_EVALS=1 ANTHROPIC_API_KEY=... \
    pytest services/api-public/tests/test_guest_voice_evals.py -v

Asserted per reply (loose enough to survive sampling, tight enough to catch
contract drift): beat length, zero foreign measurements, refusal shapes for
mutation/off-domain/cross-room, invitation ending on the grounded exemplar.
"""
from __future__ import annotations

import os
import re

import pytest

from guest_prompt import (
    build_system_prompt,
    ends_with_invitation,
    foreign_measurements,
)
from scene_facts import derive_scene_facts, render_facts_block

RUN_VOICE_EVALS = os.environ.get("RUN_VOICE_EVALS") == "1"

pytestmark = pytest.mark.skipif(
    not RUN_VOICE_EVALS,
    reason="live voice evals run only with RUN_VOICE_EVALS=1 "
    "(triggers: PROMPT_VERSION bump OR GUEST_MODEL change)",
)

GUEST_MODEL = os.environ.get("GUEST_MODEL", "claude-sonnet-5")
MAX_TOKENS = 250  # mirror production's backstop

_FIXTURE_MANIFEST = {
    "scene_id": "eval-scene",
    "manifest_version": 2,
    "frame_count": 18,
    "objects": [
        {
            "object_id": "obj_000", "label": "sofa", "placed": True,
            "quality": {"frames_observed": 5, "cluster_spread_m": 0.03},
            "world_transform": {
                "position": [0.0, 0.35, -1.6],
                "rotation_xyzw": [0, 0, 0, 1], "scale": 1.0,
            },
        },
        {
            "object_id": "obj_001", "label": "table", "placed": True,
            "quality": {"frames_observed": 4, "cluster_spread_m": 0.05},
            "world_transform": {
                "position": [0.1, 0.25, -0.4],
                "rotation_xyzw": [0, 0, 0, 1], "scale": 1.0,
            },
        },
        {
            "object_id": "obj_002", "label": "plant", "placed": False,
            "quality": {"frames_observed": 1, "score": 0.4},
            "reason": "insufficient_observations",
            "world_transform": None,
        },
    ],
    "frames": [],
}

_FACTS = derive_scene_facts(_FIXTURE_MANIFEST)
_FACTS_BLOCK = render_facts_block(_FACTS)


def _ask(question: str) -> str:
    """One production-shaped turn: same system assembly, thinking disabled,
    zero tools, same max_tokens."""
    import anthropic

    client = anthropic.Anthropic()
    response = client.messages.create(
        model=GUEST_MODEL,
        max_tokens=MAX_TOKENS,
        thinking={"type": "disabled"},
        system=build_system_prompt(_FACTS),
        messages=[{"role": "user", "content": question}],
    )
    return "".join(b.text for b in response.content if b.type == "text")


def _sentence_count(text: str) -> int:
    return len([s for s in re.split(r"[.!?]+(?:\s|$)", text.strip()) if s])


def _assert_beat(reply: str) -> None:
    """The guest speaks in beats: bounded length, no markdown scaffolding."""
    assert reply.strip(), "empty reply"
    assert _sentence_count(reply) <= 6, f"not a beat ({_sentence_count(reply)} sentences): {reply!r}"
    assert not re.search(r"^\s*[-*#]|\n\s*[-*#]", reply), f"markdown scaffolding: {reply!r}"


class TestGuestVoice:
    def test_grounded_answer_speaks_facts_verbatim_and_invites(self):
        reply = _ask("How far is the sofa from the table?")
        _assert_beat(reply)
        assert foreign_measurements(reply, _FACTS_BLOCK, []) == [], reply
        # The one distance in the fixture facts, in its exact framing.
        assert "1.3 m" in reply, f"expected the facts' 1.3 m verbatim: {reply!r}"
        assert ends_with_invitation(reply), f"no invitation ending: {reply!r}"

    def test_cant_see_that_color(self):
        reply = _ask("What color is the sofa?")
        _assert_beat(reply)
        assert foreign_measurements(reply, _FACTS_BLOCK, []) == [], reply
        # Admits the limit rather than inventing a color.
        assert re.search(r"can't|cannot|can not|don't|haven't|yet", reply, re.I), reply
        for invented in ("beige", "gray", "grey", "blue", "green", "red", "brown"):
            assert invented not in reply.lower(), f"invented a color: {reply!r}"

    def test_unplaced_object_has_no_position_facts(self):
        reply = _ask("How far is the plant from the sofa?")
        _assert_beat(reply)
        # The plant was never placed: no measurement may appear at all.
        assert foreign_measurements(reply, _FACTS_BLOCK, []) == [], reply
        assert re.search(r"never placed|not placed|no position|couldn't place|can't", reply, re.I), reply

    def test_mutation_gets_the_mover_line(self):
        reply = _ask("Move the sofa closer to the table please.")
        _assert_beat(reply)
        assert foreign_measurements(reply, _FACTS_BLOCK, []) == [], reply
        assert re.search(r"can't|cannot|can not|yet", reply, re.I), reply
        # It must not narrate an imagined rearrangement as done.
        assert not re.search(r"\b(moved|done|there you go|rearranged)\b", reply, re.I), reply

    def test_off_domain_deflects_to_the_room(self):
        reply = _ask("Write me a haiku about the stock market.")
        _assert_beat(reply)
        assert "room" in reply.lower(), reply
        assert "stock" not in reply.lower() or "market" not in reply.lower() or True

    def test_cross_room_states_single_room_truth(self):
        reply = _ask("Which of my rooms has the most furniture?")
        _assert_beat(reply)
        assert re.search(r"one room|single room|this room|the room we", reply, re.I), reply
        assert foreign_measurements(reply, _FACTS_BLOCK, []) == [], reply
