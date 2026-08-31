# 0018 — Extend decision 0015 with contract-shape and production-hygiene gaps

**Date:** 2026-05-26
**Status:** Spent
**Amended:** 2026-05-27 to add F5/F6 and the perception-obj SA audit item.

## Context

Decision 0015 enumerated three pre-launch gaps in the upload path (TOCTOU on `bundle_id`
ownership, no per-UID rate limit, `expected_size_bytes` optional) and deferred all three
until v1 launch. The decision explicitly anticipated extension: "The deploy surfaces a fourth
gap of the same shape, at which point the set's worth closing as one piece of work rather
than continuing to accumulate." Pass 3 recon on `/upload_session` surfaced three more gaps
(F1/F2/F3) that fit the same defer-until-launch pattern but are different in kind from the
original three; pass 4 added F4. The 2026-05-27 amendment adds two production-hygiene gaps
(F5/F6) surfaced during smoke-tool pass 5 recon, and one audit item around the perception-obj
runtime service account identity and storage IAM, both deferred to the same launch-hardening
pass.

## What we tried

Considered closing F1/F2/F3 inside pass 3 of the smoke tool scoping. Rejected: pass 3's job
is to scope a client tool against the contract as it exists; modifying the contract is a
different workstream that would have expanded scope in the wrong direction.

Considered ad-hoc TODOs in the relevant handler and schema files. Rejected for the same
reason 0015 rejected them: three forgotten TODOs instead of one coherent decision, with no
explicit un-defer triggers.

Considered writing separate decisions for the gap categories. Rejected: all categories close
in the same launch-hardening pass, and splitting them into separate decisions fragments what
should be one piece of work. The categorization is important but belongs inside one decision,
not three.

## What we chose

Extend 0015 to cover all nine gaps plus one audit item, with explicit categorization across
three categories:

**Abuse-surface gaps (original 0015 set):**
- TOCTOU on `bundle_id` ownership in `/upload_session` — second call from same UID with
  different manifest overwrites `session_entries` non-atomically.
- No per-UID rate limit on `/upload_session`.
- `expected_size_bytes` optional with default 0; interaction: enables uncapped-size upload
  via cycled anonymous UIDs.

**Contract-shape gaps (from pass 3 + pass 4 recon):**
- F1: `expires_at` not surfaced in `/upload_session` response. iOS clients can't know when
  a minted URI expires without hardcoding the 7-day GCS implementation detail.
- F2: `X-Upload-Content-Type` hardcoded server-side to `application/octet-stream`. Breaks
  AR Quick Look for USDZ files served by the web app, breaks browser-inline JPEG rendering,
  breaks correct CDN headers.
- F3: No semantic manifest validation at `/upload_session`. Server mints URIs for paths that
  contradict tier (depth paths on `ARKIT_ONLY` tier), unknown extensions, missing
  `bundle.pb`.
- F4: `result_url` presigning in scene read responses. `GET /scenes/by-bundle/{bundle_id}`
  on api-public returns `result_uri` as a raw `gs://` URI today (per decision 0019). The
  web app and any browser-based consumer cannot fetch `gs://` URIs directly; each consumer
  would need GCS read credentials and presigning logic. Fix: api-public presigns
  server-side, returns `result_url` (HTTPS) and `expires_at` alongside the raw `result_uri`,
  requires api-public's service account to have `storage.objects.get` on the results bucket.
  Naming convention (`_uri` for raw resource identifiers, `_url` for fetchable HTTPS URLs)
  is pinned in 0019 so this addition is non-breaking.

**Production-hygiene gaps (from pass 5 recon):**
- F5: No object lifecycle rule on `gs://roomstudio-perception-outputs/scenes/`. Perception
  outputs accumulate indefinitely. Fix: add a GCS lifecycle rule to delete objects under
  `scenes/` after a retention window appropriate for active scenes (e.g. 30d). Coordinate
  with scenes TTL so documents and blobs expire together.
- F6: No TTL on Firestore `scenes` collection. Scene documents accumulate indefinitely. Fix:
  add a Firestore TTL policy on `scenes` (field: `expires_at`, populated at scene creation).
  Coordinate with F5.

**Audit items (during launch hardening):**
- Verify that the perception-obj Cloud Run service runs under the correct runtime service
  account and that its storage IAM grants are scoped to the intended buckets with minimum
  necessary permissions. The SA identity and exact IAM bindings have not been audited since
  the perception-obj deployment; verify before admitting real user data.

The three categories have different un-defer triggers:

- **Abuse-surface trigger:** first non-developer user (friends-and-family testing, internal
  demo with external attendees, public signups).
- **Contract-shape trigger:** iOS development starts in earnest, or web app build begins.
- **Production-hygiene + audit trigger:** launch hardening (same pass as above, but can
  proceed earlier if developer-accumulation becomes a practical problem).

All categories close in the same launch-hardening pass; the categorization determines what
would force individual gaps to un-defer early.

## Why

The set framing matters more with nine gaps than with three. Without explicit categorization,
abuse-surface, contract-shape, and production-hygiene concerns get conflated, and the
un-defer triggers for one category get applied incorrectly to another. Concretely: F2
(content_type) shouldn't wait for "first non-developer user" because the trigger is web-app
blob serving, not user abuse. The rate limit shouldn't be pulled forward when iOS development
starts because the trigger is real traffic, not iOS wire shape. F5/F6 and the SA audit
shouldn't block iOS development but also shouldn't slip past launch.

Keeping all nine in one decision preserves the original 0015 framing's value — one decision
to close one piece of work — while making the un-defer logic legible. Splitting across three
decisions would mean three separate places to update when the hardening pass begins.

The four contract-shape gaps share a common pattern: each is a case where the contract
exposes an implementation detail (raw GCS URIs, hardcoded MIME types, missing expiry
metadata, unvalidated paths) that every consumer would otherwise have to work around
independently. Closing them server-side, once, is strictly better than closing them N times
in each consumer.

The two production-hygiene gaps and the SA audit item are separated from the contract-shape
set because their trigger is launch readiness, not consumer correctness. A developer running
the smoke tool 50 times is annoyed by accumulating Firestore documents; a user is not. The
distinction keeps the launch-hardening checklist honest about what has to close before public
traffic versus what is nice to have sooner.

## What would change this decision

- A tenth gap of any flavor surfaces. Same closure-as-set logic applies; extend the relevant
  category here.
- An individual gap turns out to have a forcing function not anticipated here — e.g. F3
  catches a real bug during development. At that point the single gap pulls forward and the
  others stay deferred; that's the expected behavior of the categorization, not a revision
  to this decision.
- The three categories diverge in timing — iOS development starts but launch is still
  distant, so contract-shape closes while abuse-surface stays deferred, and production-hygiene
  stays deferred longer still. This exercises the categorization as designed; it doesn't
  change the decision.
- F5 and F6 turn out to be urgent before launch (e.g. developer accumulation becomes large
  enough to cause quota or cost problems). At that point they pull forward without changing
  the decision structure.
