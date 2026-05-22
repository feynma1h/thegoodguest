# 0003 — async-perception-dispatch

**Date:** 2026-05-22
**Status:** Decided

## Context

The ingester (`services/api`) validates capture bundles and acknowledges them
but does not yet trigger perception work. Perception jobs take 30s–2min on
GPU-backed Cloud Run. The iOS client needs to know when a scene is ready, but
the user is not expected to stare at a progress spinner for that duration.

## What we tried

1. **Synchronous end-to-end** — iOS holds the HTTP connection until perception
   finishes. Rejected: ingester pinned for 30s–2min per request, mobile
   network blip loses the result, doesn't survive instance recycling.

2. **Sync within backend, async to client** — ingester returns scene_id
   immediately, then blocks on perception synchronously. Rejected: ingester
   instance still pinned for the whole duration, no durability if the instance
   dies mid-wait. Worst of both worlds — the state-store complexity of async
   without the decoupling benefits.

3. **Fully async via Cloud Tasks** — ingester validates, persists Scene,
   enqueues a task, returns. Cloud Tasks dispatches to perception. Perception
   writes results and updates state. **Chosen.**

4. **Perception services as orchestrators** — ingester just triggers,
   perception manages state itself. Rejected: smears state-machine logic across
   multiple services. State management belongs in one place.

For retry policy, considered: (A) retry everything aggressively and hide it,
(B) classify errors as transient vs. permanent, (C) no auto-retry, surface
everything to user, (D) bounded auto-retry then user-driven manual retry.
Chose (D).

For push notifications, considered APNs direct vs. FCM. Chose FCM.

## What we chose

- **Queue:** Cloud Tasks, one queue targeting `perception-obj` via HTTP.
  `maxAttempts: 3`, exponential backoff starting at 30s (max 300s).
- **State store:** Firestore. `scenes/{scene_id}` documents with status field.
- **State machine:** `queued → processing → ready | failed`.
- **Idempotency:** `scene_id` used as Cloud Tasks task name (Tasks dedupes on
  name within 1hr window). Perception endpoint must be safe to call twice with
  the same scene_id.
- **Failure handling:** any non-2xx from perception counts as a failure; Cloud
  Tasks retries up to 3 times; on exhaustion scene → `failed`; iOS shows
  manual retry button which re-enqueues with the same scene_id.
- **Notifications:** FCM. Triggered from perception service on terminal state
  change (ready or failed).
- **Scope:** `perception-obj` only. `perception-geom` stays on its current
  invocation path; the photo-upload pipeline is not being iterated on.

## Why

Cloud Tasks over Pub/Sub: HTTP-target dispatch fits one-consumer-per-job,
per-task retry policies, individual job visibility. Pub/Sub is for fan-out
we don't have.

Option 3 over option 2: ingester returns in <1s, perception scales
independently, state survives instance recycling, retries are free.

Option 3 over option 4: state-machine logic in one place (the ingester + a
state record) rather than duplicated across every perception service.

Bounded auto-retry (D) over error classification (B): avoids a maintenance
burden (misclassified errors degrade silently), keeps perception service code
simple (every failure looks the same), bounds GPU waste (3 attempts max),
still surfaces persistent failures in minutes not hours.

FCM over APNs direct: GCP is the existing platform, FCM handles APNs
internals, gives a free Android path later, costs nothing at our volume. The
"avoid Google dependency" argument doesn't apply when GCP is already the
stack.

`perception-obj` only: `perception-geom` is photo-upload-only and the photo
path is explicitly not being iterated on. Wiring it into the new dispatch flow
would be infrastructure for a deprioritized surface.

## What would change this decision

- If we ever want real-time progress (e.g. "step 2 of 5: segmentation"), the
  notification path needs to be richer than terminal-state-only. Probably
  doesn't change the queue choice, but does change the perception service's
  reporting contract.
- If perception latency drops to <5s, sync-to-client becomes viable and the
  queue is overkill.
- If the photo-upload path gets promoted back to a first-class surface,
  `perception-geom` gets its own queue entry with this same pattern.
- If we ever need multiple consumers per job (e.g. perception + analytics +
  thumbnailer), revisit Pub/Sub.
