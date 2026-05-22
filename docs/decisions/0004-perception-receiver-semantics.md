# 0004 — perception-receiver-semantics

**Date:** 2026-05-22
**Status:** Decided
**Refines:** 0003

## Context

0003 chose async dispatch via Cloud Tasks and sketched the state machine
(`queued → processing → ready | failed`) but didn't specify how the receiver
implements it. Three questions surfaced when designing the `/process` endpoint:
how to classify failures for HTTP-status purposes, how to recover from crashes
mid-processing, and who owns the `failed → queued` transition on manual retry.

## What we tried

**For failure classification:** considered (A) 0003's literal reading — every
failure returns 5xx and gets retried up to 3 times. Rejected: poison messages
(malformed payloads, missing bundles) waste two retries and 60+ seconds of
queue time. Considered (B) full error taxonomy with per-error-type retry
policies. Rejected: maintenance burden, classification errors degrade silently.
Chose (C) two-bucket classification: poison (will fail every retry) vs.
environmental (might succeed on retry).

**For crash recovery:** considered (A) accept the loss — scenes stuck in
`processing` stay stuck. Rejected: silent failure mode. Considered (B) external
watchdog job scanning for stale `processing` states. Rejected: extra moving
part, recovery logic lives away from the state machine. Considered (C)
distributed lock via a separate service. Rejected: overkill. Chose (D)
lease-TTL embedded in the Firestore document — receiver writes lease timestamp
on claim, treats stale leases as reclaimable.

**For `failed → queued` ownership:** considered receiver-side (receiver sees
`failed` on entry, transitions to `queued`, proceeds). Rejected: muddles the
state machine — the receiver would own two distinct entry transitions.
Chose ingester-side: the manual retry endpoint on the ingester resets state to
`queued` before re-enqueueing, so the receiver only ever sees `queued` or
`processing` on entry.

## What we chose

**Failure classification:**
- Poison failures (malformed payload, bundle URI 404, structurally invalid
  bundle): receiver writes `failed` to Firestore, fires FCM, returns 2xx.
  Drains task from queue.
- Environmental failures (GCS transient, model crash, Firestore write fail):
  receiver returns 5xx. Cloud Tasks retries per 0003's policy. On final
  attempt (detected via `X-CloudTasks-TaskRetryCount >= 2`), receiver writes
  `failed` + fires FCM before returning 5xx.
- When in doubt, classify as environmental. Wasted retries are cheaper than
  incorrect dead-lettering.

**Crash recovery via lease-TTL:**
- Claim transitions `queued → processing` and writes `lease_expires_at = now +
  TTL` in a Firestore transaction.
- On entry, receiver branches on lease freshness when state is `processing`:
  fresh → another instance owns it, 200-exit; stale → reclaim, refresh lease,
  proceed.
- TTL: 5 minutes (env var `SCENE_LEASE_TTL_SECONDS`). Exceeds expected
  perception duration (30s–2min per 0003) with headroom.

**State machine ownership:**
- Receiver: `queued → processing → ready | failed`.
- Ingester (manual retry path): `failed → queued`.
- Receiver treats `failed` on entry as a bug and 200-exits without clobbering.

## Why

Two-bucket classification over full taxonomy: avoids the maintenance burden
0003 already rejected for retry-policy classification, while still cutting
obvious waste on poison messages. Two buckets is the minimum that captures the
real distinction (will retry help or not?).

Lease-TTL over watchdog: self-contained, recovery logic next to the state
machine it recovers. One file to reason about instead of two services that
must agree.

Ingester-owned `failed → queued`: keeps the receiver's state machine linear.
The receiver implements one path (forward through processing); the retry path
is conceptually a new job, which is exactly what the ingester already handles.

## What would change this decision

- If perception adds intermediate progress states (e.g. `processing.segmenting`
  → `processing.reconstructing`), the lease-refresh logic needs to handle
  multiple checkpoints rather than a single claim-time write.
- If poison-vs-environmental classification produces noticeable
  misclassification in practice (good failures dead-lettered, or bad failures
  retried forever), revisit. Track via Firestore queries on `failure_reason`.
- If a third receiver type emerges that needs the same dispatch semantics,
  extract the state-machine + OIDC + lease logic to a shared package rather
  than copy-pasting.
