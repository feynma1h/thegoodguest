# 0188 — the renderer key costs what it guards, not what it holds

**Date:** 2026-08-19
**Status:** Decided and BUILT. Not deployed.

## Context

Decision 0133 took each splat's POSITION out of `SplatViewer`'s renderer key
so a proposed move would stop tearing the renderer down and re-downloading
the room. That half worked. But `viewerKey.ts` still carried `outlines` and
`labels`, on reasoning written into its own docstring: they are *"built
objects with no placement seam of their own; they are cheap to rebuild and
rare to change."*

Both halves of that sentence were wrong in the way that matters, and the
first proposal of any session paid for it: an outline appeared, the key
changed, and every splat mesh went down with it.

## What we measured

**The defect reproduces, on the room page, driven with real pointer events.**
A `!move` in the composer produced, in order: the "Assembling the room…"
overlay, `canvas-gone`, a NEW canvas, overlay off. A tag set on the live
canvas was lost. `!revert` did the same thing again on the way back.

**The re-download is real, and this is the part worth recording**, because
0130 measured it before the compressed tier and nobody had re-checked. With
the room settled, `sofa.ply` was deleted from disk and a key change forced:
the room came back **without the sofa**, while the table and lamp — still on
disk — returned. Spark holds no URL cache, and the rebuild goes to the
network for every file. A library-level cache would have been invisible in
every other instrument.

**Sizing.** A teardown re-does exactly the initial load, so its cost is a
full room load: **14–19 s for the reference room** (0125, measured on the
live bucket after the compressed tier; 87–93 s before). Locally, with 13 MB
of synthetic fixtures on localhost, the empty-room gap is ~50 ms plus several
composite frames — a floor, not a number to quote.

Whether production's HTTP cache absorbs the re-fetch is **not measured** and
could not be from here: it needs a signed URL. Two facts point at "no" —
nothing in this repo sets `cacheControl` on outputs objects (grepped), and
GCS defaults non-public objects to `private, max-age=0`. One command settles
it for whoever next holds a token: `curl -sI '<signed splat url>' | grep -i
cache-control`.

## What we chose

**Outlines and labels stop being structure. Each gets its own effect owning
its own objects end to end**, alongside the placement effect 0133 added. The
build effect publishes a seam — the live scene and the three.js namespace it
was built with — and bumps an epoch; the decoration effects draw into it, and
do nothing while there is no scene, because the build is async and they can
run first. `viewerKey.ts` grows from one key to three, each naming what its
change costs.

**The rule is restated, because the old one is what produced the defect.**
It is not "expensive things belong in the key." **A key's cost is never the
cost of the keyed object — it is the cost of everything else in the scene.**
An outline is five vertices; putting it in a global key made it cost 47 MB.
The test for membership is therefore not expense but lifetime: *does this
change while the renderer is alive?* Shell planes stay in the key on exactly
that test — they are real geometry with materials and a light rig, and assets
are fetched once, so they never change mid-session. If a shell ever updates
in place it needs the same treatment, and the docstring says so.

**`labels` was fixed with the same change even though nothing has ever
triggered it.** The workbench sets them once from a query param, which is
precisely why this copy was never seen; it is the same defect with no
witness, and leaving it would have left it to be rediscovered.

## How it was verified

A temporary probe published the scene and the mesh list, and the whole loop
was walked in a real browser with real pointer and key events (0117's
lesson). Tag survived every step; **mesh uuids identical throughout**, which
is the assertion that matters — the canvas tag surviving proves the renderer
stood, mesh identity proves nothing was quietly reconstructed inside it:

| action | scene children | Line | Sprite | splat uuids | canvas tag |
|---|---|---|---|---|---|
| baseline | 10 | 0 | – | A,B,C | kept |
| `!move` | 11 | **1** | – | A,B,C | kept |
| `!remove` | 11 | 1 | – | A,B,C (one `visible:false`) | kept |
| `!turn` | 11 | 1 | – | A,B,C | kept |
| `!revert` | **10** | **0** | – | A,B,C | kept |

The turn adding no outline is 0157 holding, and it is the control the charter
asked for. Labels were driven by a temporary toggle in the workbench: on →
3 sprites / 13 children / 24 textures, off → 0 / 10 / 21, back on → 3 / 13 /
24, mesh uuids unchanged. GPU bookkeeping round-trips exactly (geometries
6 → 7 → 6 across a move and revert), so the relocated disposal leaks nothing.
Both probes were removed; the diff is three files.

## Why it is not a deletion

Dropping the fields from the key without giving them a lifecycle would leave
outlines that never appear, never update and never clear — and it would pass
a test asserting only that the renderer key does not change. So the pins come
in pairs, and the test file says why. That the renderer key cannot *see* an
outline is now held by the type system rather than by an assertion:
`ViewerKeyInput` has no such field, so putting one back is a deliberate edit.

## What would change this decision

- **The object set becomes reactive** (add, restore, per-object selection).
  0130 measured R3F reconciling Spark correctly and 0133 descoped it; at that
  point these effects become `<Line>` and `<Sprite>` children and this seam
  disappears.
- **A shell that updates in place** — a live re-bake, or progressive shell
  delivery. It moves out of the key the same way.
- **Splat URLs stop being stable within a session** (a signed-URL refresh
  that reaches the renderer). Then the renderer key changes on its own and
  the whole rebuild path needs a different answer than "avoid it".

## Collateral, small

The old outline key carried centre and yaw but **not half-extents**, so an
outline that changed only its size silently kept the shape it was first drawn
with. The new key includes them, and a test pins it. Nothing shipped depends
on the old behaviour — a spec entry's `measured_footprint` does not change
under a re-proposal — so this is a latent bug closed, not a behaviour change.
