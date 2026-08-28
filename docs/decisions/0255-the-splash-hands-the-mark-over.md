# 0255 — the splash hands the mark over, to a measured slot

**Date:** 2026-08-28
**Status:** Decided

## Context

The launch splash morphs the wordmark into the mark at screen centre, holds a
beat, and fades out to reveal home. The cut was clean but it was a cut: the
thing that had just been centre stage disappeared, and home arrived with a
smaller copy of it in the corner.

## What we tried

The obvious implementation is to animate the mark toward a hardcoded corner
position. It is wrong on the first device nobody tested: home's header sits
below a safe area that varies by device and above content whose height varies
with the text size, so any constant is a guess.

`matchedGeometryEffect` is the idiomatic SwiftUI answer, but the splash's mark
is not a view — it is a `Shape` whose path is interpolated between two ring
sets, which is the whole reason the morph is exact rather than a cross-fade.
Handing it to a geometry effect would mean giving that up.

## What we chose

Home publishes its mark's bounds as an anchor preference (`MarkSlotKey`); the
splash reads it through `overlayPreferenceValue` and animates the rings to that
measured rectangle. The travel is a fourth beat after the existing three, and
home fades in behind it.

The morph became two chained similarities driven by one `AnimatablePair`:
lettering → mark at centre, then centre → slot. During the gather the landing is
zero and during the travel the gather is one, so exactly one is moving at any
frame.

Home's own mark holds itself invisible while the splash is playing, via an
environment value, while still laying out.

## Why

**The destination is measured rather than assumed**, which is the only version
of this that survives a device we do not own. The anchor is published by the
view that actually knows where it is.

**Chaining preserves the property the original morph was built on.** Decision
0248's splash is exact because `WordmarkGeometry.rings` IS `MarkGeometry.rings`
under a similarity, so interpolating four numbers yields the mark at every
intermediate frame. Composing a second similarity after the first keeps that
true — a similarity of a similarity is a similarity. Blending the two
simultaneously would not have.

**The mark must lay out while invisible**, not be conditionally absent. Its
frame is the thing the splash is aiming at; a view that is not there publishes
no anchor.

**Two marks converging on one point read as a doubling, not a hand-off** — hence
the environment flag rather than simply fading home in.

## The bug this uncovered, in the mark itself

Working on the hand-off exposed a rendering fault in the splash that predates
it.

Even-odd fill is what makes a ring a ring: the outer ellipse and the inner one
cancel, leaving a band. The splash put BOTH rings into one path and filled that
even-odd, so the rule kept counting — and where the two bands cross, the winding
cancelled again and the intersection was knocked out. Two white notches, at the
top and bottom crossings, on every frame of the mark.

`Mark` has always drawn each ring as its own shape, which is why the static mark
never had them. Fixed by rendering one shape per ring, exactly as `Mark` does.

**WHAT THIS DID AND DID NOT FALSIFY**, corrected by the brand lane and worth
keeping straight, because the wrong reading sends someone to re-derive the
wrong thing.

Decision 0250's claim is that the wordmark's rings ARE the mark's rings under a
uniform similarity, so interpolating their four numbers is itself a similarity
and every intermediate frame IS the mark at some size. That is a claim about
GEOMETRY, it was never false, and this fix did not move a single coordinate.

What was false is the weaker thing the note and the `SplashView` docstring
implied on top of it: that the last frame therefore LOOKED identical to the mark
it lands on. Exact geometry, wrong fill rule. Do not read this as a reason to
re-check the interpolation — the fault was never there.

**The generator already warned about it.** `tools/gen_mark.py`'s docstring names
this exact hazard — the two bands cross at four points and even-odd would punch
holes exactly there — and `tools/test_gen_mark.py` guards it by building the
wrong version and asserting ours differs. Both are on the PYTHON side. Nothing
pins the Swift or TypeScript consumers, so the generator warned, the test
passed, and a consumer re-made the mistake anyway.

The brand lane then audited every other surface that draws the ring pair — the
web mark and wordmark, the calling-card painter, `icon.svg`, the OG eyebrow, and
iOS's static `Mark` — and all six draw one path or one fill per ring.
`MorphingRings` was the only site. No further audit is owed; a consumer-side pin
is, if anyone wants this class closed rather than documented.

## What would change this decision

If any other screen ever wants to receive the mark this way, the preference key
generalises as-is; the splash would need to know which slot it was aiming at.

If the mark is re-cut such that its ink box is no longer what `Mark` frames
itself to, the slot arithmetic (scale by ink height, centre the canvas on the
slot's centre) has to be re-derived from `MarkRingShape` rather than assumed.
