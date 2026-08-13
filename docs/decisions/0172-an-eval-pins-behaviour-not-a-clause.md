# 0172 — a voice eval pins behaviour, and cannot tell you which sentence holds it up

**Date:** 2026-08-14
**Status:** Decided — the suite is revised and green live at PROMPT_VERSION 4
(17 passed, 1 xfailed; the xfail is 0173, a defect this pass found rather than
one it caused).

## Context

0058 gates a PROMPT_VERSION bump on a live eval pass. 0107 adds the harder
half: `test_mutation_gets_the_mover_line` was green for a whole version while
asserting a contract the charter no longer had, passing on phrasing luck, and
its instruction to the next bump was explicit — **revise the suite first, not
after**. 0159 is the largest bump the charter has had, so this is the first
time that instruction has been due.

## What we tried

Seven evals for the v4 contract, over a harness that rebuilds the system
prompt every turn from the spec as it stands — production's own
`_proposed_view` two-liner, with history carrying user and assistant TEXT
only, because that is what production persists. Two of 0159's four exemplars
(revert leaving a correction standing; rule 10's exclusion) do not exist
inside a single turn and cannot be tested without it.

Then, before trusting the green, **ablation**: strip the clause each new
assertion nominally guards and check the assertion goes red.

It does not. Three variants, all measured live:

- 6c stripped of "never say what it now faces, because turning a thing did
  not give you eyes" → the guest still refuses to name a facing, 2/2.
- Rule 10 stripped of its turn exclusion → the guest still speaks a turned
  piece's distance plainly, 2/2, *against an arrangement block that tells it
  to say "would", every time*. It works out for itself that turning a thing
  does not move it.
- Both 6c's clause AND rule 5's facing item stripped, and the question
  sharpened to the one that actually baits the claim ("Which way is the sofa
  facing now?") → still refuses, 3/3.

So both v4 properties are over-determined: 6c's remaining clauses, the `turn`
tool's own description, and rule 5 each carry them. Under the FULL charter the
guest answers that question with "turning it didn't give me eyes" — quoting
6c's metaphor back — so the clause is certainly being read. It is simply not
the only thing holding the line.

Three assertions were wrong when measured, which is the whole point of
measuring:

- **The rule-10 move eval passed 2 runs in 5 on replies that refused to
  answer.** "Giving you a number would mean inventing one" satisfies a bare
  `\bwould\b` while doing none of rule 10's work. That is 0107's failure
  reproduced inside the eval written to honour 0107. It now names the refusal
  directly, and is strict-xfailed against the defect it exposed (0173).
- **The invitation ending was asserted per sample where the charter makes it
  conditional** — "when it comes naturally", "never force an invitation onto
  a reply that wants to end quietly". A/B against the serving v3 charter:
  5/8 at v4, 7/8 at v3, noise apart at that n, and every miss on both sides
  ended by honestly naming the unplaced plant. The bump did not cause it; the
  assertion was always over-tight. It is a rate now.
- **The facing claim was better probed by asking than by watching.** Checking
  a correction's narration for a facing claim is incidental; asking "which way
  is it facing now?" is the question a person actually asks and the sentence
  6c exists to stop.

## What we chose

**Ship the suite, and say in it what it is.** These evals pin BEHAVIOUR. A
green run says the voice is right; it does not license deleting charter text,
and the module docstring says so with the ablation results attached.

Two shapes are worth carrying beyond this bump:

**A rule is asserted every sample; a habit is asserted as a rate.** The
verbatim number is a rule — it is checked on four samples now instead of one,
which is a strengthening. The invitation is a habit, and the only honest
instrument for a behaviour the charter conditions on judgment is a rate with
a bar set where it catches the regression that matters (the habit diluted
away entirely, which is exactly what happened at 0096). The bar is not a
target: a run scraping past it is a voice worth looking at.

**A known failure is strict-xfailed, never softened.** `strict=True` means the
test goes red when the defect is FIXED, so the gap cannot rot and cannot close
unnoticed. Weakening the assertion instead would have been the 0107 sin with
the evidence already in hand.

## Why

0107 diagnosed the mechanism — "an eval suite pinned to a charter version does
not fail when the charter moves past it, it quietly starts certifying less" —
and prescribed revising before running. Doing that surfaced a second mechanism
worth naming: **revising first is necessary and not sufficient, because a
freshly written assertion can be unfalsifiable on arrival.** Two of the seven
new ones were, and only ablation showed it. The pinned-hash test catches a
charter change without a bump; nothing catches an assertion that cannot fail,
except trying to break it on purpose.

The over-determination is good news about the charter and bad news about
inference from green runs. Honesty properties in this charter are guarded
several times over — rule 5 says the guest cannot see a facing, 6c says
turning did not change that, the tool description says the scan could not work
it out — and the model needs any one of them. That redundancy is why the voice
is robust. It also means no eval here can be read as evidence that a
particular sentence is earning its place, and a future session trimming the
charter for length must not cite these passing.

## What would change this decision

- **An assertion that ablation DOES break.** Then the eval is evidence about
  a clause, not only about behaviour, and it can be cited as such — worth
  re-testing whenever a charter clause is proposed for deletion.
- **0173 fixed.** The move half of the rule-10 pair XPASSes, the marker comes
  off, and the pair starts doing the job it was built for: today the turn
  half's green is weaker than it looks, because a guest that hedges nothing
  also passes it.
- **A cheaper live harness.** The suite is 18 tests and roughly two minutes of
  wall clock, which is fine at one run per bump and would not be if it ever
  became a per-push gate — the same quota reasoning that keeps iOS CI on
  `workflow_dispatch` (0099).
