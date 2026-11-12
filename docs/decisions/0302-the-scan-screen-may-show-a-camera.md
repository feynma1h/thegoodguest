# 0302 — the Scan screen may show a camera behind the boxes

**Date:** 2026-11-05
**Status:** Amended by 0365 — every scan now shows the camera, in every build, with the floor plan as a small card on LiDAR phones; what this says about live boxes (Debug only, 0295, 0301) stands

Amends 0072 and 0077 in one respect each.

## Context

0072 chose a capture screen with "no camera photo-feed": the room drawn as ink on a dark
backdrop, coverage felt and not shown. 0077 filled that screen with the live floor plan, the
room drawing itself from RoomPlan's updates. Live boxes (0301) are boxes on the room, and a box
needs the room behind it: a dot over an object only means something over the object.

## What we chose

While the feature is on, the Scan screen shows the camera feed behind the dots and boxes, in
place of the floor plan. Everything else on the screen is as it was: the guest's words, the
tracking indicator, the single Finish, the vignette (lighter, since a camera is not the dark
the ink was drawn on). The vignette stops taking touches, which it had always done without
anyone noticing: with a camera beneath the HUD, it swallowed every tap meant for the dots.

With the feature off, or in any non-Debug build, nothing changes: ink on dark and the floor
plan.

## Why

A camera feed on the Scan screen is not what 0072 wanted to avoid. It rejected a coverage
meter and a neon wireframe in the hope that the room could be seen whole afterwards; boxes the
person made are neither. But it IS a reversal of "no camera", so it is written down rather than
slipped in, and it is scoped to the one feature that needs it.

## What would change this decision

- **If the camera behind the Scan screen changes how people scan** — more handheld waving,
  less walking — the ink-on-dark screen comes back for everyone and boxes move to a pause.
- **If live boxes reach Release**, this note needs the product question asked again; today the
  Release scan is the stock one.
