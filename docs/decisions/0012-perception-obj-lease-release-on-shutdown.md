# 0012 — perception-obj lease release on shutdown

**Date:** 2026-05-25
**Status:** Decided
**Refines:** 0011

## Context

0011 designed the lease-expiration check at `/process` to recover from environmental
failures where the worker returns 500 but keeps its lease. Pressure-testing that
design surfaced a gap it doesn't cover: Cloud Run rolling deploys.

When a new revision rolls out, the old instance is sent SIGTERM with a 10-second
drain window before SIGKILL. A perception-obj job takes 30s–2min, so any in-flight
`/process` call during a deploy will be killed mid-execution. The lease is left held.
Cloud Tasks retries within the TTL window, the retry hits a new instance, sees the
live lease held by the now-dead instance, returns 200 noop. Cloud Tasks acks and
drops the task. The lease later expires with nothing to trigger reclamation. Scene
is stuck.

This is the same failure class 0011 fixes, but 0011's mechanism (expiration check
at `/process`) only triggers when a POST arrives after the lease has expired. If the
only retry Cloud Tasks ever sends arrives before expiration and gets acked-as-noop,
no later POST will arrive and the scene strands.

On a project with weekly redeploys during active development, this isn't an edge case.

## What we tried

1. **Accept the gap, rely on manual retry.** Rejected. Premium consumer UX cannot
   have silent stuck scenes after a deploy, and the iOS app has no signal that a
   deploy happened — the user just sees a scene that never completes.

2. **Reject the noop on Cloud Tasks retries.** When `X-CloudTasks-TaskRetryCount > 0`
   and the lease is live, force a reclaim. Rejected: same objection as 0011's
   analysis of option 2 — couples receiver to Cloud Tasks specifics, doesn't
   generalize.

3. **Active reclamation worker (Cloud Scheduler).** Rejected for the same reasons
   0011 rejected it: new component, scheduled scans, race conditions.

4. **SIGTERM handler that releases held leases.** Chosen. On SIGTERM, atomically
   release any held leases and reset their scenes to `status=queued`. Cloud Tasks
   retries arrive at a clean state.

## What we chose

Register a SIGTERM handler in the perception-obj service that, for each scene
currently held by this worker, atomically (in a Firestore transaction): clears the
lease, sets `status=queued`, increments a `shutdown_release_count` field for
observability.

Best-effort within the 10s drain. If SIGKILL fires before the handler completes,
the lease-expiration check from 0011 handles the residual case — as long as a
future POST arrives, which is now more likely because clean releases have recovered
the other deploy-affected scenes.

The handler does not attempt to finish in-flight work. Cloud Run's drain is too
short to be useful for a 30s–2min job.

Status reset is `queued`, not `failed`. The job hasn't actually failed; it's been
interrupted by infrastructure. Cloud Tasks may still have the retry pending; `queued`
lets that retry claim normally. If Cloud Tasks has dropped the task, the scene sits
in `queued` for a manual retry path to pick up. Reporting `failed` would fire an
FCM the user shouldn't get.

Single-transaction release-and-reset is non-negotiable. A two-step release (clear
lease, then update status) can be interrupted by SIGKILL between steps, leaving a
lease-free `processing` scene that confuses the expiration check (no lease to compare
against).

## Why

Eager release on shutdown is the natural counterpart to eager release on
`EnvironmentalError` (0011's option 1). Both are optimizations on top of the
expiration check, not correctness-load-bearing. The expiration check is the floor;
release-on-shutdown raises the recovery latency for the most common interruption
(deploys) from "after lease TTL plus next POST" to "immediately on next retry."

## What would change this decision

- If Cloud Run drain windows become configurable to durations longer than typical
  job time, the calculus shifts toward finishing in-flight work instead of releasing.
  Doesn't change the release path; adds a "try to finish first" mode.
- If perception-obj is moved to a worker model with explicit lifecycle hooks
  (e.g. Kubernetes pod with `preStop`), the SIGTERM handler graduates to a proper
  `preStop` script. Same logic, different trigger.
- If the structured claim/reclaim logs added per the 0011 amendment show that
  concurrent-writer scenarios actually occur, fencing tokens become urgent and the
  SIGTERM release path must also write a fencing token bump.
