"""The guest's hands: two tools, and the runner that keeps them honest.

Decision 0132. Stage 1 shipped ZERO tools by design — 0058 recorded it as
architectural, not charter. This module is the first time the guest gets
hands, and the whole shape follows from one thing found by READING the
charter rather than designing against it: **the guest cannot compute a target
position.** Rule 5 forbids it knowing which way anything faces, the shapes of
things, or the room's own walls and floor — "they may well be there on the
screen in front of the person, but they did not reach you". Rule 3b says a
size is a longest dimension with unrecoverable axis semantics.

So a tool shaped `move(object, x, y, z)` would require the guest to author
coordinates from a world in which walls, facings and footprints do not exist.
That is exactly rule 2's "made-up number wearing a measured costume — the one
lie this house cannot forgive, because no one can see it happening". A
coordinate-taking tool does not stretch the honesty contract; it inverts it.

Hence: **the guest states an INTENT in the vocabulary it can actually see; a
server-side solver turns that into a transform or refuses.** The tool RESULT
is the honest surface, and rule 2 extends by one word — transforms are
verbatim too. The guest may describe a placement only using the server's
sentence for it, for the same reason it never computes a distance. That costs
nothing to enforce: it is the mechanism 0058 already built, pointed at a
second class of value, and the foreign-measurement detector generalises to it
by widening its allowlist to facts ∪ user window ∪ TOOL RESULTS.

UNPROMPTED PROPOSALS: the guest may suggest, never act (0132). An explicit
instruction calls `propose` immediately — revert is always one action away,
so a confirmation dialog would be friction protecting nothing. An unprompted
idea is speech only. Checked the way 0058 checks voice: an observe-only flag
when a turn proposes into a message that asked for nothing.

Consumers: public_server.py (the conversation turn). Exercised directly by
tests/test_design_spec.py, and through the streaming route by
tests/test_design_spec_routes.py.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime

from design_spec import (
    DesignSpec,
    Footprint,
    SolverTrace,
    SpecEntry,
    Transform,
)
from room_geometry import RoomGeometry, RoomObject
from spec_solver import RELATIONS, Refusal, Solution, solve

logger = logging.getLogger(__name__)

PROPOSE = "propose"
REVERT = "revert"

# How many tool rounds one turn may take. Two is enough for propose-then-see
# and for a refusal the guest reacts to; more is a model looping, and a loop
# that spends the person's daily turn quota silently is worse than a turn
# that ends with the guest saying it could not manage it.
MAX_TOOL_ROUNDS = 2

TOOLS = [
    {
        "name": PROPOSE,
        "description": (
            "Propose a change to how this room is arranged, and show it to the "
            "person immediately. You state WHAT you want and WHERE relative to "
            "something; the room's own measurements decide the exact position, "
            "or refuse. You never give coordinates — you cannot see the room's "
            "walls, floor or shapes, and inventing a position would be "
            "inventing a measurement.\n\n"
            "Call this when the person asks for a change. Do NOT call it for "
            "an idea of your own: describe the idea, offer it, and wait for a "
            "yes. Each change replaces any earlier change to the same piece.\n\n"
            "The result tells you, per change, either that it was applied and "
            "gives you a sentence describing where the piece now stands — use "
            "THAT WORDING, do not write your own — or that it was refused and "
            "why. A refusal is a real answer: say it plainly."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "changes": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 4,
                    "items": {
                        "type": "object",
                        "properties": {
                            "object_id": {
                                "type": "string",
                                "description": (
                                    "The id of the piece to change, exactly as "
                                    "it appears in THE FACTS inventory."
                                ),
                            },
                            "action": {
                                "type": "string",
                                "enum": ["move", "remove"],
                                "description": (
                                    "'move' repositions the piece; 'remove' "
                                    "takes it out of the room so the person can "
                                    "see the space without it."
                                ),
                            },
                            "relation": {
                                "type": "string",
                                "enum": sorted(RELATIONS),
                                "description": (
                                    "Where to put it, for 'move' only. "
                                    "against_wall: flush against a wall. "
                                    "centered_on_wall: flush and centred. "
                                    "beside: alongside another piece. "
                                    "nearer_to / further_from: along the line "
                                    "between it and another piece."
                                ),
                            },
                            "anchor": {
                                "type": "string",
                                "description": (
                                    "What to place it relative to. For beside / "
                                    "nearer_to / further_from this must name "
                                    "another piece from the inventory. For "
                                    "against_wall and centered_on_wall you may "
                                    "pass the person's own words for a feature "
                                    "of the room — 'the window', 'the door' — "
                                    "even though you cannot see one; the room's "
                                    "measurements resolve it or refuse. Leave "
                                    "empty for simply 'against a wall'."
                                ),
                            },
                        },
                        "required": ["object_id", "action"],
                    },
                }
            },
            "required": ["changes"],
        },
    },
    {
        "name": REVERT,
        "description": (
            "Put pieces back where the room was measured. Pass the object ids "
            "to undo, or \"all\" to return the whole room to exactly how it was "
            "scanned. Always available, and always cheap — say so when someone "
            "hesitates about trying something."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "keys": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Object ids from the inventory, or the single value "
                        "\"all\"."
                    ),
                }
            },
            "required": ["keys"],
        },
    },
]


@dataclass
class ToolOutcome:
    """What one tool round did. `spec` is the arrangement after the round;
    `changed` says whether anything actually moved, so the caller only writes
    and only re-derives facts when there is something to write."""
    spec: DesignSpec
    result: dict
    changed: bool
    flags: list[str]
    descriptions: list[str]


def _find(geometry: RoomGeometry, object_id: str) -> RoomObject | None:
    """The model addresses pieces by manifest object_id — what THE FACTS
    inventory shows it. The spec keys on the box identifier where one exists
    (0131), so this is the one place the two namespaces meet."""
    want = str(object_id or "").strip()
    for obj in geometry.objects:
        if obj.object_id == want or obj.key == want:
            return obj
    # A model that answers with the spoken name instead of the id is being
    # helpful, not wrong; resolving it is cheaper than a refusal the person
    # would find baffling.
    lowered = want.lower()
    for obj in geometry.objects:
        if obj.name.lower() == lowered or obj.label.lower() == lowered:
            return obj
    return None


def _measured(obj: RoomObject) -> Transform | None:
    if obj.position is None:
        return None
    return Transform(
        position=obj.position,
        rotation_xyzw=(0.0, 0.0, 0.0, 1.0),
        scale=1.0,
    )


def _footprint(obj: RoomObject) -> Footprint | None:
    if obj.box is None:
        return None
    return Footprint(
        center_world=obj.box.center,
        half_extents_m=obj.box.half_extents,
        yaw_rad=obj.box.yaw_rad,
    )


def run_propose(
    *,
    spec: DesignSpec,
    geometry: RoomGeometry,
    manifest_transforms: dict[str, Transform],
    changes: list[dict],
    turn_index: int | None,
    client_msg_id: str | None,
) -> ToolOutcome:
    """Ground each stated change, or refuse it, and fold the survivors into
    the arrangement.

    Per-change independence is deliberate: three changes where one cannot be
    grounded ship the two that can, and the guest reports the third honestly.
    An all-or-nothing transaction would make one impossible request silently
    discard two good ones.
    """
    results: list[dict] = []
    descriptions: list[str] = []
    flags: list[str] = []
    changed = False

    for raw in changes[:4]:
        object_id = str((raw or {}).get("object_id") or "")
        action = str((raw or {}).get("action") or "")
        obj = _find(geometry, object_id)
        if obj is None:
            results.append({
                "object_id": object_id, "applied": False, "reason": "unknown_object",
            })
            continue
        if action not in ("move", "remove"):
            results.append({
                "object_id": object_id, "applied": False, "reason": "unknown_action",
            })
            continue
        measured = manifest_transforms.get(obj.key) or _measured(obj)
        if measured is None:
            results.append({
                "object_id": object_id, "applied": False, "reason": "piece_not_placed",
            })
            continue

        if action == "remove":
            entry = SpecEntry(
                key=obj.key,
                action="remove",
                label=obj.name,
                measured_transform=measured,
                proposed_transform=None,
                measured_footprint=_footprint(obj),
                solver=None,
                description=f"the {obj.name} is out of the room",
                turn_index=turn_index,
                client_msg_id=client_msg_id,
            )
            spec = spec.with_entry(entry)
            changed = True
            descriptions.append(entry.description)
            results.append({
                "object_id": obj.object_id,
                "applied": True,
                "description": entry.description,
            })
            continue

        outcome = solve(
            geometry,
            key=obj.key,
            relation=str(raw.get("relation") or "against_wall"),
            anchor=raw.get("anchor"),
        )
        if isinstance(outcome, Refusal):
            results.append({
                "object_id": obj.object_id,
                "applied": False,
                "reason": outcome.reason,
                **({"detail": outcome.detail} if outcome.detail else {}),
            })
            continue
        assert isinstance(outcome, Solution)
        entry = SpecEntry(
            key=obj.key,
            action="move",
            label=obj.name,
            measured_transform=measured,
            proposed_transform=Transform(
                position=outcome.position,
                rotation_xyzw=measured.rotation_xyzw,
                scale=measured.scale,
            ),
            measured_footprint=_footprint(obj),
            solver=SolverTrace(
                relation=outcome.relation,
                anchor_resolved_to=outcome.anchor_resolved_to,
                constraints_applied=outcome.constraints_applied,
                reasoning=outcome.reasoning,
            ),
            description=outcome.description,
            turn_index=turn_index,
            client_msg_id=client_msg_id,
        )
        spec = spec.with_entry(entry)
        changed = True
        descriptions.append(entry.description)
        results.append({
            "object_id": obj.object_id,
            "applied": True,
            "description": entry.description,
        })

    return ToolOutcome(
        spec=spec,
        result={"changes": results},
        changed=changed,
        flags=flags,
        descriptions=descriptions,
    )


def run_revert(
    *, spec: DesignSpec, geometry: RoomGeometry, keys: list[str]
) -> ToolOutcome:
    wanted = [str(k) for k in (keys or [])]
    if any(k.strip().lower() == "all" for k in wanted):
        removed = len(spec.entries)
        return ToolOutcome(
            spec=spec.without({e.key for e in spec.entries}),
            result={"reverted": removed, "description": "the room is back as measured"},
            changed=removed > 0,
            flags=[],
            descriptions=["the room is back as measured"] if removed else [],
        )
    resolved: set[str] = set()
    for k in wanted:
        obj = _find(geometry, k)
        if obj is not None:
            resolved.add(obj.key)
        elif spec.by_key(k) is not None:
            # An ORPHANED entry can still be reverted even though its object
            # is gone from the manifest — clearing it is exactly what a person
            # who sees "this piece is no longer in the room" wants to do.
            resolved.add(k)
    hit = {e.key for e in spec.entries} & resolved
    return ToolOutcome(
        spec=spec.without(hit),
        result={
            "reverted": len(hit),
            "description": (
                "put back as measured" if hit else "nothing to put back"
            ),
        },
        changed=bool(hit),
        flags=[],
        descriptions=["put back as measured"] if hit else [],
    )


def run_tool(
    name: str,
    tool_input: dict,
    *,
    spec: DesignSpec,
    geometry: RoomGeometry,
    manifest_transforms: dict[str, Transform],
    turn_index: int | None,
    client_msg_id: str | None,
) -> ToolOutcome:
    if name == PROPOSE:
        changes = tool_input.get("changes")
        if not isinstance(changes, list) or not changes:
            return ToolOutcome(spec, {"error": "no_changes"}, False, [], [])
        return run_propose(
            spec=spec,
            geometry=geometry,
            manifest_transforms=manifest_transforms,
            changes=[c for c in changes if isinstance(c, dict)],
            turn_index=turn_index,
            client_msg_id=client_msg_id,
        )
    if name == REVERT:
        keys = tool_input.get("keys")
        return run_revert(
            spec=spec,
            geometry=geometry,
            keys=keys if isinstance(keys, list) else [],
        )
    return ToolOutcome(spec, {"error": "unknown_tool", "name": name}, False, [], [])


# ---------------------------------------------------------------------------
# Observe-only telemetry (0132; the shape 0058 established)
# ---------------------------------------------------------------------------

# Words that make a message a REQUEST rather than a musing. Deliberately
# generous: this flag exists to notice a guest acting on its own idea, and a
# false negative (staying quiet about a real request) costs nothing while a
# false positive would train an operator to ignore the flag.
_REQUEST_RE = re.compile(
    r"\b(move|shift|put|place|push|pull|slide|swap|take|remove|get rid|clear|"
    r"try|show me|what if|could we|can we|can you|let'?s|go ahead|do it|yes|"
    r"sure|please|okay|ok)\b",
    re.IGNORECASE,
)


def unprompted_proposal(user_text: str, proposed: bool) -> bool:
    """Did this turn change the room without being asked?

    0132: the guest may suggest, never act. This does not block — it is the
    same non-blocking telemetry shape as the foreign-measurement detector,
    which is how this project has caught voice regressions before.
    """
    return proposed and not _REQUEST_RE.search(user_text or "")


def tool_result_texts(results: list[dict]) -> list[str]:
    """Every server-authored string a turn's tools produced.

    Feeds the foreign-measurement allowlist: 0132 extends it to facts ∪ user
    window ∪ TOOL RESULTS, because a description the server wrote is exactly
    as trustworthy as a fact the server derived — it came from the same place.
    """
    out: list[str] = []
    for result in results:
        for change in result.get("changes") or []:
            text = change.get("description")
            if isinstance(text, str) and text:
                out.append(text)
        text = result.get("description")
        if isinstance(text, str) and text:
            out.append(text)
    return out


def log_turn_tools(
    scene_id: str, results: list[dict], flags: list[str], now: datetime
) -> None:
    applied = sum(
        1 for r in results for c in (r.get("changes") or []) if c.get("applied")
    )
    refused = [
        c.get("reason")
        for r in results
        for c in (r.get("changes") or [])
        if not c.get("applied")
    ]
    logger.info(
        "conversation_tools scene_id=%s at=%s rounds=%d applied=%d refused=%s flags=%s",
        scene_id,
        now.isoformat(),
        len(results),
        applied,
        ",".join(str(r) for r in refused) or "-",
        ",".join(flags) or "-",
    )
