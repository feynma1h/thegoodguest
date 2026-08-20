# 0193 — the mark is generated, not copied

**Date:** 2026-08-21
**Status:** Decided

## Context

The product mark — the room corner — appeared on five surfaces: the three iOS
app-icon appearances, the browser tab icon, the web wordmark, the iOS in-app
lockup, and the share card's eyebrow. Nothing generated any of them. The 1024
icons were exports of a design-session file that was never committed; the
favicon's "re-export from the app icon's geometry" (`6af4661`) was done by a
script that was not committed either; the web and iOS wordmarks each drew their
own.

Five hand-maintained copies of one drawing had diverged into three different
marks, and nothing in the repo could have caught it.

## What we tried

Measured what was actually shipping, rather than trusting the files' own
claims:

- The **web wordmark** and the icon shared a construction but not a treatment.
  The wordmark stroked its outline at 1.8/20 ≈ 9.1% of mark height where the
  icon's rim band runs 68/1024 ≈ 7.8%, and used one weight for the outline and
  the seam where the icon's seam is deliberately lighter (50.4u vs 68u). Its
  outline was `currentColor` at 70% and its walls were unfilled, so on the room
  page's `bg-ink` surface the mark rendered as its own negative.
- The **iOS in-app lockup** was not the room corner at all. It drew a serif `❖`
  inside a stroked rounded square, in `HomeView`, `ColdStartView`, `ProfileView`
  and `UnsupportedDeviceView` — while its own docstring said it was "the mirror
  of the web app's `Wordmark.tsx`". The home header and the home-screen icon
  were different marks.
- The **share card** eyebrow used the same `❖`.

Recovering the real construction off the shipped 1024 settled how the mark is
built. Fitting the floor's four edges by support function gives a rim inset of
**68.28** and a seam inset of **25.18** per face — 0176's "68u band", and a
50.4u seam. The ink is not a stroke at all: hexagon area at R=380 minus the two
face colours accounts for the ink pixel count, so it is a filled plate with the
faces painted on top.

## What we chose

`tools/gen_mark.py` is the one source. It holds the geometry, the palette and
the three appearances, and emits every surface: the three 1024 PNGs, the ICO,
a theme-aware `icon.svg`, `markGeometry.ts` and `MarkGeometry.swift`. Both
wordmarks consume the generated geometry; neither authors a path.

Three properties fall out of that and are pinned in `tools/test_gen_mark.py`:

- **A fill, not a stroke.** The band is what the faces leave uncovered, so
  there is no stroke width to re-choose per size or per renderer. That second
  number is exactly what the web wordmark drifted on.
- **Two plates, not two drawings.** `framed` (R=380) on a light field,
  `frameless` (R=301.48) on a dark one. R_INNER is forced, not chosen:
  insetting a hexagon's edges by 68 drops its apothem to 261.09, so the plate
  circumscribing the faces exactly has circumradius 301.48 — which is the
  number 0176 arrived at for the dark icon by construction.
- **Absolute colours.** The faces never inherit `currentColor`. The mark
  carries its own cream and rust onto any background.

The generator reproduces all three shipped 1024s with no region differing —
every difference is a 1–4px antialiasing line and nothing survives a 5×5
erosion.

## Why

Consistency that depends on someone remembering to update four files is not a
property, it is a hope, and this repo had already lost it twice — silently,
because a wordmark that renders is a wordmark that looks fine in review. The
generator makes divergence take an edit to a generated file, which the tests
then fail on.

Absolute colours are the part that is a design decision rather than a build
one. A mark whose interior is the page showing through is a different mark on
every page — which is what made the old wordmark invert on the room surface.
Carrying its own palette is what lets one object survive the phone icon, the
tab, the site header and the dark room page.

The two plates are not an exception to that. They are the same drawing choosing
whether its outer band is present, which is a property of the field it sits on,
not of the mark — and 0176 already measured that a dark icon keeping the full
band reads as a heavy ring rather than a drawn edge.

## What would change this decision

If the product name lands and the mark is redrawn with it, the generator is
where that happens — the wordmark files stay one-file swaps for the *name*
only. If a surface ever needs a mark the two plates cannot express (a monochrome
stencil for a push icon, a single-colour print mark), that is a third
appearance in the generator, not a hand-drawn variant.

The one divergence deliberately left standing: the lockups still set the name
differently — tracked uppercase mono on the web, the display serif on iOS.
That predates this note and is a typography decision from the design spec
(§1/§10), not a mark decision. Worth settling when the real name lands, since
the name is what the two treatments disagree about.
