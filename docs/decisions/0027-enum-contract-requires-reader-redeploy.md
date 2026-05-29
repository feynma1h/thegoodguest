# 0027 — enum contract additions require co-deploying the reader

**Date:** 2026-05-29
**Status:** Decided

## Context

The ingest validation gate (board item 1) introduced a new terminal `SceneStatus` member —
`failed_invalid` — written by `api-internal` and read by `api-public`. Both services share
`SceneStatus` via `packages/api-core/roomstudio_api_core/scene.py`, but are deployed
independently on Cloud Run.

## What we tried

The gate was shipped to `api-internal` alone (revision `api-internal-00009-bej`). `api-public`
was not redeployed. When a scene reached `failed_invalid`, `GET /scenes/by-bundle/{bundle_id}`
on `api-public` returned 500. The error in `scene_read_repo.py._from_doc`:

```
ValueError: 'failed_invalid' is not a valid SceneStatus
```

The api-public image was built from an older HEAD where the member did not yet exist in
`packages/api-core/roomstudio_api_core/scene.py`. The deserialization call
`SceneStatus(data["status"])` raises `ValueError` on any unknown member. The new member and
the gate handler were introduced together in the same commit (`dea1b77`), so rebuilding
api-public from current HEAD was sufficient to fix both images in one step.

## What we chose

Rebuild and redeploy `api-public` from current HEAD. New serving revision:
`api-public-00006-quw`.

## Why

Both services install `packages/api-core` from source at image build time. When a new enum
member is added, both images must be rebuilt before the new value can safely appear in
Firestore. Deploying only the writer freezes the reader at the old definition. The failure
is silent at startup and only surfaces when a document carrying the new value is
deserialized — in this case, immediately on the first smoke run after the gate shipped.

The lesson: enum or other contract additions that cross the write→read service boundary
require redeploying the reader in the same deploy round. Check the reader side before
scoping "one service only."

## What would change this decision

If `SceneStatus` deserialization switched to a lenient pattern (returning a fallback value
for unknown members rather than raising), the reader could tolerate a brief lag behind the
writer. That trade-off is only right if callers handle unknown states gracefully. Until
then, co-deploy is the rule.
