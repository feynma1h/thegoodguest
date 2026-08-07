# 0098 — Per-UID capture ceiling: bounding GPU spend, measured

**Date:** 2026-08-08
**Status:** Decided

## Context

Decision 0087 gave `/upload_session` a per-UID daily MINT quota (50). That
bounds API calls. It does not bound GPU: one accepted bundle commits a
reconstruction run, and at 50 mints/day an account could commit far more L4
time than anyone intended. The board asked for the GPU-cost analogue, with a
measured number rather than a guess.

## What we measured

From production, over the last 30 days (Cloud Run request logs for
perception-obj `/process`):

- **51 `/process` requests, 44 of them longer than 60 s.**
- **32,021 GPU-seconds total** — 8.9 GPU-hours for the whole month's
  perception work, across the RP-6/7/8 captures and every warm re-drive.
- **Mean long request 728 s; max 900 s.** The 900 s figure is
  `PROCESS_REQUEST_BUDGET_SECONDS` binding — the several `504`s in the log are
  that ceiling doing its job, not failures.
- Per-object reconstruction cost from RP-8: **61.9 s observed** (about 2× the
  earlier offline estimate of 30 s).

Deployed shape: **1 × nvidia-L4, 8 vCPU, 32 GiB, cpu-throttling disabled**
(so CPU is billed for the whole request, not just on-CPU time).

Derived per-capture cost:

- A warm capture that completes in one request: up to 900 GPU-s.
- **A typical capture needs two requests** — RP-8's spike took exactly two to
  reach `ready`, and a cold start spends ~210 s of round one on model load. So
  **~1,500 GPU-seconds is the working per-capture figure.**
- A cluttered room is worse: `b667f891` ran four rounds and still did not
  finish (its 53-item long tail exceeds one request).

Dollar conversion is deliberately *derived*, not measured: the Cloud Billing
API is not enabled on this project and enabling it for a price lookup was not
worth a project-level change. At published Cloud Run rates (nvidia-L4
$0.000233/GPU-s, 8 vCPU ≈ $0.000192/s, 32 GiB ≈ $0.00008/s) the blended rate
is ≈ **$0.0005/second**, putting a 900 s request near **$0.45** and a typical
capture near **$0.90** — and the whole month's 32,021 s near **$16**. Those
three figures are the ones to confirm against the billing console; the
GPU-second measurements above are exact and do not depend on them.

## What we chose

A per-UID daily CAPTURE ceiling, default **12**, enforced in the same
Firestore transaction as the mint quota, on the same day-rolled document
(`upload_mint_quotas/{uid}` gains a `captures` counter). Env knob
`UPLOAD_SESSION_DAILY_CAPTURES`. Over the cap: **429 `capture_limit_reached`**
with `resets_at` and `Retry-After` — a distinct error code from
`rate_limited`.

**Charged once per `bundle_id`, on its first claim.** Re-mints and replays of
a bundle already started today are free.

**Evaluated BEFORE the mint quota**, so a refused capture burns no mint quota.

## Why

**The mint is where a capture's cost is committed.** It is tempting to enforce
at ingest instead, since that is where the Cloud Task is enqueued — but ingest
would require a new terminal `SceneStatus`, and that is a cross-service enum
contract with a deploy-ordering hazard (0027: the api-public reader needs
rebuilding first). The mint already has the transaction, the day-roll pattern,
and an established 429 contract, and the user is still standing there when it
fires.

**Counting bundle_ids, not mint calls, is what makes it a GPU bound.** A
capture may mint several times — the 0049 re-mint path sends a grown path set
for a bundle already claimed — and none of those re-mints commits new GPU. A
user with flaky uploads must not run out of captures without ever starting a
second one. The transaction already distinguishes a first claim from a replay,
so the distinction costs nothing.

**Ordering the two checks matters.** If the mint quota were charged first, a
user at the capture cap would lose a mint allowance for every refusal —
paying twice for one "no". The capture cap runs first and returns before
anything is charged or claimed.

**Sizing 12.** A person scanning a whole home does perhaps 8–10 rooms in a
sitting; 12 leaves headroom for re-scans without ever touching real use. The
heaviest observed developer day (RP-8) was 4 captures plus the spike. At the
worst-case ~4 rounds per capture it bounds one account near 43,000 GPU-s/day —
more than the entire measured month, which is the honest way to read it: this
is a runaway/hostile-client bound, not a fair-use budget. It is env-tunable
precisely so it can be tightened once real users produce a distribution.

## Known residue

- **Operator re-drives are not charged.** `tools/reenqueue_scene.py` bypasses
  ingest and the mint entirely. That is correct — they are operator cost, not
  user cost — but it means the ceiling does not bound *total* project spend,
  only per-user spend. The 4-round driver cap is the only thing bounding a
  re-drive loop.
- **The deployed iOS build treats a 429 as terminal** (`unexpectedStatus`, no
  retry — 0038's Retry-After branch is still an iOS follow-up). A user hitting
  the capture ceiling therefore sees an upload failure rather than "try again
  tomorrow". At 12/day that should not happen in real use, but the copy is
  wrong when it does.
- **Cloud Tasks retries of an admitted capture are unbounded by this.** The
  ceiling bounds how many captures start, not how many times one is retried.

## What would change this decision

- **Real usage data.** The first non-developer users will produce a captures-
  per-day distribution; size the cap from its tail rather than from this
  estimate.
- **The per-object cost moving.** 61.9 s/object is a SAM-3D-on-L4 number. A
  faster model or a bigger GPU changes the per-capture figure and therefore
  what a given cap costs — re-measure with the same log query rather than
  scaling the old number.
- **A billing alert or budget cap making this redundant at the project level.**
  It would not: a project cap protects the operator, this protects against one
  account monopolising the queue. Both are wanted.
- **Ingest-side enforcement becoming cheap.** If a `failed_quota` SceneStatus
  is added for another reason, moving the ceiling there would additionally
  bound Cloud-Tasks-driven retries.
