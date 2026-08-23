# 0186 — rule 5 forbade what rule 6 grants

**Date:** 2026-08-24
**Status:** Decided and BUILT at `PROMPT_VERSION 7`.

## Context

The guest's charter rule 5 lists what it cannot see, and ends the walls-and-
floor clause:

> …they did not reach you, so never describe them, **place anything against
> one**, or say a room has none.

Rule 6 says moving works by naming a piece and a relation, *"against a wall"*
first among its examples. The `propose` tool offers `against_wall` and
`centered_on_wall`. The charter's own exemplar has the guest answer *"Move the
sofa under the window"* with *"Done — the sofa is against the wall, under the
window."*

So the charter forbids in rule 5 the thing it demonstrates in rule 6.

## What we tried

Found by the voice evals owed since 0213/0214, on their first run with a key.
`TestRuleTenGrammar` failed at its SETUP — the guest declining to move the
sofa against the wall at all:

> I can't do that one, I'm afraid — I have no walls in my facts. The scan gave
> me the pieces and how they sit relative to each other, but the room's own
> walls and floor never reached me, so **I can't place anything against one**.

That last clause is rule 5, quoted back almost verbatim. The guest was not
confused; it was obeying.

**Measured before changing anything**, one API call per sample against the eval
suite's own fixture: **17 of 26 wall placements applied**, so roughly a third
were refused outright. That is a capability the product ships, declined at
random, with a refusal that sounds principled.

**Why it was invisible until now.** The clause dates to `PROMPT_VERSION 2`,
when the guest had no hands at all — decision 0058 shipped zero tools by
design. In a guest that could only speak, *"place anything against one"* had
exactly one reading: do not assert that a piece stands against a wall you
cannot see. 0132 gave it hands and an `against_wall` relation at version 3,
and the verb acquired a second meaning that nobody re-read the old sentence
for. Four bumps passed over it.

**Why the evals did not catch it earlier.** They never ran. This is the first
eval run since 0213/0214 merged, and it is the deploy gate CLAUDE.md carries
doing its job on its first use.

## What we chose

Rule 5 keeps every limit it exists for and loses the ambiguous verb:

> …so never describe one, never say where one is, and never say a room has
> none. Putting a piece against a wall is a different thing and it is yours to
> do: the room holds those measurements, so it does the placing and hands you
> the words for where the piece ended up.

The reconciliation is stated positively rather than by deletion, so a later
edit cannot restore the contradiction by simply not noticing an absence.

**Measured after: 14 of 14 applied.** Against 17 of 26 before, Fisher
one-sided **p = 0.011**.

Pinned as a capability truth in `test_guest_prompt.py` — the charter must not
tell the guest it may not do what the tool schema offers it — rather than as
a phrasing, which is the distinction 0172 drew and this note follows.

## Why

**A refusal that sounds principled is the most expensive kind of wrong
answer.** Every other refusal this guest gives is real: the solver could not
ground the instruction, the piece was never placed, two candidates could not
be told apart. This one was the guest correctly obeying an instruction that
should not have been there, and it is indistinguishable from the honest ones
from outside — which is why it survived five versions and a production walk.

**The clause was right when it was written, and that is the lesson.** Nothing
about rule 5 was careless. It became false when the guest's capabilities grew
underneath it, and the version that grew them (0132) changed rule 6 without
re-reading rule 5. A charter is a single document the model reads whole, so
its rules can contradict each other in ways no single rule's review would
catch.

**The one-word fix beat the alternatives.** Deleting the clause would have lost
a real limit; rewriting rule 6 would have been fixing the correct half. The
guest quoting the exact phrase in its refusals said which words to change.

## What would change this decision

- **The residual refusals return.** 14 of 14 is a small sample, and the true
  rate after the fix is not zero-with-certainty. If wall placements start being
  declined again, measure before touching anything — the harness is four lines
  over the eval suite's own `_Room`.
- **Any future capability grant.** The durable lesson is that adding a hand to
  the guest means re-reading every rule that describes what it cannot do, not
  only the rule that grants the hand. Rule 5 still says the guest cannot see
  shapes, facings, materials or light; if any of those ever becomes something
  the room can act on, this same collision is waiting.
- **`propose` gains a relation phrased like a limit.** The collision was
  between a relation's NAME and a prohibition's verb. A relation called
  `describe_wall` would be the same accident.
