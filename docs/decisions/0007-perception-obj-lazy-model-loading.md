# 0007 — Lazy model loading in perception-obj

**Date:** 2026-05-23
**Status:** Decided

## Context

perception-obj deploys to Cloud Run with `--min-instances=0` (budget
constraint — no always-warm L4 GPU pool). On every cold start, the
container loads SAM 3 (~100s) and SAM 3D Objects (~95s) synchronously at
startup, totalling ~195s before uvicorn can serve any request.

The first deploy of the `/process` receiver (revision 00019-7zr,
2026-05-23) was marked failed by Cloud Run with "Container import
failed." The actual cause was Cloud Run's default startup probe timeout
(~240s) being too close to the 195s model load: any cold-start variance
or GPU contention pushed it over. Traffic stayed on the previous
revision 00018-ppx, which has no `/process` endpoint, so Cloud Tasks
began hitting 404s on every queued scene.

## What we tried

Considered three options:

**A — Bump the startup-probe timeout.** One-line deploy-script change.
Cheapest. Keeps eager model loading. Rejected because it's a fix
that needs re-tuning every time a model is added, a checkpoint grows, or
GPU cold-start behavior shifts. Throwaway work.

**B — Lazy-load models on first `/process` call.** App-code refactor.
Container reports healthy in seconds. First `/process` after cold start
pays the 195s cost. Cloud Tasks' long retry deadlines absorb this
cleanly. Chosen — see below.

**C — Migrate to GKE with a small persistent GPU pool.** Right answer
at high scale. Wrong answer now: no users yet, no signal about traffic
patterns, premature ops complexity. Deferred until Cloud Run's cost or
scaling behavior actually becomes a constraint.

## What we chose

Option B. The shape:

- A model registry holds SAM 3 and SAM 3D as initially-`None` slots,
  with idempotent threadsafe accessors that load on first use.
- `/healthz` returns 200 immediately with no model interaction — used
  as the startup probe target.
- `/readyz` reports load state (not-loaded / loading / loaded / failed).
- `/process` calls the model accessors at the top of the handler. First
  call after cold start blocks ~195s; subsequent calls are instant.
- Deploy script sets an explicit startup probe pointing at `/healthz`
  with a fast timeout (a few seconds — just confirming uvicorn is up).
  `--min-instances=0` unchanged.

## Why

Lazy loading is correct on any platform we might end up on. Eager
loading is a code smell that recurs every time we add a model or change
infrastructure. Option A is throwaway; B compounds — the same `/healthz`
discipline that fixes today's deploy also enables proper readiness
checks, model hot-reload, and clean migration to GKE or any other
platform later.

The first-request cost (~195s on cold start) is acceptable for this
product because no user is waiting in real-time: capture flows are
async, users get an FCM push when done. Cloud Tasks tolerates 195s
trivially within its 30-minute deadline.

## What would change this decision

- If perception-obj acquired latency-sensitive synchronous endpoints
  (interactive editing, preview generation), lazy loading would push
  cold-start cost onto end users and we'd need warm instances
  (`--min-instances=1`) or pre-warming.
- If traffic patterns become sustained-high enough that we're paying
  for warm instances anyway, eager loading becomes free and the lazy
  complexity isn't earning its keep — revisit.
- If we migrate off Cloud Run to GKE/equivalent, the model registry
  shape still applies; only the probe-config wiring changes.
