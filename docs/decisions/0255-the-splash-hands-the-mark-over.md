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

## What would change this decision

If any other screen ever wants to receive the mark this way, the preference key
generalises as-is; the splash would need to know which slot it was aiming at.

If the mark is re-cut such that its ink box is no longer what `Mark` frames
itself to, the slot arithmetic (scale by ink height, centre the canvas on the
slot's centre) has to be re-derived from `MarkRingShape` rather than assumed.
