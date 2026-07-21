# 0062 — frame sampling: deterministic pose-diverse FPS, budget as the guarantee

**Date:** 2026-07-21
**Status:** Decided

## Context

Real captures carry ~100+ keyframes; the processing envelope fits ~10–16
reconstructions (900 s request budget minus ~3.5 min cold-start model load,
at ~70–130 s/frame). Some bounded selection policy had to pick which frames
get reconstructed.

## What we tried

Considered, not benchmarked (the decision is structural):

- **Stride / temporal prefix** — keeps temporal coverage, but a handheld
  scan that lingers in one corner spends most of the budget on one
  viewpoint; and iOS keyframing is already pose-delta-gated (10 cm/5°), so
  temporal spacing ≠ viewpoint spacing.
- **Random subset** — nondeterministic across Cloud Tasks retries. Per-frame
  outputs are cached in GCS keyed by frame_index; a retry that picks a
  different subset wastes its own cache.
- **Clustering (k-means over poses)** — heavier, seed-dependent, and the
  quantity fusion actually needs is mutual spread, which farthest-point
  sampling optimizes directly.

## What we chose

`services/perception-obj/sampling.py`: farthest-point sampling over

    d(a,b) = ||pos_a − pos_b|| + 0.5 m/rad · angle(view_dir_a, view_dir_b)

seeded at the most extreme frame, ties broken by lower index (fully
deterministic), output in input order, default cap 12
(`PERCEPTION_MAX_FRAMES`). View-direction angle rather than yaw-only: it is
defined for any pose (no gimbal caveats) and generalizes the same intent —
observe objects from genuinely different directions. 0.5 m/rad makes a 30°
pan (~0.26 m equivalent) comparable to a typical between-keyframe step.

The sampler TARGETS a frame count; the budget tracker (0060/0061 session,
`budget.py`) is the GUARANTEE. Sampling picks the best ≤N viewpoints,
budget admission decides how many of them actually run today. The two are
deliberately decoupled: tuning one never risks the other's invariant.

## Why

Triangulation (fusion's ARKIT_ONLY path) is served by baselines and angular
spread, which is exactly what the FPS metric maximizes. Determinism is
load-bearing, not cosmetic: retries must re-select the same subset to hit
their own per-frame GCS caches. Order preservation keeps fusion's
per-frame-uniqueness guards seeing the same invariants as an unsampled run.

## What would change this decision

- Evidence from real rooms that 12 frames under-covers typical scans
  (objects seen in <2 selected frames failing to triangulate) → raise the
  default or make the cap adaptive to trajectory length.
- If per-frame cost drops an order of magnitude (faster models), the cap
  can rise until sampling stops being the binding constraint and this
  policy becomes mostly moot.
- If selection quality ever needs image content (coverage of unseen room
  regions, not just pose spread), that's a different feature — this module
  deliberately reads only poses.
