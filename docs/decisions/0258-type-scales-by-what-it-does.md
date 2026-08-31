# 0258 — type scales by what it does, and control labels are clamped rather than capped

**Date:** 2026-08-28
**Status:** Decided

## Context

Photographing every state at accessibility XXXL (0287) made a complaint
possible that had not been checkable before: the accessibility screens lose
the app's character and read as bulky.

Measured, the aggregate looks mild — the mean screen goes from 15% inked to
25%. The distribution is the finding. The screens that grow most are the ones
that were emptiest: the contents page goes 1.1% → 6.3% and the desk 0.9% →
5.2%, both about **5.7×**. The screens that were already busy barely move
(review 1.2×, the recovery screen 1.4×). The doorway is **0.95×** — very
slightly *less* dense — and it is the only screen whose ink is a drawn graphic
rather than type.

So the app's restraint is its negative space, Dynamic Type spends negative
space first, and this app is almost entirely type with nothing fixed to hold a
composition together.

## What we tried

`RSFont.swift` already carried `maxSize`, defaulting to nil, with a recorded
reason: a blanket cap had once left a capped serif hero rendering *smaller*
than the uncapped sans support text beneath it, because the semantic
text-style variants scale without a ceiling. That dead end is real and still
holds.

The pass that landed is tiered rather than blanket, by what a line DOES:

| tier | ceiling | what it covers |
|---|---|---|
| reading | none | body copy, the guest's voice, status sentences, instructions |
| `.display` | 1.4× | serif titles and screen headers |
| `.mono` | 1.6× | IDs, elapsed clocks, capture metrics, status eyebrows |
| control | clamp | a filled or tappable label |

**The first attempt at the control tier was wrong and the screenshots caught
it.** Every filled button sets its label from a semantic style
(`RSFont.ui(.headline, weight: .semibold)`), which `maxSize` cannot reach — so
capping them meant rewriting them as `.rsFont(.ui, size: 17, relativeTo:
.headline)`. Those are not the same font. A text style carries its own line
height and a bare point size does not, so the label's box shrank and the
primary button came out **visibly shorter at the DEFAULT text size** — the
accessibility fix had broken the size nobody was complaining about. Diffed
against the pre-change frames, six screens with buttons differed by 0.6–2.7% of
their pixels.

## What we chose

Tiers by function for the fixed-size path, and for control labels a **Dynamic
Type clamp** — `dynamicTypeSize(...DynamicTypeSize.xxxLarge)` on the label —
rather than a point ceiling.

The clamp changes nothing at or below `xxxLarge`, verified pixel-identical on
every screen carrying a button, and above it holds the label where `xxxLarge`
left it. That lands at exactly 1.35× for `.headline`, 1.38× for `.callout` and
1.46× for `.footnote`: quantised to Dynamic Type's own steps rather than exact,
which is the price of not substituting the font. It is the right price.

`tools/ios_density_guard.py` gates the result at 2×.

## Why

Two numbers say whether the tiers worked, and they are cleanly separated.
Screens whose ink is controls and titles now sit at a median **1.73×**, with
**29 of 30** under the target. Screens whose ink is the guest's prose sit at a
median **3.93×**, with **0 of 37** under it.

That is not the tiers failing. Reading text scales without limit *by design* —
it is the first rule of the brief, and someone who has turned AX5 on has asked
for exactly that. The caps hit the target everywhere they were permitted to
act, and the entire residue is the one category they were told not to touch.
Closing it means showing less on those screens, which is a product decision
about what a person at AX5 is allowed to see, not a typography one.

**Two inversions are the acknowledged cost**, both visible in the frames: the
contents page's colophon is now larger than the row titles above it, and the
desk's guest line is larger than the desk's own title. Capping titles at 1.4×
while body scales ~3.1× cannot preserve a hierarchy — it deliberately
compresses one, and past a certain size it reverses it. Ruled acceptable for
now because the alternative measured worse: at full size those titles were the
single largest thing on the screen and the whole complaint.

## What the tiers could not reach, and what did

The tiers were measured and reported before this note closed, and the split was
clean: screens whose ink is controls and titles came out a median **1.73×**,
29 of 30 under a 2× target; screens whose ink is the guest's prose came out a
median **3.93×**, 0 of 37 under it. Read on their own those are two facts. Put
against the operator's judgement — *the screens still look crowded* — they are
one: the caps did everything they were allowed to, and the residue was the
category rule 1 protected.

Two ways to close it, and only one was available. Showing less at accessibility
sizes was ruled out explicitly: nothing may be dropped or omitted, and both
sizes must read as the same structure. That leaves stopping the growth.

**A tier for reading text would have been wrong**, and the arithmetic says why.
To help, a prose ceiling has to be tighter than the display tier above it,
which is the inversion this file already warns about — the contents page's
colophon set larger than the row titles it sits under, which the tier-only pass
had in fact produced.

**So the ceiling is uniform and sits above everything**: `RSTypeSize.ceiling`,
`.accessibility2`, body 17 → 33pt, applied once at the app root. Uniform is the
whole point — every ratio between every pair of styles stays exactly where the
default size has it, so the accessibility layout is the same layout, larger.
The tiers still bind underneath it and still serve their own purposes; the
ceiling is what makes them safe, because with prose bounded the display tier no
longer inverts anything.

**Three re-compositions were deleted rather than kept**: home's claim/sentence
swap, the contents row stacking, the house dropping its stamp onto its own
line. Each was the right fix for unbounded type — the sentence really did go
below the fold — and each is dead weight under a ceiling: a second layout to
verify, for no remaining gain, on a brief whose constraint is that the two
sizes look structurally the same. `ContentsRowView` needed one thing in
exchange: the title and the status take `layoutPriority(1)` so the dot leaders
yield, a leader being filler. Without it "The house" wrapped to two lines at the
ceiling while "The desk", two characters shorter, did not.

Measured after, across all 83 states: mean density **10.2% → 14.5% (1.42×)**,
layout audit **0 of 62** at both sizes, and every screen inside what the
ceiling's arithmetic accounts for. Verified by looking at all 83 accessibility
frames, not only by the numbers: profile's ID card and the doorway's CTA are on
screen at AX5 for the first time, both having previously been below the fold.

## What the density gate actually bounds

Ink area scales with the SQUARE of type size, so a screen showing the same
content at 1.94× is **3.77×** denser with nothing whatever wrong. The 2× target
was therefore unreachable by construction while showing everything: meeting it
needed either type below 1.41× — barely an accessibility size — or content
removed. The gate now bounds by that arithmetic, and the informative reading is
inverted from the obvious one: a ratio at the square means the screen is a
faithful larger copy of itself, and a ratio well BELOW it means content is
falling off the bottom of the frame.

## What would change this decision

**The ceiling is the number to argue with, and it is one line.** It trades a
real thing away: someone who sets the top step asks for 53pt body text and gets
33. Raising it costs crowding and `tools/ios_density_guard.py` will price that
in ink; lowering it buys quiet at the expense of the people the setting exists
for. Nothing else in this decision has to move when it does — that is what
being uniform buys.

If reading text ever gains a ceiling of its OWN, below the uniform one, the
display tier has to move with it or the inversions return. The two numbers are
related: a title cap only preserves hierarchy while it stays above the scaled
body size, which without the uniform ceiling meant about 2.2× for a 24pt title,
not 1.4×.

If a screen gains a fixed non-text element — the doorway's portal is the
existing proof that this works — its density falls towards 1.0 with no type
change at all. That remains the cheaper lever than lowering the ceiling, and it
is the only one that costs a low-vision reader nothing.

The three deleted re-compositions are deleted, not parked. If the ceiling is
ever raised far enough that content stops fitting, the answer is not to restore
them — it is that the ceiling went too high.
