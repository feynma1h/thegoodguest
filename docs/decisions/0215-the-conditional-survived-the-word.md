# 0215 — the conditional survived the word

**Date:** 2026-08-24
**Status:** Decided. The instrument is widened; the charter is not changed.

## Context

Decisions 0213 and 0214 shipped to `main` on 2026-08-21 with their unit
coverage green and their live voice evals never run, because the lane had no
`ANTHROPIC_API_KEY` and neither did the coordinator. CLAUDE.md carried that as
a deploy gate: `api-public` must not serve the refusal until the evals run
once.

The key was never missing. `anthropic-api-key` has been in Secret Manager
since 2026-07-21, enabled and readable by the operator's own account, and it
is already mounted into perception-obj's deploy. Nothing had connected it to
the eval harness. The gate cost this lane two days for want of one line.

## What we tried

The owed run, at `PROMPT_VERSION 6` / `FACTS_VERSION 4`: **26 passed, 1
failed**. The failure is
`TestRuleTenGrammar::test_a_moved_piece_speaks_its_new_distance_conditionally`.

**Every per-sample assertion in that test passed.** No invented provenance, no
refusal, the arrangement's own distance spoken — the three properties 0174
built the test to protect, and the three it demonstrated falsifiable against
the pre-fix block at 8/8. What failed is a RATE assertion over three samples
on the literal word "would", and all three replies read like this:

> About 2.2 m between the sofa's center and the table's center — that's how it
> stands with the sofa where it is now.

**The first attempt to measure the rate was unsound, and the way it was unsound
is worth recording.** Re-running the whole test five more times gave five more
reds, which looked like overwhelming evidence. It was not evidence at all: the
runs were counted by pass/fail without recording WHICH assertion failed, and
decision 0186 then found that the test's own setup — asking the guest to move
the sofa against a wall — was being refused about a third of the time. A run
that dies at setup collects no replies, so most of those reds say nothing
about "would". **A rate measured through a test that can fail for a second
reason is not a rate.**

Measured properly instead, one API call per sample against the same fixture,
counting only runs whose setup succeeded:

| | literal "would" | marked as the arranged room |
|---|---|---|
| before 0186's fix | 2/10 | 9/10 |
| after 0186's fix | 2/14 | 12/14 |
| **combined** | **4/24 (17%)** | **21/24 (88%)** |

Against 0174's measurement of the same two things — 12/16 for the word, 16/16
for the property — **the word has collapsed and the property has held**. Which
is what makes this a defect in the instrument rather than in the guest.

**Attribution to 0214 is SETTLED, and it is exonerated.** It gave the
rearranged room a provenance line opening *"as it stands on screen"*, and the
guest's replies echo that verb closely enough to suspect the facts block had
taught it a register that displaced rule 10's. The first attempt to test this
re-ran the whole test three times and read three reds — uninterpretable, by
the same flaw described above. Measured properly instead, paired and
interleaved, alternating the two provenance openings sample by sample:

| provenance opening | literal "would" | marked as arranged |
|---|---|---|
| shipped ("as it stands on screen") | 2/16 | 14/16 |
| neutral (the clause removed) | 4/16 | 14/16 |

The two arms do not separate (p = 0.33), and — the part that actually settles
it — **the neutral arm is still far below 0174's 12/16** (p = 0.006). Removing
the suspect clause does not bring the word back. Whatever moved rule 10's
grammar, it is not this. The property holds at 14/16 either way, which is the
same 88% the table above records.

That leaves the model behind `GUEST_MODEL` as the remaining explanation, and
the suite's own header already names a model change as trigger 2.

## What we chose

**Widen the instrument. Leave the charter alone.**

`_MARKED_AS_ARRANGED` replaces `_HEDGE` at that one assertion, accepting the
conditional mood OR an explicit scoping of the number to the arranged room.
What it must still reject is pinned offline, in `test_guest_prompt.py`, beside
what it accepts — because an instrument widened to match what the model
happens to do now is how an eval becomes a tautology, and because an
instrument only exercisable with an API key is only checked at the moment it
is being trusted.

**`_HEDGE` itself is untouched**, and that is the whole reason the new object
exists rather than the old one growing. Its other two uses assert the guest
does NOT reach for a conditional on facts a change never touched. Widening it
there would read a scoping clause as an over-hedge and fail the guest for
being precise — a test getting stricter as a side effect of another test
getting more accurate.

Rule 10 keeps saying *"Say 'would' and mean it"*.

## Why

**The test was failing replies its own comment had already blessed.** The
comment above the assertion reads: *"a reply can still let the person hear
which room it means without it ('that's how it stands with the sofa against
the wall now')"*. That is, to the word, the construction all 27 samples used.
The author knew the property was broader than the word, wrote that down, and
then asserted the word.

**Rule 10 states a property and suggests a form, and the suite graded the
form.** The rule's own sentence is *"the person must always be able to hear
which room you are describing"* — "would" is how it recommends doing that.
0174 measured the word at 12/16 and the property at 16/16, so the gap between
them was visible in the founding measurement and the narrower number is the
one that became the gate.

**Not changing the charter is the conservative half, and it is deliberate.**
An instruction may ask for more than an acceptance test requires; that is not
a contradiction, it is the difference between what we tell the guest to aim at
and what we refuse to ship without. Blessing the weaker form in the charter
would be a real loosening of an honesty rule — "that's how it stands" asserts
where "would be" supposes — and that is a taste call belonging to the
operator, not a side effect of an eval turning red.

**This is what the deploy gate was for.** The gate existed to stop unproven
voice work reaching production, and it caught something on its first use: not
a defect in 0213 or 0214, but a drift underneath them that no unit test could
see. The suite header already names a `GUEST_MODEL` change as trigger 2 and
notes that model swaps move voice more than prompt edits do.

## What would change this decision

- **The operator rules on the charter.** If "would" is worth insisting on,
  rule 10 and the arrangement block are where to insist, and this instrument
  should narrow back to `_HEDGE` in the same change. Listed in the lane's
  batched-judgment report.
- **A reply passes this instrument while genuinely wearing the measured
  room's grammar.** Then the widening went too far and the offline pins in
  `TestTheEvalInstruments` are where to tighten it — add the sample, watch it
  fail, then narrow.
- **`GUEST_MODEL` moves again.** Every rate in this suite was measured against
  one model, and this note is the evidence that they do not survive a swap.
  0172 already recorded that a green run does not say which sentence is
  holding the voice up; this adds that a red one does not say the voice broke.
- **A future model brings the word back on its own.** If a later
  `GUEST_MODEL` reads rule 10 the way 0174's did, this instrument becomes
  wider than it needs to be, and narrowing it back to `_HEDGE` costs nothing.
  Measure before doing it: the harness is four lines over the suite's own
  `_Room`, and running it paired and interleaved is what made both of this
  note's attributions cheap.
