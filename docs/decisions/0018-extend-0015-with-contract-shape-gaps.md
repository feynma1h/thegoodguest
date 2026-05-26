# 0018 — Extend decision 0015 with contract-shape gaps (F1/F2/F3)

**Date:** 2026-05-26
**Status:** Accepted

## Context

Decision 0015 enumerated three pre-launch gaps in the upload path (TOCTOU on `bundle_id`
ownership, no per-UID rate limit, `expected_size_bytes` optional) and deferred all three
until v1 launch. The decision explicitly anticipated extension: "The deploy surfaces a fourth
gap of the same shape, at which point the set's worth closing as one piece of work rather
than continuing to accumulate." Pass 3 recon on `/upload_session` surfaced three more gaps
that fit the same defer-until-launch pattern but are different in kind from the original
three.

## What we tried

Considered closing F1/F2/F3 inside pass 3 of the smoke tool scoping. Rejected: pass 3's job
is to scope a client tool against the contract as it exists; modifying the contract is a
different workstream that would have expanded scope in the wrong direction.

Considered ad-hoc TODOs in the relevant handler and schema files. Rejected for the same
reason 0015 rejected them: three forgotten TODOs instead of one coherent decision, with no
explicit un-defer triggers.

Considered writing separate decisions for the two gap categories (0018-abuse-surface,
0019-contract-shape). Rejected: both categories close in the same launch-hardening pass, and
splitting them into separate decisions fragments what should be one piece of work. The
categorization is important but belongs inside one decision, not two.

## What we chose

Extend 0015 to cover all six gaps, with explicit categorization:

**Abuse-surface gaps (original 0015 set):**
- TOCTOU on `bundle_id` ownership in `/upload_session` — second call from same UID with
  different manifest overwrites `session_entries` non-atomically.
- No per-UID rate limit on `/upload_session`.
- `expected_size_bytes` optional with default 0; interaction: enables uncapped-size upload
  via cycled anonymous UIDs.

**Contract-shape gaps (new from pass 3 recon):**
- F1: `expires_at` not surfaced in `/upload_session` response. iOS clients can't know when
  a minted URI expires without hardcoding the 7-day GCS implementation detail.
- F2: `X-Upload-Content-Type` hardcoded server-side to `application/octet-stream`. Breaks
  AR Quick Look for USDZ files served by the web app, breaks browser-inline JPEG rendering,
  breaks correct CDN headers.
- F3: No semantic manifest validation at `/upload_session`. Server mints URIs for paths that
  contradict tier (depth paths on `ARKIT_ONLY` tier), unknown extensions, missing
  `bundle.pb`.

The two categories have different un-defer triggers:

- **Abuse-surface trigger:** first non-developer user (friends-and-family testing, internal
  demo with external attendees, public signups).
- **Contract-shape trigger:** iOS development starts in earnest, or web app build begins.

Both categories close in the same launch-hardening pass; the categorization determines what
would force individual gaps to un-defer early.

## Why

The set framing matters more with six gaps than with three. Without explicit categorization,
abuse-surface and contract-shape concerns get conflated, and the un-defer triggers for one
category get applied incorrectly to the other. Concretely: F2 (content_type) shouldn't wait
for "first non-developer user" because the trigger is web-app blob serving, not user abuse.
Conversely, the rate limit shouldn't be pulled forward when iOS development starts because
the trigger is real traffic, not iOS wire shape.

Keeping all six in one decision preserves the original 0015 framing's value — one decision
to close one piece of work — while making the un-defer logic legible. Splitting across two
decisions would mean two separate places to update when the hardening pass begins.

## What would change this decision

- A seventh gap of either flavor surfaces. Same closure-as-set logic applies; extend the
  relevant category here.
- An individual gap turns out to have a forcing function not anticipated here — e.g. F3
  catches a real bug during development. At that point the single gap pulls forward and the
  others stay deferred; that's the expected behavior of the categorization, not a revision
  to this decision.
- The two categories diverge in timing — iOS development starts but launch is still distant,
  so contract-shape closes while abuse-surface stays deferred. This exercises the
  categorization as designed; it doesn't change the decision.
