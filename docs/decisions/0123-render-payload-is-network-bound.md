# 0123 — the render payload is network-bound; parse has no headroom to give

**Date:** 2026-08-09
**Status:** Decided

## Context

A room took 6–7 minutes to appear on production (`docs/briefs/splat-payload-p0.md`).
The brief framed the open question as **network-bound vs parse/GPU-bound**, and
said the answer decides which fix is worth building: compression if network,
decimation/LOD if parse. Nobody had separated the two terms, because every
`/viewer` walk read local fixtures over localhost and Gate B fetched one splat
with curl — which sends no `Origin` and waits for no renderer.

## What we tried

All figures below are for the reference scene `a7e073ae` — **10 splats,
275.8 MB, 4,056,000 Gaussians at 68.0 B/Gaussian** (SH degree 0; 17 float32
per Gaussian). Measured against the live outputs bucket, 2026-08-09.

**Network** — real bytes, real bucket, four independent clients:

| client | wall | aggregate |
|---|---:|---:|
| python, 6 connections | 56.1 s | 39.3 Mbps |
| python, 10 connections | 33.8 s | 65.2 Mbps |
| curl, **HTTP/2, one connection**, 10 streams | 25.4 s | 86.9 Mbps |
| real browser + real Spark, bytes via localhost proxy | 30.6 s | ~72 Mbps |

Per-connection throughput is capped at 6.8–11.2 Mbps; TTFB 0.77–2.63 s.

**Parse and GPU** — a harness running the *shipped* renderer (Spark 2.1.0 +
three 0.185, out of `web/node_modules`), driving `new SplatMesh({url})` and
`await Promise.all(m.initialized)` — SplatViewer's exact call shape:

- all 10 splats initialized from local bytes: **0.55 s**
- fetch and parse timed separately, one file at a time: parse 56–485 ms per
  splat, **2.41 s** for the whole 275.8 MB room
- first frame including GPU upload: 51–81 ms. Steady frame: 0.2–0.3 ms
- JS heap holding the finished room: 83 MB against a 4295 MB limit

**Two hypotheses raised during the work, both killed by measurement:**

1. *Signed URLs churn the viewer's effect key and re-download the room.* The
   key at `SplatViewer.tsx:196` does contain `s.url`, signature and all — but
   the shell-grace refetch loop in `RoomStage.tsx` runs entirely **before**
   `setResult`, so the viewer is not mounted while URLs change. No thrash.
2. *A browser is throttled because it multiplexes over a single HTTP/2
   connection to `storage.googleapis.com`, while the python legs used 6–10
   separate ones.* Refuted: one HTTP/2 connection was the **fastest** client
   measured (25.4 s / 86.9 Mbps).

## What we chose

**Network-bound, and not marginally.** Parse plus GPU upload is 0.6–3 s — under
1% of a 6-minute wait — so it has no headroom to give. Any fix must reduce
**bytes on the wire**. Decimation and LOD are not the lever for *this* symptom;
they only become interesting if the goal shifts to GPU cost or memory.

The brief's framing was right to ask the question and wrong in one assumption:
it treated ~6 Mbps as "slow for a download but plausible for parsing". Parsing
276 MB of PLY costs 2.4 s, which is 900 Mbps of parse throughput. The renderer
was never the suspect it looked like.

Two supporting measurements bound what a fix can buy:

- **Generic compression is not the cheap win.** gzip -6 gives 1.36×, zstd -3
  gives 1.40× on a real splat. Serving the existing PLYs with
  `Content-Encoding: gzip` — no client change, no re-bake — was the cheapest
  imaginable fix and it is worth about a third. float32 is high-entropy.
- **Quantization is worth ~4.3×.** Re-encoding to the SPZ-class layout
  (position 3×16-bit within the object's own bbox, scale/rotation/colour 8-bit)
  takes the room from 275.8 MB to **64.1 MB** at a measured position error of
  0.006 mm mean / 0.013 mm max. Note the honest limit of this number: the
  position field was really quantized and really entropy-coded, and its error
  is measured on real data; the other fields are counted at their layout width
  rather than encoded. So 4.3× is a **floor**, not an encoder benchmark.
  Spark already decodes SPZ, SPLAT, KSPLAT and PCSOGS natively
  (`SplatFileType`), so the client side of a compressed tier is a format flag.

**~10% of the payload is downloaded and then discarded** — 27.4 MB of this
room: 4.1% of Gaussians fall outside the decision-0104 `splat_clip` volume,
which SplatViewer deletes with an inverted box SDF, and 5.8% are below
alpha 0.02. Neither is a fidelity trade — the clipped mass is already declared
false by the server. It is real and it is not the lever.

## Why

Because the two candidate fixes differ by weeks of work and the measurement
separates them cleanly. Building a compressed tier is justified; building LOD
or decimation to fix *this* symptom is not, and the brief explicitly warned
that getting this backwards costs weeks on the wrong term.

The remaining gap is bandwidth, not code. Every client measured here needs
25–56 s for this room on a healthy connection; the operator's observed 2 min
and 6–7 min imply 5.3–18.4 Mbps at those moments, on the same machine. A
276–390 MB room is simply too large to survive ordinary variance in a home
connection, and that is the thing to fix.

## What would change this decision

- If a room's Gaussian count grew far beyond ~4M, parse would stop being free
  and the 0.55 s figure would need re-measuring — the instrument for the byte
  half is `tools/measure_render_payload.py`, but parse needs a real browser.
- If a compressed tier lands and rooms are still slow, re-measure before
  reaching for LOD: at 64 MB the terms may reorder.
- If the reveal (0097) is driven progressively, "time to *first* object" —
  not time to last byte — becomes the number that matters, and a 51.8 MB
  cabinet arriving last stops being a problem.
- The one thing not measured here is the operator's own browser against
  `storage.googleapis.com` directly. A HAR from a real signed-in session
  would settle it; nothing measured so far suggests it would change the
  conclusion, since transport was refuted as a factor.
