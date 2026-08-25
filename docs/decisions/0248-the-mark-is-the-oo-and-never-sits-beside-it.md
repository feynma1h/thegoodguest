# 0248 — the mark is the "oo", and never sits beside it

**Date:** 2026-08-26
**Status:** Decided

## Context

A new brand identity arrived as a Claude Design file plus 31 artwork files: a
new mark, a new palette, a traced script wordmark. The mark is two interlocking
elliptical rings leaning 35 degrees. It replaces the room-corner hexagon that
decision 0193 made `tools/gen_mark.py` the single source of.

The operator then named the constraint that shapes everything else: **the mark
IS the "oo" of "the good guest"** — the same two loops the script draws in the
middle of "good" — so the two must never appear side by side.

## What we tried

**Carrying the supplied path data verbatim.** The design file ships exact `d`
strings for all four masters. Pasting them into the generator would have made it
a container rather than a generator, and 0193's property — that a change to the
mark is a change to one file — would have quietly become "a change to the mark
is a change to one file and whatever the designer sends next".

**Reconstructing the construction instead.** The supplied `_geom.json` gives
four numbers per master (a, b, band, dx). Rebuilding the paths from those and
comparing term by term against the supplied strings: the worst coordinate
disagreement across all four masters is **0.05 on a 1024 canvas**, which is
exactly the rounding granularity of the supplied data (one decimal place). The
three app icons match the design file's own PNG exports with **zero pixels
surviving a 5×5 erosion**.

## What we chose

The generator is parametric over four masters. Each is (a, b, band, dx) with a
shared axis ratio of 1.4047 and a shared tilt of −35°; the band is the region
between two concentric ellipses rather than a stroke, so there is no
renderer-dependent width to re-pick per size.

Every surface takes the mark **or** the name, never both:

- chrome — the web header, the room page, the iOS app — takes the MARK, because
  it is a signature for someone already inside;
- the artifacts that leave and reach a stranger — the calling card, the OG
  image — take the NAME, because a small abstract mark tells a stranger nothing;
- the iOS splash is the single exception and shows them in SEQUENCE (0250).

`tools/test_gen_mark.py` pins the rule as a string proximity check across six
files, because the failure mode is someone adding the name back beside an
existing mark without knowing why it is not already there.

## Why

**On the generator.** A generator that reproduces its input to the input's own
precision is strictly better than the input: it can emit the four masters, the
tight ink-bounds viewBox, the Swift ellipse parameters the splash animates, and
the raster — all provably one drawing, because the PNG is flattened from the
same cubics the SVG carries.

**On the four masters.** They are not a nicety. At the logo's own proportions
the ring band rasterises to 0.72 px in a 16 px tab icon — a grey smear. The
16 px master carries 1.62 px and also opens the ring separation from 0.538 a to
0.620 a, because at that size two counters any closer merge into one dark
lozenge. Side by side at the same size the masters are visibly different
drawings; that is deliberate and it is the only way this mark holds at tab
scale.

**On the rule.** A lockup of the mark and the name prints the same two letters
twice, once as a drawing and once as a word. It is not a style preference, it
is a statement that is false. It also settles a question the punchlist had open
(G2-03, "the web lockup is still set in mono", whose reasoning was that the name
forces the serif): there is no web lockup to re-cut, because there is no lockup.

## What would change this decision

If the wordmark were ever re-drawn so its "oo" is no longer the mark — a
different ligature, or the mark rebuilt from something other than those two
loops — the never-together rule loses its reason and becomes ordinary taste. It
would then be a live question rather than a settled one, and the pin in
`test_gen_mark.py` should go with it rather than be worked around.
