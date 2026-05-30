# 0031 — schema_version string: "1.0.0" → "1"

**Date:** 2026-05-30
**Status:** Decided

## Context

The capture bundle proto uses a `schema_version` string field. The backend
rejects bundles with unknown versions (decided in 0030 and board item 2).
When the ingest validation gate shipped (0027 era), `SCHEMA_VERSION` was set
to `"1.0.0"` and `SUPPORTED_VERSIONS` accepted `{"1.0.0"}`. Decision 0030
and CLAUDE.md board item 2 both specified the canonical value as `"1"` —
a discrepancy that needed resolving before iOS P2 serializes its first real
`bundle.pb`.

## What we tried

No alternatives explored. `"1.0.0"` vs `"1"` is not a tradeoff; it is a
correctness question about what the version field is supposed to mean.

## What we chose

Standardize on `"1"`. `SCHEMA_VERSION` in `packages/schemas/roomstudio_schemas/__init__.py`
and `SUPPORTED_VERSIONS` in `services/api-internal/validation.py` both set to
`"1"`. `"1.0.0"` is not carried in the accepted set.

One commit, writer and reader together: `SCHEMA_VERSION` is imported by every
fixture and emitter (`build_capture_bundle()`, `tools/build_test_bundle.py`,
`test_ingest.py`, `test_ingest_eventarc.py`, `test_process_receiver.py`), so
all update automatically from the single constant change.

Handler ordering confirmed correct: `_check_schema_version` runs as check 1
inside `validate_bundle` (step 3 in `_run_ingest`), before the image-blob
decodability check (step 5b). No reordering needed.

## Why

The `schema_version` contract is exact-match with monotonic bumps on breaking
changes, not semver. Semver (`"1.0.0"`) advertises a sub-version compatibility
structure — patch and minor ranges — that this contract does not have. The
backend accepts or rejects a version string exactly; there is no "accept
1.x.x" logic and no plans for any. `"1"` is an honest representation: the
version is a named contract revision, not a version triplet.

Additionally, 0030 and CLAUDE.md board item 2 stated "no enforcing check
exists in the ingest handler today," but `_check_schema_version` was already
live when those notes were written (it shipped with the validation gate,
0027 era). The P2 gate work was a value fix (`"1.0.0"` → `"1"`), not a
greenfield implementation. Board item 2 is satisfied by this commit.

## Addendum — schema rejection behavior (same session)

After behavior-verification, a second divergence from 0030 was found: the
schema rejection path returned HTTP 400 with no Scene record. Decision 0030's
binding rule requires `failed_invalid` Scene + structured log; the
implementation did neither.

**Why this matters (two load-bearing reasons):**

1. The iOS client never calls `/ingest` directly — it uploads to GCS and polls
   `GET /scenes/by-bundle/{bundle_id}`. Without a Scene, the client polls into
   the void with no terminal state.

2. On the Eventarc path, a non-2xx triggers Pub/Sub redelivery. At the first
   real schema bump (backend "2", old clients "1"), every stale client's bundle
   would trigger an infinite retry loop with no Scene written.

**Fix:** `_run_ingest`'s schema rejection block (step 3) now mirrors the
image-decode rejection block (step 5b): calls `_handle_failed_invalid` + returns
HTTP 200. `_handle_failed_invalid` gained `rejection_kind` / `rejection_detail`
parameters so schema rejection emits a distinct structured log line:

    Scene X failed_invalid: bundle_id=Y reason=unsupported_schema_version detail=...

This is the only operator-visible discriminator between schema and image-decode
rejections (both share `failed_invalid`; no new `SceneStatus` enum per
decisions 0027/0030).

Fallback to HTTP 400 only when no pollable Scene is possible: no `bundle_id`
extractable from the GCS URI, or the bundle carries no device identity.

**Live-verified (2026-05-30, `api-internal-00013-qeg`):**
- `"1.0.0"` bundle uploaded to GCS → Eventarc fires → Scene `efc7aa03` in
  Firestore with `status=failed_invalid`, `last_error="unsupported_schema_version: ..."`
- Cloud Logging entry:
  `Scene efc7aa03 failed_invalid: bundle_id=bf50b7d3 reason=unsupported_schema_version detail=...`
- HTTP 200 returned → Pub/Sub acknowledged, no retry.

## What would change this decision

If the version scheme ever evolves to carry minor/patch semantics (e.g. a
"1.1" that is backward-compatible with "1"), the accepted-set logic would
need updating and the version string convention would need re-specifying.
That would be a new decision note, not a revision of this one.
