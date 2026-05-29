# 0029 — iOS capture app: five-phase plan and ARKit contract notes

**Date:** 2026-05-29
**Status:** Decided

## Context

iOS capture app development begins in earnest (Phase 1). Before writing code, the
prior session verified the ARKit→proto field mapping against the live proto and
settled a five-phase build plan. This note captures both so future sessions don't
re-derive them.

## What we chose

### Five-phase plan (flex on scope, not on order)

- **P1 — Capture skeleton:** ARWorldTrackingConfiguration, keyframe accumulation by
  pose delta, JPEG writes to temp dir, minimal SwiftUI (start/stop + frame counter).
  No proto serialization, no networking.
- **P2 — Tier dispatch + full proto assembly:** detect LiDAR capability, select
  `CaptureTier`, assemble a real `CaptureBundle` proto in memory, serialize to
  `bundle.pb` on disk. `schema_version = "1"` must be set here; backend enforcement
  (board item 2) blocks P2 merge.
- **P3 — Firebase anonymous auth + `/upload_session`:** obtain `idToken`, call
  `POST /upload_session`, receive manifest, store session locally.
- **P4 — Background upload, `bundle.pb` last:** upload blobs per manifest (resumable
  PUT), upload `bundle.pb` only after all blobs succeed. Background URLSession so
  upload survives app backgrounding.
- **P5 — Polling + FCM + state UI:** `GET /scenes/by-bundle/{bundle_id}` polling,
  FCM push for terminal states, scene-status screen.

### ARKit→proto contract findings

Verified against `packages/schemas/capture_bundle.proto` at HEAD `6251cbc`.
All mappings confirmed correct:

| Proto field | ARKit source | Notes |
|---|---|---|
| `Pose.{pos_x,y,z}` | `camera.transform.columns.3.xyz` | meters, world frame |
| `Pose.{quat_x,y,z,w}` | `simd_quaternion(camera.transform).vector.{x,y,z,w}` | `simd_quatf.vector` is `(ix,iy,iz,r)` = our `(x,y,z,w)` ✓ |
| `Gravity.{x,y,z}` | derived from `camera.transform` | camera-local unit vector; skip rule per 0028; extraction formula to be confirmed during implementation against pose_math.py and the gravity docstring |
| `Intrinsics.{fx,fy,cx,cy}` | `camera.intrinsics` cols: fx=`[0][0]`, fy=`[1][1]`, cx=`[2][0]`, cy=`[2][1]` | ARKit already undistorted |
| `Intrinsics.{width,height}` | `camera.imageResolution` | |
| `Frame.timestamp_us` | `Int64(frame.timestamp * 1_000_000)` | same domain as `CACurrentMediaTime` |
| `Device.hardware_id` | `sysctlbyname("hw.machine")` | see 0028; proto comment says `utsname` but that's stale — diverges on simulator |

**Two findings that bite in P2:**

1. **`schema_version = "1"` enforcement:** P1 has no serialization so this is
   dormant. P2 must not merge until `api-internal`'s ingest handler rejects
   unknown versions (board item 2). Both sides must ship together.

2. **Depth intrinsics (LiDAR frames):** `Depth.intrinsics` is the depth raster's
   own intrinsics, not the RGB frame's. Source:
   `ARFrame.capturedDepthData.cameraCalibrationData.intrinsicMatrix` —
   `[0][0]`=fx, `[1][1]`=fy, `[2][0]`=cx, `[2][1]`=cy. Depth resolution is
   typically 256×192 vs RGB 1920×1440. P1 does not write depth; capture this
   here so P2 doesn't have to re-derive.

### Gravity and hardware_id rules

See decision 0028. Not restated here.

## Why

Capturing the plan and contract mapping keeps future sessions from re-reading the
full proto docstring and re-deriving ARKit field sources. The two P2-blocking
findings (schema_version gate, depth intrinsics) are easy to miss mid-sprint;
they're worth a dedicated forward reference.

## What would change this decision

- Phase order could collapse (e.g. P2+P3 merge) if development is faster than
  expected and end-to-end testing on a real device demands real uploads sooner.
- The depth intrinsics extraction path changes if Apple alters the
  `ARDepthData` / `AVCameraCalibrationData` API in a future iOS release.
- `schema_version` bump invalidates the P2 mapping table entry; a new note
  should be written at that point.
