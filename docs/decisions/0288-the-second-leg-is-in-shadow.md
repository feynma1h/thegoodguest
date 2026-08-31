# 0288 — the second leg is in the frame, in shadow, five pixels away

**Date:** 2026-08-29
**Status:** Decided (measured; the operator located it)

## Context

The operator's original observation was that none of the candidate masks has the
desk's SECOND leg. Everything measured across 0261-0269 tracks the NEAR foot —
the region the long desk mask adds over the short one — and none of it addresses
the question that was asked.

Four attempts to locate the second leg from the imagery were wrong, in ways
worth recording because they were all the same mistake:

1. read as recovered by the runner-up mask — that was the near foot, which the
   seed already held;
2. concluded **never photographed**, from a real measurement (the capture spans
   44 degrees of azimuth around this table and 22 among the frames that see its
   whole box) that does not support the conclusion — a narrow arc says nobody
   circled the desk, not that the part is invisible;
3. identified a rounded piece below the desktop edge — measured at **88.5%
   already claimed by the desktop mask**, so it was the desktop's own underside;
4. identified a 22,000 px unclaimed region — cropped, it is **concrete floor**.

Each measurement was sound and each target was wrong. The common cause is
estimating pixel coordinates by eye from scaled crops and then measuring there.
The operator located it in one message, from a grid overlay: **C5**.

## What we tried

C5 maps to x 1053-1269, y 822-1028. Within it, the post the operator means:

| | |
|---|---|
| unclaimed pixels | **19,328** |
| mean luma | **111** (desk top 204, near foot 152, seed mask 195) |
| inside the measured RoomPlan box | **100%** |
| distance to the shipped desk mask | **~5 px** |
| covered by the shipped desk mask | **0.0%** |
| covered by any of the 12 tracker candidates | **0.1%** |

**It is in shadow**, which is why every colour-based search ran past it: at
luma 111 it sits below the `> 120` brightness filter used to find "desk-coloured"
material, and it reads like the concrete floor beside it.

**And it is not far away.** Five pixels from the mask that ships. It is severed
by the desktop's own edge, not by distance.

## What we chose

**Record the target, and re-examine two things it breaks.**

**The material guard is wrong and would reject it.** `check27`'s third test
refuses growth more than 60 luma from the object; the second leg is **84 luma**
from the seed. That test was written to catch the wooden chair the part prompt
returned, and it does — but it also refuses the real part, because a part in
shadow is not the same colour as the same object in light. **A brightness
difference does not distinguish a foreign object from a shadowed one**, and this
is the counterexample. It comes out.

**The box is NOT the obstacle here, and that is worth knowing.** The second leg
is 100% inside the measured RoomPlan box. Every argument in 0262/0263 about the
box being a few centimetres too small applies to the NEAR foot and not to this
one. A patch that retires the box from judging masks would not, by itself, have
recovered this part.

## Why

**The failure mode is the same at every layer, including mine.** SAM 3 stopped
at a strong edge — the lit desktop against a shadowed underside — and every
instrument built on top of it inherited that boundary: the overlap sort, the
threshold sweep, the click loop, the part query, and the guards. Four separate
mechanisms and none of them ever proposed a region 5 px away, because the model
never offered one and nothing else generates candidates.

**"Not photographed" was the most expensive of my four wrong answers**, because
it is the one that closes an investigation. It was reached from a real number
about camera coverage and it recommended giving up. The number was right; the
inference was not measured. A conclusion that ends a line of work needs the same
standard as one that opens one.

**The operator's eyes located in one message what four automated searches
missed**, and this is the second time tonight that has happened. That is the
argument for the batched-judgement protocol rather than an argument about any
particular instrument.

## What would change this decision

**The target is now defined and everything already built can be tested against
it.** The three live questions, all cheap: does a click placed IN it grow the
mask to include it; does a negative-free positive prompt at that point return
anything; and is the part-query vocabulary able to name it at all — `table leg`
and `desk leg` returned nothing on this frame, and the region is dark enough
that `chair leg` found a wooden chair instead.

**The luma guard needs a replacement, not a threshold change.** What it was
reaching for is "is this the same object" and brightness cannot answer that. The
wooden chair was distinguishable because a separate detection claimed 99% of it;
the second leg is claimed by nothing. That test — does another detection own
this region — is the one that separates them, and it needs no colour at all.
