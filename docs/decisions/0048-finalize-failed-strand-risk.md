# 0048 — release_failed strand risk: bounded retry + alertable log, not a reconciliation system

**Date:** 2026-07-16
**Status:** Decided

## Context

In perception-obj, `_finalize_failed` (process_receiver.py) is the last
opportunity to mark a scene `failed` and clear its lease on both terminal
paths: PoisonError (200 drain — the task leaves the queue) and
EnvironmentalError on the final Cloud Tasks attempt (maxAttempts exhausted —
no further deliveries). If the `release_failed` Firestore write is lost to a
transient error at that moment, the scene is permanently stranded in
`processing`: nothing retries it, the client polls forever, and the lease
expires into a state no worker will ever reclaim (the queue has no task for
it anymore). A code-review pass flagged that this was silently accepted as
log-and-continue, without an explicit decision.

## What we tried

Three options were weighed:

1. **Accept as best-effort** (status quo) — single attempt, `logger.error`,
   move on.
2. **Bounded in-process retry + alertable structured log** — retry the write
   a couple of times over ~1.5 s; if it still fails, emit an ERROR line with
   a stable discriminator (`scene_strand_risk=true scene_id=…`).
3. **A reconciliation mechanism** — a sweeper (cron or on-claim scan) that
   finds scenes stuck in `processing` with long-expired leases and no queue
   task, and fails them.

## What we chose

Option 2. `_finalize_failed` now retries `release_failed` on a
`(0.5s, 1.0s)` schedule (3 attempts total), distinguishes non-retryable
`ValueError` (wrong state / scene missing — nothing is stranded) from
transient errors, and logs `scene_strand_risk=true` with the scene_id when
all attempts fail. Manual reconciliation for the residual case: re-enqueue
the scene the same way as the canonical stuck-scene reference
(`f077e9ed-…`, see CLAUDE.md).

## Why

- The strand window is the intersection of two low-probability events
  (terminal failure path AND Firestore down at exactly that moment). A
  ~1.5 s bounded retry covers the common transient blip without meaningfully
  extending the request (both paths are already terminal; the Cloud Tasks
  deadline has ample headroom there).
- A reconciliation sweeper is real distributed-systems surface (who runs it,
  how it distinguishes "stranded" from "slow", interaction with the lease
  machinery decisions 0011/0012) — unjustified pre-launch with zero traffic,
  and easy to add later behind the same structured log.
- The `scene_strand_risk=true` discriminator makes the residual case
  alertable the day log-based alerting exists, and greppable today.
- `time.sleep` in the (sync-called-from-async) handler briefly blocks the
  event loop; acceptable at ≤1.5 s on a concurrency=1 service, on a path
  that fires at most once per failed scene.

## What would change this decision

Real traffic plus an observed `scene_strand_risk=true` occurrence — or the
launch-hardening pass standing up alerting — would justify promoting this to
a reconciliation sweeper (option 3). If Firestore writes gain a client-level
retry policy config instead, the hand-rolled loop can be replaced by it.
