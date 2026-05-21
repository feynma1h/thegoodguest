# 0001 — Pivot from photo-upload composition to iOS-first capture

**Date:** 2026-05-21
**Status:** Decided

## Context

Through session 4, the project's capture path was photo upload: user uploads 9 HEIC photos, VGGT reconstructs a pointmap, SAM 3 segments objects, SAM 3D Objects reconstructs per-object splats, the orchestrator composes them into a scene.

By end of session 4, composition was the broken step. Per-object orientation, scale calibration, and gravity recovery all required manual knobs (`--up-axis`, `--world-yaw-deg`, `--splat-yaw-deg`, `--room-scale-meters`) that were iterative-by-hand and didn't generalize across objects.

## What we tried

- Manual axis discovery via `inspect_splats.py` — solved up-axis but not per-object orientation.
- Global `--splat-yaw-deg` — single global yaw can't fix it; different objects need different yaws, and the knob also had an axis-confusion bug (tilts instead of rotating around the up axis).
- 5/95 percentile clip in `_estimate_placement` — fixed the plant being killed by confidence threshold, but didn't address scale calibration.

## What we chose

Pivot to an iOS-first capture path. The iOS app uses ARKit (and RoomPlan on LiDAR devices) to capture poses, gravity, intrinsics, and optionally depth + parametric walls. These are uploaded as a "capture bundle" (protobuf). The backend consumes the bundle directly — no VGGT, no UniDepth, no gravity-from-RANSAC.

The photo-upload pipeline stays alive (it's the Android / no-iPhone fallback) but is NOT iterated on. Composition bugs we were chasing become non-issues on the iOS path because ARKit provides what we were trying to recover.

## Why

Every bug in composition was a bug in *recovering* information ARKit gives for free:

- Gravity: ARKit provides it per frame, sub-degree accurate.
- Scale: ARKit's visual-inertial odometry produces metric-scale poses.
- Per-object orientation: with gravity correct and the camera frame known, SAM 3D's per-object output lands upright without any yaw knob.

The photo-upload composition path was trying to reconstruct, from pixels alone, what a phone's IMU + ARKit was measuring directly. That's never going to be more accurate than the sensor data we were ignoring.

Premium-product framing also pushed this: a flow that says "upload 9 photos and pray the up-axis is right" is not a 2026 product. ARKit RoomPlan is the modern capture surface.

## What would change this decision

- If ARKit's metric scale on non-LiDAR iPhones is worse than expected in practice — possible on iPhones without LiDAR, where scale comes from VIO alone. Would mean UniDepth V2 stays in the iOS pipeline as a scale refiner. Doesn't undo the pivot, just complicates the LiDAR-free tier.
- If iOS distribution turns out to be too hard (App Store rejection, signing friction) and the web-fallback becomes the de-facto primary path again. Would revisit fixing composition properly.
