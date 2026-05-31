# 0033 — C decoupled from B's depth residual; B-3 split per-tier

**Date:** 2026-05-31
**Status:** Decided

## Context

P2 chunk B (iOS proto assembly) gated chunk C (gravity formula) behind "B-3
device-verify on both tiers" (P2 handoff; 0029 phase ordering). B-3 requires a
device-produced bundle.pb inspected clean on both ARKIT_ONLY and LIDAR_ARKIT.
Only a non-LiDAR device (iPhone 16e / iPhone17,5) is available; a LiDAR device
is ~1–2 months out.

## What we chose

1. **Split B-3 per tier.** ARKIT_ONLY is closed; LIDAR_ARKIT is deferred until
   LiDAR hardware is available (~1–2 months).
   ARKIT_ONLY device bundle inspected clean: schema_version "1", lowercased-UUID
   bundle_id, real-device provenance (iPhone17,5 + 63 real frame blobs),
   quaternion norm error 0, RGB intrinsics sane (fx 1471.8 @ width 1920),
   gravity = zero-stub as expected (C not yet run; inspect's gravity-vs-pose
   delta of exactly 1.0 is the stub fingerprint, not a bug).

2. **Decouple C from B.** C (gravity) proceeds now on the non-LiDAR device.
   Gravity reads camera.transform and writes the Gravity field; it has no
   dependency on the depth path. ARKit pose/gravity is hardware-independent, so
   C verified on a non-LiDAR phone — including the mandatory on-device eyeball
   gate — is C verified. This reorders the documented plan (ordering, not a true
   dependency); recorded here so the deviation is on the record.

3. **Bank B-1 in two halves, hardware-free:**
   - Type-level fix (0032) confirmed by clean compile — the old
     ARDepthData.cameraCalibrationData call would not have compiled on device.
   - Scaling arithmetic extracted to a pure scaleIntrinsics(...) function and
     unit-tested against hand-computed literals (fx 1471.8 → 196.2, cx → 123.2,
     cy → 96.1 at depth 256×192 / RGB 1920×1440), catching the fx≈1440
     unscaled-intrinsics failure mode on any device or the simulator.

## B's remaining residual (hardware-gated only)

The LIDAR_ARKIT run must still confirm, and only it can:
- frame.sceneDepth returns non-nil (the core of the B-1 fix vs. the always-nil
  capturedDepthData path)
- depth buffer dimensions are 256×192 as assumed
- one depth blob written per frame
- depthIntrinsics(from:depthMap:) wrapper field mapping (the pure scaleIntrinsics
  it calls is tested; the ARCamera unpacking is device-only — ARCamera has no
  public initializer)

Inspect check for that run: depth fx ≈ 190–210 @ width 256 (≈1440 = unscaled
bug → stop); depth blob count = frame count; RGB fx a distinct object in
~1440–1920.

## Note: the scaling test cannot detect an axis swap

Because the sensor pair preserves aspect ratio (RGB 1920×1440 and depth 256×192
are both 4:3), sx == sy, so the literal test cannot distinguish swapping the x-
and y-scales. Benign: sx == sy is guaranteed in production, making the swap a
no-op wherever it could occur. A non-square test is not worth adding — it would
exercise a physically impossible input.

## P2 merge (open — Code's call)

With chunk A deployed and C committed, P2 can merge, but depth runtime stays
unverified for ~1–2 months. No live depth consumer exists yet (P3/P4/P5 unbuilt),
so an undiscovered depth-runtime bug has near-zero blast radius until then.
Either hold the merge for the LiDAR run, or merge with this residual explicitly
noted — do not silently declare B done.

## What would change this decision

- LiDAR device arrives → run LIDAR_ARKIT, close B's residual, update CLAUDE.md.
- If a live depth consumer (P3/P4/P5) ships before the LiDAR run, the low-blast-
  radius justification for deferral no longer holds and the LiDAR run becomes
  merge-blocking.
