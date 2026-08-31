# 0017 — Smoke tool: manifest derivation and upload contract (pass 3)

**Date:** 2026-05-26
**Status:** Decided

## Context

`tools/upload_test_bundle.py` is the substitute iOS client for end-to-end testing the
two-service upload path (see decision 0016). Pass 3 of the scoping work pins how the smoke
tool constructs the `/upload_session` manifest, sequences uploads, and maps responses. Recon
from a prior Code session established the current `/upload_session` contract: flat list of
`{relative_path, expected_size_bytes}` entries, response is a flat list of
`{relative_path, session_uri}` mapped by path, `bundle.pb` is one ordinary manifest entry,
server doesn't enforce upload ordering. Three contract-shape gaps surfaced (F1/F2/F3) and
are deferred to decision 0015's extension (see 0018); this decision is scoped strictly to
the smoke tool against the contract as it currently exists.

## What we tried

Four passes of scope evaluation. Pass 1 deferred everything to launch hardening. Pass 2
pulled `content_type` and `expires_at` forward into pass 3 under an "executable
specification" framing — the smoke tool as the iOS engineer's wire-format reference. Pass 3
sharpened `content_type` toward server-side derivation via canonical extension map. Pass 4
cut both pulls back out: the executable-specification frame holds for request construction
(the iOS engineer copying the wire shape and field names) but overextends to response
handling and to server-side schema decisions that belong in the hardening pass where the
contract itself changes. The bias across passes 1–3 was monotonic scope growth under
"long-term thinking"; pass 4 applied a counter-test ("would a reviewer ask why this is in
this PR") and subtracted.

Considered `asyncio` for the parallel-upload phase. Initially framed as 50/50 with
iOS-shape-fidelity as the tiebreaker — `URLSession` background tasks look like `asyncio`
coroutines. Reconsidered: `URLSession` background tasks are OS-managed, not
Python-async-managed, so the fidelity argument was illusory. Threads win on codebase
consistency (`requests`-based `AuthorizedSession` is already the idiom) with no real
counterweight.

## What we chose

Six locked bullets for pass 3, scoped strictly to the smoke tool:

1. **Manifest derivation.** Iterate `TestBundleArtifacts.blobs` in sorted-path order; emit
   `{"relative_path": path, "expected_size_bytes": len(bytes)}` per entry; append
   `{"relative_path": "bundle.pb", "expected_size_bytes": len(bundle_bytes)}` last. Real
   sizes always — never 0 or omitted.

2. **Wire shape.** `POST /captures/{bundle_id}/upload_session` with
   `Authorization: Bearer <firebase_id_token>`, body `{"manifest": [...], "fcm_token": null}`.
   Response is a flat list of `{relative_path, session_uri}`.

3. **Upload sequencing.** Two hard-separated phases. Phase 1 uploads non-`bundle.pb` blobs
   via `ThreadPoolExecutor(max_workers=8)`. Phase 2 uploads `bundle.pb` only after all
   Phase 1 uploads return 200 or 201. Phase 1 failure aborts before Phase 2 begins.

4. **PUT headers.** `Content-Length: <size>` and `Content-Range: bytes 0-<size-1>/<size>`.
   No client-set `Content-Type` header — the server's `X-Upload-Content-Type` (set when the
   resumable URI was minted) controls content type. Accept 200 or 201; treat 308 explicitly
   as an error (308 signals an incomplete resumable upload, which the smoke tool doesn't
   support).

5. **Response mapping.** Map response entries by `relative_path`. Assert that the response
   path set exactly equals the request path set; any mismatch is exit code 1.

6. **Bundle ID.** Fresh UUIDv4 `bundle_id` per invocation, logged at tool startup. No
   `--bundle-id` override flag. Combined with `--reuse-uid` (stable Firebase UID across
   runs), this gives clean run isolation while preserving UID stability for Firestore
   debugging.

## Why

The smoke tool is the executable specification for request construction — the iOS engineer
writing `URLSession` will copy the wire shape, field names, and derivation logic. That
argument is load-bearing for bullet 1 (real sizes always, not 0 or omitted) and motivates
the strict response-set assertion in bullet 5. It does not extend to server-side schema
decisions (`content_type` derivation, `expires_at` surfacing, semantic manifest validation),
which belong in the hardening pass where the contract itself changes.

Two-phase sequencing with `bundle.pb` last (bullet 3) is the structural property decision
0014 designed against the race condition: `bundle.pb` finalize triggers Eventarc, so all
referenced blobs must already exist in GCS. Enforcing this client-side, even though the
server doesn't require it, means the smoke tool never produces an upload ordering that
exposes the latent server-side gap.

Threads over `asyncio` (bullet 3): the `URLSession` background-task analogy is an iOS-side
concern that doesn't translate to the smoke tool's process model. Codebase consistency
(the server uses `AuthorizedSession`) wins on the merits.

Fresh `bundle_id` per invocation (bullet 6): avoids the F5 idempotency-vs-size interaction
— path-set idempotency means a second call with the same paths and different sizes returns
stale URIs minted against the original size constraints.

## What would change this decision

- The contract changes (F1/F2/F3 close, or 0015's third gap closes by making
  `expected_size_bytes` required at the schema layer). Pass 3 was written against the
  contract as-is; if the contract changes, manifest derivation and response handling need
  a corresponding update.
- The smoke tool grows beyond its current four modes. The current scope assumes
  single-bundle, single-upload-attempt runs; multi-bundle or retry-loop semantics would
  change the bundle_id strategy.
- `asyncio` becomes the codebase idiom elsewhere (unlikely in the near term). Threads were
  chosen for codebase consistency, not on intrinsic merit; if the idiom flips, so does this
  choice.
