# 0025 — Synthetic fixtures intentionally cannot reach reconstruction `ready`

**Date:** 2026-05-29
**Status:** Decided

## Context

The smoke tool (`tools/upload_test_bundle.py`) builds a `CaptureBundle` from synthetic
fixture data. The image blobs it uploads contain non-decodable placeholder bytes (not real
JPEG/PNG frames). This was discovered during the Phase 7 happy-path run on 2026-05-29:
SAM 3D loaded successfully (P1 resolved), but reconstruction failed immediately after with
"Frame 0 image cannot be opened." The scene reached `failed` rather than `ready`.

## What we tried

The obvious fix is to embed a real, decodable JPEG into the fixture so the full path passes.
We considered it and decided against it (see Why).

## What we chose

Leave the fixture pixels as non-decodable placeholders. Add an ingest-layer validation gate
in `/ingest/eventarc` that detects non-decodable image blobs before enqueuing to Cloud Tasks.
With that gate, happy-path smoke will reach `failed_invalid` in ~3 s (instead of polling
until timeout after a 94–138 s GPU cold start). `failed_invalid` is the correct terminal
state for a synthetic fixture — it proves the gate fires, which is what smoke is testing.
Reaching `ready` requires real sensor data from an iOS device; that is deferred to iOS client
integration testing.

## Why

1. **Real images in the fixture are a cost/time problem.** A real decodable frame of useful
   resolution would add a large binary to the repo and cause a ~95 s GPU cold-start on every
   smoke run. Smoke is supposed to be a fast, cheap integration check, not a reconstruction
   benchmark.

2. **The fixture validates the ingest path, not the reconstruction path.** The smoke tool's
   job is to prove that: (a) a bundle can be uploaded and ingested, (b) Eventarc delivers,
   (c) Cloud Tasks is enqueued, (d) auth boundaries hold. Reconstruction correctness is
   tested by the perception-obj owner's own suite against real data, not by this tool.

3. **Catching non-decodable input at ingest is the right fix.** An invalid frame should
   never reach a GPU cold-start. The validation gate is the architecturally correct place to
   intercept it. The fixture's non-decodable pixels become the gate's positive-case test input.

## What would change this decision

If we ever need smoke to exercise the full reconstruction path end-to-end (e.g. for a
regression test after a perception-obj change), we'd add a separate `reconstruction-smoke`
mode with real image data stored in GCS (not in the repo) and invoked manually, not as part
of the normal deploy runbook.
