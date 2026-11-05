# 0353 — A per-scan spend ceiling is checked before every call

**Date:** 2026-11-05
**Status:** Decided — the default is a placeholder to be set by the operator

## Context

Claude is ~10x the render cost per scan and scales with the iteration cap. A cap is a launch blocker (design 4.6).

## What we chose

`FINISH_MAX_USD` (default 12) per scan. Before each call `SpendLedger.check` requires spent + the call's worst case (estimated input tokens plus `max_tokens` at the model's output price) to fit under the ceiling, else `SpendCeilingReached`. Cost is computed from the `usage` the API reports (input, output, cache read/write) at list prices; an unpriced model is billed as the dearest. Pieces run in separate tasks, so each worker appends to its own `work/spend/<worker>.json` (one writer per file) and the total is the sum of the files; concurrent workers can overshoot by the calls in flight. Hitting the ceiling ends the scan's Claude work: a piece with a passing model keeps it, a piece without one fails, the finish stays measured-only, and the room is published with what passed.

## Why

Per-worker files keep the single-writer rule; the bound on overshoot is small and stated. A retried task re-reads its own file, so it does not forget what it spent.

## What would change this decision

Real call costs: the prices and token estimates are list prices and assumptions until a real scan is run.
