# 0332 — scene-finish is its own CPU service, with gate numbers taken from its renderer

**Date:** 2026-11-05
**Status:** Decided

## Context

The finish and furniture passes run after every scan. perception-obj is one L4
instance at concurrency 1 with a ~195 s model load; the passes want many small
parallel workers and must not starve SAM (phase 2 design, section 3).

## What we chose

- `services/scene-finish`: a flat-module FastAPI service, own image (Node for
  the driver, Python for the service, Playwright's Chromium headless shell, the
  flagged viewer built in the same Dockerfile), `GET /health` and
  `POST /render` for now. The Claude-layer routes (finish, furniture-piece,
  furniture-merge) are added to the same app by the next track. It imports
  `packages/room-look` (0330); it has no cloud dependency yet.
- `infra/deploy_scene_finish.sh` and `infra/cloudbuild/scene-finish.yaml`,
  written in the perception-obj pattern: dedicated runtime SA, secret-scoped
  Anthropic key, platform-gated (`--no-allow-unauthenticated`, run.invoker for
  the Cloud Tasks invoker), candidate mode. Sizing is an estimate: 4 vCPU,
  8 GiB, concurrency 1, 900 s, max 12 instances. NOT RUN.
- Gate tolerances live in `services/scene-finish/thresholds.py`. The one
  measured number is the renderer's own noise, 0.16 L between SwiftShader and a
  GPU (0331); the design's tolerances (0.5 L to accept a hint, 1.0 L for a
  furniture edit) stay, because they are 3 to 6 times that noise. A test pins
  that ratio. The photo-versus-render numbers (bounding-box gap, placement
  error) were not measured: they need the spec loop.

## Why

Separate service, same image shape as its siblings, so the next track adds
routes rather than infrastructure. Thresholds in one importable module so a gate
cannot carry a private literal.

## What would change this decision

A measured 4-vCPU render time that breaks the 900 s per-piece budget, a render
equality result on a second scene that contradicts 0331, or Claude's first
real specs landing inside the noise band (then the tolerances tighten).
