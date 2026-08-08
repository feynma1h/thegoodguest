# 0125 — the compressed tier is a transcode, and Spark already reads it

**Date:** 2026-08-09
**Status:** Decided

## Context

Decision 0123 measured the render payload as network-bound and put a floor of
~4.3× on what quantization could buy, noting in passing that Spark decodes SPZ
natively so "the client side of a compressed tier is a format flag". The
coordinator then found that Spark 2.1.0 also *exports* `SpzReader`, `SpzWriter`
and `transcodeSpz`.

That mattered far beyond convenience. It decides whether converting the nine
existing rooms is a cheap re-encode or a re-bake — and a re-bake would trigger
decision 0070's rule that any change to what ships must be re-adjudicated on
the reference room first, plus the 0089 person-suppression question for every
pre-0089 scene. So the probe came before any design.

## What we tried

`transcodeSpz` run headless in Node against the reference scene `a7e073ae`'s
ten rendered splats — the real files from the live outputs bucket, encoded by
the same `spark.module.js` the browser decodes with.

| | PLY | SPZ | |
|---|---:|---:|---|
| room total | 275.8 MB | **47.2 MB** | **5.84×** |
| per splat | 68.0 B/Gaussian | 10.9–12.4 B/Gaussian | 5.47–6.23× |
| Gaussians | 4,056,000 | 4,056,000 | **exact, all ten** |
| encode | — | 8.0 s for the room | |

Both formats are fixed-width per Gaussian, so the ratio is **structural**, not
a property of this sample — the only variable is how well the quantized stream
gzips. That is why the range is narrow and why it extrapolates.

Round-trip error, measured per Gaussian against the source PLY, across all ten:

- position **0.117 mm mean, 0.21 mm max**
- rotation 0.081° mean, 0.26° max
- scale 0.005% mean · alpha 0.001 · rgb 0.003 mean
- the rgb tail beyond 0.05 is 0.001%–0.64% of Gaussians (out-of-gamut `f_dc`
  clipped by 8-bit colour), worst on the rug

Renders correctly through the actual `SplatViewer` with a clean console, as
does a deliberately **mixed** room with five SPZ and five PLY composited
together — the realistic state of an interrupted conversion or a re-drive.

Then, on the real bucket, same client, back to back: **87–93 s → 14–19 s**.

## What we chose

Ship it as a transcode. `tools/transcode_scene_splats.mjs` reads a scene's
PLYs and writes an SPZ beside each one.

**It is not a re-bake, and that is the load-bearing claim.** The PLY is the
input; nothing re-segments, no perception decision is recomputed, and every
byte of every existing artifact stays where it is. So 0070's re-adjudication
rule is not triggered — and, just as importantly, a pre-0089 scene's
person-suppression status is carried across *unchanged*. This makes such a
scene no better and no worse. A scene that needs suppression still needs a
re-drive; the transcode must never be described as fixing it.

## Why

Because the probe answered the only question that could have made this
expensive, and answered it in the cheap direction. 5.84× at 0.1 mm, with the
Gaussian count preserved exactly, is not a fidelity trade anyone has to
adjudicate — it is the same room in fewer bytes.

Two smaller findings, recorded so nobody re-derives them:

- **Two levers were measured and cut.** `transcodeSpz` accepts
  `opacityThreshold` and `clipXyz`, which looked like a free ~10% from 0123's
  waste figure. Measured, `opacityThreshold: 0.02` drops 0.76%/0.90%/2.42% of
  Gaussians on three real objects for ~1–2.5% of bytes, and `fractionalBits:
  11` buys 5.1–5.5% at twice the position error. Neither is worth changing
  what ships for. **This also corrects 0123**, which put 5.8% of Gaussians
  below alpha 0.02; the real figures are those three. It does not disturb
  0123's conclusion — that number was inside a term 0123 itself called "not
  the lever".
- **A probe bug worth remembering.** The first fidelity run reported 133° mean
  rotation error. The PLY stores *un-normalized* quaternions (INRIA 3DGS does
  not constrain the norm) and the SPZ writer normalizes; comparing them raw is
  meaningless. `[0.0034, 0.1935, -0.0398, 0.2041]` has norm 0.284, and dividing
  through gives the SPZ values exactly. The room rendering correctly was the
  clue that the instrument, not the data, was wrong.

## What would change this decision

- If a future bake emits spherical harmonics above degree 0, the per-Gaussian
  widths change on both sides and the 5.84× needs re-measuring. Today's rooms
  are all SH degree 0.
- If Spark's SPZ encoder changes across a version bump, the writer and reader
  are the same package by construction — but the tool pins nothing, so a bump
  should be followed by one re-transcode and one browser walk.
- If a room ever needs sub-0.1 mm positions, `fractionalBits` is the knob and
  costs ~5% per bit.
