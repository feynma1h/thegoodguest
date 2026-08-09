# 0105 — Ingest requires every blob the bundle declares

**Date:** 2026-08-09
**Status:** Decided and BUILT — `_collect_bundle_blob_paths` in
`services/api-internal/ingest_server.py`. NOT deployed: api-internal still
serves `api-internal-00021-yam`, which predates this, so the gate is inert
until that service is redeployed.

## Context

The pre-GPU existence gate checks that every blob a capture bundle references
actually landed in GCS, and holds the scene at `failed_incomplete` with the
absent paths in `missing_paths` when one did not. It collected frame RGB,
depth, confidence — and the RoomPlan **usdz**, but not the RoomPlan **json**.

Nothing recorded whether that asymmetry was intended. A LIDAR_ROOMPLAN bundle
whose `roomplan/room.json` never arrived therefore passed the gate, dispatched
to the GPU, and degraded at the shell stage to `room_json_missing` — rendering
the LiDAR-ARKit envelope shell instead of the CapturedRoom geometry the user
scanned for. Silently: the scene reaches `ready`, and nothing in the product
says the room on screen was assembled from a fallback.

## What we tried

Reading the record for an intent to preserve, and finding none. Three things
settle it instead, all verifiable:

- **The client only claims the tier when the file exists.**
  `RoomPlanWire.finalTier(hasLidar:roomPlanShipped:)` returns `.lidarRoomplan`
  only when `roomPlanShipped` — which means `roomplan/room.json` was written —
  and `roomQualifies` requires a built room with at least one wall or floor
  before that. Both are pure functions with table pins. So a ROOMPLAN bundle
  missing its room.json is a **lost blob by construction**, not a capture that
  legitimately had no room. That is exactly the condition `failed_incomplete`
  and `missing_paths` were built to describe.

- **The cost/benefit inverted this week.** When the gate was written,
  `failed_incomplete` was close to a dead end for the user — the client had no
  way to re-send the missing blobs, so failing honestly meant losing the
  capture. The `.recoverable` re-upload coordinator has since merged
  (`CaptureRecovery`, decision 0084, un-blocked by the `force_remint` mint
  contract in 0116), which turns `failed_incomplete` into a one-tap re-send of
  exactly the named paths. Failing honestly now costs the user a tap.

- **The degraded run is not free.** A capture that reaches the GPU and produces
  the wrong shell burns roughly 1,500 GPU-seconds — the measured per-capture
  figure behind the daily ceiling in decision 0098 — to render something the
  capture did not ask for.

## What we chose

State the collection as a **rule** rather than maintain a list: *every blob the
bundle DECLARES must have arrived.* `room_plan.json_gcs_path` joins the check
because it is declared.

The rule is the point. A list invites a per-field argument about whether each
one is load-bearing enough to hold a capture for, and every new optional
message that carries a GCS path re-opens it. Under the rule:

- **The usdz needs no special case.** It is declared, so it is required — even
  though it is a debugging artifact nothing in the pipeline reads. If a future
  decision stops uploading it, it stops being declared and drops out of the
  check automatically, with no code change here.
- **A new wire field is covered the day it ships**, without anyone remembering
  to come back to this function.
- **A bundle that declares nothing new behaves identically**, which is what the
  degrade lock pins.

## Why

A manifest entry is not a hint. The capture wrote that path, told the server
about it, and the upload session minted a URI for it. A declared path with no
object behind it is an upload that did not finish — one fact, with one honest
response, and the client can now act on it.

The alternative — dispatching and degrading — spends real GPU budget to produce
a room that is quietly not the one that was scanned. Between a failure the user
can fix in a tap and a success they cannot tell is wrong, the failure is
kinder.

**0077's shell-side `room_json_missing` degrade is untouched and still
correct.** It covers a different case: the captures bucket sweeps at age 1 day,
so a scene re-driven later has no room.json through no fault of the upload.
Ingest checks *arrival*, once, while the blobs are fresh; the shell degrades
over *sweeps*, forever after. They are complementary, and removing either would
leave a real case unhandled.

## What would change this decision

- If a client is ever built that legitimately sets a tier whose geometry blob
  is optional, the rule as stated stops fitting and the tier — not this
  function — is what needs re-designing.
- If `failed_incomplete` stops being recoverable on some platform, the
  cost/benefit that made this worth doing inverts back for that platform.
- If a declared-but-huge blob ever makes the existence check itself expensive,
  the check may need to sample rather than enumerate; the rule survives, the
  implementation would not.
