"""Tests for guest_prompt.py — the guest's contract (decision 0058).

The load-bearing test is the pinned hash: (PROMPT_VERSION, sha256(charter))
must move together. Changing the charter without bumping the version — or
bumping the version without touching the charter — goes red here, and a red
run is the signal to re-run the live voice eval suite
(tests/test_guest_voice_evals.py).

Also pinned: build_system_prompt's assembly order and cache breakpoints
(static → facts, both ephemeral; user text never in system), and the
observe-only telemetry semantics (foreign-measurement allowlist = facts
block ∪ history-window USER messages; assistant self-quotes still flag).

Run from repo root:
  pytest services/api-public/tests/test_guest_prompt.py -v
"""
from __future__ import annotations

import guest_prompt
from guest_prompt import (
    PROMPT_VERSION,
    STATIC_CHARTER,
    STATIC_CHARTER_SHA256,
    build_system_prompt,
    ends_with_invitation,
    foreign_measurements,
    measurement_tokens,
    telemetry_flags,
)
from scene_facts import derive_scene_facts, render_facts_block

# ---------------------------------------------------------------------------
# THE PIN. If this test fails you changed the charter: bump PROMPT_VERSION,
# update the hash below, and re-run the voice eval suite before shipping.
# ---------------------------------------------------------------------------

_PINNED = (
    4,
    "61e36ce3b48ea122c679af9fbd5ac975f436f6e46db5ba26bffedbd60fb537ce",
)


class TestPinnedCharter:
    def test_version_and_charter_hash_move_together(self):
        assert (PROMPT_VERSION, STATIC_CHARTER_SHA256) == _PINNED, (
            "STATIC_CHARTER or PROMPT_VERSION changed. If the charter changed: "
            "bump PROMPT_VERSION, re-pin (PROMPT_VERSION, sha256) here, and "
            "re-run tests/test_guest_voice_evals.py against the live model."
        )

    def test_charter_carries_the_capability_truths(self):
        # The two-level can't-see-that: capability truths live in the charter.
        lowered = STATIC_CHARTER.lower()
        for needle in (
            "center to center",   # distances framing
            "one room per conversation",
            "walls and floor",
            # 0096: the two new claim classes carry their epistemics in the
            # charter, not just in the facts block.
            "longest dimension",
            "floors, not measurements",
            # 0132: the hands rules. Each is a truth the model would
            # otherwise have to infer from the tool schema alone.
            "you never choose coordinates",   # rule 6: no invented positions
            "a refusal is a real answer",     # rule 6a
            "stay ideas until they say yes",  # rule 6b: suggest, never act
            "placements are verbatim too",    # rule 2a
            "conditional",                    # rule 10
            # 0159: a facing correction is the one change the guest makes to
            # something it cannot see, so who the authority is has to be
            # written down rather than inferred from a tool that takes no
            # direction.
            "theirs to know, not yours",      # rule 6c
            "did not give you eyes",          # rule 6c: no facing claims after
            "turning a piece is not rearranging",  # rule 10's exclusion
        ):
            assert needle in lowered, f"charter lost capability truth: {needle}"

    def test_charter_has_fifteen_exemplars(self):
        # 0096 added the clearance-floor and longest-dimension refusals; 0132
        # replaced the "I can't move things yet" exemplar with five covering
        # a successful move, a solver refusal, an ambiguous anchor, an
        # unprompted idea offered rather than acted on, and a conditional
        # clearance in a rearranged room; 0159 added four for facings — the
        # correction itself, the direction a turn cannot take, a piece with no
        # second way round, and a revert that leaves a correction standing.
        assert STATIC_CHARTER.count("Person:") == 15
        assert STATIC_CHARTER.count("Guest:") == 15

    def test_charter_no_longer_claims_the_guest_cannot_move_anything(self):
        """0132 gave the guest hands. A charter still saying "eyes, not
        hands" would make it refuse the feature it now has — the same class
        of false statement about the product as the shell test below."""
        lowered = STATIC_CHARTER.lower()
        assert "eyes, not hands" not in lowered
        assert "cannot move" not in lowered

    def test_charter_does_not_claim_the_shell_is_missing(self):
        """The shell SHIPS now (0066/0069/0077) and the person may be looking
        at it. The guest still can't see it — but "the walls haven't arrived"
        would be a false statement about the product, not an honest limit."""
        lowered = STATIC_CHARTER.lower()
        assert "haven't arrived" not in lowered
        assert "still on its way" not in lowered


# ---------------------------------------------------------------------------
# System prompt assembly
# ---------------------------------------------------------------------------

def _facts():
    return derive_scene_facts({
        "scene_id": "scene-1",
        "manifest_version": 2,
        "frame_count": 10,
        "objects": [
            {
                "object_id": "obj_000", "label": "sofa", "placed": True,
                "quality": {"frames_observed": 4, "cluster_spread_m": 0.02},
                "world_transform": {
                    "position": [0.0, 0.3, -1.6],
                    "rotation_xyzw": [0, 0, 0, 1], "scale": 1.0,
                },
            },
            {
                "object_id": "obj_001", "label": "table", "placed": True,
                "quality": {"frames_observed": 4, "cluster_spread_m": 0.02},
                "world_transform": {
                    "position": [0.1, 0.25, -0.4],
                    "rotation_xyzw": [0, 0, 0, 1], "scale": 1.0,
                },
            },
        ],
    })


class TestBuildSystemPrompt:
    def test_assembly_order_and_breakpoints(self):
        blocks = build_system_prompt(_facts())
        assert len(blocks) == 2
        static, facts_block = blocks
        assert static["text"] == STATIC_CHARTER
        assert static["cache_control"] == {"type": "ephemeral"}
        assert facts_block["text"] == render_facts_block(_facts())
        assert facts_block["cache_control"] == {"type": "ephemeral"}

    def test_user_text_never_in_system(self):
        # Structural: the builder takes derived facts and a server-rendered
        # arrangement block — there is no parameter through which user text
        # could enter the system prompt. `arrangement` is produced by
        # render_arrangement_block from SOLVER output only, which the
        # companion test below pins.
        import inspect
        params = inspect.signature(build_system_prompt).parameters
        assert list(params) == ["facts", "arrangement"]

    def test_arrangement_block_is_optional_and_unbreakpointed(self):
        # No arrangement -> byte-identical to stage 1, so a room nobody
        # rearranged pays nothing for this feature (including cache-wise).
        assert build_system_prompt(_facts(), "") == build_system_prompt(_facts())
        blocks = build_system_prompt(_facts(), "THE ARRANGEMENT — ...")
        assert len(blocks) == 3
        # The arrangement changes most often, so it must NOT hold a cache
        # breakpoint: it rides the rolling message one instead.
        assert "cache_control" not in blocks[2]
        assert blocks[0]["cache_control"] == {"type": "ephemeral"}
        assert blocks[1]["cache_control"] == {"type": "ephemeral"}

    def test_arrangement_block_carries_only_server_sentences(self):
        from design_spec import SpecEntry, Transform

        measured = Transform((0.0, 0.0, 0.0), (0, 0, 0, 1), 1.0)
        entry = SpecEntry(
            key="box:X", action="move", label="bed",
            measured_transform=measured, proposed_transform=measured,
            measured_footprint=None, solver=None,
            description="the bed is against the wall",
            turn_index=0, client_msg_id="c",
        )
        block = guest_prompt.render_arrangement_block([entry])
        assert "the bed is against the wall" in block
        # Rule 10 has to be actionable from this block alone.
        assert "would" in block.lower()
        assert guest_prompt.render_arrangement_block([]) == ""


# ---------------------------------------------------------------------------
# Telemetry: measurement tokens
# ---------------------------------------------------------------------------

class TestMeasurementTokens:
    def test_units_normalize(self):
        assert measurement_tokens("about 1.3 m") == {("1.3", "m")}
        assert measurement_tokens("1.30 meters") == {("1.3", "m")}
        assert measurement_tokens("58 cm and 58 centimetres") == {("58.0", "cm")}
        assert measurement_tokens("6 ft or 6 feet") == {("6.0", "ft")}
        assert measurement_tokens("12 inches") == {("12.0", "in")}

    def test_bare_in_is_not_a_unit(self):
        assert measurement_tokens("3 in the corner") == set()

    def test_min_is_not_meters(self):
        assert measurement_tokens("about 5 min later") == set()

    def test_plain_numbers_are_not_measurements(self):
        assert measurement_tokens("all 4 pieces made it") == set()


class TestForeignMeasurements:
    FACTS_BLOCK = "about 1.3 m between the sofa's center and the table's center"

    def test_facts_numbers_are_legitimate(self):
        assert foreign_measurements(
            "About 1.3 m between their centers.", self.FACTS_BLOCK, []
        ) == []

    def test_invented_number_flags(self):
        assert foreign_measurements(
            "Roughly 2.4 m of open space.", self.FACTS_BLOCK, []
        ) == ["2.4 m"]

    def test_user_echo_is_legitimate(self):
        assert foreign_measurements(
            "Your 2.1 m estimate isn't something I can confirm.",
            self.FACTS_BLOCK,
            ["is it about 2.1 m across?"],
        ) == []

    def test_assistant_self_quote_still_flags(self):
        # The guest's own prior invention is NOT in the allowlist — only the
        # facts block and USER messages are.
        assert foreign_measurements(
            "As I said, about 2.4 m.", self.FACTS_BLOCK, ["how far apart?"]
        ) == ["2.4 m"]

    def test_unit_conversion_of_a_true_fact_flags(self):
        # 1.3 m restated as 130 cm is a re-derived quantity → flags.
        assert foreign_measurements(
            "That's 130 cm between their centers.", self.FACTS_BLOCK, []
        ) == ["130.0 cm"]


class TestInvitationHeuristic:
    def test_question_ending(self):
        assert ends_with_invitation("Shall we look at the corner?")

    def test_invite_phrase_ending(self):
        assert ends_with_invitation(
            "The sofa holds that wall. Happy to walk the rest with you."
        )

    def test_flat_ending(self):
        assert not ends_with_invitation("The sofa holds that wall.")

    def test_empty(self):
        assert not ends_with_invitation("   ")


class TestTelemetryFlags:
    def test_healthy_reply_is_flagless(self):
        flags = telemetry_flags(
            "About 1.3 m between their centers. Want the rest of the room?",
            TestForeignMeasurements.FACTS_BLOCK,
            [],
        )
        assert flags == []

    def test_flags_accumulate(self):
        flags = telemetry_flags(
            "It spans 2.4 m and that is that.",
            TestForeignMeasurements.FACTS_BLOCK,
            [],
        )
        assert flags == ["foreign_measurement:2.4 m", "no_invitation_ending"]

    def test_charter_exemplar_numbers_are_not_silently_allowlisted(self):
        # Guard against a tempting regression: exemplar numbers ("1.3 m" in
        # the imaginary-room examples) must not become a fabrication channel.
        # In a room whose facts carry no 1.3 m, parroting the exemplar flags.
        assert guest_prompt.foreign_measurements(
            "About 1.3 m between their centers.",
            "no measurements here",
            [],
        ) == ["1.3 m"]
