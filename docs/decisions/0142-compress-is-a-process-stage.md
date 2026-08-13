# 0142 — /compress is a stage on perception-obj, not a sidecar service

**Date:** 2026-08-09
**Status:** Decided

## Context

Decision 0125 established that the compressed splat tier is a transcode rather
than a re-bake, and 0126 put the `.spz` beside the `.ply` with a
`compressed.json` index. That left the existing rooms convertible by an
operator tool — but it did not answer where compression runs for a capture that
has not happened yet. Without an answer, every new capture is born slow and
waits for someone to remember to sweep it.

## What we tried

Three placements were considered for the work.

A **sidecar service** dedicated to transcoding. Priced honestly, it needs its
own Cloud Run service, runtime service account, IAM grant set, cloudbuild
config, container smoke, and a runbook phase — for a job measured at 1.2 s per
splat.

A **sweep** as the primary path: keep the operator tool and run it periodically
over the bucket.

A **third stage on perception-obj**, beside `/process` and `/shell`.

## What we chose

A third stage: `/compress`, fired the same way `/shell` is, reusing
perception-obj's existing Cloud Tasks queue and invoker service account for
zero new IAM. It carries its own OIDC audience (`RECEIVER_URL + "/compress"`),
so a `/process` or `/shell` token will not open it.

The encode itself does not live in Python. It sits in `tools/spz_encode.mjs`,
which the operator tool imports: Python owns GCS and the index, Node owns
bytes-in and bytes-out, and nothing authenticates twice.

The sweep survives as what it already was — the backfill path for rooms
captured before this existed.

## Why

`/shell` had already proved the pattern: a derived-asset stage can ride this
service without touching a model, and it inherits the queue, the invoker
identity, and the deploy path that already exist. Against that, a sidecar's
entire cost is fixed overhead purchased for a second of work.

The sweep was rejected as the primary path for a product reason rather than a
technical one: it does not fix born-slow for the person who just captured. That
person is the one waiting.

**One encoder, not two.** Decision 0126 made the encoder Spark's own
`SpzWriter` precisely so it could not drift from the browser's decoder. The
same argument applies writer-to-writer: a second encoder written for the server
path would be a second thing that can drift, and the drift would be silent
until a room failed to render. Sharing `spz_encode.mjs` between the server
stage and the operator tool means there is exactly one implementation of the
bytes.

Every failure path ends at the same place — no compressed tier for that splat —
and the PLY is always signed, so a missing `.spz` degrades to the behaviour
that shipped before this existed.

Measured: the refactored tool reproduces 0125's numbers against the live bucket
(275.8 MB → 47.2 MB, 5.84×, with "10 already current" on a second run), and a
real 34 MB splat encodes at 5.86× in 1.2 s, byte-deterministic.

One finding is recorded because it was found by running the thing rather than
by reading it: **Spark logs to stdout.** The Python caller parses that stdout
as JSON, so the log lines would have corrupted the parse. Anything else layered
onto this path has to keep stdout clean.

## What would change this decision

If compression ever stops being cheap — a format needing real computation, or a
per-object encode that runs in minutes rather than seconds — the fixed overhead
of a dedicated service stops being the dominant cost and the sidecar becomes
worth revisiting.

If a second consumer outside perception ever needs to transcode, the encoder's
home should be reconsidered before it is imported from a third place.
