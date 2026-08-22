# 0223 — the yaw is not a measurement

**Date:** 2026-08-22
**Status:** Decided

## Context

The calling card's plan is a uniform similarity from world XZ to card pixels,
so every length reproduces at exactly one scale. Its stated precedent,
`docs/product/og-card.html`, draws the hero room with NO rotation: world +X is
card +X, world +Z is card +Y, at 82 px/m. `measure.test.ts` reproduces that
placement to 0.0055 px on a 382 px span.

Following the precedent exactly would mean drawing every room at whatever
angle its capture happens to sit at.

## What we tried

**Unrotated, as the precedent draws it.** The hero room came out as a diamond
at roughly 34°, which looks striking — and is why the precedent looks good.

Then the same room was drawn after normalising the angle, and it turned out to
be a plain 3.55 × 3.02 m rectangle. The precedent's diagonal was not a
property of the room. It was where the person happened to be standing when
they started the scan.

That is general. ARKit's default `worldAlignment` is `.gravity`: Y is aligned
to gravity, and the yaw is taken from the device's heading at session start.
It is not north, it is not the room, and it is not measured. Two scans of one
room, minutes apart, produce two different angles.

The unrotated version also has a failure mode the hero happens to dodge. At
34° a room reads as a deliberate composition; at 3° it reads as a mistake, and
the product cannot choose which one a capture will hand it.

## What we chose

The plan is rotated so the wall it dimensions lies horizontal, with the room
above it and the dimension line below — the plan convention. `orientation()`
in `lib/card/layout.ts` derives it from the datum wall alone.

The precedent is not followed on this point, and `measure.test.ts` still holds
the world-space geometry to it, which is the layer where the two are
comparable.

## Why

**A rotation discards nothing, because there was nothing in it.** Normalising
an arbitrary yaw is the same kind of act as centring the drawing in its box —
which no one would call a distortion. Nothing about the room is lost, and the
similarity keeps every length exact.

**It removes a class of bad outcomes rather than improving a good one.** The
gain on the hero room is small. The gain is that no room is ever drawn at a
few degrees off-axis, which reads as sloppiness in a way no amount of care in
the rest of the card recovers.

**A dimension that reads bottom-to-top is a worse dimension.** With the datum
wall flat, the printed length is always the right way up. The unrotated
version had "3.5 m" running vertically up the side of the hero room, which is
legible and is not good.

**The card has no north to lose.** A capture carries no GPS and the app never
requests location (Privacy Policy §3), so there is no compass direction the
drawing could be preserving even in principle.

## What would change this decision

- **A room acquires a true orientation.** If lineage (`social-layer.md` §5)
  ever aligns two captures of the same physical room, their shared frame
  becomes meaningful and two cards of one room should agree — which is a
  reason to rotate consistently, not to stop rotating, but it changes what the
  rotation is derived from.
- **The card gains a second room, or anything else that must sit in a fixed
  frame relative to it.**
- **A north indicator ships.** It would need a heading the capture does not
  currently carry, and it would make the drawn angle mean something.
