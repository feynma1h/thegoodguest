# 0032 — Depth intrinsics: scaled RGB, not capturedDepthData

**Date:** 2026-05-31
**Status:** Decided — corrects decision 0029 finding-2

## Context

Decision 0029 finding-2 stated that depth intrinsics for LiDAR frames should
come from `ARFrame.capturedDepthData.cameraCalibrationData.intrinsicMatrix`.
This was wrong. The error was caught during B-1 review in chunk B implementation
before on-device compilation (would have been a compile error).

## What was wrong in 0029

`ARFrame.capturedDepthData` is an `AVDepthData?` — the **front TrueDepth
camera**, used for Portrait Mode and FaceID depth. It is `nil` for all
rear-camera captures including room scanning. `AVDepthData` has
`cameraCalibrationData`; `ARDepthData` does not.

`ARFrame.sceneDepth` is an `ARDepthData?` — the **rear LiDAR sensor**,
available when the `sceneDepth` frame semantic is enabled. `ARDepthData`
exposes only `depthMap: CVPixelBuffer` and `confidenceMap: CVPixelBuffer?`.
It has no intrinsics object.

Using `capturedDepthData` for room scanning would have produced `nil` on
every frame and silently written no depth data.

## What we chose

Use `frame.sceneDepth` as the depth source. Derive depth intrinsics by
scaling the RGB camera's intrinsics to the depth buffer dimensions:

```swift
static func depthIntrinsics(from camera: ARCamera,
                            depthMap: CVPixelBuffer) -> RSIntrinsics {
    let dW = CVPixelBufferGetWidth(depthMap)
    let dH = CVPixelBufferGetHeight(depthMap)
    let sx = Float(dW) / Float(camera.imageResolution.width)
    let sy = Float(dH) / Float(camera.imageResolution.height)
    let K  = camera.intrinsics
    return RSIntrinsics.with {
        $0.fx = K.columns.0.x * sx
        $0.fy = K.columns.1.y * sy
        $0.cx = K.columns.2.x * sx
        $0.cy = K.columns.2.y * sy
        $0.width  = UInt32(dW)
        $0.height = UInt32(dH)
    }
}
```

**Sanity signal:** depth fx should be on the order of the depth width.
For 256-wide depth against 1920-wide RGB: sx ≈ 0.133, fx_rgb ≈ 1440,
so fx_depth ≈ 192. An fx_depth ≈ 1440 (unscaled) in a 256-wide field is
a capture client bug — `inspect_bundle.py` now warns on this.

## Why this works

The LiDAR depth raster is registered to the wide RGB camera — Apple processes
the raw ToF output into a depth map that is spatially aligned with the RGB
frame. The relationship between RGB and depth pixels is a pure scale (the
aspect ratio is preserved). Scaling the RGB intrinsics is therefore exact up
to the registration accuracy of the hardware, which is the correct model for
this sensor pair.

## What the 0029 note got wrong

0029 was derived from the proto docstring and the ARKit API surface, not from
a running app. The docstring says "depth raster's own intrinsics, not the RGB
frame's" — which is true semantically but led to reaching for `cameraCalibration
Data` on the wrong type. The prototype note should have read "derived by scaling
the RGB frame's intrinsics to the depth buffer dimensions." The sentence in 0029
has been struck and replaced with a pointer here.

## What would change this decision

If Apple ships a future ARKit version in which `ARDepthData` gains its own
`cameraCalibrationData`, that data should be preferred over the scaling
heuristic. Until then, scaling is the correct approach.
