# 0358 — Observability is structured log lines and a summary with no pixels

**Date:** 2026-11-05
**Status:** Decided — alert rules are defined in code, not yet deployed

## What we chose

Every Claude call logs one JSON line on `scene_finish.claude` (stage, scene and box ids, iteration, model, outcome, image counts by kind, input/output/cache tokens, latency, the SDK request id, dollars). Pieces, the finish and the publish log `scene_finish.events` lines (`piece_done`, `finish_done`, `render_failed`, `published`, `alert`). `work/summary.json` records time to look, spend against the ceiling, and per-piece status, reason, edits and calls. `observe.alerts` evaluates the design's conditions (more than 30% of pieces failed, spend at the ceiling, time to look over 30 minutes, deadline hit) on every publish and logs each as an `alert` line for a log-based alert to match. No prompt, image, workspace path or key appears in any line (tested).

## What would change this decision

The alert policies themselves (log-based metrics and notification channels) are infra and are not created here.
