# 0036 — user_id under anonymous auth; offline-safe serialization order
**Date:** 2026-05-31
**Status:** Decided — resolves the 0022 question for P3

## Context
CaptureBundle.user_id was deferred at chunk B (BundleAssembler.swift: "populated
in P3 after Firebase auth is wired") — empty string, proto default. P3 wires
Firebase anonymous auth and must decide what user_id carries and when bundle.pb
is serialized.

## What we chose
user_id = the Firebase anonymous UID (stable per install, persisted in Keychain).
- Set at assemble time from the CACHED anon user (currentUser?.uid), which is
  available OFFLINE after the first online sign-in. Capture and serialization
  stay offline-safe.
- Gate sign-in on currentUser: signInAnonymously() only when nil; reuse
  otherwise. Never churn the UID (a new UID orphans prior scenes at poll time).
- Backstop for a first-ever-offline launch (no cached UID): leave user_id empty,
  set it and re-serialize bundle.pb at the upload step, which requires the
  network and therefore always has the UID.

## Why
api-internal does NOT cross-check token-UID == bundle.user_id. The two ingest
paths differ: direct /ingest reads scene.user_id = bundle.user_id or None (empty
→ owner None → defensive 403 on polling, per 0019); the iOS Eventarc path
IGNORES bundle.user_id and takes the owner from the upload_sessions doc that
api-public wrote from the verified Bearer token. So for production ownership the
only load-bearing fact is that the same persisted anon user calls /upload_session
and later polls. bundle.user_id correctness matters for the direct /ingest path
(smoke tool, admin re-ingest) and proto hygiene, not production access — which
is why capture must NOT be gated on auth/network.

## What would change this decision
If a non-anonymous auth method is added (Sign-in-with-Apple, etc.), user_id
source changes and this note is revised. If ingest ever adds a
token-UID == bundle.user_id cross-check, the empty-then-backfill path becomes
invalid and must be tightened.
