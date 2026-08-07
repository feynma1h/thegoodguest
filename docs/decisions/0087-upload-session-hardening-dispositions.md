# 0087 — /upload_session hardening: gaps a/b/c/F1/F2/F3 dispositions

**Date:** 2026-08-07
**Status:** accepted (a/b/c/F3 shipped; F1/F2 resolved won't-build with re-open triggers)

## Context

The launch-hardening pass closes decision 0015/0018's upload-path gaps. The
0035 wire shape is frozen: request/response JSON shapes unchanged; additions
are validation tightenings and two new status codes on failure paths that
conforming clients never hit. This note records the endpoint-shape decisions
and the two won't-build dispositions.

## Gap (a) — atomic bundle_id ownership

`create_or_get` now claims ownership inside one Firestore transaction
spanning the session record and the caller's quota doc; the claim lands
BEFORE any GCS mint, so a crash mid-mint leaves an owned record whose empty
`session_entries` routes the same-UID retry to a fresh mint. A foreign UID
gets `ForeignBundleError` → 403 (same body as the old pre-check).
Deliberate scope line: **same-UID concurrent mints stay last-write-wins** on
the stored record. Both callers receive real, working GCS resumable sessions
(the blobs are identical bytes from the same client), and serializing them
would need a lease with 409s the deployed iOS 0038 status map treats as
fatal. Cross-UID exclusion is the security property 0015 named — the loser
of the old race uploaded blobs into a prefix whose scene the winner owned.

## Gap (b) — per-UID daily mint quota

The conversation repo's UTC-day-roll transaction pattern (0058), applied to
mints: `upload_mint_quotas/{uid}` {day, count}, charged inside the admission
transaction ONLY when the call will actually mint. Replays are free — a
client retrying a timed-out POST (RP-8's observed 3-POST mint) can never be
rate-limited into a corner, and an at-cap replay still serves. A 429'd
first-mint claims nothing (the bundle_id is not burned). 429 body:
`{error: rate_limited, detail, resets_at}` + `Retry-After` header — the
shape 0038 reserved for its future client branch. **Known edge, recorded:**
the deployed iOS build maps 429 to `unexpectedStatus` (fatal, no retry);
the default cap (`UPLOAD_SESSION_DAILY_MINTS=50`) sits ~2× above the
heaviest observed developer day so a real user should never see it. Also
recorded: quota is charged at admission, so a GCS mint failure burns a slot
(rare, generous cap, not worth a refund transaction); and per-UID limiting
does not bound cycled anonymous UIDs — 0015 already named LB-level controls
(Cloud Armor) as that layer if it's ever needed.

## Gap (c) — expected_size_bytes required + enforced

Required, integer (bool excluded), >= 1, capped per blob; the mint layer now
ALWAYS sets `X-Upload-Content-Length` (plus a defensive raise on size < 1),
so GCS itself rejects uploads that differ from the declared byte count —
declared size becomes an enforced cap, not a hint. Compatibility gate
verified before enforcement: iOS ManifestBuilder reads real on-disk sizes on
every mint path (client half, 2026-07-21), the smoke tool's `_build_manifest`
sends `len(blob)`, its auth-rejection minimal manifest declares 1, and the
api-core fixture builder doesn't build manifests (the smoke tool derives
them from its blobs). No client change needed; none made.

## Gap F3 — semantic manifest validation

New `roomstudio_api_core.manifest_validation`: path grammar pinned to the
union of what deployed writers emit (`frames/*.jpg`, `depth/*.f32`,
`confidence/*.png`, `roomplan/*.json|usdz`, root `bundle.pb`), exactly one
bundle.pb (a manifest without it can never complete ingest — early 400 is
honest), no duplicates, filename charset with no hidden files, and caps:
per-blob 100 MiB, bundle.pb 10 MiB (mirrors ingest MAX_BUNDLE_BYTES — a
larger bundle.pb would upload cleanly then bounce at ingest's fetch guard
forever), 6000 paths, 8 GiB declared total (largest real manifest: 2,170
paths / ~517 MB). Env-tunable caps; the grammar itself is code-only by
design (a new blob class is a client release). **Tier/path consistency
deliberately stays at ingest** (`validate_bundle`'s tier-vs-depth check):
the 0035 request shape carries no tier, and inferring one from paths would
guess. 0035's note anticipated this closure — the client may now drop its
remaining F3 compensation.

## Gap F1 — expires_at in the response: WON'T BUILD as conceived

The only client consumer of a mint timestamp (BlobUploadManager's 12h
staleness guard) measures time-since-mint, not URI expiry — a different
quantity than the resumable URI's ~7-day nominal life — and the 410-triggered
re-mint path already handles genuine URI death. The value that WOULD matter
server-side is the captures-bucket lifecycle window (the client mirrors it as
a hardcoded 12h), but surfacing it is only useful if a client would change
behavior on it, and changing either side needs a coordinated deploy anyway.
Re-open trigger: the captures lifecycle window changes, or a second client
platform needs the staleness constant and hardcoding it twice becomes drift.

## Gap F2 — X-Upload-Content-Type hardcode: KEEP

0018's rationale (AR Quick Look, browser-inline JPEG, CDN headers) assumed
capture blobs would someday be served to browsers. They aren't and won't be:
captures are consumed only by the backend (perception reads bytes,
content-type immaterial) and swept at age 1d; everything browser-facing is
served from the outputs bucket where perception sets types at write time.
The client sends no Content-Type on PUT (0040), so a future per-extension
mint-time type map would be invisible to clients and can be added whenever a
browser consumer of captures actually appears — the named re-open trigger.
Until then, uniform octet-stream is one less thing to sniff.

## What would change this decision

- A client 429 branch ships (0038's reserved follow-up) → the fatal-429 edge
  note above dissolves.
- Abuse from cycled anonymous UIDs is observed → LB-level rate limiting
  (Cloud Armor) joins the per-UID quota; this endpoint's semantics stay.
- A new capture blob class ships → extend ALLOWED_SUBDIRS in the same client
  release.
- F1/F2 re-open triggers above.
