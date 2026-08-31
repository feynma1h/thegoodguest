# 0015 — rate-limiting and concurrency guards deferred until v1 launch

**Date:** 2026-05-26
**Status:** Spent

## Context

Pre-deploy reconnaissance on the new `/upload_session` and `/ingest/eventarc`
endpoints (CLAUDE.md board item 1, the `services/api` redeploy that opens
iOS bundle upload) surfaced three holes in the upload path that are
individually small and collectively form a real abuse surface once there
are real users. The system has no users today, so none of the three is
exploitable in practice. Documenting them as a set rather than three
separate ad-hoc TODOs so the closure is one decision, not three forgotten
ones.

## What we tried

Considered fixing all three before the initial deploy. Each fix is cheap
in isolation:

- **TOCTOU race on bundle_id ownership.** `/upload_session` checks
  Firestore for an existing `user_id` on the bundle_id, then upserts.
  Two non-transactional Firestore operations. Two concurrent calls from
  the same UID with different manifests both pass the check, and the
  second overwrites session_entries — orphaning the first call's minted
  GCS resumable URIs. Fix: wrap in `@firestore.transactional` with a
  read-then-conditional-write inside the transaction.

- **No per-UID rate limit on `/upload_session`.** Anonymous Firebase UIDs
  are cheap (the iOS API key is in the binary, not a secret). Each
  `/upload_session` call mints a real GCS resumable session URI, which
  is a real GCS API operation. An attacker with cycled anonymous UIDs
  can drive GCS API quota and cost. Fix: rate limit at the load balancer
  (Cloud Armor), or per-UID counters with a Firestore backing store.

- **`expected_size_bytes` optional, defaults to 0.** When the client
  sends 0 (or omits the field), the mint code skips the
  `X-Upload-Content-Length` header and GCS accepts arbitrary size on
  that URI. Combined with the no-rate-limit gap, an attacker can mint a
  URI under one UID and upload an arbitrarily large blob to it. Fix:
  make the field required in the manifest schema; set the header
  unconditionally.

Fixing all three pre-deploy would push the iOS-unblock by a few days
without changing what the smoke test actually proves about the happy
path.

## What we chose

Defer all three until before v1 public launch. Ship the deploy with the
gaps documented. Add a board item ("Close the three pre-launch gaps from
decision 0015 before public traffic") that gates opening signups, not
the iOS prototype work.

## Why

The deploy's purpose is to unblock iOS code, not to harden the system
against adversaries that don't exist yet. Today's threat model is "the
developer running `tools/upload_test_bundle.py` and, soon, the developer
running an iOS build on their own phone." Neither attacks the system.
Rate limiting and concurrency guards added now would be tuned against
zero real traffic — the thresholds would be guesses, and the first real
traffic would re-tune them anyway. Documenting the gaps as a coherent
set, gated explicitly behind launch, is more honest than landing three
"// TODO: rate limit" comments and hoping someone finds them in six
months.

The set framing matters. Any one of these in isolation looks like an
oversight a reviewer would push back on. Together with the "pre-launch,
no users" context, the prioritization is deliberate and legible.

## What would change this decision

- Any non-developer gets an account before the gaps close (friends-and-
  family testing, internal demo with external attendees, etc.). The
  launch gate becomes "first non-developer user," not "public signups."
- A real abuse event during developer testing (unlikely — only people
  with repo access would be involved — but possible if the iOS app is
  ever installed on a phone that's also doing other things).
- The deploy surfaces a fourth gap of the same shape, at which point
  the set's worth closing as one piece of work rather than continuing
  to accumulate.
