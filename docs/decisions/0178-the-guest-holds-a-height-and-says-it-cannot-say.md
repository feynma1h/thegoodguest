# 0178 — the guest holds a height and says it cannot say

**Date:** 2026-08-14
**Status:** Decided; the change itself is scheduled, not built

## Context

A sitting asked the operator to rule on one small thing: the guest used
inline markdown emphasis in 2 of 48 sampled replies, `_assert_beat` catches
markdown only at line start so both passed, and the charter asks for "short
beats". Charter wrong, or assertion wrong?

The operator declined the framing — "rather than trying to conform to the
test or the charter, see what makes sense as a product" — and objected to
something else in the sample reply entirely: "telling the user that we can't
do something in a 3D space which is supposed to carry measurements doesn't
sit well with me."

Both halves of that turn out to be right, and the second is much the larger.

## What we tried

**The markdown half, measured as a product question.** There is no markdown
renderer anywhere in `web/src` — the guest's text reaches the DOM as
`{turn.assistant_text}`, a JSX text child. So `*used*` is displayed to the
user as literal asterisks. Separately, the guest's line is already set in
italic serif: italic *is* the guest's voice in the design system, so
rendering emphasis correctly would mean un-italicising a word rather than
emphasising it.

**The refusal half.** The reply the operator was shown is from the pre-0174
baseline and is one of that measurement's 8/8 false-provenance failures. The
refusal in it no longer happens: 0174 measured 0 refusals across 16 samples
on the shipped text, and the serving guest answers the same question with
"About 2.2 m between the sofa's center and the table's center."

But the objection survives its example. Charter rule 3b gives a measured
piece its LONGEST dimension only, and the charter teaches it by exemplar:

> **Person:** How tall is the wardrobe?
> **Guest:** I can't say — what I have is its longest dimension, about 1.9 m,
> and I don't know which way that length runs.

The manifest for that wardrobe carries `roomplan_box.extent_axes_m.up_m` =
1.912 at box confidence **high**. Across the four walked rooms, **31 of 31
box objects carry a measured height.**

## What we chose

**One charter revision covering both, and one live voice-evals run.** Inline
markup is named as a voice defect; rule 3b stops being longest-only and
speaks measured heights and horizontals from `extent_axes_m`, with a
`FACTS_VERSION` bump and `_assert_beat` widened in the same change. Nothing
was built in the sitting; the follow-on is written instead.

**Widening `_assert_beat` alone was rejected.** The shipped charter does not
forbid inline emphasis, so a widened assertion would fail the suite against
behaviour the guest is currently permitted — a red gate that is the test's
fault, not the guest's. The assertion moves with the rule it enforces.

One correction landed immediately, because it was a false claim rather than a
feature: `scene_facts.py`'s SIZES docstring said "no manifest this service
reads carries it yet", which was true when written and is not true now. The
re-drives shipped the field. Speaking a height was never waiting on
perception; it is waiting on this revision.

## Why

The size rule was correct when it was written and its stated reason has since
been measured false — twice, from two directions. 0096 recorded the `dims`
triple as descending-sorted with no recoverable axis semantics, so the
longest dimension was the only claim it could support. 0137 measured 31 boxes
and found the triple is not sorted in any order, with index 1 the vertical
extent; 0143 then had perception declare the up axis explicitly rather than
leave anyone inferring it. What remained was a rule outliving its reason.

That matters more than an ordinary stale rule, because of what it makes the
guest do. This product's claim is that it measures a room and tells the truth
about it. A guest that holds a high-confidence measured height and answers "I
can't say" is not being careful — it is withholding a measurement, which
reads to the person in the room as the product not knowing. The honesty
rules exist to stop confident wrong answers, and here they are suppressing a
confident right one.

The two halves ship together because they cost the same thing. A charter
change needs live voice evals (0058), an eval that cannot fail for the right
reason certifies nothing (0107, 0172), and the evals run is the expensive
part — not the text. Two revisions would mean two runs.

The splat-extent half of the SIZES rule is untouched and still governs. A
real meter-scale rug ships `extent_m_sorted` of 0.46 × 0.29 × 0.005, and
every splat extent is exposed to visible-region truncation (0075, 0080). Only
box dims are size truth, and only at box confidence high/medium — the spike
room's wardrobe arrives as a low-confidence "refrigerator", and withholding a
size that would attach to a wrong name is the same rule the iOS floor plan
already follows for names.

## What would change this decision

Nothing foreseeable for the markup half — if a markdown renderer is ever
added to the conversation surface, the reason changes but the answer does
not: the guest's line is italic serif, and emphasis inside it inverts.

For the size half, the gate is the evals. If speaking heights measurably
degrades the voice — hedging lost, invitations dropped, sizes stated where
the box is absent — the rule was load-bearing for more than its stated reason
and should come back with the real one recorded this time.
