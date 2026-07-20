# 0053 — Splat renderer: Spark (three.js/WebGL2), contained in one component

**Date:** 2026-07-20
**Status:** Decided

## Context

CLAUDE.md's original framing said "WebGPU splat rendering" but no library had ever been
chosen. The web viewer needs to render many per-object 3DGS splats with independent
world transforms (manifest v2's fused objects), mixed with ordinary meshes (grid,
future gizmos/replacements), on whatever device a shared link is opened on.

## What we tried

Compared four options: **Spark** (`@sparkjsdev/spark`, World Labs — three.js, WebGL2 by
explicit design, loads raw 3DGS PLY plus spz/splat/ksplat/sogs, LoD streaming in 2.0,
built for multi-splat-object + mesh scenes), **Babylon.js** (true WebGPU pipeline with
WebGL2 fallback, first-class 3DGS loaders, but a different ecosystem than three.js —
weakens decision 0050's ecosystem rationale for keeping Next.js),
**mkkellogg/GaussianSplats3D** (three.js but no longer actively developed), and a
**custom WebGPU renderer** (maximum ceiling; a large build-and-maintain commitment —
GPU radix sort, LoD, format parsing — before any product surface exists).

## What we chose

Spark, with a hard containment rule: **all Spark/three.js API usage lives in
`web/src/components/SplatViewer.tsx`**, whose input contract is a renderer-agnostic
list of `PositionedSplat`s ({url, position, rotation_xyzw, scale, label}). Nothing else
imports the rendering library in either direction, so a future renderer swap is a
one-file rewrite, not a cross-app refactor.

Verified working in-session: renders the synthetic fixture room (INRIA-layout PLYs)
with correct transforms — ARKit world and three.js share handedness and up-axis, so
transforms apply with no basis change — orbit controls, clean console.

## Why

Not primarily compatibility (prompting users to update browsers is acceptable). On the
merits: WebGPU-only ships a *hard* failure (blank canvas) on blocklisted GPU/driver
combos where WebGL2 degrades but works; WebGL2's debugging tooling is far more mature;
WebGPU's cross-browser consistency is less battle-tested (each browser wraps a
different native API underneath); and Spark's implementation complexity is far below
hand-rolling a WebGPU path for exactly our multi-object-splat-plus-mesh use case, in
the three.js ecosystem decision 0050 already bet on.

Deliberately left unresolved (not worth a comparison spike against writing real code):
whether WebGPU's compute-shader sorting/blending precision meaningfully matters at our
actual scale — 5–20 objects, human-scale rooms, not massive outdoor benchmarks.

## What would change this decision

A *condition to watch*, not a scheduled re-evaluation: WebGPU splat renderers mature
(Babylon 3DGS, WebSplatter-class engines) **and** profiling on a real captured room
shows Spark is the actual fidelity/performance bottleneck on target devices. The
containment rule keeps the cost of acting on that condition at one file.
