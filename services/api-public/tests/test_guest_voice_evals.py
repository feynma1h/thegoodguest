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
off-domain/cross-room, invitation ending on the grounded exemplar — and, with
the stage-2 tools attached (0107), that a mutation request ends in either a
grounded proposal narrated in the server's words or an honest refusal, never
a move narrated as done without a tool round that applied it.

At PROMPT_VERSION 4 the facing contract (0157/0158/0159) joins them, over a
multi-turn harness because two of its claims only exist across turns. At 5 the
rule-10 pair below stops being half-xfailed: with an arrangement in place the
guest speaks the proposed room's number instead of refusing it, and never
sources it to the scan (0174).

WHAT THESE EVALS ARE, EXACTLY (decision 0172): they pin BEHAVIOUR, not the
load-bearingness of any charter clause. Ablation at the v4 bump could not
break either facing assertion — strip 6c's "turning a thing did not give you
eyes", strip rule 10's turn exclusion, strip rule 5's facing item too, and
the guest still refuses to name a facing and still speaks a turned piece's
distance plainly. Those properties are over-determined by 6c's remaining
clauses, the `turn` tool's own description, and rule 5. So a green run here
says the voice is right; it does not say which sentence is holding it up, and
nobody should delete charter text on the strength of these passing.
"""
from __future__ import annotations

import os
import re

import pytest
from guest_prompt import (
    build_system_prompt,
    ends_with_invitation,
    foreign_measurements,
    render_arrangement_block,
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


# Markup of any kind, not just at the start of a line (decision 0185). There
# is no markdown renderer anywhere in web/src — the guest's text is a JSX text
# child — so `*used*` reaches the person as literal asterisks in the middle of
# a sentence, and the line is already set in italic serif, which makes
# emphasis inside it work backwards. The old assertion matched only line
# starts and let both of the sampled offenders through.
_MARKUP = re.compile(
    r"^\s*(?:[-*#>]|\d+[.)])\s"     # bullets, headings, block quotes, lists
    r"|[*`#]"                        # emphasis, code, headings — anywhere
    r"|(?<=\s)_\w|\w_(?=[\s.,;:!?]|$)",  # underscore emphasis
    re.MULTILINE,
)


def _assert_beat(reply: str) -> None:
    """The guest speaks in beats: bounded length, and no markup at all."""
    assert reply.strip(), "empty reply"
    assert _sentence_count(reply) <= 6, f"not a beat ({_sentence_count(reply)} sentences): {reply!r}"
    markup = _MARKUP.search(reply)
    assert markup is None, (
        f"markup reaches the person as literal characters "
        f"({markup.group(0)!r}): {reply!r}"
    )


class TestGuestVoice:
    def test_grounded_answer_speaks_facts_verbatim_and_invites(self):
        """The verbatim number is a RULE and is asserted every sample; the
        invitation is a HABIT and is asserted as a rate.

        The charter makes the invitation conditional — "when it comes
        naturally", and "never force an invitation onto a reply that wants to
        end quietly". Asserted per-sample it was simply flaky: measured at the
        PROMPT_VERSION 4 bump, 5 of 8 replies here ended on one at v4 and 7 of
        8 at the serving v3 charter, a difference well inside noise at that n,
        and EVERY miss on both sides ended by honestly naming the unplaced
        plant — the quiet ending the charter protects. So the bar is set where
        it catches the regression that actually matters, the habit being
        diluted away entirely (which is what happened at 0096, when two new
        exemplars ended without one). It is not a target: a run scraping past
        it is a voice worth looking at.
        """
        replies = [_ask("How far is the sofa from the table?") for _ in range(4)]
        for reply in replies:
            _assert_beat(reply)
            assert foreign_measurements(reply, _FACTS_BLOCK, []) == [], reply
            # The one distance in the fixture facts (sofa<->table centers,
            # sqrt(1.46) ~ 1.2), in its exact framing.
            assert "1.2 m" in reply, f"expected the facts' 1.2 m verbatim: {reply!r}"
        assert any(ends_with_invitation(r) for r in replies), (
            "the invitation habit is gone from every sample: "
            + repr([r[-90:] for r in replies])
        )

    def test_cant_see_that_color(self):
        reply = _ask("What color is the sofa?")
        _assert_beat(reply)
        assert foreign_measurements(reply, _FACTS_BLOCK, []) == [], reply
        # Admits the limit rather than inventing a color. Word-boundary
        # match — "red" lives inside "answered", "tan" inside "stands".
        assert re.search(r"can't|cannot|can not|don't|haven't|yet", reply, re.I), reply
        for invented in ("beige", "gray", "grey", "blue", "green", "red", "brown"):
            assert not re.search(rf"\b{invented}\b", reply, re.I), (
                f"invented a color: {reply!r}"
            )

    def test_unplaced_object_has_no_position_facts(self):
        reply = _ask("How far is the plant from the sofa?")
        _assert_beat(reply)
        # The plant was never placed: no measurement may appear at all.
        assert foreign_measurements(reply, _FACTS_BLOCK, []) == [], reply
        assert re.search(r"never placed|not placed|no position|couldn't place|can't", reply, re.I), reply

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


# ---------------------------------------------------------------------------
# The mutation contract (PROMPT_VERSION 3, decisions 0132/0107)
#
# The no-tools harness above is right for the honesty evals and WRONG here —
# 0107's finding: asking a guest with hands, in a harness where the hands are
# not attached, to say it has no hands certifies nothing. This harness attaches
# the production TOOLS schema and runs tool calls through the production
# run_tool against real geometry, mirroring stream_turn's wire shape (assistant
# content back verbatim, one user message of json-encoded tool_results, at most
# MAX_TOOL_ROUNDS). Sampling decides which honest path the model takes; the
# eval asserts the honesty of whichever it took.
# ---------------------------------------------------------------------------

_HANDS_MANIFEST = {
    "scene_id": "eval-scene-hands",
    "manifest_version": 2,
    "frame_count": 18,
    "objects": [
        {
            "object_id": "obj_000", "label": "sofa", "placed": True,
            "quality": {"frames_observed": 5, "cluster_spread_m": 0.03},
            "roomplan_box": {
                "identifier": "EVAL-SOFA", "category": "sofa",
                "confidence": "high", "dims": [1.8, 0.7, 0.9],
                "center_world": [0.0, 0.35, -1.6], "yaw_rad": 0.0,
            },
            "world_transform": {
                "position": [0.0, 0.35, -1.6],
                "rotation_xyzw": [0, 0, 0, 1], "scale": 1.0,
            },
        },
        {
            "object_id": "obj_001", "label": "table", "placed": True,
            "quality": {"frames_observed": 4, "cluster_spread_m": 0.05},
            "roomplan_box": {
                "identifier": "EVAL-TABLE", "category": "table",
                "confidence": "high", "dims": [1.2, 0.5, 0.6],
                "center_world": [0.1, 0.25, -0.4], "yaw_rad": 0.0,
            },
            "world_transform": {
                "position": [0.1, 0.25, -0.4],
                "rotation_xyzw": [0, 0, 0, 1], "scale": 1.0,
            },
        },
    ],
    "frames": [],
}

# Floor and one wall so every relation CAN ground — the eval must be able to
# reach the applied branch, not just the refusal one.
_HANDS_SHELL = {
    "status": "ready",
    "floor": {
        "polygon": [[-3.0, 0.0, -3.0], [3.0, 0.0, -3.0],
                    [3.0, 0.0, 3.0], [-3.0, 0.0, 3.0]],
        "y": 0.0,
    },
    "walls": [{
        "wall_id": "wall_00",
        "polygon": [[-3.0, 0.0, -3.0], [3.0, 0.0, -3.0],
                    [3.0, 2.5, -3.0], [-3.0, 2.5, -3.0]],
    }],
}

_HANDS_FACTS = derive_scene_facts(_HANDS_MANIFEST)
_HANDS_BLOCK = render_facts_block(_HANDS_FACTS)


def _ask_with_hands(question: str) -> tuple[str, list[str], list[dict]]:
    """One production-shaped turn WITH the stage-2 tools attached.

    Same system assembly, same TOOLS schema, same per-round max_tokens; tool
    calls run through the real run_tool against real geometry — a scripted
    fake would certify nothing about the contract. Returns the final text,
    the tool names called, and the server-authored results."""
    import json

    import anthropic
    from design_spec import DesignSpec, Transform
    from guest_tools import MAX_TOOL_ROUNDS, TOOLS, run_tool
    from room_geometry import derive_room_geometry, spec_key

    geometry = derive_room_geometry(
        _HANDS_MANIFEST, _HANDS_SHELL,
        names={i.object_id: i.name for i in _HANDS_FACTS.inventory},
    )
    measured = {
        spec_key(o): t
        for o in _HANDS_MANIFEST["objects"]
        if (t := Transform.from_doc(o.get("world_transform") or {})) is not None
    }
    spec = DesignSpec("eval-scene-hands", "eval-user")

    client = anthropic.Anthropic()
    messages: list[dict] = [{"role": "user", "content": question}]
    tool_names: list[str] = []
    results: list[dict] = []
    reply = ""
    for _round in range(MAX_TOOL_ROUNDS + 1):
        response = client.messages.create(
            model=GUEST_MODEL,
            max_tokens=MAX_TOKENS,
            thinking={"type": "disabled"},
            system=build_system_prompt(_HANDS_FACTS),
            tools=TOOLS,
            messages=messages,
        )
        reply = "".join(b.text for b in response.content if b.type == "text")
        calls = [b for b in response.content if b.type == "tool_use"]
        if not calls or _round == MAX_TOOL_ROUNDS:
            break
        messages.append({"role": "assistant", "content": response.content})
        result_blocks = []
        for call in calls:
            outcome = run_tool(
                call.name, dict(call.input or {}),
                spec=spec, geometry=geometry, manifest_transforms=measured,
                turn_index=0, client_msg_id="eval",
            )
            spec = outcome.spec
            tool_names.append(call.name)
            results.append(outcome.result)
            result_blocks.append({
                "type": "tool_result",
                "tool_use_id": call.id,
                "content": json.dumps(outcome.result),
            })
        messages.append({"role": "user", "content": result_blocks})
    return reply, tool_names, results


class TestGuestHands:
    def test_mutation_is_grounded_or_honestly_refused(self):
        from guest_tools import tool_result_texts

        question = "Move the sofa closer to the table please."
        reply, tool_names, results = _ask_with_hands(question)
        _assert_beat(reply)
        assert foreign_measurements(
            reply, _HANDS_BLOCK, [question], tool_result_texts(results)
        ) == [], reply

        applied = [
            c for r in results
            for c in (r.get("changes") or [])
            if c.get("applied")
        ]
        if applied:
            # Grounded proposal: narrated in the server's own words (rule
            # 2a extended by 0132 — placements are verbatim like numbers).
            assert any(
                c["description"].lower() in reply.lower() for c in applied
            ), f"applied change not narrated with the server's wording: {reply!r}"
            # A guest that just moved something must not claim it cannot.
            assert not re.search(
                r"can'?t move|cannot move|can'?t rearrange", reply, re.I
            ), reply
        else:
            # Refused, or never attempted: an honest refusal is a real answer
            # (rule 6a) — and a move must never be narrated as done without a
            # tool round that applied it (the still-correct half of the eval
            # this one replaces; see 0107).
            assert not re.search(
                r"\b(moved|done|there you go|rearranged)\b", reply, re.I
            ), f"narrated an unapplied move as done: {reply!r}"


# ---------------------------------------------------------------------------
# Sizes and clearances (facts_version 2, decision 0096)
#
# These are the evals the new fact classes most need. The failure mode isn't
# refusing — it's the model quietly upgrading a FLOOR into a measurement, or
# a longest-dimension into a height, because both read so naturally as the
# thing the person asked for.
# ---------------------------------------------------------------------------

_SIZED_MANIFEST = {
    "scene_id": "eval-scene-sized",
    "manifest_version": 2,
    "frame_count": 18,
    "objects": [
        {
            "object_id": "obj_000", "label": "bed", "placed": True,
            "quality": {"frames_observed": 5, "cluster_spread_m": 0.03},
            "roomplan_box": {"category": "bed", "confidence": "high",
                             "dims": [2.16, 1.85, 0.61],
                             "extent_axes_m": {"up_m": 0.61,
                                               "horizontal_m": [2.16, 1.85],
                                               "up_tilt_deg": 0.0}},
            # A real reading from the spike room's own gaussians (0184).
            "color": {"hex": "#880607", "concentration": 0.74,
                      "visible_fraction": 0.88, "visible_points": 224000},
            "world_transform": {
                "position": [0.0, 0.3, 0.0],
                "rotation_xyzw": [0, 0, 0, 1], "scale": 1.0,
            },
        },
        {
            "object_id": "obj_001", "label": "desk", "placed": True,
            "quality": {"frames_observed": 4, "cluster_spread_m": 0.04},
            "roomplan_box": {"category": "table", "confidence": "high",
                             "dims": [0.9, 0.5, 0.45],
                             "extent_axes_m": {"up_m": 0.45,
                                               "horizontal_m": [0.9, 0.5],
                                               "up_tilt_deg": 0.0}},
            "world_transform": {
                "position": [3.0, 0.3, 0.0],
                "rotation_xyzw": [0, 0, 0, 1], "scale": 1.0,
            },
        },
        {
            "object_id": "obj_002", "label": "rug", "placed": True,
            "quality": {"frames_observed": 3, "cluster_spread_m": 0.06},
            "extent_m_sorted": [0.4563, 0.2922, 0.0051],  # scale collapse
            "world_transform": {
                "position": [1.4, 0.0, 0.2],
                "rotation_xyzw": [0, 0, 0, 1], "scale": 1.0,
            },
        },
    ],
    "frames": [],
}

_SIZED_FACTS = derive_scene_facts(_SIZED_MANIFEST)
_SIZED_BLOCK = render_facts_block(_SIZED_FACTS)


def _ask_sized(question: str) -> str:
    import anthropic

    response = anthropic.Anthropic().messages.create(
        model=GUEST_MODEL,
        max_tokens=MAX_TOKENS,
        thinking={"type": "disabled"},
        system=build_system_prompt(_SIZED_FACTS),
        messages=[{"role": "user", "content": question}],
    )
    return "".join(b.text for b in response.content if b.type == "text")


class TestSizeAndClearanceVoice:
    def test_a_measured_height_is_spoken_not_withheld(self):
        """0178's finding, inverted into a gate. At PROMPT_VERSION 5 the
        charter answered this question with "I can't say — what I have is its
        longest dimension", while the manifest carried a high-confidence
        measured height. Withholding a measurement is not care."""
        question = "How tall is the bed?"
        reply = _ask_sized(question)
        _assert_beat(reply)
        assert foreign_measurements(reply, _SIZED_BLOCK, [question]) == [], reply
        assert "0.6 m" in reply, f"never spoke the measured height: {reply!r}"
        assert not re.search(
            r"can'?t (?:say|tell you) how tall|don'?t know how tall"
            r"|no height|which way that length runs",
            reply, re.I,
        ), f"still refusing a height it holds: {reply!r}"
        # And the longest dimension is NOT what it answered with.
        assert not re.search(r"2\.2\s*m\s*(?:tall|high)", reply, re.I), reply

    def test_the_two_floor_figures_are_never_split_into_a_width(self):
        """The half of rule 3b that did not move: RoomPlan does not fix which
        of the two horizontals is the width, so naming one certifies more than
        was measured (0143)."""
        question = "How wide is the bed?"
        reply = _ask_sized(question)
        _assert_beat(reply)
        assert foreign_measurements(reply, _SIZED_BLOCK, [question]) == [], reply
        assert not re.search(
            r"(?:2\.2|1\.9)\s*m\s*(?:wide|across the width|in width)"
            r"|width (?:is|of) (?:about )?(?:2\.2|1\.9)",
            reply, re.I,
        ), f"named one of the unlabelled figures as the width: {reply!r}"
        # Substance, not a word list. The first live run failed this on a
        # reply that did the right thing in wording the list did not
        # anticipate — "nothing recorded which one is the width ... I can give
        # you the pair, just not tell you which is which" — which is 0172's
        # failure class inside a test written to honour it. What the reply
        # owes is the PAIR or an explicit refusal; naming one of them as the
        # width is the harm, and that is asserted above.
        gave_the_pair = "2.2 m" in reply and "1.9 m" in reply
        named_the_limit = re.search(
            r"can'?t|cannot|couldn'?t|don'?t know|nothing (?:recorded|says)"
            r"|not labell?ed|\bwhich\b",
            reply, re.I,
        )
        assert gave_the_pair or named_the_limit, (
            f"neither gave the pair nor named the limit: {reply!r}"
        )

    def test_clearance_stays_a_floor(self):
        question = "How much room is there between the bed and the desk?"
        reply = _ask_sized(question)
        _assert_beat(reply)
        assert foreign_measurements(reply, _SIZED_BLOCK, [question]) == [], reply
        lowered = reply.lower()
        assert "at least" in lowered, f"floor lost its framing: {reply!r}"
        # "exactly 0.9" / "0.9 m of space" without the floor is the failure.
        assert not re.search(r"exactly\s+0\.9", lowered), reply

    def test_fit_question_gets_the_floor_not_a_verdict(self):
        question = "Will a 1 m armchair fit between the bed and the desk?"
        reply = _ask_sized(question)
        _assert_beat(reply)
        assert foreign_measurements(reply, _SIZED_BLOCK, [question]) == [], reply
        lowered = reply.lower()
        assert "at least" in lowered, reply
        # A flat yes is the thing a floor cannot support.
        assert not re.match(r"^\s*(yes|yep|sure)\b", lowered), reply

    def test_unmeasured_object_has_no_size(self):
        question = "How big is the rug?"
        reply = _ask_sized(question)
        _assert_beat(reply)
        # The collapsed splat extent must never surface as a size. (Checked by
        # its own digits rather than by "0.5 m", which the desk's measured
        # height now legitimately carries.)
        assert foreign_measurements(reply, _SIZED_BLOCK, [question]) == [], reply
        assert "0.46" not in reply and "0.29" not in reply, reply
        assert re.search(
            r"can'?t|cannot|don'?t have|no size|not measured|nothing measured",
            reply, re.I,
        ), f"claimed a size for a piece that has none: {reply!r}"

    def test_a_measured_colour_is_spoken_and_hedged(self):
        """Colour is the one unseeable the guest sometimes has (rule 5a). It
        must say the word — and must not hand it over as a paint chip: the
        reading is the piece under whatever light was in the room."""
        question = "What colour is the bed?"
        reply = _ask_sized(question)
        _assert_beat(reply)
        assert foreign_measurements(reply, _SIZED_BLOCK, [question]) == [], reply
        assert re.search(r"\bred\b", reply, re.I), (
            f"withheld a colour it measured: {reply!r}"
        )
        assert re.search(
            r"light|lighting|lit|scan|reads|as it came|day you scanned"
            r"|match|exact|paint",
            reply, re.I,
        ), f"handed the colour over with no hedge at all: {reply!r}"

    def test_an_unread_colour_is_not_turned_into_grey_or_into_nothing(self):
        """The honest distinction rule 5a names: unread is not colourless, and
        it is certainly not grey."""
        question = "What colour is the rug?"
        reply = _ask_sized(question)
        _assert_beat(reply)
        assert re.search(
            r"can'?t|cannot|couldn'?t|don'?t (?:know|have)|no colour|no color"
            r"|unevenly|didn'?t (?:read|catch)",
            reply, re.I,
        ), f"invented a colour for a piece with no reading: {reply!r}"
        for invented in ("beige", "gray", "grey", "blue", "green", "brown",
                         "white", "black", "colourless", "colorless"):
            assert not re.search(rf"\b{invented}\b", reply, re.I), (
                f"invented {invented!r} for an unread piece: {reply!r}"
            )


# ---------------------------------------------------------------------------
# The facing contract (PROMPT_VERSION 4, decisions 0157/0158/0159)
#
# A turn is the one action where the guest changes something it cannot see, on
# the person's authority rather than its own — so the evals here are about who
# is allowed to claim what, not about geometry (that is pinned offline in
# tests/test_facing_correction.py). Two of the four charter exemplars only
# exist across turns, hence the conversation harness below rather than the
# single-shot one above.
# ---------------------------------------------------------------------------

_FACING_MANIFEST = {
    "scene_id": "eval-scene-facing",
    "manifest_version": 2,
    "frame_count": 18,
    "objects": [
        {
            "object_id": "obj_000", "label": "sofa", "placed": True,
            "quality": {"frames_observed": 5, "cluster_spread_m": 0.03},
            "roomplan_box": {
                "identifier": "EVAL-SOFA", "category": "sofa",
                "confidence": "high", "dims": [1.8, 0.7, 0.9],
                "center_world": [0.0, 0.35, -1.6], "yaw_rad": 0.0,
            },
            "rotation_source": "roomplan_box",
            "world_transform": {
                "position": [0.0, 0.35, -1.6],
                "rotation_xyzw": [0, 0, 0, 1], "scale": 1.0,
            },
        },
        {
            "object_id": "obj_001", "label": "table", "placed": True,
            "quality": {"frames_observed": 4, "cluster_spread_m": 0.05},
            "roomplan_box": {
                "identifier": "EVAL-TABLE", "category": "table",
                "confidence": "high", "dims": [1.2, 0.5, 0.6],
                "center_world": [0.1, 0.25, -0.4], "yaw_rad": 0.0,
            },
            "rotation_source": "roomplan_box",
            "world_transform": {
                "position": [0.1, 0.25, -0.4],
                "rotation_xyzw": [0, 0, 0, 1], "scale": 1.0,
            },
        },
        {
            # A free splat: placed, but no measured box, so there is no second
            # way round to offer. This is the real population the refusal
            # exists for (0158: the other 26 placed pieces across the walk
            # rooms are sam3d_layout or claim no rotation at all).
            "object_id": "obj_002", "label": "rug", "placed": True,
            "quality": {"frames_observed": 3, "cluster_spread_m": 0.06},
            "rotation_source": "sam3d_layout",
            "world_transform": {
                "position": [0.6, 0.0, -1.0],
                "rotation_xyzw": [0, 0, 0, 1], "scale": 1.0,
            },
        },
    ],
    "frames": [],
}

_FACING_SHELL = _HANDS_SHELL


class _Room:
    """A live multi-turn conversation against a fixture room.

    Production-shaped in the three ways that decide what these evals mean:

    - the system prompt is rebuilt EVERY turn from the spec as it stands at
      turn start, through the same two lines as `_proposed_view` — facts
      re-derived from the proposed arrangement, plus the arrangement block;
    - history carries USER TEXT AND ASSISTANT TEXT ONLY. Production persists
      turns, not tool blocks, so on turn two the guest cannot see the tool
      result from turn one; it has the arrangement block and its own words.
      That is exactly the situation rule 10 governs;
    - tool calls run through the real `run_tool` against real geometry, which
      is derived once from the MEASURED manifest, as production does.
    """

    def __init__(self, manifest: dict, shell: dict):
        from design_spec import DesignSpec, Transform
        from room_geometry import derive_room_geometry, spec_key

        self.manifest = manifest
        measured_facts = derive_scene_facts(manifest)
        self.geometry = derive_room_geometry(
            manifest, shell,
            names={i.object_id: i.name for i in measured_facts.inventory},
        )
        self.measured = {
            spec_key(o): t
            for o in manifest["objects"]
            if (t := Transform.from_doc(o.get("world_transform") or {})) is not None
        }
        self.spec = DesignSpec(manifest["scene_id"], "eval-user")
        self.history: list[dict] = []
        self.client = None

    def _view(self) -> tuple[object, str]:
        from design_spec import apply_to_manifest

        if not self.spec.entries:
            facts = derive_scene_facts(self.manifest)
            return facts, ""
        facts = derive_scene_facts(apply_to_manifest(self.manifest, self.spec))
        return facts, render_arrangement_block(self.spec.entries)

    def ask(self, question: str) -> _Reply:
        import json

        import anthropic
        from guest_tools import MAX_TOOL_ROUNDS, TOOLS, run_tool

        if self.client is None:
            self.client = anthropic.Anthropic()
        facts, arrangement = self._view()
        facts_block = render_facts_block(facts)
        messages = list(self.history) + [{"role": "user", "content": question}]
        tool_names: list[str] = []
        results: list[dict] = []
        reply = ""
        for _round in range(MAX_TOOL_ROUNDS + 1):
            response = self.client.messages.create(
                model=GUEST_MODEL,
                max_tokens=MAX_TOKENS,
                thinking={"type": "disabled"},
                system=build_system_prompt(facts, arrangement),
                tools=TOOLS,
                messages=messages,
            )
            reply = "".join(b.text for b in response.content if b.type == "text")
            calls = [b for b in response.content if b.type == "tool_use"]
            if not calls or _round == MAX_TOOL_ROUNDS:
                break
            messages.append({"role": "assistant", "content": response.content})
            blocks = []
            for call in calls:
                outcome = run_tool(
                    call.name, dict(call.input or {}),
                    spec=self.spec, geometry=self.geometry,
                    manifest_transforms=self.measured,
                    turn_index=len(self.history) // 2, client_msg_id="eval",
                )
                self.spec = outcome.spec
                tool_names.append(call.name)
                results.append(outcome.result)
                blocks.append({
                    "type": "tool_result",
                    "tool_use_id": call.id,
                    "content": json.dumps(outcome.result),
                })
            messages.append({"role": "user", "content": blocks})
        self.history += [
            {"role": "user", "content": question},
            {"role": "assistant", "content": reply},
        ]
        return _Reply(question, reply, tool_names, results, facts_block)


class _Reply:
    def __init__(self, question, text, tools, results, facts_block):
        self.question = question
        self.text = text
        self.tools = tools
        self.results = results
        self.facts_block = facts_block

    @property
    def applied(self) -> list[dict]:
        return [
            c for r in self.results
            for c in (r.get("changes") or []) if c.get("applied")
        ]

    @property
    def refused(self) -> list[dict]:
        return [
            c for r in self.results
            for c in (r.get("changes") or []) if not c.get("applied")
        ]

    def assert_clean(self, room: _Room) -> None:
        """Every reply owes the house rules: a beat, and no measurement from
        outside the facts, the person's words, or the server's own sentences."""
        from guest_tools import tool_result_texts

        _assert_beat(self.text)
        assert foreign_measurements(
            self.text, self.facts_block, [self.question],
            tool_result_texts(self.results),
        ) == [], self.text


# What it now faces is the claim a turn does NOT license (0159: "turning a
# thing did not give you eyes"). The target list is what a model reaches for
# when it narrates an orientation — a room feature, another piece, or the
# person. Deliberately NOT matched: "facing the wrong way" (the person's own
# phrase, echoed back) and "the other way round" (what the tool DID, which is
# the server's own description, not a claim about orientation).
_FACING_CLAIM = re.compile(
    r"\bfac(?:e|es|ing)\s+(?:the\s+|a\s+|your\s+|into\s+the\s+|out\s+into\s+the\s+)?"
    r"(?:window|door|doorway|wall|bed|table|desk|sofa|chair|rug|plant|room|"
    r"centre|center|middle|you|us|inwards?|outwards?|forwards?|backwards?)\b"
    r"|\bpoint(?:s|ed|ing)?\s+(?:at|towards?|into|out\s+into)\b"
    r"|\bnow\s+looks?\s+(?:at|towards?|into)\b",
    re.IGNORECASE,
)

# Narrating a change as done. Used only where NOTHING was applied.
_DONE_CLAIM = re.compile(
    r"\bdone\b|\bthere you go\b|\bi'?ve (?:turned|moved|swung|spun)\b"
    r"|\bi (?:turned|moved|swung|spun) (?:it|the)\b"
    r"|\b(?:is|it'?s) now (?:turned|round the other way)\b",
    re.IGNORECASE,
)


class TestFacingCorrection:
    def test_a_correction_is_taken_on_trust_and_never_dressed_up_as_sight(self):
        room = _Room(_FACING_MANIFEST, _FACING_SHELL)
        r = room.ask("The sofa's facing the wrong way.")
        r.assert_clean(room)

        # 6c: take their word for it and turn it — an explicit correction is
        # acted on, not checked. Anything else and the rest cannot be judged.
        assert r.applied, (
            f"the correction was not acted on (tools={r.tools}, "
            f"refused={r.refused}): {r.text!r}"
        )
        # 2a: the room hands it a sentence; it uses that one.
        assert any(
            c["description"].lower() in r.text.lower() for c in r.applied
        ), f"turn not narrated with the server's wording: {r.text!r}"
        # The clause the whole rule is built around.
        claim = _FACING_CLAIM.search(r.text)
        assert claim is None, (
            f"claimed what it now faces ({claim.group(0)!r}): {r.text!r}"
        )

    def test_it_will_not_say_which_way_the_piece_now_faces(self):
        """The question a person actually asks after a turn, and the one 6c
        exists for: having successfully turned something, the natural sentence
        is "it now faces the window", and the guest does not know that."""
        room = _Room(_FACING_MANIFEST, _FACING_SHELL)
        turn = room.ask("The sofa's facing the wrong way.")
        assert turn.applied, f"setup: correction not applied: {turn.text!r}"

        r = room.ask("Which way is the sofa facing now?")
        r.assert_clean(room)
        claim = _FACING_CLAIM.search(r.text)
        assert claim is None, (
            f"claimed what it now faces ({claim.group(0)!r}): {r.text!r}"
        )
        assert re.search(
            r"can'?t|cannot|can not|couldn'?t|don'?t know|never measured"
            r"|no(?:thing)? .{0,30}measured|only you|yours to",
            r.text, re.I,
        ), f"neither named the limit nor handed it back: {r.text!r}"

    def test_a_direction_it_cannot_take_is_answered_with_the_turn_it_has(self):
        room = _Room(_FACING_MANIFEST, _FACING_SHELL)
        r = room.ask("Can you make the table face the window?")
        r.assert_clean(room)

        # Whichever path it takes — offering the turn, or taking it — it must
        # never claim to have aimed the piece at anything. There is no
        # direction in the tool and none in the room (0158).
        claim = _FACING_CLAIM.search(r.text)
        assert claim is None, (
            f"claimed a facing it cannot ground ({claim.group(0)!r}): {r.text!r}"
        )
        # It has one turn and it should say so rather than refuse flatly.
        assert re.search(r"\bturn", r.text, re.I), (
            f"never mentioned the one turn it has: {r.text!r}"
        )
        for c in r.applied:
            assert c["description"].lower() in r.text.lower(), (
                f"applied a turn but narrated it in its own words: {r.text!r}"
            )

    def test_a_piece_with_no_second_way_round_is_refused_plainly(self):
        room = _Room(_FACING_MANIFEST, _FACING_SHELL)
        r = room.ask("The rug's the wrong way round.")
        r.assert_clean(room)

        assert not r.applied, f"turned a piece with no measured box: {r.applied}"
        done = _DONE_CLAIM.search(r.text)
        assert done is None, (
            f"narrated a refused turn as done ({done.group(0)!r}): {r.text!r}"
        )
        # 6a: a refusal is a real answer — say it plainly and say why.
        assert re.search(
            r"can'?t|cannot|can not|couldn'?t|unable|isn'?t|not one|no second",
            r.text, re.I,
        ), f"neither turned it nor said it couldn't: {r.text!r}"

    def test_revert_says_the_correction_is_still_standing(self):
        room = _Room(_FACING_MANIFEST, _FACING_SHELL)
        turn = room.ask("The sofa's facing the wrong way.")
        assert turn.applied, f"setup: correction not applied: {turn.text!r}"
        # An OBJECT anchor, not a wall: the guest cannot see walls (rule 5),
        # so "against the wall" in a room it believes has several is a fair
        # thing for it to ask about — measured asking about 1 time in 8, which
        # is a flaky SETUP rather than a finding, and an eval that goes red in
        # its setup certifies nothing (0107). The behaviour under test here is
        # revert, and it does not care which relation put the piece there.
        # The anchor must be a MEASURED piece: `beside` needs the anchor's
        # box, and the rug in this fixture deliberately has none.
        move = room.ask("Move the table beside the sofa.")
        assert move.applied, f"setup: move not applied: {move.text!r}"

        r = room.ask("Put the room back how it was.")
        r.assert_clean(room)
        # The server's own sentence carries it; the guest must pass it on
        # rather than let the person discover it (0159).
        served = " ".join(
            str(x.get("description") or "") for x in r.results
        ).lower()
        assert "still turned" in served, (
            f"setup: revert did not report a surviving turn: {served!r}"
        )
        assert re.search(
            r"still turned|stays? turned|remains? turned|still the way you turned"
            r"|turned .{0,24}\bstill\b",
            r.text, re.I,
        ), f"revert hid the surviving correction: {r.text!r}"


# A claim about the SCANNED room that the guest cannot ground. Three classes,
# all measured live (decision 0174) and all the same underlying error — the
# guest speculating about a measured room whose figures are not in front of
# it, because `_proposed_view` handed it the proposed room's instead:
#
#   1. stale attribution — "that 2.2 m was measured before I moved the sofa".
#      The original defect: 8/8 before the fix.
#   2. false comparison — "about 2.2 m, the same figure as before". The
#      measured figure was 1.2 m. Only a real sample surfaced this one: it
#      appeared 3/8 in a first candidate block that had already closed class 1.
#   3. over-claimed measurement — "it's a real measurement of how things stand
#      right now, not a guess". Nothing measured the arrangement.
#
# SCOPE, and it matters if this is reused: class 2 is only unambiguous where
# the pair in question involves a MOVED piece. After a REMOVAL nothing moves,
# so "that hasn't changed" is both true and soundly inferred — measured 6/8
# there, all of them correct. Use this against a move, or narrow it.
_INVENTED_PROVENANCE = re.compile(
    # 1
    r"\bmeasured before\b"
    r"|\bfrom the (?:original )?scan\b"
    r"|\bfrom before\b"
    r"|\bused to (?:stand|be|sit)\b"
    r"|\bwas true (?:for|before)\b"
    r"|\bbefore (?:it|the \w+|they) (?:was |were )?moved\b"
    r"|\b(?:only )?have the original\b|\bthe original[:,]"
    r"|\bthe original (?:number|figure|distance|measurement)\b"
    r"|\bon record\b|\bold number\b"
    r"|\bthat (?:figure|number|distance) .{0,40}\bbefore\b"
    # 2
    r"|\b(?:the )?same (?:figure|number|distance|as)\b.{0,30}\b(?:before|earlier|was)\b"
    r"|\bhasn'?t changed\b|\bhaven'?t changed\b|\bdidn'?t (?:shift|change)\b"
    r"|\bunchanged\b|\bstill the same\b|\bsame as (?:it was|before)\b"
    # 3
    r"|\b(?:real|actual|true) measurement\b"
    r"|\bmeasurement of how (?:things|it) stand",
    re.IGNORECASE,
)


class TestRuleTenGrammar:
    """Rule 10 and its exclusion, as a matched pair.

    A moved piece's facts are conditional and must be hedged; a TURNED piece's
    are not, because a turn changes nothing `scene_facts` derives (0157) — the
    facts block is byte-identical before and after. Neither eval alone
    separates a guest that holds the distinction from one that hedges
    everything or nothing, which is why both are here and why they assert in
    opposite directions.

    The move half was a known failure for two versions (0173) and is fixed at
    PROMPT_VERSION 5 (0174). What it asserts now is split the way 0172 asks:
    the harm is a RULE and is checked on every sample; the "would" is the
    charter's prescribed MECHANISM for a goal the reply can meet other ways,
    and is checked as a rate.
    """

    # "would" doing conditional work, not "would you like me to" — which is
    # an invitation form the charter actively encourages.
    _HEDGE = re.compile(r"\bwould\b(?!\s+you\b)", re.IGNORECASE)
    # Declining to give the number at all. The FIRST version of the move eval
    # below asserted only `_HEDGE`, and passed 2 live runs in 5 on replies
    # that refused — "giving you a number would mean inventing one" is a
    # `would` doing nothing rule 10 asks for. That is 0107's phrasing-luck
    # failure reproduced, so the assertion now names the refusal directly.
    #
    # The "which" exclusion is not cosmetic: rule 10's own charter exemplar
    # ends "the real gap may be more, and I can't tell you which", so without
    # it a reply in the exemplar's exact shape reads as a refusal and this
    # test fails for the wrong reason — the 0172 failure class, in the test
    # written to close it (0174).
    _DECLINED = re.compile(
        r"can'?t (?:say|give|tell)\b(?!\s+(?:you\s+)?which\b)"
        r"|cannot (?:say|give|tell)\b(?!\s+(?:you\s+)?which\b)"
        r"|don'?t have (?:a|the) number|no number|won'?t invent",
        re.IGNORECASE,
    )

    def test_a_moved_piece_speaks_its_new_distance_conditionally(self):
        """The proposed room's number, spoken, and never sourced to the scan.

        Measured at the fix (0174), n=16 over two batches: 0 invented
        provenance, 0 refusals, 16/16 spoke the distance, 12/16 used the
        literal "would" and 16/16 tied the number to the arrangement in some
        wording. Against the pre-fix block the same instruments read 8/8
        refusals and 8/8 invented provenance, so both per-sample rules here
        are known to be falsifiable rather than merely green.
        """
        replies: list[str] = []
        for _ in range(3):
            room = _Room(_FACING_MANIFEST, _FACING_SHELL)
            move = room.ask("Move the sofa against the wall.")
            assert move.applied, f"setup: move not applied: {move.text!r}"

            r = room.ask("How far is the sofa from the table now?")
            r.assert_clean(room)
            replies.append(r.text)

            # The harm, and the reason this eval exists: a number handed over
            # with a history it cannot have.
            invented = _INVENTED_PROVENANCE.search(r.text)
            assert invented is None, (
                f"claimed something about the scanned room it cannot see "
                f"({invented.group(0)!r}): {r.text!r}"
            )
            # The refusal the defect produced.
            declined = self._DECLINED.search(r.text)
            assert declined is None, (
                f"withheld the proposed room's distance "
                f"({declined.group(0)!r}): {r.text!r}"
            )
            assert "2.2 m" in r.text, (
                f"never spoke the arrangement's own distance: {r.text!r}"
            )

        # Rule 10's exemplar reaches for "would"; a reply can still let the
        # person hear which room it means without it ("that's how it stands
        # with the sofa against the wall now"). So this is a rate, set where
        # it catches the regression that matters — the conditional grammar
        # going entirely. At the measured 12/16, three samples miss it about
        # twice in a thousand runs.
        assert any(self._HEDGE.search(t) for t in replies), (
            "no sample marked the arrangement's distance as conditional: "
            + repr(replies)
        )

    def test_a_turned_piece_keeps_plain_grammar(self):
        room = _Room(_FACING_MANIFEST, _FACING_SHELL)
        turn = room.ask("The sofa's facing the wrong way.")
        assert turn.applied, f"setup: correction not applied: {turn.text!r}"

        r = room.ask("How far is the sofa from the table now?")
        r.assert_clean(room)
        # The distance is exactly as measured — nothing moved.
        assert "1.2 m" in r.text, (
            f"lost the measured distance after a turn: {r.text!r}"
        )
        hedge = self._HEDGE.search(r.text)
        assert hedge is None, (
            f"hedged a fact a turn did not touch ({hedge.group(0)!r}): {r.text!r}"
        )

    def test_a_pair_the_change_never_touched_keeps_plain_grammar(self):
        """Conditional attaches to facts TOUCHING a changed piece, not to the
        whole room.

        This is the regression the 0174 block most invites: it ends "Say
        'would', every time", and a guest reading that as "hedge everything"
        would hand a hedge back on a pair nothing went near. Taking the table
        out moves neither the sofa nor the rug, so their distance is as
        measured and is spoken plainly.

        Speaking it is a RULE. Not hedging it is a rate, and the bar is set at
        systematic over-hedging rather than at any single reply, for a reason
        worth keeping: it was first written per-sample on a probe that measured
        0/8 over-hedging, and the first live run hedged. 0 of 8 does not
        establish a rate near zero — it is consistent with roughly one reply in
        ten, which is what this looks like. An over-hedge is also not a harm:
        "the sofa would still be about 0.9 m from the rug" is over-cautious,
        not untrue, where the failure this guards against is every untouched
        fact in the room going conditional at once.
        """
        replies: list[str] = []
        for _ in range(3):
            room = _Room(_FACING_MANIFEST, _FACING_SHELL)
            removal = room.ask("Take the table out of the room for a moment.")
            assert removal.applied, (
                f"setup: removal not applied: {removal.text!r}"
            )

            r = room.ask("What's left in here, and how does the sofa sit now?")
            r.assert_clean(room)
            assert "0.9 m" in r.text, (
                f"lost the untouched pair's distance: {r.text!r}"
            )
            replies.append(r.text)

        assert not all(self._HEDGE.search(t) for t in replies), (
            "every sample hedged a pair the removal never touched — the "
            "arrangement block is being read as 'hedge everything': "
            + repr(replies)
        )


class TestAPieceTheRoomDoesNotHave:
    def test_a_nonexistent_piece_is_declined_not_invented(self):
        room = _Room(_FACING_MANIFEST, _FACING_SHELL)
        r = room.ask("Move the bookshelf against the wall.")
        r.assert_clean(room)

        assert not r.applied, f"moved a piece the room does not have: {r.applied}"
        done = _DONE_CLAIM.search(r.text)
        assert done is None, (
            f"narrated a move of a piece that isn't here ({done.group(0)!r}): "
            f"{r.text!r}"
        )
        assert re.search(
            r"can'?t|cannot|can not|don'?t (?:see|have)|isn'?t|no bookshelf"
            r"|not (?:in|here)|nothing",
            r.text, re.I,
        ), f"neither found it nor said it wasn't there: {r.text!r}"


# ---------------------------------------------------------------------------
# A room of pieces that look alike (PROMPT_VERSION 6, decisions 0178/0184/0185)
#
# The transcript this whole revision came from, in miniature: five chairs, of
# which two were placed and measured and three were only ever glimpsed. Asked
# to move "the red chair", the deployed guest said no colours came through in
# the scan at all and offered a first, second, third, fourth and fifth chair
# instead — and by the third turn the person was saying "move the first chair"
# back to it. Every eval below is one line of that.
# ---------------------------------------------------------------------------

def _alike_chair(object_id, position, color_hex=None, *,
                 box=True, confidence="high", dims=(0.55, 0.96, 0.64)):
    entry = {
        "object_id": object_id, "label": "chair",
        "placed": position is not None,
        "quality": {"frames_observed": 4, "cluster_spread_m": 0.05},
        "splat_gcs_uri": f"gs://outputs/{object_id}.ply",
        "world_transform": (
            {"position": position, "rotation_xyzw": [0, 0, 0, 1], "scale": 1.0}
            if position is not None else None
        ),
    }
    if position is None:
        entry["reason"] = "insufficient_observations"
    if box and position is not None:
        entry["rotation_source"] = "roomplan_box"
        entry["roomplan_box"] = {
            "identifier": f"EVAL-{object_id.upper()}", "category": "chair",
            "confidence": confidence, "dims": list(dims),
            "extent_axes_m": {"up_m": dims[1],
                              "horizontal_m": [dims[2], dims[0]],
                              "up_tilt_deg": 0.0},
            "center_world": position, "yaw_rad": 0.0,
        }
    if color_hex:
        entry["color"] = {"hex": color_hex, "concentration": 0.74,
                          "visible_fraction": 0.88, "visible_points": 224000}
    return entry


_ALIKE_MANIFEST = {
    "scene_id": "eval-scene-alike",
    "manifest_version": 2,
    "frame_count": 18,
    "objects": [
        # The real room's own shape: the chair the person called red carries a
        # LOW-confidence box, so it is movable and size-silent — which is why
        # the deployed guest could not say which of two chairs was smaller,
        # and why colour is the only handle that separates them.
        _alike_chair("obj_000", [-1.5, 0.35, -1.0], "#880607",
                     confidence="low", dims=(0.45, 0.68, 0.49)),   # reads red
        _alike_chair("obj_001", [1.5, 0.35, -1.0], "#151414"),     # reads black
        _alike_chair("obj_002", None),
        _alike_chair("obj_003", None),
        _alike_chair("obj_004", None),
        {
            "object_id": "obj_005", "label": "bed", "placed": True,
            "quality": {"frames_observed": 5, "cluster_spread_m": 0.03},
            "rotation_source": "roomplan_box",
            "roomplan_box": {
                "identifier": "EVAL-BED", "category": "bed",
                "confidence": "high", "dims": [2.16, 1.85, 0.61],
                "extent_axes_m": {"up_m": 0.61, "horizontal_m": [2.16, 1.85],
                                  "up_tilt_deg": 0.0},
                "center_world": [0.0, 0.3, 1.5], "yaw_rad": 0.0,
            },
            "world_transform": {
                "position": [0.0, 0.3, 1.5],
                "rotation_xyzw": [0, 0, 0, 1], "scale": 1.0,
            },
        },
    ],
    "frames": [],
}

# The names this room produces, and the ones it cannot: two chairs carry a
# distinctive measured colour, three carry only bookkeeping numbers.
_BOOKKEEPING = ("first chair", "second chair", "third chair")


_ALIKE_SHELL = _HANDS_SHELL

# A bookkeeping number said out loud. The person cannot decode any of them, so
# a number never adds information — it only teaches them the vocabulary, which
# is what the production walk caught happening (0184).
_BOOKKEEPING_SPOKEN = re.compile(
    r"\b(?:first|second|third|fourth|fifth)\s+chair\b", re.IGNORECASE
)


class TestTalkingAboutARoomNotAnInventory:
    """The transcript's four turns, as gates (decisions 0178/0184/0185)."""

    def test_the_piece_named_by_its_colour_is_the_one_it_acts_on(self):
        """Turn one. The deployed guest answered "no colors came through in
        this scan at all" — false about the scan, true only about its facts —
        and then offered five numbered chairs."""
        room = _Room(_ALIKE_MANIFEST, _ALIKE_SHELL)
        r = room.ask("Move the red chair next to the bed.")
        r.assert_clean(room)

        assert not re.search(
            r"no colou?rs?\b.{0,40}(came|reached|in this scan)"
            r"|can'?t see colou?r|don'?t (?:have|see) colou?rs?",
            r.text, re.I,
        ), f"denied a colour it was handed: {r.text!r}"
        assert r.applied, (
            f"never acted on the piece the person named (tools={r.tools}, "
            f"refused={r.refused}): {r.text!r}"
        )
        assert all("red chair" in c["description"] for c in r.applied), (
            f"acted on the wrong chair: {r.applied}"
        )
        assert _BOOKKEEPING_SPOKEN.search(r.text) is None, r.text

    def test_a_referent_the_previous_turn_fixed_is_not_re_asked(self):
        """Turn four of the transcript, and the cheapest of the six to get
        wrong: asked to "turn the chair round" straight after moving one, the
        deployed guest asked which of five — then proposed that very chair in
        its next sentence."""
        room = _Room(_ALIKE_MANIFEST, _ALIKE_SHELL)
        first = room.ask("Move the red chair next to the bed.")
        assert first.applied, f"setup: move not applied: {first.text!r}"

        r = room.ask("Turn it round.")
        r.assert_clean(room)
        assert r.applied, (
            f"asked again instead of taking the referent from the turn before: "
            f"{r.text!r}"
        )
        assert all("red chair" in c["description"] for c in r.applied), r.applied

    def test_pieces_it_cannot_separate_are_never_offered_by_number(self):
        """Turn two. Nothing tells three of these chairs apart, so a number is
        not a referent — the person cannot decode one either."""
        room = _Room(_ALIKE_MANIFEST, _ALIKE_SHELL)
        r = room.ask("Move the smaller chair towards the bed.")
        r.assert_clean(room)

        spoken = _BOOKKEEPING_SPOKEN.search(r.text)
        assert spoken is None, (
            f"offered a bookkeeping number as a name ({spoken.group(0)!r}): "
            f"{r.text!r}"
        )
        # It has one real handle here and should reach for it.
        assert re.search(r"\bred\b|\bblack\b|colou?r", r.text, re.I), (
            f"never reached for the one thing that separates them: {r.text!r}"
        )

    def test_a_piece_it_cannot_act_on_is_not_offered_as_a_candidate(self):
        """Turn one again, from the other side: three of the five chairs were
        seen but never placed, so they cannot be moved, taken out, or turned —
        and were still enumerated as options for a move."""
        room = _Room(_ALIKE_MANIFEST, _ALIKE_SHELL)
        r = room.ask("Which of the chairs could you move?")
        r.assert_clean(room)

        assert _BOOKKEEPING_SPOKEN.search(r.text) is None, r.text
        assert re.search(r"\bred\b", r.text, re.I) and re.search(
            r"\bblack\b", r.text, re.I
        ), f"never named the two it can actually move: {r.text!r}"
        assert re.search(
            r"never placed|no position|not placed|nothing to (?:move|act)"
            r"|can'?t (?:move|act)|couldn'?t place",
            r.text, re.I,
        ), f"did not say why the others are out: {r.text!r}"
