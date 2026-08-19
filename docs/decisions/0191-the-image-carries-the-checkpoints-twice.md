# 0191 — the perception image carries the SAM 3D checkpoints twice

**Date:** 2026-08-19
**Status:** Decided (recommended, not executed)

## Context

The durable half of the registry problem is that the `perception-obj` image is
38.07 GiB. A cleanup policy bounds how many copies are held (0190); it does
nothing about the rent each copy charges. The charter asked for this to be
costed rather than executed, so it was measured rather than estimated.

## What we tried

The layer sizes were read from the registry manifest and mapped to build steps
through the image config's `history` — no pull, so measuring a 38 GiB image
cost two HTTP requests. Two layers are 75% of the image:

| GiB | step |
|---|---|
| 17.207 | `snapshot_download('facebook/sam3')` + `snapshot_download('facebook/sam-3d-objects')` into `/models` |
| 11.199 | `cp -rL "$sam3d_dir"/checkpoints/. /opt/sam3d/checkpoints/hf/` |
| 4.712 | `pip install -e '.[dev]'` |
| 2.769 | `mamba env create` |
| 1.056 | DINOv2 weights |

The second layer is a dereferenced copy of part of the first. `cp -L` is
deliberate and correct — the HF cache stores blobs behind symlinks and the
destination has to be self-contained — but the cache it copied out of is never
removed, and it cannot be: the `rm` would have to live in the same `RUN` as
the download, and the download and the copy are two separate `RUN`s.

So **11.2 GiB — 29% of the image — is the SAM 3D checkpoints stored a second
time.** The runtime reads them from the copy: `models/sam3d.py:28` defaults to
`/opt/sam3d/checkpoints/hf/pipeline.yaml`. The SAM 3 half of `/models` is
genuinely needed — `build_sam3_image_model()` resolves through `HF_HOME`,
which the Dockerfile sets to `/models`.

## What we chose

**Recommend, do not execute.** The fix is to merge the download and the copy
into one `RUN` that deletes the `facebook/sam-3d-objects` snapshot from
`/models` after copying it out, leaving the `facebook/sam3` snapshot in place.

## Why

The saving is real but small against what it costs to land. At three retained
images (0190), 11.2 GiB × 3 = 33.6 GiB ≈ **$3.4/month**. Validating it needs a
build whose layer cache is invalidated from the checkpoint step onward — so a
~58-minute build — plus a deploy and a live re-drive to prove SAM 3D still
loads, on a service where 0182 has already shown the build is fragile. Spending
an hour of GPU-adjacent build and a deploy cycle to save $3.40 a month is not
the trade, on its own.

It becomes the trade when the build has to happen anyway. 0182 already owes a
rebuild (the unpinned `git clone --depth 1` of SAM 3D wants pinning to
`f91db411c50efee93d8db7aeb323885650f6f722`), and that build pays the same cache
invalidation. Bundled there, this is a Dockerfile edit riding an existing
smoke.

The non-storage benefits are the better argument and are not quantified here:
38 GiB is pushed on every build and streamed on every cold start of a
scale-to-zero GPU service. Nobody has measured how much of the ~3.5 min GPU
cold start is image streaming, so this note does not claim it.

## What would change this decision

- The next `perception-obj` Dockerfile change that already invalidates the
  checkpoint layer — do it there, in the same build.
- If `keepCount` rises: the saving scales with retained copies, and at ten it
  is $11/month rather than $3.40.
- If cold-start latency is ever measured against image size and streaming is a
  material share of it, this stops being a storage question.
