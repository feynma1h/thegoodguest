# 0260 — a probe must not be able to become pipeline state

**Date:** 2026-08-27
**Status:** Decided

## Context

0259 needed to see what SAM 3 finds in frames the sampler never picked. Nothing
could do that. `/process` carries only `{scene_id, bundle_uri}`, re-runs the
census sampler, and always reconstructs — so an unsampled frame was unreachable
at any price, and the cheap half of the question (is the mask any good?) could
not be asked without paying the expensive half.

A segmentation-only route is obvious. What is not obvious is that most of the
work is keeping it harmless.

## What we tried

`/segment` takes an EXPLICIT frame list, runs pass 1 only, and returns what the
model saw plus a PNG per detection — the frame with the mask lit beside the RGBA
cut-out SAM 3D would receive. SAM 3 is ~4 s a frame against ~25 s an object, and
the route never loads SAM 3D at all, which also skips its ~124 s cold load. The
19-frame probe that produced 0259 cost well under two minutes.

Three faults surfaced on 0%-traffic candidates, and **not one was visible to the
local suite**, which was green at 1067 passed throughout.

**1. The auth path was never executed.** `verify()` was called with the FastAPI
`Request` rather than the Authorization header value, and the first live call
returned 500 on `'Request' object has no attribute 'strip'`. Every test passed
`oidc_verifier=None`, so the one line with the bug in it never ran. A route whose
auth path is only tested with auth disabled is a route whose auth path is
untested.

**2. It reused `/process`'s OIDC verifier**, whose audience is
`RECEIVER_URL + "/process"`. `oidc.py`'s entire per-route design is that a token
minted for one route cannot be replayed against another; reusing the verifier
discards that. `/shell` and `/compress` each have their own.

**3. Nothing could legitimately call it.** perception-obj is platform-gated
(0106), the verifier demands a token whose email is `tasks-invoker@`, and
impersonating that SA is denied (0090). The route had been designed as though it
could be curl'd, on a service that has not been curl-able for months.

## What we chose

**Two containment invariants, both pinned by tests, and a Cloud Tasks dispatcher.**

- **It writes only under `scenes/{id}/segment_probe/`, never `frames/{idx}/`.**
- **It never touches Firestore** — no claim, no lease, no status.
- `tools/segment_frames.py` mirrors `reenqueue_scene.py`: Cloud Tasks mints the
  OIDC token, so no impersonation is needed and least privilege is not weakened
  to make the probe possible.

## Why

**The prefix is the whole safety argument.** `/process` treats a frame's
`objects.json` as a cache and logs `Frame N cache hit` — that is exactly how a
warm re-drive skips completed work (0160, and confirmed live in 0247 where frame
124 was the only cached frame and the only one skipped). A `masks.npz` written
into the real frame prefix by a probe of an UNSAMPLED frame would therefore be
read as production state by the next real run. The probe would have quietly
become the pipeline. One directory name prevents it, which is why the boundary
is a path and not a flag.

**Not touching Firestore is the other half.** A warm re-drive regresses a `ready`
scene to `queued` — 0247 did exactly that and had to be reverted from a backup.
A probe that answers a question about a room must not be able to take that room
away from the person while it does so.

**And the dispatcher is the honest resolution of the gate.** The tempting fix for
fault 3 was to grant the operator `serviceAccountTokenCreator` on the invoker SA,
or to let the verifier accept a user identity. Both weaken 0090/0106 permanently
to make one probe convenient. Cloud Tasks already mints these tokens for every
other route; using it costs one small tool and leaves the gate exactly as tight.

One sharp edge is recorded in that tool because it will bite anyone who copies
it: **Cloud Tasks defaults the OIDC `audience` to the request URL**, which is
correct for the stable service URL and WRONG for a `candidate---` host, where
the verifier still expects `RECEIVER_URL`'s. Probing a candidate is this route's
normal case, so the default would have failed every time it mattered. The
audience is pinned explicitly.

## What would change this decision

If `/segment` ever needs to write something a later run should reuse, that is a
different route and it should say so in its name. The moment probe output is
worth caching, the containment argument above stops holding and this note
becomes wrong rather than merely superseded.

If a future route also needs pass-1-only access, generalise `segment_probe/`
into a probe-output convention rather than adding a second prefix — the value is
that ONE path segment marks everything a real run must ignore.
