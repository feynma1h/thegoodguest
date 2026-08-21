"""The guest's hands: two tools, and the runner that keeps them honest.

Decision 0132. Stage 1 shipped ZERO tools by design — 0058 recorded it as
architectural, not charter. This module is the first time the guest gets
hands, and the whole shape follows from one thing found by READING the
charter rather than designing against it: **the guest cannot compute a target
position.** Rule 5 forbids it knowing which way anything faces, the shapes of
things, or the room's own walls and floor — "they may well be there on the
screen in front of the person, but they did not reach you". Rule 3b gives it a
height and an unlabelled pair of floor figures, and no way to tell which of
that pair runs which way.

So a tool shaped `move(object, x, y, z)` would require the guest to author
coordinates from a world in which walls, facings and footprints do not exist.
That is exactly rule 2's "made-up number wearing a measured costume — the one
lie this house cannot forgive, because no one can see it happening". A
coordinate-taking tool does not stretch the honesty contract; it inverts it.

Hence: **the guest states an INTENT in the vocabulary it can actually see; a
server-side solver turns that into a transform or refuses.**

A FACING CORRECTION IS THE EXCEPTION THAT PROVES IT (decision 0157). The
guest may not know which way a piece faces — and neither does the pipeline:
the 180° sign of a splat inside its measured box is settled by no instrument,
five families having now been refuted on it. So `turn` takes no direction and
no angle. The person supplies the only evidence that exists; the room selects
the other of the two mappings it already enumerated. It is the one place where
the guest changes something it cannot see, and it does so on the person's
authority rather than its own.

The tool RESULT
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
from dataclasses import dataclass, replace
from datetime import datetime

from design_spec import (
    DesignSpec,
    Footprint,
    SolverTrace,
    SpecEntry,
    Transform,
)
from room_geometry import RoomGeometry, RoomObject
from spec_solver import RELATIONS, Refusal, Solution, solve, turn_around

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
            "yes. A second change to the same piece replaces the first, except "
            "that turning it round and putting it somewhere are independent — "
            "a piece can be both.\n\n"
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
                                "enum": ["move", "remove", "turn"],
                                "description": (
                                    "'move' repositions the piece; 'remove' "
                                    "takes it out of the room so the person can "
                                    "see the space without it; 'turn' sits it "
                                    "the other way round where it stands.\n\n"
                                    "Use 'turn' only when the person tells you a "
                                    "piece is facing the wrong way. The scan "
                                    "could not work out which way round a piece "
                                    "sits, so it guessed, and they are the only "
                                    "one who can see the answer. There is "
                                    "exactly one turn available — the other way "
                                    "round — and it takes no direction, no angle "
                                    "and no anchor. Turning twice returns it to "
                                    "the way the scan drew it."
                                ),
                            },
                            "relation": {
                                "type": "string",
                                "enum": sorted(RELATIONS),
                                "description": (
                                    "Where to put it, for 'move' only — a turn "
                                    "takes none. "
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
            "hesitates about trying something.\n\n"
            "This undoes moves and removals. A piece the person told you was "
            "facing the wrong way STAYS turned — nothing measured which way it "
            "faces, so there is no measurement to put it back to, and they "
            "would only have to tell you again. To undo that, turn it once "
            "more."
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


def _spoken_form(text: str) -> str:
    """A spoken name reduced to what it says, so punctuation and articles
    cannot decide whether a piece is found.

    THE FACTS inventory shows the model a NAME, and this field is called
    object_id, so the model reasonably turns "the red chair" into "red_chair".
    Measured on the transcript's own first turn: 5 of 8 samples emitted the
    underscored form and were refused. It is not a new gap — 2 of 8 missed on
    the bare article under the pre-0184 ordinal names — but multi-word names
    made it fire far more often, and a person asking for their red chair being
    told the room does not recognise it is the worst refusal we ship.

    Reduction only, never fuzzy matching: names are unique space-separated
    words, so this can resolve more and can never resolve differently.
    """
    lowered = re.sub(r"[_\-]+", " ", str(text or "").lower())
    lowered = re.sub(r"\s+", " ", lowered).strip(" .,'\"")
    return re.sub(r"^the\s+", "", lowered)


def _find(geometry: RoomGeometry, object_id: str) -> RoomObject | Refusal:
    """Resolve whatever the model put in `object_id` to a piece of the room,
    or refuse.

    Three namespaces meet here and only here: the manifest object_id, the spec
    key (the box identifier where one exists, 0131), and the spoken NAME — the
    last of which is what THE FACTS inventory actually shows the model, which
    is why the name path carries most of the traffic and all of the tolerance.

    TWO CANDIDATES REFUSE RATHER THAN PICK (decision 0213). The name path
    falls back to the bare LABEL, and a label is shared: "chair" in a
    two-chair room used to resolve to whichever object sorted first, and
    nothing anywhere told the person which one it had picked. That is the one
    failure this layer must never have — a wrong piece moves on screen and
    reads as the room being wrong. The discipline and the tiering are
    `spec_solver.resolve_object_anchor`'s, which has refused ambiguous
    ANCHORS since 0132; the subject of a change simply never got the same
    treatment.

    Tiers are tried in order and the first that hits anything decides, so a
    name that is exact for one piece is never lost to a label two pieces
    share: "red chair" resolves where "chair" refuses.

    UNPLACED PIECES ARE CANDIDATES HERE, unlike in `resolve_object_anchor`,
    which considers only what it can measure against. A glimpsed piece is
    something the person can still refer to, and resolving it earns the
    specific `piece_not_placed` refusal below rather than the baffling
    `unknown_object`.
    """
    want = str(object_id or "").strip()
    for obj in geometry.objects:
        if obj.object_id == want or obj.key == want:
            return obj
    # A model that answers with the spoken name instead of the id is being
    # helpful, not wrong; resolving it is cheaper than a refusal the person
    # would find baffling.
    spoken = _spoken_form(want)
    if not spoken:
        return Refusal("unknown_object")
    for match in (
        lambda o: _spoken_form(o.name) == spoken,
        lambda o: _spoken_form(o.label) == spoken,
    ):
        hits = [o for o in geometry.objects if match(o)]
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:
            return Refusal("ambiguous_object", _candidates(hits))
    return Refusal("unknown_object")


def _candidates(hits: list[RoomObject]) -> str:
    """What the guest may offer the person, and an honest count of what it
    may not.

    A bookkeeping name is an ordinal scene_facts assigned because nothing
    measured separates that piece from its siblings, and 0184 is explicit
    that it is not a referent — the person cannot tell which chair is the
    third one either. Listing them here would hand the guest exactly the
    vocabulary the production walk caught it teaching people, arriving by a
    new road: a tool result is server-authored, and rule 2a asks the guest to
    quote those verbatim.

    So the detail names only the pieces a person could have meant, and says
    plainly how many it cannot name. Where that is all of them, the refusal
    is the whole answer — which is the honest end of "nothing separates
    them", not a gap in this function.
    """
    named = [o for o in hits if not o.named_by_bookkeeping]
    nameable = sorted({o.name for o in named})
    rest = len(hits) - len(named)
    label = hits[0].label
    if not nameable:
        return f"{len(hits)} {label}s that nothing separates"
    if not rest:
        return ", ".join(nameable)
    return (
        f"{', '.join(nameable)}, and {rest} more {label}"
        f"{'s' if rest > 1 else ''} that nothing separates"
    )


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
        found = _find(geometry, object_id)
        if isinstance(found, Refusal):
            results.append({
                "object_id": object_id,
                "applied": False,
                "reason": found.reason,
                **({"detail": found.detail} if found.detail else {}),
            })
            continue
        obj = found
        if action not in ("move", "remove", "turn"):
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

        # A facing correction survives whatever else happens to the piece: it
        # is something the person KNOWS about their room, not an experiment,
        # so moving or removing a corrected piece must not quietly undo it.
        prior = spec.by_key(obj.key)
        was_flipped = prior is not None and prior.facing_flipped

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
                facing_flipped=was_flipped,
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

        if action == "turn":
            turned = turn_around(geometry, key=obj.key)
            if isinstance(turned, Refusal):
                results.append({
                    "object_id": obj.object_id,
                    "applied": False,
                    "reason": turned.reason,
                    **({"detail": turned.detail} if turned.detail else {}),
                })
                continue
            existing = spec.by_key(obj.key)
            if existing is not None and existing.facing_flipped:
                # Turning is its own inverse, so a second turn puts the piece
                # back the way the scan drew it. Storing an entry that claims
                # a change equal to no change would have the room reporting
                # "1 piece turned" while nothing is turned, so the entry goes
                # instead — and with it any move it had composed onto, which
                # is why this reverts rather than merely un-flipping.
                spec = spec.without({obj.key})
                changed = True
                description = f"the {obj.name} is back the way the scan drew it"
                descriptions.append(description)
                results.append({
                    "object_id": obj.object_id,
                    "applied": True,
                    "description": description,
                })
                continue
            # A turn composes onto whatever this piece is already doing: a
            # moved piece keeps its proposed position, and only the facing
            # changes. Dropping the move here would silently discard
            # something the person asked for one turn earlier.
            base = existing.proposed_transform if existing is not None else measured
            entry = SpecEntry(
                key=obj.key,
                action=existing.action if existing is not None else "turn",
                label=obj.name,
                measured_transform=measured,
                proposed_transform=Transform(
                    position=(base or measured).position,
                    rotation_xyzw=turned.rotation_xyzw,
                    scale=(base or measured).scale,
                ),
                measured_footprint=_footprint(obj),
                solver=(
                    existing.solver if existing is not None
                    else SolverTrace(
                        relation="turn_around",
                        anchor_resolved_to="",
                        constraints_applied=("keeps_position", "keeps_footprint"),
                        reasoning=turned.reasoning,
                    )
                ),
                description=(
                    turned.description if existing is None
                    else f"{existing.description}, turned around"
                ),
                turn_index=turn_index,
                client_msg_id=client_msg_id,
                facing_flipped=True,
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
                rotation_xyzw=(
                    prior.proposed_transform.rotation_xyzw
                    if was_flipped and prior.proposed_transform is not None
                    else measured.rotation_xyzw
                ),
                scale=measured.scale,
            ),
            measured_footprint=_footprint(obj),
            solver=SolverTrace(
                relation=outcome.relation,
                anchor_resolved_to=outcome.anchor_resolved_to,
                constraints_applied=outcome.constraints_applied,
                reasoning=outcome.reasoning,
            ),
            description=(
                f"{outcome.description}, still turned around"
                if was_flipped else outcome.description
            ),
            turn_index=turn_index,
            client_msg_id=client_msg_id,
            facing_flipped=was_flipped,
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


def _revert_entries(
    spec: DesignSpec, geometry: RoomGeometry, keys: set[str]
) -> tuple[DesignSpec, int]:
    """Put the named pieces back where the room was measured, KEEPING any
    facing correction (decision 0157).

    Revert restores measurements. A facing correction departs from no
    measurement — the 180° sign of a splat inside its box is settled by
    nothing — so there is no measured facing for a revert to restore, and
    dropping the correction would re-introduce an error the person has
    already told us about. The measured room really is one step away
    (0133's invariant): a turn never left it.

    So an entry that carries a facing correction is REDUCED to a pure turn
    rather than dropped, its reasoning regenerated by the solver so the
    sentence has one author. A piece that has since stopped being turnable —
    a re-drive that dropped its box — cannot have that trace regenerated, and
    is dropped rather than described in words nothing can source.
    """
    kept: list = []
    reverted = 0
    for entry in spec.entries:
        if entry.key not in keys:
            kept.append(entry)
            continue
        reverted += 1
        if not entry.facing_flipped:
            continue
        turned = turn_around(geometry, key=entry.key)
        if isinstance(turned, Refusal):
            continue
        kept.append(SpecEntry(
            key=entry.key,
            action="turn",
            label=entry.label,
            measured_transform=entry.measured_transform,
            proposed_transform=Transform(
                position=entry.measured_transform.position,
                rotation_xyzw=turned.rotation_xyzw,
                scale=entry.measured_transform.scale,
            ),
            measured_footprint=entry.measured_footprint,
            solver=SolverTrace(
                relation="turn_around",
                anchor_resolved_to="",
                constraints_applied=("keeps_position", "keeps_footprint"),
                reasoning=turned.reasoning,
            ),
            description=turned.description,
            turn_index=entry.turn_index,
            client_msg_id=entry.client_msg_id,
            facing_flipped=True,
        ))
    return replace(spec, entries=tuple(kept)), reverted


def _revert_description(spec: DesignSpec, whole_room: bool) -> str:
    """What a revert says it did. It must never claim the room is as measured
    while a facing correction still stands — the person would hear that the
    thing they told us had been thrown away."""
    turned = sum(1 for e in spec.entries if e.facing_flipped)
    base = "the room is back as measured" if whole_room else "put back as measured"
    if not turned:
        return base
    piece = "piece" if turned == 1 else "pieces"
    return f"{base}, with the {turned} {piece} you turned still turned"


def run_revert(
    *, spec: DesignSpec, geometry: RoomGeometry, keys: list[str]
) -> ToolOutcome:
    wanted = [str(k) for k in (keys or [])]
    refused: list[dict] = []
    whole_room = any(k.strip().lower() == "all" for k in wanted)
    if whole_room:
        resolved = {e.key for e in spec.entries}
    else:
        resolved = set()
        for k in wanted:
            found = _find(geometry, k)
            if not isinstance(found, Refusal):
                resolved.add(found.key)
                continue
            if spec.by_key(k) is not None:
                # An ORPHANED entry can still be reverted even though its
                # object is gone from the manifest — clearing it is exactly
                # what a person who sees "this piece is no longer in the room"
                # wants to do.
                resolved.add(k)
                continue
            if found.reason == "ambiguous_object":
                # The same discipline as propose (0213): putting the wrong
                # piece back is as wrong as moving the wrong piece. Silence
                # would be worse here than in propose, because "nothing to
                # put back" is a lie in this case — there IS something, and
                # the room simply cannot tell which of them was meant.
                refused.append({
                    "key": k, "reason": found.reason, "detail": found.detail,
                })
    hit = {e.key for e in spec.entries} & resolved
    out, reverted = _revert_entries(spec, geometry, hit)
    if reverted:
        description = _revert_description(out, whole_room)
    elif refused:
        description = ""
    else:
        description = "nothing to put back"
    result: dict = {"reverted": reverted}
    if description:
        result["description"] = description
    if refused:
        result["refused"] = refused
    return ToolOutcome(
        spec=out,
        result=result,
        changed=bool(reverted),
        flags=[],
        descriptions=[description] if reverted else [],
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
    ] + [
        # revert refuses too, since 0213 — and an ambiguous reference is
        # exactly the thing worth counting in production, because it is the
        # one refusal shape no real conversation has ever produced.
        c.get("reason") for r in results for c in (r.get("refused") or [])
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
