# 0258 — type scales by what it does, and control labels are clamped rather than capped

**Date:** 2026-08-28
**Status:** Decided

## Context

Photographing every state at accessibility XXXL (0270) made a complaint
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

## What would change this decision

If reading text ever gains a ceiling, the display tier has to move with it, or
the inversions above get worse rather than better. The two numbers are related:
a title cap only preserves hierarchy while it stays above the scaled body size,
which at AX5 means about 2.2× for a 24pt title, not 1.4×.

If a screen gains a fixed non-text element — the doorway's portal is the
existing proof that this works — its density ratio should fall towards 1.0
without any type change at all, and that is the cheaper lever for the
prose-heavy screens than capping prose.

The density gate assumes the amount of content on screen is held still. It is
not scale-invariant: capping the house's stamp fit more rows into the viewport
and took it 3.73× → 3.96× while the screen visibly improved. If a later pass
starts hiding content at accessibility sizes, this measure stops being
comparable across passes and needs replacing with ink-per-glyph.
