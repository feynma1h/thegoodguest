# 0034 — ARKit `camera.transform` is a fixed landscapeRight frame

**Date:** 2026-05-31
**Status:** Decided

## Context

During chunk C (gravity formula) implementation, a Code session's on-device test note
stated that holding the phone "upright in portrait, camera toward the horizon" should read
gravity ≈ (0, -1, 0). That was wrong and would have looked like a sign/axis gate failure on
a correct formula. The cause is a property of ARKit that is easy to miss and was recorded
nowhere in this repo.

## The convention

`ARCamera.transform` defines a camera-local coordinate space that is **constant with respect
to device orientation** — it does not rotate with the UI interface orientation. Per Apple's
documentation, the axes are defined relative to `UIDeviceOrientation.landscapeRight`:
- x-axis points right (along the device's long axis),
- y-axis points up,
- z-axis points out of the screen toward the user; the camera looks down -Z.

Consequence: the identity quaternion (camera-local frame == ARKit world frame) corresponds
to holding the device in **landscape**, not portrait. Held in portrait, the transform carries
a 90° roll about the viewing axis, and world-down resolved into camera-local lands on the
camera **X** axis (≈ (±1, 0, 0)), not Y.

## Practical rules

1. The PoseTests gravity vectors — identity → (0,-1,0), pitch-to-floor → (0,0,-1) — are
   landscape-frame ground truth. They are correct; they assume a landscape hold.

2. On-device gravity eyeballing depends on hold orientation:
   - Floor → (0,0,-1) and ceiling → (0,0,+1) are roll-invariant (viewing axis -Z aligns with
     world-down/up; rolling about it doesn't change Z). Strongest checks; hold in any orientation.
   - Horizon check is orientation-dependent: landscape reads (0,-1,0); portrait reads
     ≈ (±1,0,0) with Z≈0. A portrait (±1,0,0) reading is CORRECT, not a bug. Robust statement:
     Z≈0 and the (x,y) part points at the true ground.

3. Anyone interpreting the Gravity field, per-frame Intrinsics, or Pose downstream must
   remember the camera frame is landscapeRight-fixed, independent of physical hold at capture.

## Why this is recorded

The error already happened once and produced a confidently-wrong test instruction. It will
recur for: the deferred LiDAR depth run (depth intrinsics live in the same camera frame), any
future gravity revisit, and any backend consumer reasoning about camera-local vectors. The
don't-flip-a-sign rule (0030) depends on knowing this — a portrait reading that "looks
backwards" must not be patched by negating a correct formula.

## What would change this decision

- If the capture app pins a fixed interface orientation and converts the transform into that
  frame at the boundary, the rule simplifies to that one frame (the conversion then needs its
  own note).
- If Apple changes the `ARCamera.transform` frame definition in a future ARKit (stable for
  many releases to date), this note is revised.
