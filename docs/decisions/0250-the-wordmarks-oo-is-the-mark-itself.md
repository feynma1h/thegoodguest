# 0250 — the wordmark's "oo" is the mark itself

**Date:** 2026-08-26
**Status:** Decided

## Context

The supplied wordmark is traced artwork — the operator's own lettering, traced
at a 50% iso-contour and re-fitted as 634 cubics across 15 contours. It cannot
be regenerated from numbers, which is why `tools/brand/wordmark-traced.json` is
a source file rather than an output.

Its "oo" in the middle of "good" is two interlocking loops, and the mark is two
interlocking rings — but the design file is explicit that they are NOT the same
geometry: "the ligature's rings are rounder and barely tilted, the icon's are
elliptical and tilted −35°." The operator asked for an exact morph on the iOS
splash, and authorised changing the lettering to get it.

## What we tried

**A cross-fade at the moment of alignment.** Cheapest, and invisible at speed.
Rejected by the operator on the merits: it hides a shape change rather than not
having one.

**Cutting the "oo" out and splicing rings in.** This is what shipped, and the
measurements are why it was worth doing rather than a compromise.

## What we chose

The wordmark's "oo" is replaced by `MarkGeometry`'s own rings, uniformly scaled
into place. `gen_mark.py` reads the traced source, removes the ring outlines
from contour 1, and emits the lettering and the rings as separate paths.

The substitution is very nearly a no-op on the lettering:

| | measured |
|---|---|
| the traced ring pair | 138.93 × 80.46, aspect 1.7267 |
| the mark at that height | 138.22 × 80.46, aspect 1.7179 |
| the mark's band at that height | **6.20** |
| the script's own monoline stroke | **6.2** |

The mark IS the "oo" at its natural size. Nothing was rescaled to fit and the
letters either side did not have to move.

**The cut.** Contour 1 is the connected outline of "good": it runs right-to-left
along the top edge and back left-to-right along the bottom, so the ring pair
occupies two runs (segments 13–29 and 72–88) rather than one. The segments
either side of them — 12 and 71 — are the CONNECTOR edges where the g and the d
meet the rings, and they are kept; cutting those too would leave the letters
joining onto nothing.

`load_wordmark()` re-measures the ring pair off the artwork rather than trusting
those indices, and **refuses to run** if what it cut does not have the ring
pair's aspect.

## Why

**On doing it at all.** The morph is the payoff: because both ends of the splash
animation are now the same shape at two similarities, interpolating their four
numbers is itself a similarity of that shape. With `a0/b0 = a1/b1 = r`, the ratio
of the two lerps is `r` again at every `t`, and the tilt never varies — so every
intermediate frame is the mark at some size. Exact by construction rather than
by tuning, and nothing to re-check if the lettering is ever re-traced. See 0251.

**On the guard.** Segment indices into a traced path are the most fragile thing
in this repo: they are correct for exactly one file and carry no way to notice
they have stopped being correct. A re-supplied trace would otherwise mangle the
lettering silently, and the only instrument that would catch it is a human
looking at the word. The aspect check is cheap and turns a silent corruption
into a refusal to run.

**On the source file.** The wordmark is the one piece of this identity that is
artwork rather than construction. Keeping it as JSON with its provenance in the
file makes that honest, and makes a future re-trace a data swap rather than a
code edit.

## What would change this decision

If the lettering is re-traced, `RING_TOP`/`RING_BOTTOM` will not survive it. The
aspect guard will fire; the fix is to re-derive the two runs against the new
path, not to widen the guard until it passes.

If the mark's proportions ever change, the "oo" changes with them automatically
— which is correct — but the 6.20-vs-6.2 coincidence that made this free will
not necessarily survive. Re-measure the band against the script's stroke before
assuming the lettering still needs no adjustment.
