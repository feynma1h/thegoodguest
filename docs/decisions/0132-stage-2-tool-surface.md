# 0132 — Stage 2's tool surface: the guest states intent, the server solves geometry

**Date:** 2026-08-09
**Status:** Decided and BUILT, not yet deployed — `services/api-public/
guest_tools.py` ships `propose` and `revert`, and the charter moved to
PROMPT_VERSION 3. Merged to `main` 2026-08-09; no real model has called the
tools yet and the live voice evals have not run. Extends 0058's guest contract.

## Context

Stage 1 ships **zero tools by design** — 0058 records it as architectural, not
charter: *"The model call has ZERO tools — read-only is architectural, not
charter"*, with the refusal worked into the prompt (`guest_prompt.py` rule 6,
"today you have eyes, not hands") and an exemplar for *"Move the sofa under the
window."* Stage 2 is the first time the guest gets hands, and the question is the
minimum set, and how honesty survives contact with them.

## What we found first, by reading the charter rather than designing against it

The guest **cannot compute a target position**, and this is recorded, not
speculative. Rule 5 forbids it knowing which way anything faces, the shapes of
things, or **the room's own walls and floor** — *"they may well be there on the
screen in front of the person, but they did not reach you"*. Rule 3b (0096) says
a size is a longest dimension with unrecoverable axis semantics. Rule 3a says
clearances are floors, not measurements.

So a tool shaped `move(object, x, y, z)` would require the guest to author
coordinates from a world in which walls, facings and footprints do not exist.
That is precisely rule 2's *"made-up number wearing a measured costume — the one
lie this house cannot forgive, because no one can see it happening."* A
coordinate-taking tool does not stretch the honesty contract; it inverts it.

Meanwhile the **server** holds exactly what is missing: the shell's floor polygon
and wall polygons with parented door/window openings (0069/0077), RoomPlan boxes
with position, yaw and dims, clip volumes (0104), and closed-form contact solvers
that already exist — `solve_floor_contact`, `solve_wall_contact`,
`minimal_rotation` in `placement_math.py`, built for 0067 chunk D.

## What we chose

**Two tools. The guest states an intent in the vocabulary it can actually see;
a server-side solver turns that into a transform or refuses.**

```
propose(changes: [{ key, action: "move" | "remove", relation?, anchor? }])
revert(keys: [...] | "all")
```

- `relation` comes from a closed vocabulary the solver can genuinely satisfy —
  against a wall, beside a piece, centred on a wall, further from / nearer to a
  piece. Not free text.
- `anchor` is either **another object** (the guest can see the inventory) or
  **the person's own referring expression**, passed through verbatim. The guest
  may write `anchor: "the window"` without knowing where any window is; the
  solver resolves it against the shell's openings, or refuses when there are two.
- The **tool result is the honest surface**: per change, either
  `{applied: true, description: "<server-authored sentence>", facts_delta: {...}}`
  or `{applied: false, reason: "<machine reason>"}`.

**Rule 2 extends by one word: transforms are verbatim too.** The guest may
describe a placement only using the server's sentence for it. It never says where
something now stands in its own words, for the same reason it never computes a
distance. This costs nothing to enforce — it is the mechanism 0058 already built,
pointed at a second class of value — and the existing foreign-measurement
detector generalises to it directly: the allowlist becomes facts ∪ user window ∪
**tool results**.

**One new charter rule, and it is the load-bearing one:**

> **10. Facts about a proposed arrangement are conditional, and you say so.**
> A clearance in a room you have rearranged is what *would* be guaranteed if the
> piece went there. It is still a floor and still never a fit. Never speak a
> proposed arrangement in the same grammar as a measured one.

The rest of the honesty machinery **transfers unmodified**, which is the good
surprise: `derive_scene_facts` reads box dims and positions, a proposal changes
positions, and the circumradius clearance bound in 0096 is true under any yaw and
therefore true under any arrangement. So the solver can re-derive facts for the
proposed room with the same code and the same epistemics. Sizes do not change at
all.

**No read tools.** The facts block is the guest's world (0058: "the model's
ENTIRE world"), and adding a lookup tool would give it a second, ungoverned
channel to the manifest — reopening exactly what 0058 closed by refusing to put
the raw manifest in the prompt.

**Unprompted proposals: the guest may suggest, never act.**

- An explicit instruction ("move the bed to the other wall") calls `propose`
  immediately. Revert is always one action away, so confirmation dialogs would be
  friction protecting nothing.
- An unprompted idea is **speech only**. The guest describes it and offers; the
  tool fires only if the person says yes.

This keeps stage 1's invitation-shaped charter intact rather than replacing it,
and it is checkable the way 0058 checks voice: an observe-only flag when a turn
calls `propose` and the user's message contains no request — the same
non-blocking telemetry shape as the foreign-measurement detector, which is how
this project has caught voice regressions before.

## Why

**The split puts each claim with whoever can source it.** The guest owns
language, the solver owns geometry, and neither is asked for the other. Every
alternative we considered fails on the same seam: a coordinate tool asks the
model to invent measurements; a "solve it in the prompt" approach means putting
walls and footprints into the facts block, which is the raw-manifest rejection
from 0058 arriving by a different road; a free-text relation makes the refusal
path unenumerable.

**Refusal is the feature, not the fallback.** The solver returning
`{applied: false, reason}` is the same shape as `placed: false` with a reason,
which this pipeline has shipped since 0052 and which 0067 chunk D restated as
THE EVIDENCE RULE: *a proposed transform ships only if it reprojects onto the
object's own mask; a guessed transform is never emitted.* A proposal that cannot
be grounded in measured geometry should not exist, and the guest saying "I
couldn't place that, here's why" is entirely in voice — it is what rule 6 already
does today, with a better reason.

**Passing the person's own words through to the solver is what lets the guest
stay honest about the window.** It never claims to see one. It tries, and reports
what came back. Compare the alternative — teaching the guest about openings so it
can pick a wall — which would require breaking rule 5, the rule that currently
keeps it from describing a room it cannot see.

## What would change this decision

- **Sizes gain axis semantics.** 0096's own re-open trigger: one additive
  manifest field for the up-axis extent retires longest-dimension-only. Then the
  guest could reason about footprints, and a richer relation vocabulary
  ("along the long wall") becomes sayable.
- **The solver needs geometry the conversation path does not load.** Today the
  conversation route loads only the manifest, via
  `cached_scene_facts(scene_id, load_manifest)`; the shell is read only in
  `/assets`. The solver needs the shell, so this adds a read to the turn's hot
  path. 0124 measured `/assets` signing at 0.9–2.6 s and deliberately left it;
  the shell needs no signing, but the fetch is new and should be measured, not
  assumed cheap.
- **Direct manipulation ships.** Dragging a piece produces a transform with no
  relation and no solver reasoning, which is a different provenance class (0131).
- **A relation proves unsolvable often enough to be a bad promise.** If the
  refusal rate on a common relation is high, the honest move is to drop it from
  the vocabulary rather than loosen the solver.
