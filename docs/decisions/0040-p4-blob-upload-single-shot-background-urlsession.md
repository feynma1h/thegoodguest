# 0040 — P4 blob upload: single-shot whole-blob PUT over background URLSession

**Date:** 2026-05-31
**Status:** Decided — routed to and signed off by Chat

## Context

P4 uploads each capture blob to its `session_uri` (from `/upload_session`, persisted per
decision 0037), then uploads `bundle.pb` last to trigger Eventarc ingest (decisions
0023/0029). The contract read (Code recon, 2026-05-31) confirmed the server side. This
note resolves the flagged tension: GCS resumable URIs are designed for a multi-chunk
mid-stream-resume handshake, while iOS *background* URLSession uploads are OS-managed
whole-request single PUTs that cannot drive that handshake.

## Contract as read (confirmed)

Single-shot whole-blob PUT against `session_uri`: `Content-Range: bytes 0-(N-1)/N` plus
`Content-Length`, success 200/201 (decision 0017 bullet 4; smoke tool `_put_blob`).
`X-Upload-Content-Type` hardcoded server-side to `application/octet-stream` (gap F2) —
PUT must NOT set `Content-Type`. No chunk-size rule for a complete single-shot PUT.
`bundle.pb`-last ordering is entirely client-enforced. Object layout:
`captures/{bundle_id}/{relative_path}`.

## Corrections to the recon, on the record

1. The `age=1` lifecycle window is **per-object** (from each blob's own creation time),
   enforced asynchronously with batch lag — NOT a global sub-24h clock. The acute failure
   mode is a stalled upload losing early blobs before `bundle.pb` finalizes, not a
   countdown from session creation.

2. **410 Gone is the dead-session signal** and must be handled (re-mint via P3 path). The
   recon status table omitted it.

3. `failed_incomplete` as a term is verified: `SceneStatus.FAILED_INCOMPLETE = "failed_incomplete"`
   in `packages/api-core/thegoodguest_api_core/scene.py`; `_handle_failed_incomplete` in the
   ingest handler creates/updates to that state when referenced blobs are absent at
   existence-check time. Confirmed correct; not a guess.

## What we chose

**1. Single-shot whole-blob PUT, no chunking.** Blob sizes (JPEG frames, ~0.8 MB depth
`.f32` rasters, sub-1 MB `bundle.pb`) are far below where mid-stream resume earns its
complexity cost.

**2. Background URLSession `uploadTask(with:fromFile:)`.** Uploads survive backgrounding
(decision 0029). Set `Content-Range: bytes 0-(N-1)/N`; let URLSession set `Content-Length`
from the file; set NO `Content-Type` (F2 — the session URI fixes it server-side).

**3. "Resume" = re-PUT the whole blob, never a mid-stream offset query.** OS-managed retry
re-PUTs from byte 0; GCS resumable URI accepts a new complete PUT of the same data. No
mid-stream 308 query needed.

**4. PUT response → action map** (blob-layer analog of decision 0038):
   - `200`/`201` → blob done; mark uploaded in persisted record.
   - `410 Gone` → session dead → re-mint via `/upload_session`, persist (0037), restart
     affected blobs.
   - `308` → anomalous for a complete PUT → re-PUT whole blob once; persistent `308` →
     fatal for that blob, abort bundle.
   - Other `4xx` (`400`/`403`/`404`) → fatal; abort, surface, no retry.
   - `5xx` / network / timeout → OS-managed retry; on OS give-up, bounded client
     re-enqueue (≤ 3, exp backoff + jitter per 0038), then fatal.

**5. Phase-1→Phase-2 gate persists across suspension/kill.** Extend the 0037 record with
per-`relative_path` status (`pending`/`uploaded`). The `bundle.pb` task enqueues only when
every non-`bundle.pb` entry is `uploaded`; the check runs in the background completion
delegate AND reconstructs from the persisted record on relaunch (load record → check
`allNonBundlePbBlobsUploaded` → enqueue `bundle.pb` if true and not yet done).

**6. Staleness guard.** If elapsed since the persisted mint timestamp (decision 0037)
exceeds 12 h (conservative, below the lifecycle floor), re-mint and re-verify rather than
finalizing `bundle.pb` against possibly-GC'd blobs.

**7. No foreground or keep-awake requirement.** Handing tasks to the background URLSession
is the only step requiring the app foreground: create `URLRequest` per blob + call
`uploadTask(with:fromFile:) / task.resume()`. This is sub-3 s even for a ~200-blob
capture (no per-blob disk I/O — file URLs come from paths already on disk; no hashing;
no blocking network). All transfer, the gate check, `bundle.pb` finalize, `410` re-mint,
and the staleness guard run OS-managed in the background completion delegate or on
relaunch.

The app MUST NOT set `isIdleTimerDisabled`, MUST NOT require the user to stay on the
upload screen, and MUST let the user background/lock immediately after pressing stop.
Terminal status is delivered via FCM (P5). User-perceived foreground/awake time after
stop stays sub-3 s (enqueue only); total transfer is OS-scheduled and invisible.

## Why

Single-shot is the only model compatible with background URLSession and is correct for
these blob sizes. The `410` → re-mint branch and the staleness guard make "no mid-stream
resume" safe across the lifecycle window. The persisted gate is the load-bearing
correctness property: `bundle.pb`-last only protects the decision 0023 Eventarc race if
"all blobs done" survives app death. Background-only upload (item 7) is what makes the
premium phone-in-pocket experience hold — it is a constraint, not an incidental benefit.

## What would change this decision

- Blobs grow past ~tens of MB → revisit mid-stream resume (also breaks the background
  guarantee; separate design required).
- Server adds a finalize/commit endpoint validating blob presence → staleness guard can
  lean on it instead of the client-side timestamp heuristic.
- `/upload_session` gains per-UID rate limiting (decision 0015 gap b) → `410` re-mint
  path must respect `429`/`Retry-After`.
