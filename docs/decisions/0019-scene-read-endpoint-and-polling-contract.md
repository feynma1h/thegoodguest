# 0019 — Scene read endpoint and polling contract (smoke tool pass 4)

**Date:** 2026-05-26
**Status:** Decided

## Context

`tools/upload_test_bundle.py` is the substitute iOS client for end-to-end testing the
two-service upload path (decision 0016). Pass 4 of the scoping work pins how the smoke
tool watches scene state after upload completes. The recon (prior Code session) established
that api-public has no read endpoint for scenes today; api-internal exposes only `/ingest`
and `/ingest/eventarc`. Pass 4 therefore covers both the new public endpoint and the smoke
tool's polling logic against it. Decision 0017 pinned the upload-side contract; this
decision pins the read-side contract.

## What we tried

Three options considered for how the smoke tool reads scene state.

**Option A — direct Firestore read via `google-cloud-firestore` with Application Default
Credentials.** Easiest to implement, requires no new endpoint. Bypasses any future Firestore
security rules and doesn't exercise the public surface that other consumers (web app BFF,
operational tooling, possible future Android client) will need.

**Option B — new api-public endpoint; smoke tool polls it with the same Firebase ID token
it used for `/upload_session`.** Mirrors the eventual consumer pattern, exercises the same
auth path other consumers will use, builds public surface that has to exist anyway. Cost:
endpoint implementation, plus an `api-core` repository split.

**Option C — direct Firestore read authenticated with the Firebase ID token via Firestore's
REST API.** Mirrors iOS's eventual auth model without requiring a new endpoint. The endpoint
doesn't get built, so the next consumer that needs read access (web app, ops tooling) has
to build it then.

The initial reflex was Option A on grounds of simplicity, walked back when the consumer set
was honestly enumerated — the smoke tool isn't the only thing that will read scenes through
a non-listener path, and choosing A means deferring an endpoint that has to exist anyway.
The fourth-pass meta-lesson from decision 0017 ("scope-anxiety dressed as architectural
restraint") applies cleanly: the easy answer wasn't the right answer.

Three repository structures considered for sharing scene read logic between api-internal
and api-public: full `SceneRepository` move to api-core (over-shares write capability with
api-public); read/write split with api-internal composing the read repo (looser coupling,
more ceremony); read/write split with api-internal inheriting the read repo (tighter
coupling, less ceremony). Chose inheritance — the read methods are a strict subset of what
the write repo needs and composition would be ceremony for no real isolation benefit.

Considered whether `result_uri` should be presigned to an HTTPS URL in the response.
Concluded the smoke tool doesn't need this and the right home for the work is decision
0018's contract-shape gap set (F4), gated by "web app build begins." Pinned a naming
convention (`_uri` for raw resource identifiers, `_url` for fetchable HTTPS URLs) so the
future addition of `result_url` is non-breaking.

Considered explicit stall detection in the polling loop. Rejected — `--timeout` (default
120s) handles the bound, and adding a separate stall concept is feature creep for a CLI
tool.

## What we chose

Option B with the inheritance-based repository split. Concretely:

1. **`SceneReadRepository` in `packages/api-core/`** — `get(scene_id)` and
   `get_by_bundle_id(bundle_id)`. No write methods.

2. **`SceneRepository` in `services/api-internal/repository.py`** refactored to extend
   `SceneReadRepository`. All existing write methods retained. Construction signature
   unchanged.

3. **`GET /scenes/by-bundle/{bundle_id}` on api-public.** Auth via Firebase ID token in
   `Authorization: Bearer <token>` header, mirroring `/upload_session`. Authorization:
   requesting UID must equal `scene.user_id`. If `scene.user_id is None`, return 403 with
   detail `"scene has no owner"` and emit a server-side warning log — the case shouldn't
   happen in normal operation and is a diagnostic signal when it does.

4. **Response shape — 200:**
   ```json
   {
     "scene_id": "...",
     "bundle_id": "...",
     "status": "...",
     "result_uri": "gs://...",
     "missing_paths": [...],
     "created_at": "...",
     "updated_at": "..."
   }
   ```
   Excluded fields: `last_error` (server-side only); lease machinery (`lease_expires_at`,
   `lease_holder_id`, `shutdown_release_count`); `bundle_uri` (ingest implementation
   detail); `device_id` / `device_id_source` / `user_id` (caller proved ownership);
   `attempt_count` (always 0 in current code; increment logic unimplemented).

5. **Error response shapes** mirror `/upload_session`: 401 `missing_token` /
   `invalid_token`, 403 `forbidden`, 400 `invalid_bundle_id`, 404 `not_found` (new shape;
   this endpoint establishes it).

6. **Scene status is body-only, never mapped to HTTP status codes.** A scene in `failed`
   or `failed_incomplete` returns 200; the consumer reads `status` to act on the failure.
   404 is reserved for "no scene exists for this bundle_id."

7. **Naming convention:** fields ending in `_uri` are raw resource identifiers (likely
   `gs://` paths) that the client probably cannot fetch directly; fields ending in `_url`
   are fetchable HTTPS URLs with a paired `expires_at`. Today the response has `result_uri`
   (raw). When presigning lands (F4 in decision 0018), `result_url` joins as an additional
   field rather than replacing `result_uri`.

8. **Smoke tool polling contract:**
   - Poll at the configured `--poll-interval` (default 2s).
   - 404 is normal for the first ~15s after upload completes (Eventarc delivery latency).
     After 15s, 404 means ingest stalled — exit 1.
   - Status field drives termination. Terminal states: `ready`, `failed`,
     `failed_incomplete`, `failed_invalid`. Transient states: `queued`, `processing`.
   - `--timeout` (default 120s) bounds the whole polling phase. Timeout → exit 3.
   - `updated_at` is surfaced in `--verbose` mode for debugging but does not drive control
     flow. No separate stall detection.

9. **Mode-to-terminal mapping:**
   - `happy-path` — expected: `failed_invalid` (exit 0). The synthetic fixture carries
     non-decodable placeholder pixels; the ingest validation gate fast-fails them to
     `failed_invalid` (~3s). `ready` requires real image data (deferred to iOS client).
     Unexpected: `failed`, `failed_incomplete`, `ready` (exit 1). Timeout: exit 3.
     See docs/decisions/0025.
   - `skip-blob` — expected: `failed_incomplete` with the deliberately-dropped path present
     in `missing_paths` (exit 0). Unexpected: any other terminal, or `missing_paths` not
     containing the dropped path (exit 1). Timeout: exit 3.
   - `duplicate-event` — expected: `failed_invalid` on first pass, then `failed_invalid`
     with the same `scene_id` on second pass (idempotency held; exit 0). Unexpected:
     any other terminal on first pass, or `scene_id` changes on second pass (exit 1).
     Timeout: exit 3.
   - `auth-rejection` — does not reach polling. Fails at `/upload_session` with 401/403
     (exit 0, expected outcome).

## Why

The endpoint is public surface that exists in the system's future regardless of the smoke
tool. The web app's BFF will need server-side scene reads. Operational tooling will need
them. Any future non-iOS client will need them. Building the endpoint now, with the smoke
tool as its first client, follows the same logic as decision 0017's "executable
specification" frame — the contract gets exercised by a real client at the moment it's
defined, which is the cheapest moment to find contract problems.

The repository split via inheritance encodes the service-contract surface in the import
graph. api-public's imports declare that it can only read scenes; api-internal's imports
declare it can read and write. A future maintainer adding an endpoint to api-public cannot
accidentally write to scenes because the methods don't exist on the imported repository.
This is not a security boundary in the trust sense (the security boundary is Firebase ID
token vs OIDC token, enforced elsewhere); it is a discoverability property, which matters
for a system that will have multiple client teams reading the backend code.

The `_uri` vs `_url` naming convention costs nothing today and prevents a breaking change
later. When F4 lands and presigning is added, the response gets a new `result_url` field
with its `expires_at`; the existing `result_uri` field can stay (raw GCS path for ops and
BFF use) or be deprecated when no consumer reads it. Either path is non-breaking.

Defensive 403 on `user_id = None` instead of relying on `None == None` to fail naturally:
the comparison would in fact fail (the requesting UID is a non-empty string), but making
the rejection explicit produces a diagnostic message ("scene has no owner") that surfaces
the bug to ops instead of looking like a generic permission failure.

Status-in-body rather than status-mapped-to-HTTP: a failed scene is a successful retrieval
of a failure state. Conflating transport errors with application state would be a bad
contract idiom for consumers who must distinguish "I couldn't reach the server" from "the
server reached the scene and it's in a failed state."

## What would change this decision

- F4 closes (presigning lands) ahead of schedule. The response shape gains `result_url`
  and `expires_at`. Existing consumers continue to work because the field is additive.
- A second backend service needs scene read access (e.g. the BFF gets its own Cloud Run
  service). `SceneReadRepository` in api-core already supports this; no decision change.
- Scene sharing or admin-read becomes a product requirement. The simple authorization model
  (requesting UID equals `user_id`) is replaced with a richer model. Endpoint shape and
  the 403-on-`user_id=None` defensive case both get revisited.
- The smoke tool grows a mode that needs to inspect more fields than the current response
  exposes. Decision is whether to expand the response (probably right if the field has
  consumer value) or to add an api-internal-only debug endpoint (right if the field is
  server-side-only).
- Firestore security rules get added later and require the smoke tool to authenticate
  Firestore reads directly. Doesn't change this decision — the endpoint stays — but adds a
  parallel direct-read path for tests that need it.
