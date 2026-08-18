# 0176 — the tinted icon is not a multiply

**Date:** 2026-08-18
**Status:** Decided

## Context

The app shipped with an empty `AppIcon.appiconset` — three declared 1024
slots (light, dark, tinted) and no image files — so it installed with a
blank icon. A mark came back from a design session: the site's room-corner
favicon redrawn as true 30° isometric vector, split into the three iOS 18
appearances, with a page arguing that the tinted variant needed its four
surfaces re-spaced onto an even value ladder because straight desaturation
welds the rust floor to the ink outline.

The page previewed that ladder by multiplying the grayscale master by a
tint colour. That is the obvious approximation, and the one this session
reached for independently before checking. Nothing in the repo recorded
what iOS actually does to a tinted icon, so neither preview had standing.

## What we tried

Installed the delivered set, built to an iOS 26.5 simulator, and sampled
rendered pixels off a real home screen in each appearance. Four samples per
icon: a wall, the floor, the outline band, and the tile field.

Tinted, source grayscale to system output:

| surface | source | rendered |
|---------|--------|----------|
| walls   | 0.949  | 0.965    |
| floor   | 0.529  | 0.666    |
| outline | 0.141  | 0.360    |
| field   | 0.102  | 0.345    |

The 0.847 span becomes 0.620 — about 0.73× — with the dark end lifted by
0.24. Light and dark, by contrast, render *verbatim*: measured `rgb(23,17,8)`
against an authored `#181109`, walls `#f7efdf`, floor `#8e3b2f`, exact.

## What we chose

Ship the delivered light and tinted unchanged. Rebuild the dark variant by
shrinking the ink hexagon from circumradius 380 to 301.48, where it
circumscribes the three faces exactly — ink survives in the seams, nothing
shows at the rim. Record the mapping here.

## Why

The multiply model is wrong in the direction that matters. It predicts a
near-black tile; the real tile is mid-blue. Anyone judging a tinted asset
from a multiply preview will misjudge how it looks on a phone.

But the ladder decision survives contact with the real renderer — the floor
stays 0.30 clear of the walls and 0.31 clear of the outline. It also
validates the *rejection* of the naive alternative for a better reason than
the page had: run that option through the true mapping and its floor and
outline land ~0.10 apart, still welded. The reasoning was sound even though
the instrument wasn't.

The frame does not survive tinting at all — outline lands 0.015 from the
field, inside noise. So in tinted the mark is *already* frameless, which is
what settled the dark variant: a dark icon keeping its full 68u band would
be the only one of the three carrying a frame, and dark is passed through
untransformed, so that band sits 0.11 off the field and reads as a heavy
ring rather than a drawn edge.

Dark and light rendering verbatim has a useful corollary: those two can be
judged offline at true size with no device in the loop. Only tinted needs
hardware.

Rejected on measurement: removing the ink hexagon entirely rather than
shrinking it. The seams then fall to 0.067 against a 0.069 field and the
drawn interior stops existing — the walls still separate, because they are
bright against dark, but the line that makes the mark read as a *drawing*
of a corner is gone. The ink stays in the seams; only the rim goes.

## What would change this decision

The mapping is iOS 26.5's, measured by four pixel samples off a home-screen
screenshot — re-measure on a major iOS release before trusting the numbers.
If Apple ever documents the transform, prefer the documentation to this.
And if the tinted mark is ever redrawn to depend on separation below ~0.10
in the source, re-derive: the compression is multiplicative, so tight
source pairs get tighter, not looser.
