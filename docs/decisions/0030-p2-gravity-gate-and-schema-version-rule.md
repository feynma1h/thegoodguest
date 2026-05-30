# 0030 — P1→P2 gravity gate and schema_version enforcement rule

**Date:** 2026-05-30
**Status:** Decided

## Context

iOS P1 is complete. Two hard gates must clear before P2 merges:
`PoseExtractor.gravity(from:)` is unimplemented (zero-vector stub), and the
backend's `schema_version = "1"` enforcement check doesn't exist yet. Both
were deferred deliberately at P1 with explicit rules for how they must land.
This note records those rules so they survive session boundaries.

## What we chose

### Gate 1 — Gravity formula and test

`PoseExtractor.gravity(from:)` in `ios/RoomStudioCapture/RoomStudioCapture/
Capture/PoseExtractor.swift` returns `RSGravity()` (zero vector) in P1.
The formula is deferred because gravity is the one ARKit→proto mapping that
0029 left unconfirmed — and it is a silent sign/direction trap.

The trap: the gravity field is the world-down vector `(0, −1, 0)` rotated
into the camera's local frame via the **inverse** (world→camera) rotation.
An inverse-vs-forward error, or a sign flip on world-down, produces a
different unit vector — but still a valid unit vector. A norm check passes
on all of them. A cross-check against `pose_math.py` also passes whenever
both sides apply the same formula, right or wrong.

**Binding rules for the P2 implementation:**

1. Both the implementation of `gravity(from:)` and its test must be routed
   to Chat for review before P2 commits the gravity field. This is a
   coordinate-frame derivation; per CLAUDE.md, wrong answers propagate.

2. The test must assert against camera-local ground-truth values derived
   from first principles for at least two known orientations (e.g. camera
   upright/viewing horizontally, and camera pitched to look straight down at
   the floor). The specific expected vectors are derived and reviewed in Chat
   together with the formula — they are NOT pre-stated in this note, because
   the expected value is the disputed quantity the gate exists to verify.
   Locking a vector here before the derivation is reviewed would recreate
   the trap the note describes.

3. The test must NOT use a self-referential round-trip (asserting
   `gravity(from: cam) == rotate(q, worldDown)` where both sides share the
   same formula). It must NOT rely on norm-only checks. It must NOT
   cross-check against `pose_math.py` unless `pose_math.py` derives gravity
   by a provably independent route.

### Gate 2 — `schema_version = "1"` backend enforcement

`api-internal`'s ingest handler has no `schema_version` check today. P2
is the first iOS phase that serializes a real `bundle.pb` with
`schema_version = "1"` set. The backend gate must ship, be tested, and be
deployed before P2 merges.

**Binding rule:** the enforcement check must reject unknown versions into
the existing `failed_invalid` Scene state — not a new enum member. Adding a
new `SceneStatus` value would require a coordinated reader redeploy across
both services (see decision 0027 for why this is expensive). `failed_invalid`
already means "bundle rejected before GPU work"; schema rejection is the
same category.

## Why

**Gravity trap.** The proto's `Gravity` docstring says camera-local unit
vector, and the ARKit frame is gravity-aligned (+Y up), so the derivation
looks simple. But there are four plausible formulas that all compile and all
produce unit vectors:
`R * worldDown`, `R.T * worldDown`, `R * (0,1,0)`, `R.T * (0,1,0)`.
Only one is correct. The only test that distinguishes them is comparison
against independently derived expected values — which is why the two
hand-computed orientations are required, why the specific vectors must be
derived and reviewed in Chat (not pre-stated), and why self-referential
tests are explicitly banned.

**`failed_invalid` reuse.** Decision 0027 recorded the cost of adding a new
`SceneStatus` enum member: every service that reads the field must be
redeployed atomically or it sees an unknown value. `failed_invalid` was
added in 0027 precisely because it's the general "pre-GPU rejection" bucket.
Schema rejection is pre-GPU; it belongs there.

## What would change this decision

- If ARKit ever exposes a gravity vector directly on `ARFrame` or `ARCamera`
  (it does not today), the derivation step goes away and the formula risk
  drops to near zero. The test rule still applies — pin expected values
  derived independently, don't trust norm-only.
- If a new terminal `SceneStatus` is added for an unrelated reason and
  `failed_invalid` becomes overloaded in a way that confuses operators,
  a dedicated `failed_schema` state may be warranted. The 0027 reader-redeploy
  cost doesn't go away; it just becomes worth paying.
