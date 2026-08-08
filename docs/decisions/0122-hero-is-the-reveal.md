# 0122 — the landing hero is the reveal, not a room

**Date:** 2026-08-08
**Status:** Decided

## Context

The `/` hero was designed around a live demo room (decision 0057: "one-claim
hero with the live demo room"). That room never existed on a deployed origin
— `DemoRoom.tsx` loaded `/dev-fixtures/manifest.json`, which is gitignored and
hosting-ignored, and documented itself as pending "a curated real-room
capture". It degraded correctly, so the first thing every visitor saw was the
degraded state: copy on parchment with no image at all.

The obvious repair — stage a curated capture and render it — is the one this
note rejects.

## What we tried

Three shapes were weighed against the founding thesis and against what the
pipeline actually ships today:

1. **A curated real room, objects and all.** What 0057 originally specified.
2. **Geometry only** — the first two movements of the reveal choreography
   (decision 0097: the measured boundary drawing itself, then the surfaces
   materializing in place) against a real capture's shell, with no object
   splats and the score capped after the surfaces.
3. **Geometry plus exactly one piece**, settling in at the end and named, as
   the score already does for a small room.

(3) was built as a taste probe rather than argued about: `?hero=b`, reading an
optional `public/hero/piece.json` sidecar. Both were rendered and screenshotted
side by side.

## What we chose

(2) ships. (3) stays in the tree as a probe whose splat is deliberately
un-shippable — gitignored AND hosting-ignored — so the operator can look at it
locally without any deploy being able to carry it.

The fixture is scene `ce68e24f`'s `shell.json` v3, verbatim, wrapped in a
`SceneAssets` document with an empty `objects` list, at
`web/public/hero/room.json` — **3,557 bytes**.

No new choreography code. A shell with zero objects already ends the score at
the surfaces, because `planReveal`'s `nothingToPlay` requires BOTH shell and
splats to be empty; `heroRoom.test.ts` pins that against the real fixture so
the cap breaks loudly if objects are ever added.

## Why

**A demo room is necessarily someone else's clutter.** The thesis is "the best
version of *your* home". A stranger's lived-in bedroom at hero scale argues
against the product's own claim, and no amount of pipeline quality fixes that
framing.

**Half a room is an anti-demo.** The best walked room places 13 of 25 objects,
with the RP-8 defect list still partly open. A hero is scrutinised in a way an
operator walk is not.

**The room drawing itself is the more distinctive claim.** Any scanner renders
a room; almost none show a room *understanding* itself. The contour is the AI
layer made visible, and the measured empty room is the most literal reading of
"the version its owner has never seen".

**Kilobytes, not megabytes.** 3.5 KB against ~460 MB for the scene's full splat
set. Measured while building the probe: the cheapest splat from this scene that
still reads as a *piece of furniture* is 18 MB (a desk — and it renders as a
pale truncated slab, decision 0080's class-6 defect); the one that reads well
is the bed, at 44 MB, and it takes seconds to appear.

**It dissolves the privacy question rather than managing it.** With no splats
there are no possessions on a public origin — a floor polygon, wall heights,
four measured colours and a window opening.

### Which room, and why the choice was constrained

Chosen on how the *contour traces*, then filtered hard by one requirement:
**every frame of the scene must have been segmented after decision 0089.**
`person` was absent from the SAM vocabulary before 0089, so a pre-0089 scene's
zero person-detections prove nothing — the detector was never asked. A
pre-0089 shell can therefore carry a person in a measured albedo with no
evidence trail, which is exactly the defect 0089 fixed on `f3d70236`'s
`wall_03`.

That single rule disqualified the best-looking contour. The RoomPlan spike room
`a7e073ae` — 10 floor corners with a real entry alcove, the most distinctive
trace of any candidate — was segmented 2026-08-05 and its shell baked
2026-08-07T18:39Z, both before revision `perception-obj-00036-l9l`
(2026-08-07T21:27:53Z). Of the post-0089 shells, `ce68e24f` was the only one
with coherent geometry: four walls all at one height (2.99 m), one window
opening, and three of four walls with measured albedo. `972fc0a8`'s walls are
2.08 m (squat); `b12538fa` has a 0.12 m sliver wall, two short walls and almost
no observed surface; `f3d70236` is the noisy 7-corner ARKIT_ONLY v2 shell.

Its floor carries two collinear vertices, which put two contour risers in the
middle of a flat wall. Left alone: they mark where one measured wall ends and
the next begins, which is honest, and suppressing them would mean editing
`lib/reveal.ts` — shared with the room page, whose reveal the operator is about
to walk.

## What would change this decision

- **The spike room becomes eligible.** If `a7e073ae` (or any richer-contoured
  room) is re-driven on a suppression-armed revision, swap the fixture — the
  10-corner floor with the alcove is the better trace, and the swap is one file.
- **Placement quality passes an operator walk at hero scrutiny.** If the
  RP-8 list closes to the point where a full room reads correctly to a stranger,
  the objects argument reverses and this becomes a room again.
- **The operator prefers (3) on looking.** The bed screenshot is a real
  counter-argument: one well-chosen piece proves "scanned, not modelled" in a
  way geometry cannot. If it wins, the cost is a multi-MB possession on a public
  origin, and both `web/.gitignore` and `web/firebase.json` have to be opened
  deliberately — which is the point of ignoring it in two places.
- **The material gate moves.** The fixture's albedos were baked at
  `SHELL_MATERIAL_MIN_CONF=0.6`; decision 0100 recommends 0.75. Raising it can
  only turn families null (clean matte in the measured albedo), and the fixture
  is a frozen snapshot, so nothing changes until it is regenerated — but a
  regenerated fixture may differ in colour.
