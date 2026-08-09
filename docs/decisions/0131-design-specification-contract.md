# 0131 — The Design Specification: a proposal sitting beside the measurement, never over it

**Date:** 2026-08-09
**Status:** Decided and BUILT, not yet deployed — `design_spec.py`,
`spec_solver.py`, and `room_geometry.py` in api-public, with the web overlay in
`web/src/lib/designSpec.ts`. Merged to `main` 2026-08-09; api-public still
serves the pre-stage-2 image, and the live voice evals decision 0058 requires
on a PROMPT_VERSION bump have not run. Extends 0056's stage-2 half.

## Context

0056 named the Design Specification and the reactive scene as "two halves of one
mechanism (conversation mutates the spec; the scene reconciles against it)" and
scheduled both for stage 2. 0055 lists "a specification contract driving all
rendering" as durable architecture. Neither says what the document *is*.

The board-9 brief poses the central question sharply: this project's deepest
invariant is that **measurement is never falsified** — 0069 ships `measured_quad`
beside the rendered quad, 0082 refuses to move an object to hide a splat artifact,
0104 declares a clip volume rather than rescaling, placement ships `placed: false`
with a reason rather than a guessed transform — and a Design Specification is by
construction a set of **non-measured** transforms. How proposed and measured
coexist without the product lying had to be answered before any schema.

## What we chose

**The spec is a sibling of the manifest, not a mutation of it — the same
relationship the shell already has** (0069: "a SIBLING of the manifest, read from
`scenes/{id}/shell.json` beside it"). It is a short list of *proposed
placements*; every object it does not name is exactly where perception measured
it. It never rewrites a manifest, and a manifest re-drive never invalidates it
silently.

**Every entry carries the measurement it departs from.** This is the whole
answer to the honesty question, and it is the house pattern rather than a new
idea: 0069 ships `measured_quad` beside the rendered quad, so a spec entry ships
`measured_transform` beside `proposed_transform`. The proposal is renderable and
the truth is one field away, always, at every layer — not reconstructible from
somewhere else, present in the same object.

Shape, per entry:

- `key` — see below
- `action` — `move` | `remove`
- `proposed_transform` — position/rotation/scale, absent for `remove`
- `measured_transform` — verbatim from the manifest, always present
- `solver` — `{ relation, anchor_resolved_to, constraints_applied[], reasoning }`
  (the reasoning trace 0055 lists as durable, produced by the solver, not the
  model)
- `origin` — `{ turn_index, client_msg_id }`: which exchange caused this

**Keying: `roomplan_box.identifier` where the object has a box, `object_id`
otherwise, with an explicit orphan state.** Object ids are assigned by fusion and
this project re-drives scenes constantly (0080's four warm re-drives changed
object counts on every room), so a spec keyed on `object_id` alone would silently
re-point at a different object. RoomPlan box identifiers are UUIDs carried
verbatim from the capture's `room.json`, which RP-3 reads from the outputs cache
on every re-drive — so within a scene they are stable across re-drives in a way
`object_id` is not. Entries whose key stops resolving become **orphaned and are
surfaced**, never dropped and never re-pointed.

**The spec renders through the existing viewer contract, with no new input
shape.** A spec entry becomes an override applied to `assembleScene`'s output:
`move` replaces the `PositionedSplat` transform, `remove` withholds the splat.
`PositionedSplat` already carries position, rotation, scale and clip — 0053's
containment boundary means the renderer never learns that a proposal exists.

**On screen, the measurement survives as its outline.** A moved piece leaves its
measured footprint drawn on the floor in the contour language decision 0097
already built for the reveal — the pen in the paper tone, which in this product
*means measurement*. This is deliberately not a badge or a chip: 0057 deleted
StatusBadge and settled that state reads as treatment plus words, and gold stays
light-semantic. Reusing the contour costs no new ornament, and it says the true
thing in the vocabulary the room already speaks.

**It lives server-side, keyed like the conversation.** Same
`{scene_id}__{user_id}` grain as 0058's conversations, in a **sibling document**
so that clearing a conversation does not silently discard an arrangement and
vice versa. The client stays a reader. Two consequences worth stating: a reload
shows the same proposed room, and the client never has an opportunity to author
a transform — which matters because 0058 already rejected client-computed values
feeding the guest's grounded claims.

## Why

**Sibling-not-mutation is forced, not chosen.** The manifest is perception's
output and is re-derived; a spec that edited it would be destroyed by the next
warm re-drive, and this project re-drives constantly. Keeping it beside also
means the answer to "where is my bed really?" is never a diff against a lost
original.

**Measured-beside-proposed is the only formulation this codebase would accept.**
Every place the project has faced "the honest value and the shipped value differ"
it has shipped both — `measured_quad`, `measured_polygon`, `splat_clip` declared
rather than applied to the geometry, `placed: false` with a reason. A spec that
carried only the proposal would be the first time the product held a position it
could not source, and it would be indistinguishable at the API from a
measurement. Carrying both makes the lie structurally unavailable rather than
prohibited by discipline — the same move 0058 made when it put `SceneFacts`
between the manifest and the model.

**The keying problem is real and is the kind that stays hidden.** A spec pointing
at the wrong object after a re-drive would not error; it would move the wrong
piece of furniture, and nothing in the system would notice. Orphaning loudly is
the same instinct as 0080's version-blind shell fast-path, which nooped silently
for a week.

**Rendering through `PositionedSplat` means the spec can ship before R3F.**
0056 called the spec and the reactive scene "two halves of one mechanism", and
they are — but only the *object set* changing needs reconciliation. Changing a
transform does not. That separation is what makes stage 2 schedulable
independently (see 0133).

## What would change this decision

- **Sharing arrives.** Then a spec is a thing one person shows another, and
  per-user keying becomes wrong in the same way 0058 flagged for conversations.
  The schema accommodates it; the product question is whose arrangement a
  visitor sees.
- **Proposals need to compose into named alternatives.** v1 is one arrangement
  per scene+user (0133). A second arrangement makes this a list and re-opens the
  version-history direction CLAUDE.md files as not-a-commitment.
- **A spec entry ever needs to be authored by anything other than the solver.**
  Direct manipulation (drag a piece in the viewer) would produce transforms with
  no `solver` block. That is a coherent extension, but it changes `reasoning`
  from always-present to sometimes-absent and the UI must then not imply one.
