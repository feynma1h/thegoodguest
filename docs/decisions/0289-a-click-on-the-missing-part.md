# 0289 — a click on the missing part, and the luma guard that refuses it

**Date:** 2026-08-29
**Status:** Decided (measured; nothing ships)

## Context

0269 recorded the click loop deleting the near foot. 0288 located the object of
the original question — the desk's SECOND leg, in shadow, five pixels from the
shipped mask, covered by 0.1% of the twelve candidates that run produced.

The loop's opening click lands in the seed's own interior, which asks "what
object is here" — a question that can only return the object it already has.
This is the first run that could ask a different one, because the target was
finally located.

## What we tried

The identical repair with one variable changed: an extra opening positive click
at (1192, 967), luma 93, the pixel deepest inside the located region. Both
recordings kept.

| | without the click | with the click |
|---|---|---|
| best second-leg coverage, any candidate | **0.1%** | **75.0%** |
| taken mask, round 0 | 289,485 px, −52,730 vs seed | **357,538 px, +15,323** |
| seed retained, round 0 | 83.3% | **99.3%** |
| near foot retained, round 0 | 3.2% | **97.9%** |

**The click changed three things at once.** It stopped the mask collapsing, it
preserved the near foot, and it recovered roughly half the second leg. The
candidate that holds most of the second leg — 75.0% — keeps only 63.8% of the
seed and would be refused by the retention bar; the best that also retains the
seed is round 2 rank 1, at 99.9% seed, 99.8% near foot, 48.7% second leg.

Simulated with the patch set — retention bar, then merge:

| | result |
|---|---|
| **with** the luma test | **342,215 px — nothing merged, 0% of the second leg** |
| **without** it | **364,571 px, 100% seed, 100% near foot, 48.2% second leg**, 22,356 px gained, 94% inside the box |

## What we chose

**The luma test is removed.** It refused every merge in the clicked run — eight
refusals across four rounds, at growth-to-object gaps of 62 to 95 — and the
whole of the recovered leg with them. It was written to catch a wooden chair the
part query returned, and it does; it also refuses the real part, because **a
shadowed part of an object is not the same brightness as the lit part of the
same object**, and this desk's leg sits 84 luma from its own tabletop.

Its replacement is the test that actually separated the wooden chair: **does
another detection own this region.** A `chair` detection covered 99.0% of the
wood; nothing covers the second leg. That test needs no colour and has no
threshold to tune against shadow.

**Nothing ships.** This is one object, one frame, one click that a person
placed.

## Why

**The click is the whole difference, and it is a difference of question.** Every
prompt before this one pointed at the object; this one pointed at what was
missing from it. Twelve candidates without it held 0.1% of the leg between them
— the model was never asked, so it never offered. That is the case the
operator's patch 5 makes, and it is now measured rather than argued.

**But the pointer here was a human eye**, and that is the honest limit of the
result. Four automated searches failed to find this region: a colour filter
skipped it because at luma 111 it reads as concrete, the part query returned
nothing for `table leg` and `desk leg`, the threshold sweep found only a
boundary skirt, and the unclicked loop never proposed anything within five
pixels of it. What is proven is that a repair works WHEN pointed; what is not is
that anything we have can do the pointing.

**Half is not whole, and the note should not round up.** 48.2% of the leg, or
75% in a candidate the retention bar refuses. The remainder is presumably the
part of the leg the desktop occludes, which no click in this frame can reach.

**And the guard that had to be removed was mine, written two runs ago against
the previous failure.** That is now four guards in this investigation, each
sound against the case that motivated it and blind to the next one. The pattern
is worth more than any of the individual rules: a guard written from one
counterexample encodes that counterexample, not the principle.

## What would change this decision

**An automatic pointer is the only thing standing between this and a mechanism.**
The candidates are a vision model asked where the object is incomplete, and the
unclaimed-depth detector that already exists and cannot run on this capture.
Both are untested against a target that is now defined, which makes them
cheap to test for the first time.

**The retention bar and the merge should be re-measured with the luma test
gone**, on the other preserved captures, before either is called safe. Removing
a check because it refused one correct answer is exactly the move that produced
the check in the first place.
