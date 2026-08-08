# 0116 — force_remint: separating "retry my POST" from "my session is dead"

**Date:** 2026-08-08
**Status:** Decided

## Context

Decision 0084 recorded the `.recoverable` re-upload coordinator as
SERVER-BLOCKED and named the un-defer trigger: "a mint contract change that
vends fresh URIs for consumed/dead sessions". This is that change.

The blocking mechanism: `create_or_get` returns the STORED session URIs
whenever the request's path-set matches the stored manifest, and the
`upload_sessions` doc lives for 7 days. A finalized GCS resumable session is
single-use — re-PUTting one is read as a status query of the finished upload,
so it cannot re-create an object the captures lifecycle rule (age=1 day) swept.
The client either silently no-ops or 410s into the `remint_returned_stale_uris`
fatal (0049).

The design difficulty, stated by the coordinator and correct: the path-set is
the idempotency key, so "same request" and "retry the dead session" are
indistinguishable.

## What we tried

**Measured first, and it corrected the problem statement.** A probe through
the real `InMemoryUploadSessionRepository` (four sequential calls, a minter
returning a distinguishable URI per call):

| request | result |
|---|---|
| full path-set, first time | mints |
| full path-set again | **replay** — identical stored URIs |
| SUBSET path-set | **fresh URIs** |
| full path-set after that | fresh (the stored manifest had shrunk) |

So a caller can already obtain fresh URIs today by sending a different
path-set — the replay branch simply falls through. That is an accident of the
idempotency check, not a designed affordance, and it does **not** cover the
case that matters: when the age=1d lifecycle rule has swept a capture's blobs,
the client's recovery manifest is the FULL path-set, which is exactly the one
that replays dead URIs. Getting fresh URIs by shrinking the manifest would
mean misreporting what is being uploaded in order to defeat an idempotency
check. The gap is real, but it is narrower and sharper than "re-mint is
impossible": it is **same path-set + dead sessions**.

**Rejected: server-side session-state verification.** Probe each stored
session (`GET` with `Content-Range: bytes */size`) and re-mint the dead ones.
Rejected on two independent grounds. Cost: one HTTP round trip per path, 2,170
on a real LiDAR manifest — the exact shape that OOM-killed this 512 MiB service
once already (RP-8). Correctness: it answers the wrong question, because a
session can report "complete" while the lifecycle rule has swept the object out
from under it, which is the dominant real case.

**Rejected: a client-supplied idempotency nonce** (`attempt_id`) in place of
the path-set key. More principled in the abstract, and it is how payment APIs
draw this line. Rejected because the deployed client sends no such field, so
absent-nonce would have to fall back to path-set semantics anyway — two
idempotency mechanisms coexisting forever — and because the recovery case is
not "a new request". It is "the grant you gave me is dead", which is a
different statement and deserves its own word.

**Rejected: a separate `/upload_session/remint` endpoint.** Duplicates auth,
manifest validation, ownership and both quotas for one boolean's worth of
difference.

## What we chose

An additive, defaulted `force_remint` on the existing request body, threaded
into `create_or_get` on the ABC and both implementations.

The boundary, stated as the thing it is: **the path-set answers WHAT the
caller intends to upload; `force_remint` answers WHETHER the URIs it already
holds still work.** One input cannot carry two independent questions — that
is the whole defect — so the fix is a second input, not a cleverer reading of
the first.

`force_remint=True` suppresses the replay branch and nothing else. Ownership
is still evaluated first (a foreign UID gets 403 before any mint), it charges
mint quota like any real mint, and it charges a CAPTURE only when it is also a
first claim — re-minting to finish an existing capture commits no new GPU.
Fresh entries REPLACE the stored ones, so a later ordinary replay serves the
new URIs rather than handing back the dead ones the client just escaped.

The server trusts the claim rather than verifying it. The blast radius of a
client that sets the flag when it did not need to is one mint-quota unit and a
set of fresh, working URIs — bounded by the same daily cap as every other
mint, corrupting nothing.

`force_remint` is typed `Optional[bool] = False`, and null means false. A
strict `bool` 422s on an explicit null, Swift's `JSONEncoder` emits exactly
that for a nil `Bool?`, and the client's 0038 policy classifies 422 as a fatal
`clientError`. Modelling the field as optional is the obvious Swift spelling,
so strictness would have turned a natural client implementation into a dead
upload. Absent and null both mean "I am not claiming anything about my URIs".

## Why

Only the mint half was missing. The ingest half has been ready since the
cleanup pass: a re-delivered `bundle.pb` transitions a `FAILED_INCOMPLETE`
scene back to `QUEUED` with the same scene_id. And `validate_manifest` already
requires exactly one `bundle.pb`, so a recovery manifest necessarily carries
the blob whose finalize event re-triggers ingest — the grammar enforces the
thing the loop needs, for free.

Keeping the flag's effect to *exactly one branch* is what makes it safe to
reason about. Every property that protects the system — cross-UID exclusion,
the mint cap, the GPU ceiling — is evaluated identically whether or not the
flag is set, so the flag cannot become a way around any of them. The one
security-shaped question ("can this reach someone else's bundle?") is answered
structurally rather than by testing: ownership is checked before the flag is
consulted, and both implementations have a comment saying so.

## What would change this decision

- **If the deployed client ever sends `force_remint` on ordinary POST
  retries**, the trust model breaks down — each retry would burn quota and
  mint new URIs. The flag is for evidence-backed recovery (a 410, or a
  `failed_incomplete` scene naming missing paths), not for retries. If that
  discipline fails in the field, the answer is a server-side justification
  check, and the honest one is scene state — with the caveat that a bundle
  whose `bundle.pb` never landed has no scene at all and would be wrongly
  refused, so the check cannot simply require `FAILED_INCOMPLETE`.
- **If probing sessions ever becomes cheap** (a batch GCS status API), the
  server could stop trusting and start verifying — though the swept-object
  case would still need the flag, because a swept object's session still
  reports complete.
- **If the captures lifecycle window changes** from age=1d, the balance shifts:
  a longer window makes the subset path cover more real cases and this flag
  rarer; a shorter one makes it the normal path.
- **If a second platform needs recovery**, revisit whether the flag should
  carry a reason string for telemetry rather than being a bare boolean.
