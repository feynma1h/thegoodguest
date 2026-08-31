# 0108 — "back against the wall" reads as a revert, and stands anyway

**Date:** 2026-08-09
**Status:** Spent — the word changed (2026-08-10)

> **Outcome (2026-08-10):** the operator ruled "back" is revert's word,
> exclusively. The unconditional branch now reads "the {name} is against the
> wall"; the idiom survives only when the user supplies it (the charter
> exemplar keeps it in the user's mouth, and every other "back" in the
> exemplars is genuine revert-speak — no charter change, PROMPT_VERSION
> stays 3). The four flow-through pins were updated and a direct solver pin
> added (`test_a_first_time_move_never_says_back`) so the ruling cannot
> silently regress. Verified live on the deployed revision by re-running
> this note's own turn — "move the bed against a wall" on the reference
> room — and reading the reply and the spec description.

## Context

The first live conversational turn a real model ever took with the stage-2
tools, run against the api-public candidate before flipping traffic. The turn
worked: `propose` was called, the solver grounded the bed to `wall_10`, the
`arrangement` SSE event fired ahead of the text deltas, and the design spec
carried `measured_transform` beside `proposed_transform` exactly as decision
0131 requires.

The reply itself was:

> Done — the bed is back against the wall.

Nothing had been moved back. The bed was measured mid-room and this was its
first placement against a wall.

## What we tried

Checked whether the model had invented the word, since that would be a rule-2a
violation (placements are verbatim) on the very first live tool call.

It had not. The string is the **server's own**, at `spec_solver.py:422`:

```python
description=(
    f"the {obj.name} is against the wall, {where}"
    if opening is not None or relation == "centered_on_wall"
    else f"the {obj.name} is back against the wall"
),
```

So the guest quoted the room verbatim, which is precisely what it is told to
do. The guest is correct and the sentence it was handed is wrong.

The wording is also deliberate rather than a slip — `spec_solver.py:168`
documents the intent in a comment, calling the nearest-wall solve "a
measurable reading of *push it back against the wall*", and the charter
exemplar at `guest_prompt.py:173` puts that same idiom in the **user's**
mouth. Read as that idiom, "back" is directional (rearward, flush), not
temporal, and the sentence is fine.

## What we chose

Leave the string. Record the ambiguity and hand it to the operator as a voice
call.

## Why

Two reasons to leave it, and one real reason it may still want changing.

Leave it, because it is deliberate and it is voice. The comment proves intent,
so a future session that "fixes" it without this note would be undoing a
considered choice. And the string is test-pinned in four places
(`test_guest_prompt.py`, `test_design_spec.py`, `test_design_spec_routes.py`
×2), so changing it is a small edit with a wide blast radius — the kind of
thing that should be done on purpose, not folded into a deploy.

The reason it may want changing: the idiom only survives when the *user*
supplies it. My request was "move the bed against a wall", with no "back"
anywhere, and the reply came back "the bed is back against the wall" — which
reads as a revert. That reading is not far-fetched, because **`revert` is a
real operation in this same surface**, and its description is "the room is
back as measured". So "back" now does double duty across the two operations a
user most needs to tell apart: *you moved it* and *you put it back*. On a
one-sentence reply with no other context, those are genuinely ambiguous.

Worth noting the fix is small if it is wanted: the unconditional branch could
simply drop the word ("the bed is against the wall"), which loses nothing —
the idiomatic reading was never load-bearing, since the user's own phrasing
carries it whenever they use it.

## What would change this decision

- Anyone reading a transcript and misreading a first-time placement as an
  undo. That is the failure this predicts, and one real instance settles it.
- The reply shape more generally deserves the operator's eye: the charter's
  exemplar for a successful move is four sentences (what happened, that the
  old footprint is still drawn, that it is one step back, an invitation) and
  the live reply was one. That may be the model matching a short request's
  length per the charter's own "match their length" rule, or it may be the
  exemplar not landing. One turn is not enough to tell, and it is the same
  operator walk this note's ambiguity wants.
