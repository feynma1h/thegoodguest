# 0130 — Probe 2: R3F reconciles a Spark SplatMesh, and load orchestration belongs outside the renderer

**Date:** 2026-08-09
**Status:** Decided (answers the risk 0056 named and left an escape hatch for)

## Context

Decision 0056 scheduled R3F/Drei for "when the scene graph becomes reactive
state", and explicitly left an escape hatch: *"if per-object selection lands and
R3F friction with Spark proves worse than expected in practice, the containment
rule permits staying imperative."* Nobody had ever tried it. Decision 0053
contains Spark to `SplatViewer.tsx` precisely to keep this swappable, so the
question was answerable at any time and had simply never been asked.

The board-9 design session asked it before designing anything, because the
Design Specification and the reactive scene are "two halves of one mechanism"
(0056) and the wrong answer here changes the other half.

There is also a live coordination reason: the compressed-tier session
(`../roomstudio-spz`, the P0 in 0123/0124) is building progressive loading, and
progressive loading and the reactive scene touch the same module. That session
needed the answer before the rest of this design was done.

## What we tried

A throwaway probe (`web/src/app/probe-r3f/page.tsx`, deleted with this session)
mounting the real 10-object spike-room fixture — 4,056,000 Gaussians across ten
real PLYs — as declarative JSX, with **every `SplatMesh` construction counted by
a `Proxy` on the constructor** and every React mount/unmount logged. That makes
"reconciled in place" versus "torn down and rebuilt" a measurement rather than an
impression, which matters because both look identical on screen.

Four things had to be found before anything rendered, and all four are worth
recording because each one produced a plausible false negative:

1. **`<Canvas>` never mounts any child in the automation browser.** It measures
   itself with ResizeObserver, and this pane never fires ResizeObserver at all —
   verified directly: `observe()` on a 1280×860 element produced zero callbacks,
   including the initial one the spec requires. Not an R3F/Spark problem. The
   probe drives `createRoot(canvas).configure({size})` instead, which runs the
   same reconciler without the DOM-measurement wrapper.
2. **R3F v9 no longer auto-populates the THREE catalogue.** Without
   `extend(THREE)` even `<ambientLight>` throws *"AmbientLight is not part of the
   THREE namespace"*, and the throw does not stop the page — the tree silently
   mounts nothing.
3. **Spark needs several frames after load before it composites.** The pane runs
   no idle rAF (the artifact already recorded in 0122), so R3F's rAF-driven loop
   never ticked: `gl.info.render.frame` stayed at 0. Driving `advance()` by hand
   renders correctly. An intermediate reading blamed scene-child ORDER for this;
   a controlled A/B refuted that — SparkRenderer at index 0 and at index 1 both
   composite 8,112,000 triangles.
4. **`args` must be memoized.** This one is the actual finding, below.

## What we chose

**R3F can reconcile a Spark `SplatMesh`. Adopt it when the scene becomes
reactive state — 0056's schedule stands, and its escape hatch is not needed.**
Measured, on the real fixture:

| question | result |
|---|---|
| Q1 SparkRenderer inside R3F's loop | **works** — `new SparkRenderer({renderer: gl})` with R3F's own `gl`, added to R3F's own scene. Scene graph built correctly from JSX: 10 `_SplatMesh` nodes at their world transforms + `_SparkRenderer`. All ten loaded (`isInitialized: true`, 94k–762k splats each) and composite at 8,112,000 triangles in 1 draw call. |
| Q2 state-driven transform | **reconciles in place** — after moving one object by React state: constructions 10 → **10**, unmounts **0**, same instance (`uuid` unchanged), `numSplats` preserved, position updated. Sub-millisecond to schedule. |
| Q3 add/remove | **surgical** — dropping one object: exactly **1** unmount, **0** constructions, 9 nodes left. Restoring it: exactly **1** construction, 1 mount, back to 10, fully re-initialized. |
| Q4 glue cost | ~15 lines for the stage + ~20 for the splat component. |

**Three conditions, each of which we measured the failure of first:**

- **Memoize `args` on the URL.** R3F re-instantiates a host object whenever
  `args` changes by reference. With a fresh `[{url}]` literal every render,
  moving ONE object rebuilt ALL TEN: constructions 10 → **20**, every `uuid`
  replaced, every PLY re-parsed — while `mounts` stayed at 10, so React looked
  innocent and the cost was entirely invisible above the host layer.
- **Key on stable object identity, never list position.** With
  `key={label-index}`, removing one object shifted every later index and React
  remounted 8 unrelated objects: constructions 10 → **18**, 7 unmounts, for a
  single removal. With `key={url}` the same operation costs exactly 1 unmount.
- **`extend(THREE)` once at setup** (R3F v9).

**One cost that shapes the mutation design:** unmount/remount is a full
re-download and re-parse. A removal the user can undo should therefore hide the
object, not unmount it — and per-object `visible` was separately verified to work
imperatively against Spark and to take effect immediately.

## The handback to the compressed-tier session: yes, outside the renderer

**Load orchestration should live outside the renderer, and this is now measured
rather than predicted.**

In both architectures the download begins at exactly one moment: the
construction of `new SplatMesh({url})`. Imperatively that happens inside
`SplatViewer`'s effect as it walks the `splats` array; declaratively it happens
when a `<Splat>` enters the tree. In both, **what starts a download is a
`PositionedSplat` appearing in the list the renderer is given.** So an
orchestrator that decides *which splats are in that list yet, and in what order*
is identical under both, and survives the migration untouched.

Concretely:

- Keep `PositionedSplat[]` as the boundary (0053). Progressive loading is
  feeding that array in stages — a pure data concern.
- Put the policy (order, concurrency, which file tier) in a module or hook
  *above* `SplatViewer`. Under R3F, the effect that currently holds this logic
  does not exist at all.
- Do **not** extend `SplatViewer`'s existing gate. Today it is all-or-nothing
  inside the renderer: `await Promise.all(meshes.map((m) => m.initialized))` at
  `SplatViewer.tsx:590`, then the canvas fades in and the reveal begins. That
  single line is the thing progressive loading has to replace, and it is also
  the line an R3F migration deletes.
- One thing that must stay renderer-internal: the signal that a piece has
  actually landed. Spark composites several frames after a mesh initializes, so
  "this piece is on screen" can only be reported from inside.
- Load order and reveal order are separable, and worth separating. A mounted
  splat that Spark has not yet composited is invisible, so the orchestrator may
  load smallest-first for fastest first pixels while the 0097 reveal still
  presents largest-first. The P0 brief notes largest-first is the worst order for
  time-to-first-pixel; it only is if the two orders are coupled, and they need
  not be.

## Why

The escape hatch in 0056 existed because nobody knew whether a third-party
renderer that owns its own accumulation pass would tolerate React's reconciler.
It does, and the failure modes are ordinary React failure modes — reference
identity in `args`, and keys — not Spark incompatibilities. Both were found only
because the probe counted constructions; on screen, all four variants (correct,
un-memoized, index-keyed, and the two-phase mount) look the same. That is the
argument for keeping the construction counter in whatever test guards this later.

Answering the load-orchestration question now, from the same probe, costs the
compressed-tier session nothing and saves it from putting sequencing in the one
module a migration rewrites.

## What would change this decision

- **Drei's controls, gizmos or `<Select>` prove to fight Spark's picking.** Not
  probed at all — only `@react-three/fiber` was installed; `@react-three/drei`
  never was (its install failed on network and was not retried, since
  reconciliation was the question). Per-object selection needs raycasting against
  splats, and `SplatMesh` exposes `raycast` and `appendRaycastBuffer` — unexercised
  here.
- **The reveal (0097) proves hard to express declaratively.** It is currently an
  imperative timeline reading a pure plan from `lib/reveal`. Nothing in this probe
  touched it, and it is the largest single consumer of `SplatViewer`'s internals.
- **Frame cost under R3F diverges from the imperative path.** Not measured: the
  probe never ran a real render loop (no idle rAF in this pane), so per-frame
  cost under R3F is unknown. 0123 measured the imperative path at 0.2–0.3 ms
  steady frame; that number was not reproduced here and should not be assumed.
