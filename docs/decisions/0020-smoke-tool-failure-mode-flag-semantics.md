# 0020 — Smoke tool: failure-mode flag semantics (pass 5)

**Date:** 2026-05-27
**Status:** Accepted

## Context

`tools/upload_test_bundle.py` is the substitute iOS client for end-to-end testing the
two-service upload path (decision 0016). Pass 5 of the scoping work pins how each of
the four CLI modes triggers its scenario, plus the cross-cutting flags (`--cleanup`,
`--verbose`, `--json`, exit code 2). Decision 0017 pinned the upload contract; 0019
pinned the read contract and the mode-to-terminal mapping. This decision is the last
scoping pass before implementation begins.

The recon for this pass established the GCS artifact layout: captures live in
`gs://roomstudio-captures/captures/{bundle_id}/` with a 24h lifecycle; perception outputs
live in `gs://roomstudio-perception-outputs/scenes/{scene_id}/` with no lifecycle rule.
Firestore `upload_sessions` has a 7d TTL; `scenes` has none. IAM splits asymmetrically:
api-public can delete from captures but not from outputs; api-internal cannot delete from
either; developer ADC can delete from both buckets and both collections.

## What we tried

**auth-rejection — four token variants.** No-header (header-presence branch), malformed
structure (JWT parse branch), wrong signature (signature branch), wrong-project
(audience/issuer branch). Considered a sub-variant flag (`--auth-rejection-mode`) to test
all four; rejected as scope creep dressed as forward thinking. The verifier branches are
already covered by api-public's unit tests; the smoke tool's job is wire-contract
verification of a realistic iOS failure mode, not verifier-branch coverage.

**duplicate-event — re-upload timing.** Three candidate windows: during `queued` (Cloud
Tasks dedupe tested), during `processing` (lease interaction tested), after `ready`
(terminal idempotency tested). The during-`processing` case is the most product-meaningful
(highest-risk surface, modal redelivery scenario in production once perception-obj is slow)
but requires racing a window we can't predict the size of without perception-obj runtime
data. After-`ready` is deterministic.

**`--cleanup` — uniform vs. per-mode, and API-mediated vs. direct.** Considered making
cleanup mode-specific (happy-path keeps results, skip-blob removes partial uploads, etc.);
rejected because the artifacts created vary by mode but the cleanup mechanism doesn't.
Considered routing cleanup through an api-public endpoint to keep credentials out of the
smoke tool; rejected because api-public lacks delete IAM on the outputs bucket and
api-internal cannot delete from either bucket. Cleanup has to run as developer ADC against
GCS and Firestore SDKs directly.

**`--cleanup` — should it exist at all.** Considered deferring `--cleanup` entirely on the
grounds that the real fix is launch-hardening gaps F5 (perception-outputs lifecycle) and F6
(scenes TTL) plus the perception-obj SA audit. Rejected because (a) those gaps close on the
launch trigger, not the iOS-development trigger, and (b) repeated developer runs during iOS
contract debugging produce real accumulation that's worth addressing now even if the
production-hygiene story is incomplete.

## What we chose

Seven locked items. Implementation begins after this decision.

1. **`happy-path`.** No edge cases. Use passes 3+4 contracts end-to-end. `--tier` and
   `--frame-count` parameterize the bundle; manifest derivation falls out of
   `TestBundleArtifacts.blobs`.

2. **`skip-blob`.** The dropped blob is included in the manifest sent to `/upload_session`,
   never PUT to its session URI. `bundle.pb` still references the dropped path in its frame
   fields. Tests the ingester's `_check_bundle_blobs_exist()` branch. `--drop-blob-kind`
   cross-validated against `--tier` (exit 2 on `depth`/`confidence` with `arkit-only`; on
   `usdz` with anything but `lidar-roomplan`). Mode requires `--drop-blob-kind` (exit 2
   otherwise).

3. **`duplicate-event`.** Re-upload `bundle.pb` to its GCS path via `google-cloud-storage`
   SDK after first reaching `ready`. Wait 15s for Eventarc redelivery (matching the 0019
   stall-detection threshold), poll again. Assert `scene_id` unchanged and `status == ready`
   on second poll. The during-processing variant is named as a deferred future mode
   (`duplicate-event-during-processing`); un-defer trigger is "we have perception-obj runtime
   data and can size the race window."

4. **`auth-rejection`.** Omit the `Authorization` header entirely. Skip Firebase sign-in.
   POST `/upload_session` with a minimal manifest. Assert 401 `missing_token`. Exit 0 on
   that exact shape; exit 1 on anything else. Never reaches Phase 1, Phase 2, or polling.

5. **`--cleanup`.** Uniform across modes, best-effort, four targets via developer ADC:
   - `gs://roomstudio-captures/captures/{bundle_id}/` (list + delete via
     `google-cloud-storage`)
   - `gs://roomstudio-perception-outputs/scenes/{scene_id}/` (same; skipped if `scene_id`
     unknown)
   - Firestore `upload_sessions/{bundle_id}` (delete via `google-cloud-firestore`)
   - Firestore `scenes/{scene_id}` (same; skipped if `scene_id` unknown)

   Each target's deletion failure logs a warning and continues. Cleanup never causes a
   non-zero exit code. Cleanup runs after the run terminates regardless of exit code.
   Absence of `--cleanup` leaves all four behind. `scene_id` is unknown for modes that
   never reach polling (`auth-rejection`) or where polling never returns a document — those
   targets are silently skipped.

6. **`--verbose` and `--json`.** Default: human-readable progress, one line per phase
   transition, final summary block on stdout. `--verbose`: per-request HTTP detail (status,
   latency, response body for non-2xx), full manifest sent and received, `updated_at` on
   each poll, resolved `device_id` and `device_id_source`, blob inventory before upload;
   goes to stderr, default progress stays on stdout. `--json`: NDJSON to stdout, one event
   per line, schema covers `run_start`, `auth_complete`, `bundle_built`,
   `upload_session_response`, `phase_1_complete`, `phase_2_complete`, `poll`,
   `run_complete`. NDJSON over single-final-JSON because runs may take ~2 minutes and
   intermediate events are useful for tailing. `--verbose` and `--json` combine; verbose
   adds detail fields to each NDJSON event.

7. **Exit code 2 (tool misconfig).** Distinct from exit 1 (system under test misbehaved).
   Cases: required flag missing with no env-var fallback; `--reuse-uid` cache file missing
   or malformed; `--public-url`/`--internal-url` not resolvable; `--drop-blob-kind`
   incompatible with `--tier`; mode `skip-blob` without `--drop-blob-kind`;
   `--frame-count < 1`; Firebase API key rejected during anonymous sign-in. Distinguishing
   test: "would changing the system under test fix this?" No → exit 2.

## Why

Three load-bearing arguments.

First, the smoke tool is the executable specification for wire-contract behavior, not a
unit-test substitute. The `auth-rejection` mode's job is "prove the auth boundary is
enforced at the wire," not "exercise every branch of `verify_id_token`." No-header tests a
realistic iOS failure mode (forgetting to attach the token) and produces a deterministic
wire response (`401 missing_token`) without requiring synthetic key material or a second
Firebase project. Verifier-branch coverage belongs in api-public's unit tests, which
already exist.

Second, deterministic over racy when the racy variant tests something that needs separate
scoping anyway. The during-processing duplicate-event variant tests lease interaction, which
is the riskier surface, but sizing the polling race window without perception-obj runtime
data would produce a flaky test. Naming the deferred mode with an explicit un-defer trigger
("we have perception-obj runtime data") follows the 0015/0018 pattern: name the deferred
work, give it a trigger, don't accumulate TODOs.

Third, `--cleanup` belongs in the smoke tool only because the production hygiene gaps that
would otherwise handle it (F5 perception-outputs lifecycle, F6 scenes TTL) are themselves
deferred to launch. The two concerns have different triggers: cleanup matters for iOS
development (now); production hygiene matters for launch (later). Conflating them would
either over-build the smoke tool (cleanup mechanisms designed for production scale) or
under-build production hygiene (relying on developer-tool cleanup for production load).
Keeping them separate, with the production gaps tracked in 0018's extended set, makes the
work legible at both phases.

The accepted cost is that `--cleanup` reaches into Firestore and the outputs bucket
directly, bypassing the API surface. This is honest about what's currently possible given
IAM — api-public lacks delete on outputs, api-internal lacks delete on either bucket, and
bolting a cleanup endpoint onto api-public would require IAM changes that aren't justified
by smoke-tool needs alone. Once the production hygiene work lands, `--cleanup`'s scope
shrinks to "accelerate what would have happened anyway via lifecycle rules and TTLs."

## What would change this decision

- Perception-obj runtime data becomes available (typical end-to-end run time is measured):
  the deferred `duplicate-event-during-processing` mode becomes implementable. Adds a new
  top-level mode, doesn't change the existing four.
- F5 (perception-outputs lifecycle rule) lands. `--cleanup`'s outputs-bucket target becomes
  redundant for runs older than the lifecycle window; smoke tool can still keep it for
  immediate cleanup. No code change required.
- F6 (scenes TTL) lands. Same shape as F5 for the scenes Firestore target.
- The deploy runbook (workstream B) adds an api-public cleanup endpoint with appropriate
  IAM. `--cleanup` could route through the API instead of direct SDK calls. Reconsider
  then; the current direct-SDK shape is correct for current IAM.
- A fifth mode is needed (e.g. testing partial Phase 1 failures, multi-bundle batching,
  retry-after-failure). The four-mode CLI surface gains a fifth positional value; the
  pattern is established and additive.
- The smoke tool grows beyond developer use (e.g. runs in CI from a service account, not
  ADC). Direct Firestore and GCS calls would need IAM grants on that service account, which
  would re-open the question of whether cleanup should route through an API endpoint.
