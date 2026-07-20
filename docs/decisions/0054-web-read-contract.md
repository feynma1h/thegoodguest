# 0054 — Web read contract: scene list, signed-assets endpoint, CORS posture

**Date:** 2026-07-20
**Status:** Decided

## Context

A browser client hit three hard gaps in api-public: no CORS at all, no way to discover
the caller's scenes (the read surface was by-bundle only — the iOS poller knows its
bundle_id; a web app doesn't), and `result_uri` is a raw `gs://` URI whose manifest
references further `gs://` splat URIs — a browser can fetch none of it (gap F4's
contract-shape trigger, "web app build begins", was met this session).

## What we tried

For asset delivery, three shapes were considered: (a) presign only `result_uri` and
have the client request per-asset signing round trips; (b) rewrite the manifest
server-side, replacing every `gs://` URI with a signed URL; (c) return the manifest
**verbatim** plus a separate `asset_urls: {gs_uri → signed URL}` map. (a) multiplies
round trips and pushes signing knowledge into the client; (b) forks the manifest
contract — the perception pipeline's manifest and the client's would drift, and
provenance fields (frames) would carry rewritten URIs that no longer match GCS.

## What we chose

- **`GET /scenes?limit=`** — newest-first list of the caller's scenes, same per-scene
  shape as `/scenes/by-bundle` via a shared serializer (decision 0019 fields;
  `last_error`/`invalid_blobs` stay server-side). Firestore query is filter-only on
  `user_id` (automatic single-field index) with Python-side sort/cap; a server-side
  `order_by` would need a composite (user_id, created_at) index — the named upgrade
  path if per-user counts grow.
- **`GET /scenes/{scene_id}/assets`** — shape (c): fetches the manifest server-side,
  returns it verbatim plus V4-signed HTTPS URLs (TTL 1h) for each unique
  `splat_gcs_uri` in the manifest-v2 fused `objects[]` (the set the viewer renders;
  rgb/masks can be added later). Non-ready scenes get **409 `scene_not_ready` + the
  current status** — clients poll `/scenes/by-bundle` until ready; manifest/signing
  failures are 502 (retryable upstream, distinct from client error).
- **Signing via IAM signBlob** (`generate_signed_url` with the runtime SA's
  email+token): Cloud Run has no private key on disk. Deploy prerequisites: runtime SA
  needs `roles/iam.serviceAccountTokenCreator` on itself + `storage.objectViewer` on
  `gs://roomstudio-perception-outputs`.
- **CORS** gated on `CORS_ALLOWED_ORIGINS` (comma-separated env; unset = middleware not
  installed), GET/POST/OPTIONS, Authorization+Content-Type, **no credentials mode** —
  auth is the Bearer header, not cookies, so nothing cookie-shaped is exposable.

## Why

The verbatim-manifest + URL-map shape keeps the manifest contract single-sourced in
perception-obj (the map is additive; the manifest never forks), costs one round trip,
and lets the client keep using `gs://` URIs as stable object identities while fetching
through the map. Signing only the fused objects' splats bounds signBlob calls per
request to the object count (5–20), not frames × objects. The 409-until-ready shape
mirrors the polling contract the iOS client already established (0019/0027) instead of
inventing a second readiness channel.

## What would change this decision

- Per-user scene counts large enough that unordered streaming hurts → add the composite
  index and server-side order_by (mechanical).
- The viewer needing frame assets (rgb, masks) → extend the signed set; if the URL
  count grows past tens, switch to short-TTL signed *prefixes* via a different
  mechanism or a manifest-scoped token.
- An editing/write surface for the web → separate decision; this note covers reads.
- If clients start caching assets across the 1h TTL, add explicit re-fetch semantics
  (the `expires_at` field already exists for this).
