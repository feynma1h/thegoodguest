# 0126 — the compressed tier sits beside the PLY, discovered by a sibling index

**Date:** 2026-08-09
**Status:** Decided

## Context

The operator's call (recorded in `docs/briefs/splat-payload-p0.md`): the
compressed tier is **additive** — the viewer prefers the compressed file and
falls back to the PLY, so no existing scene needs a re-bake to stay correct —
and rooms **keep every placed object**, with compression carrying the fix.

That leaves one real design question: how does the client learn a compressed
file exists?

## What we tried

Three shapes, weighed against re-drives, round trips, and the response
contract.

1. **A field on the manifest.** Rejected. A re-drive rewrites `manifest.json`,
   so an index living inside it is silently erased by the pipeline's normal
   operation, leaving orphan `.spz` blobs nobody references.
2. **Existence-check each sibling at request time.** Rejected. One GCS
   metadata round trip per object, on a path decision 0124 had already
   measured at 0.9–2.6 s of pure time-to-first-byte for signing alone.
   Listing the scene prefix instead is one call but returns every frame's
   masks and splats — hundreds of objects to find ten.
3. **A sibling index blob**, `scenes/{id}/compressed.json`. Chosen.

## What we chose

`shell.json`'s precedent, deliberately: an optional sibling that api-public
reads with the `fetch_optional` it already has. Absent means the tier was
never built for that scene — which is where every scene starts, and a
perfectly good state, not an error.

The index is **keyed by the PLY's `gs://` URI**, and the response gains an
additive `asset_urls_compressed` map keyed the same way, so the client looks
up one key and picks a format. `assembleScene` prefers compressed, falls back
to PLY.

Two properties are load-bearing:

- **`asset_urls` never narrows.** The PLY is signed whether or not an SPZ
  exists, so the fallback is a real URL rather than a nominal one. A malformed
  index, an unreachable one, a stale entry, an entry that is not an object —
  all degrade to PLY and none of them 500s. Pinned, including a stale-key case.
- **Keying by URI makes re-drive staleness safe by construction.** A re-drive
  that moves a splat to a new frame path produces a key the index does not
  have; the lookup misses and the room falls back. The one genuine hazard is a
  re-drive rewriting the *same* path with new content, which the recorded
  `source_generation` catches on the converter's next run — the converter is
  the only writer, so that check belongs there and not on the request path.

Signing now runs in a bounded, order-preserving pool
(`ASSET_SIGN_CONCURRENCY`, default 8, one flat wave rather than one per
format). That is **decision 0124's own named trigger firing**: it measured the
serial loop at 0.9–2.6 s and deliberately left it, saying to fix it "once the
payload lands in the tens of MB". At 47.2 MB it has. The pool is modest on
purpose — 0080's mint OOM came from per-call session construction, which the
signer does not do (it reuses one `storage.Client`), but a 512 MiB service
earns a conservative ceiling anyway.

## Why

Because the alternative shapes each fail on something the pipeline actually
does. Re-drives are routine here, and a design whose index is erased by a
routine operation is a design that will be quietly broken the first time
someone re-drives a room and nobody notices, because the symptom is only
"slow again".

Storage came in at **+17%** on the reference room, under the ~25% the operator
budgeted.

The one thing deliberately *not* done, though it was tempting while in the
same loop: filtering signing to placed-only. 0124 flagged it as a separate,
independently correct change that narrows the response contract, and it should
be judged on its own rather than smuggled in beside a payload change.

## What would change this decision

- If perception ever writes the SPZ itself at bake time, the index becomes the
  pipeline's output rather than a backfill tool's, and could then legitimately
  live in the manifest — the re-drive objection disappears when the re-drive
  is what writes it.
- If a second compressed format is ever worth serving (SOG, a different
  quantization), `asset_urls_compressed` is a single map and would need to
  become format-keyed. Nothing today needs that.
- If a room's index ever grows large enough that fetching it costs real time,
  it should move into the assets response's own cache rather than a blob.
