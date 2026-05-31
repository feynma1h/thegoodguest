# 0035 — P3 is a single-sided client build against a live contract
Date: 2026-05-31  •  Status: Decided

## Context
P3 (Firebase anon auth + POST /upload_session) is a write→read contract
boundary — the class that ate most of P2 (0027 reader-redeploy, 0031 schema
value/mechanism). The kickoff decision was to read the backend contract before
writing client code.

## What we chose
Build P3 as a single-sided CLIENT build against the already-deployed endpoint
(api-public-00006-quw, asia-southeast1). No backend change, no co-deploy. Integrate
against the live endpoint during P3 (NullTokenVerifier "test-uid:<uid>" for
tests; one live exercise with a real anon idToken) rather than mock-and-defer.

## Why
Unlike 0027 (enum write→read needing atomic co-deploy) and P2's schema gate
(backend had to ship before merge), the read side here is frozen and
smoke-verified green (Phase 7, 2026-05-29). The boundary is safe to single-side
precisely because the server is not in flight. "Live contract" does not mean
"assumptions are safe," so the client compensates for two known gaps:
- F1: response carries no expires_at — client persists its own mint timestamp.
- F3: no semantic manifest validation server-side — client owns manifest
  correctness (extensions, tier/path consistency, relative_path rules).
Effective upload window is bounded by the captures bucket lifecycle (age=1 day)
and the upload_sessions Firestore TTL, NOT the 7-day GCS resumable-URI nominal.

## What would change this decision
If api-public adds expires_at (closes F1) or semantic manifest validation
(closes F3), the client can lean on the server for those and drop the
compensation. If the endpoint contract is revised, this note is superseded.
