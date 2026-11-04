# 0312 — the furniture twin room has a day and a night

**Date:** 2026-11-05
**Status:** Decided

## Context

Once pieces of the room are drawn as clean twins (decision 0311), the room
needs light that shows them off. The shell's own rig is a flat wash meant to
read the same from every side, which hides the furniture's shapes; a
render-vs-photo calibration light reproduces the photos, shadowed interiors
and all, and looks dull.

## What we tried

- The calibrated light as the only look. Faithful to the photos, flat as a
  design.
- A high sun. Short, hard shadows under every piece; the room read as lit by a
  ceiling lamp, not a window.
- Several night lamp strengths. Too strong washed the shell out (26, 19); too
  weak left the room unlit (13, 7, 3.5). 5 reads as a lamp in a dark room.

## What we chose

`furnitureScene.ts` draws the twins in a diorama look (the calibrated light
stays available as `look=photo`) with two modes and a toggle beside the view
pill:

- Day: a warm sun, low (about 30 degrees) and from the window side, so long soft
  shadows run away from the window; no white surround on the window; the shell's
  flat wash turned down so the light has something to shape.
- Night: a cool moon, the shell wash dimmed, and a point light of intensity 5
  inside the part named `lamp-shade`, whose shade glows at 0.55.

The window side is read from the bundle: a twin whose category is `window`.
The lamp is the part named `lamp-shade`. Both are naming conventions in the
spec, documented in `tools/FURNITURE_TWIN_FLOW.md`; a general light-emitter
property is for later.

## Why

A low window sun is what makes a diorama read as a lit room. The night values
were found by looking, not derived: they are the final ones after five rounds
and live in one `ModeParams` object so they can be tuned live.

## What would change this decision

If twins get a generic light-emitter property, the lamp stops being found by
name. If the product room page draws twins, day and night become a product
choice and the control and look move there.
