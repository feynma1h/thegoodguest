# 0038 — /upload_session client retry/backoff policy
Date: 2026-05-31  •  Status: Decided

## Context
The /upload_session call can fail transiently (network, 5xx) or terminally
(auth, client bug, ownership). The client needs a status-code -> action map that
distinguishes retryable from fatal, so it neither gives up on transient failure
nor hammers a fatal one.

## What we chose
Implemented in UploadSessionClient (UploadSessionClient.swift):
- 200 -> success.
- 401 -> refresh token (getIDToken) and retry ONCE; still 401 -> fatal.
- 403 -> fatal (ownership conflict); surface, do not retry.
- 400 / 422 -> fatal client bug; log and stop, do not retry.
- 5xx / network / timeout -> exponential backoff + jitter, bounded attempts.
  maxRetries = 3 (condition: attempt < 3, starting at attempt = 0), giving
  1 initial call + up to 3 retries = 4 total attempts maximum.
  Delay formula: min(1.0 × 2^attempt + U[0, 1.0) seconds, 30.0 seconds).
  Actual delays: attempt 0→1 ≈ 1–2 s; attempt 1→2 ≈ 2–3 s; attempt 2→3 ≈ 4–5 s.

## Why
Idempotency is path-set keyed, so retrying /upload_session is safe — a repeat
with the same path set returns the stored URIs without re-minting. 4xx (except
401) signals a deterministic client error that a retry cannot fix; retrying
wastes the bounded budget and can mask the bug. 401 is the one 4xx worth a single
token-refresh retry because token expiry (~1h) is the common transient cause.

## Live-verified status codes (2026-05-31, api-public-q62kcditqa-as.a.run.app)
- 200 happy path: confirmed.
- 400 manifest path violation (leading slash): confirmed.
  Body: {"error":"invalid_manifest","detail":"path must be relative (no leading slash): '...'"}
- 401 invalid token: confirmed (FirebaseTokenVerifier in production).
- Idempotency (same path-set → same URIs): confirmed.

## What would change this decision
If api-public adds per-UID rate limiting (pre-launch gap b, 0015), a 429 ->
respect Retry-After branch must be added. Manifest-violation status code is
confirmed as 400 — the fatal-set mapping is correct and no change needed.