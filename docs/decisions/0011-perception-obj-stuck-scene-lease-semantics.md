# 0011 — perception-obj lease semantics: fix the stuck-scene bug

**Date:** 2026-05-24
**Status:** Decided

## Context

On 2026-05-24 a perception-obj run hit a CUDA OOM mid-processing and
ended up with the scene permanently stuck in Firestore `status=processing`.
Investigation (see `outputs/investigation-2026-05-24-oom-stuck.md`,
not committed) found the cause is structural, not an implementation slip:

- The OOM handler in `/process` correctly catches the error, returns
  500, and intentionally does NOT write `status=failed` to Firestore
  — it relies on Cloud Tasks to retry (per 0003's bounded-auto-retry
  policy). The lease is left held.
- Cloud Tasks retries 31 seconds later (minBackoff = 30s).
- The retry sees the still-active lease (TTL = 300s, 269s remaining)
  and returns `{"status": "noop", "reason": "already_owned"}` — a
  200, by design, to prevent double-processing.
- Cloud Tasks interprets the 200 as success and permanently removes
  the task from the queue.
- The lease later expires. There is no active reclamation worker.
  Passive reclamation on the next `/process` POST never fires because
  Cloud Tasks has stopped sending POSTs for this scene.
- The scene is stuck.

This will happen to every job that fails environmentally more than 30
seconds into processing. Given that perception-obj cold-start model
loading takes ~3.5 minutes, every cold-start environmental failure
hits this. It is not an edge case.

The bug is the conflation of two mechanisms: the lease (designed for
crash recovery, "this worker owns the scene") and the idempotency
check (designed to prevent double-processing, "someone is on it,
don't start over"). They are implemented as the same check, so a
transient failure that holds a lease causes its own retry to be
rejected as a duplicate.

## What we tried

Considered five fixes:

1. **Release lease in error handlers.** Eager release on caught
   `EnvironmentalError`. Acceptable, but narrow — doesn't help if the
   worker crashes before reaching the handler (process killed, native
   segfault, GCP infrastructure event). Leaves the same broken state
   in those cases.

2. **Cloud Tasks retry-header-aware reclamation.** At `/process`, if
   `X-CloudTasks-TaskRetryCount > 0`, treat ALREADY_OWNED as "the
   previous worker is gone, reclaim and process." Works for OOMs and
   crashes, but couples the receiver to Cloud Tasks specifics. Fails
   on AWS or any other queue. Also handles user-initiated retries
   poorly — a fresh task with retry count 0 arriving after the lease
   should have expired won't trigger reclamation.

3. **minBackoff > lease TTL.** Set Cloud Tasks minBackoff to e.g.
   360s so retries always arrive after the lease expires. Trivial,
   no code change. Rejected: every retry now takes 6+ minutes
   minimum, bad UX. Fragile — anyone tuning either value later
   without remembering the invariant breaks correctness.

4. **Active reclamation worker.** Cloud Scheduler job scanning for
   expired leases and re-enqueueing. Rejected: most operational
   overhead, new component to maintain, race conditions between
   reclamation and Cloud Tasks retries.

5. **Lease-expiration check at `/process`.** When a scene is
   already-owned, check whether the lease has actually expired. If
   yes, reclaim and process. If no, return noop. **Chosen.**

## What we chose

Option 5 as the load-bearing correctness fix. Option 1 layered on
top as an optimization.

Specifically:

- `/process` already-owned path becomes:

```
if lease.expires_at <= now():
    reclaim_and_process()   # stale lease — take it
else:
    return_noop_200()       # active lease — skip
```

  The `holder_id == self` case is dropped entirely. If it fires, the
  defensive noop is correct behavior; there is no normal path that
  reaches it.

  The reclaim must be a single Firestore transaction (read lease,
  verify still expired, write new lease + status). A read-verify-write
  sequence outside a transaction has a TOCTOU window where two
  concurrent workers both see an expired lease and both proceed.

- A structured log line is emitted at every lease claim, reclaim,
  release, and noop with fields `worker_id`, `scene_id`,
  `lease_expires_at`, and `action_taken` (one of `claim`,
  `reclaim_stale`, `release_error`, `release_shutdown`,
  `noop_live_lease`). This makes concurrent-writer scenarios detectable
  and gates the fencing-token decision on observed data.

- The `EnvironmentalError` handler releases the lease before returning
  500. Optimization only — correctness comes from the lease-expiration
  check above. Lets retries happen immediately rather than waiting
  ~lease-TTL.
- `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` added to Cloud
  Run env config. Orthogonal to the lease fix; addresses fragmentation
  on the OOM itself.

The Cloud Tasks `minBackoff` (30s) and lease TTL (300s) no longer have
to be in any particular relationship for correctness. They should
still be sensible (TTL > model-loading time + typical job duration,
backoff not so short that retries thunder), but no invariant binds them.

## Why

The lease-expiration check is the right mechanism because it expresses
the actual semantics: "is the lease live, or stale-but-not-yet-reclaimed?"
That question has nothing to do with Cloud Tasks, retries, or any queue
system. It's a property of the lease itself.

Compared to the alternatives:

- Better than option 1 (eager release alone): handles crashes where
  the worker can't run the release code.
- Better than option 2 (retry-header check): platform-agnostic. Same
  logic works on SQS, RabbitMQ, anything.
- Better than option 3 (longer backoff): doesn't degrade retry latency,
  doesn't create a fragile invariant.
- Better than option 4 (active reclamation): no new components, no
  scheduled jobs, reclamation is opportunistic and happens exactly
  when something needs to happen anyway (a POST arrives).

Layering option 1 on top is cheap and improves retry latency without
adding complexity. It's not load-bearing — if the release-on-error
code has a bug, the system still recovers via the expiration check —
which is the right relationship between correctness and optimization.

## Known limitation: no fencing tokens

This design does not prevent a "stale writer" scenario: worker A
claims a lease, network-partitions, lease expires, worker B reclaims
and finishes, worker A's network heals and it writes results that
overwrite worker B's. The current code has no fencing token on
Firestore writes, so worker A's write succeeds.

This is a pre-existing gap, not a regression introduced by this fix.
Addressing it requires lease fencing tokens (monotonic counter per
lease claim, checked on every write), which is a larger change.
The structured logging added above is what generates the evidence to
trigger that work. Implement fencing tokens if either of the following
occurs: (a) the claim/reclaim logs show a `reclaim_stale` followed by
a write from the prior holder's `worker_id` within the same scene, or
(b) a second writer to scene state is added beyond perception-obj
(web app edit flow, re-processing path, or anything else that touches
scene fields under a lease).

## What would change this decision

- If two workers writing to the same scene becomes a real observed
  problem, add fencing tokens. The lease-expiration logic stays;
  it just gains a counter.
- If perception-obj is ever moved to a queue system without
  per-task retry semantics (e.g. fan-out via Pub/Sub), the
  reclaim-on-stale-lease behavior still applies but the broader
  retry policy needs re-thinking.
- If model loading time becomes negligible (e.g. resident GPU pool),
  the lease TTL can be shortened dramatically and the whole window
  where this bug manifested narrows. Doesn't change the fix; might
  obsolete the optimization (option 1) since retries would already
  be fast.
- The deploy-mid-job gap (Cloud Run SIGTERM with 10s drain killing an
  in-flight job before the lease-expiration check can fire) is a
  separate structural failure mode. See `docs/decisions/0012`.
