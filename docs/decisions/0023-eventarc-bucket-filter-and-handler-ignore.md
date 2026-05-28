# 0023 — Eventarc trigger uses bucket-level filter + handler-side `bundle.pb` check (addendum to 0014)

**Date:** 2026-05-27
**Status:** Accepted

## Context

Decision 0014 specified the ingest trigger as "Eventarc trigger on
`google.cloud.storage.object.v1.finalized` for `captures/*/bundle.pb`." That spec wording
assumes Eventarc can filter object events by a path suffix pattern. It cannot, for this
trigger type.

GCS Eventarc's `object.v1.finalized` trigger type supports `bucket=` filters only; the
`match-path-pattern` operator on `resourceName` works exclusively on Cloud Audit Log
triggers (`google.cloud.audit.log.v1.written`), not on direct GCS object events. Suffix
matching on `bundle.pb` is not expressible at the trigger.

The current implementation creates a bucket-wide trigger on `roomstudio-captures` and
routes every finalize event to `/ingest/eventarc`, which currently 400s on non-`bundle.pb`
paths. Pub/Sub interprets 400 as delivery failure and retries with exponential backoff,
producing a redelivery loop on every pixel-blob upload. Surfaced as v2 PR finding #17
during runbook recon.

## What we tried

**Option 1 — switch trigger to Audit Log type with `match-path-pattern`.** Filter precisely
on `captures/*/bundle.pb` at the trigger. Costs: requires Data Access audit logs enabled for
GCS write methods (billable, scales with pixel-blob write volume — the wrong axis); Audit Log
events have higher delivery latency than direct GCS events, which spends the latency budget
that decision 0014's experience constraint (phone-in-pocket → notification arrives)
explicitly protects.

**Option 2 — bucket-level filter + handler-side `bundle.pb` check returning 200 on
non-match.** Trigger filters on `bucket=roomstudio-captures` only. Handler reads
`objectName` from the CloudEvent; if it doesn't match `captures/*/bundle.pb`, returns 200
with a structured ignore-log instead of 400. Pub/Sub sees 200 and stops retrying. Cost:
bucket-wide Cloud Run invocations on every pixel-blob finalize, each ~microseconds (one path
check, no I/O).

**Option 3 — hybrid future: keep Option 2; tighten trigger if Eventarc adds suffix matching
to direct GCS triggers later.** Not selectable today; named as the un-change path.

## What we chose

Option 2. The contract splits across two layers:

- **Trigger layer:** `gcloud eventarc triggers create captures-bundle-pb-finalized` with
  `--event-filters="type=google.cloud.storage.object.v1.finalized"` and
  `--event-filters="bucket=roomstudio-captures"`. No path filter.
- **Handler layer:** `/ingest/eventarc` checks `objectName` matches
  `captures/{bundle_id}/bundle.pb`. On match: proceed with existing ingest logic. On
  non-match: return 200 with structured INFO log `event=eventarc_ignored, object_name=…,
  reason=not_bundle_pb`. The non-match log is observable via log query if filter behavior
  needs auditing.

The 200-on-non-match is the load-bearing change: it converts "filter mismatch" from a
Pub/Sub-visible failure into a successful acknowledgment of an event with no work to do.

## Why

The 0014 spec's intent (`/ingest/eventarc` fires only on `bundle.pb` finalize) is preserved;
the filter mechanism is split because GCS Eventarc's filter language can't express it in one
layer. Routing via Audit Log triggers to express the filter purely at the trigger would trade
the latency budget protecting the experience constraint against a cost (handler-side path
check) that's effectively free. The latency budget is more valuable than the
filter-architecture preference.

Returning 400 on non-match was the original handler shape because non-`bundle.pb` paths
arriving at this endpoint look like a contract violation. With the bucket-wide trigger, they
aren't a violation — they're the expected steady-state traffic given the platform's filter
limitations. 200 is the contract-correct response: "received, no work, acknowledged."

## What would change this decision

- GCS Eventarc adds suffix or glob matching to `object.v1.finalized` triggers. Trigger
  tightens to `captures/*/bundle.pb`; handler check becomes belt-and-suspenders, kept for
  defense in depth.
- Cloud Audit Log trigger latency or pricing changes such that the Option 1 tradeoff
  inverts. Reconsider trigger type then.
- A second object kind in `roomstudio-captures` becomes meaningful to `/ingest/eventarc`
  (unlikely given the bundle.pb-last sequencing in 0014). Handler grows a dispatch table;
  trigger stays bucket-wide.
- Bucket-wide invocation cost stops being negligible (e.g. a future capture flow uploads
  thousands of small blobs per bundle and the per-invocation overhead aggregates). At that
  point the right move is probably tightening the trigger if Eventarc has gained the
  capability by then, or accepting Option 1's tradeoff if it hasn't.
