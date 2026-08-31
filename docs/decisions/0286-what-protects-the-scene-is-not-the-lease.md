# 0286 — what protects the scene is not the lease

**Date:** 2026-08-31
**Status:** Decided
**Refines:** 0011, 0012

## Context

Three concerns came out of the lease-semantics design session and were never
checked against a running system. This note checks them at parking, so the
answers survive the pause.

The timing matters for what can be re-derived later. The check ran on
2026-08-31, partly BEFORE and partly AFTER the parking wipe: the Firestore
corpus (65 scenes) and the GCS bundles were read while they still existed and
were deleted hours later. Cloud Logging survived the wipe but ages out at 30
days, and the last perception run was 2026-08-25 — so **every number below
becomes unreproducible around 2026-09-25**, with no new traffic to replace it.
That is why they are recorded here rather than left in a report.

Nothing was changed. This note is the finding; the work it implies is on the
punchlist.

## What we tried

### 1. Does the lease TTL cover worst-case processing?

`SCENE_LEASE_TTL_SECONDS` still defaults to 300 and is still not set in
`infra/deploy_perception.sh`, so production runs the default. The claim is
still taken AFTER the lazy model load — `server.py` loads both models, then
calls `handle_process`, which claims — so the TTL still times the processing
phase only, as designed.

Lease-held time was measured across 66 paired production runs (logs 2026-08-05
→ 2026-08-25). Method: request-log latency minus model-load time, where model
load is `900 − remaining_s` from each run's `process budget` line. Verified
against the claim-log timestamps, which land at request start + model load to
within 50 ms.

| | |
|---|---|
| max lease held | **899.8 s** |
| median | **613.5 s** |
| min | 46.8 s |
| runs exceeding the 300 s TTL | **46 of 66 — 70%** |

The TTL is not marginal. It is routinely exceeded by two to three times, and
the median run's lease is dead for roughly half its duration. Cold starts are
the MILD case (220–465 s of model load, then a short remainder); the severe
cases are warm re-drives that claim instantly and then process for 880 s.

**Two workers on one scene has nonetheless never happened, and neither guard
that prevents it is the lease.** `DISPATCH_DEADLINE_SECONDS = 930` in
api-internal exceeds the 900 s Cloud Run timeout, so Cloud Tasks never retries
a running attempt; and `--max-instances=1 --concurrency=1` allows one request
at a time per revision. The lease has been wrong throughout and nothing that
could act on it has consulted it.

**One thing does consult it.** `tools/reenqueue_scene.py` uses the lease as its
"is a worker active?" test. Because the lease is dead for most of a real run,
pointing it at an actively-processing scene returns `PROCEED — stranded:
processing with expired/absent lease` with no `--force` and no warning, then
resets the doc and dispatches a second task — a dispatcher outside the 930 s
invariant. `max-instances` is per-revision, so a 0%-traffic candidate (there
was one live at measurement time) supplies the second instance.

**No observability would catch it, for three separate reasons.** All five
`_log_lease_action` call sites pass only `scene_id`, so the `lease_expires_at`
field 0011 specified for exactly this prints `none` in every production line
ever emitted. `RECLAIMED` is returned identically for an expired lease and a
cleared one, and both log `reclaim_stale`, so the logs cannot distinguish the
two. And the one place the harm would surface — a reclaimed-from worker's
`release_ready` / `release_failed` hitting the holder guard — is a bare
`return` with no log; the worker then reports 200 "ready" to Cloud Tasks having
written nothing. There are zero log-based metrics and zero alert policies.

### 2. Is there a cycle limit on the SIGTERM → queued reset?

No. `shutdown_release_count` is written by both repository implementations and
read by **nothing** outside tests — the only other references in the tree are
two docstrings. 0019 excludes it from the client-facing scene read, so the
phone cannot see it either.

**The path has never fired in production.** 0 of the 65 scenes carried a
non-zero count, and there is no `release_shutdown` line in the logs. Two
reasons, and the second is structural: perception-obj scales to zero and
deploys candidate → flip, so drains usually catch nothing in flight; and
`run_perception` is a plain synchronous function called directly from the async
handler with no `to_thread`, so it blocks the main thread for the whole run.
Python delivers SIGTERM to the main thread at a bytecode boundary, so during a
long C-level call (a CUDA forward, a GCS read) the handler is deferred. Against
a 10 s drain, a SIGTERM arriving mid-forward is lost to SIGKILL. **0012's
mechanism is not merely unexercised — it is unreliable by construction.**

The runaway loop the concern describes cannot run away: Cloud Tasks is
`maxAttempts=3` and a reset to `queued` does not reset the attempt count.

## What we chose

**The TTL is wrong and the fix is 960 s — proposed, not applied.** The lease
should outlive the longest possible request, and the request is already
hard-bounded at 900 s by the platform and by `budget.py`. At 960 s "the lease
is live" means "a worker may be running", which is what `reenqueue_scene.py`
already assumes it means. The cost is that a hard-crashed worker waits up to
960 s for passive reclamation instead of 300 s — acceptable, because the eager
release paths already cover the crashes that can run code, and 0011 deliberately
severed the TTL/backoff invariant so nothing else binds it.

**The `shutdown_release_count > N` gate is REFUSED, not deferred.** It would
gate on a counter that has never incremented, inside a handler that may be
unable to run when it matters, to bound a loop Cloud Tasks already caps at 3.
Every one of those three premises has to hold for the gate to do anything, and
none of them does.

**The real failure is the terminal one, and it is a different shape.** After
attempt 3 a scene sits in `queued` permanently — no terminal state, no
`expire_at` (only failure statuses are stamped), no FCM. Reached in three steps
rather than infinitely, but the same limbo. At measurement time 4 scenes sat in
`queued` and 8 in `processing`; none showed SIGTERM residue, so a sweep for
stale non-terminal scenes would have caught all twelve and the counter gate
none of them. That is the item worth building, and it is a GC/monitoring
concern rather than a lease one.

**The correctness path is still unverified, and can no longer be verified
here.** In a month of logs `reclaim_stale` appears three times and **every
occurrence is preceded by a `release_error` from the same worker seconds
earlier** — all eager release. The lease-expiration branch, which is the
load-bearing one because it works when the worker could not run any code, has
only ever executed in unit tests (86 of which pass).

Scene `f077e9ed-d339-4be8-8dbf-37b952abfec2` was the reference for it: still
`processing` with a lease expired 2026-05-24, the only scene in the corpus in
that state, and — contrary to the standing belief — its bundle had survived,
because the captures-bucket lifecycle rule carries `matchesPrefix:
["captures/"]` and that bundle sat under `smoke-test/`. **The parking wipe
deleted both hours later.** The reference is gone.

It would not have worked anyway: `reenqueue_scene.py` resets a scene to
`queued` before dispatching, which erases the expired lease that is the whole
subject of the test. A run through it logs `claim`, not `reclaim_stale`. So the
tool exercises the wrong branch and destroys the state on the way.

## Why

The three concerns look like three bugs and are really one shape: **the lease
is a claim nobody checks.** It is wrong 70% of the time, its designated log
field was never populated, its violation is silent by construction, and the
things actually keeping the system correct are a queue deadline in another
service and a scaling flag. A mechanism in that condition is not a safety net;
it is a comment that happens to be executable.

That is also why the TTL fix is worth more than it looks. It costs one number
and buys the invariant everything already assumes — and until it lands, the
re-drive tool's guard is reading a value that is usually a lie.

The counter gate is refused on the opposite reasoning: it adds a mechanism to
guard a mechanism that has never run, which is how a system accumulates code
that cannot be verified and cannot be removed. 0237's rule applies — dead code
that accrues unverified fixes rusts shut rather than staying ready.

## What would change this decision

- **The TTL fix ships and the guard question changes.** Once the lease outlives
  the request, `reenqueue_scene.py`'s liveness test becomes sound and the
  double-dispatch path closes without any other change.
- **A second dispatcher, or max-instances above 1.** Both guards that currently
  substitute for the lease would stop being sufficient, and fencing tokens
  (0011's known limitation) move from theoretical to urgent.
- **`run_perception` moves off the main thread.** That is the one change that
  would make 0012's SIGTERM handler reliable, and it would also stop `/health`
  and `/ready` blocking for the length of a run. It is a prerequisite for
  trusting the shutdown path, not an optimization of it.
- **A new stuck-scene reference appears.** The expiration branch is still
  untested in production. The cheapest way to test it is now to construct the
  state deliberately on a fresh capture — write a `processing` scene with a past
  lease and dispatch WITHOUT the reset — rather than to preserve one by
  accident. Success is `reclaim_stale` with no preceding `release_error`, and a
  clean transition to `ready` or `failed`.
- **The evidence expires around 2026-09-25.** After that the numbers above
  cannot be re-derived from logs, and re-measuring needs fresh captures and a
  re-drive corpus that no longer exists.
