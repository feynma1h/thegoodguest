# 0251 — the splash carries whole letters, and the cut is found by crossings

**Date:** 2026-08-26
**Status:** Decided

## Context

`SplashView` opens on the name and resolves it into the mark. It is the only
place both appear, and it is allowed only because they appear in SEQUENCE —
0248's rule stated as a motion instead of broken.

The operator directed the motion in three corrections, each of which rejected
what was there:

1. the letters must MOVE toward the "oo" rather than fade where they stand;
2. each letter must travel on its own clock, not as one block per side;
3. the pieces must be whole letters — "the pieces have individual letters cut
   up as well".

## What we tried

**A uniform scale about the ring pair's centre.** Every point gets the same
schedule, so the word arrives as two slabs — everything left of the loops,
everything right. This is what correction 2 rejected.

**A per-POINT delay from each point's own distance.** Continuous, needs no
cutting, and does cascade. But moving each point on its own clock DEFORMS the
letterforms: the word stretches and rolls as it travels. Correction 3 named it.

**Cutting on total ink per column.** The first cut-finder took evenly spaced
letter-width targets and snapped each to the thinnest column nearby. It put a
cut through the "d" of "good" and through the final "t", chopping single letters
into halves that then walked off in different directions — exactly what
correction 3 was about. Total ink cannot distinguish a connector between two
letters from a thin spot inside one.

## What we chose

Each letter is drawn from the whole word and CLIPPED to its own column, then
offset as a rigid body. Clip before offset, so the column travels with its
letter; clipping after would hold a window still and wipe the letter across it.

The cut is found by asking **how many separate strokes a vertical line
CROSSES**, not how much ink it meets:

- between two letters the line crosses exactly one thing, the connector;
- inside a letter it crosses at least two — a bowl and a baseline, an ascender
  and a shoulder.

One-stroke columns come in runs, and the run's WIDTH is the second test: a
connector runs horizontally for a while, so its zone is wide, while the
incidental one-stroke crossings inside a letter are narrow. Zones touching
either end are dropped — those are the entry and exit flourishes, where the line
crosses one stroke because there is only one stroke left.

That yields seven cuts and eight pieces: `the` · `g` · the "oo" gap · `d…g` ·
`u` · `e` · `s` · `t`.

## Why

**On rigid over continuous.** The word is handwriting. Deforming a letter while
it moves says the letters are made of rubber; carrying them says they were
always separate things that happened to be written together — which is the
sentence the whole splash is making about the "oo".

**On crossings over ink.** It is the difference between a measurement of the
drawing and a measurement of the drawing's density. Two strokes crossing a
column is a structural fact about being inside a letter, and it is the only
signal tried that got the "d" and the "t" right.

**On the uneven pieces.** `the` is one piece and `d…g` is one large piece,
because this hand joins t-h-e with no single-stroke column between them and runs
the d's flourish straight into the g of "guest". A whole large piece beats a
chopped letter: the animation reads correctly with 8 pieces and reads BROKEN
with a letter in two halves. Granularity was the thing to give up.

**On the pacing.** Roughly 3.6 s, held at the operator's direction: the name is
on screen about 1.45 s before anything moves. Every duration is in one `Timing`
enum, so that is one number to change rather than six.

## What would change this decision

If the lettering is re-traced, the cuts re-derive automatically — they are
computed from the drawing, not stored against it. But `MIN_JOIN_WIDTH` (1.5% of
the word's width) is tuned to this hand; a much looser or tighter script would
want it re-checked, and the symptom of it being wrong is either a letter in
halves or the whole word in one piece.

If a splash on every cold launch turns out to be too much, `Timing` is where to
shorten it. Deleting the splash entirely would leave `SplashView` as the only
consumer of `WordmarkGeometry.letterCuts` and of the wordmark on iOS at all.
