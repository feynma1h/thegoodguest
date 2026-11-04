# 0301 — live boxes ride the capture's own session

**Date:** 2026-11-05
**Status:** Decided — Debug builds only, because the detector is AGPL-3.0 (0295); Release, TestFlight and App Store builds carry none of it

Supersedes 0297. Amends nothing else: 0295's licence boundary, 0296's lift and 0299/0300's
glass route all stand and are what runs.

## Context

0297 kept live boxes out of the capture flow: the review ran its own ARSession, and starting
one stops the capture's, so it opened only from the Home Screen and was refused anywhere
between Scan and review. That made them a measuring instrument, not a feature. The operator's
direction since is that live boxes belong DURING the scan: the person sees what the detector
found as they walk the room, taps an object to box it, and walks round it to improve the box.
Boxed objects will later get furniture models made for them; unboxed objects drop out of the
room; the expensive 3D reconstruction of an object the person boxed can be skipped. None of
that is built here — this note is only about where the detector runs.

## What we tried

A spare session was never an option: one ARSession exists per scan, and the scan is the
product. The alternative to riding it was a second one, which would have stopped the scan.

The first version of riding it was a throwaway build for a demonstration, installed on the
operator's phone. The bundle is built by `CaptureManager` exactly as before; what the detector
costs the scan on a real walk — heat, memory, RoomPlan ending early, a phone without a Pro
chip — was left for the operator to judge and is not written down. This note keeps what that
build was for and none of its scaffolding.

## What we chose

- **The capture owns the session; the detector reads it.** `CaptureManager` forwards each
  frame and each tracking-state change from its own `ARSessionDelegate` to
  `LiveBoxesFrameDriver` (`CaptureManager.frameTap`). `LiveBoxesSession` never starts, pauses
  or reconfigures ARKit; `CaptureSessionSetup` (0066, 0076, 0079) is the capture's alone, and
  the capture's depth guard is the only one.
- **Nothing enters the bundle.** Boxes and the stills on the strip live in memory on the
  screen. A scan with live boxes produces the bundle a scan without them does.
- **One feature switch** (`LiveBoxesFeature.isEnabled`, a code constant, default ON) decides
  whether a Debug build shows the camera layer and starts the detector. OFF, the Scan screen is
  the stock one. Debug-only compilation is the licence boundary, not this switch.
- **Depth is LiDAR where the phone has it, otherwise a depth model**: Depth Anything v2 Small
  (`DepthPolicy`). v3's code stays and is switched off by `DepthPolicy.allowsDepthAnything3`,
  because on the operator's depth walks v2 beat v3.
- **No RoomPlan box is used for what the person boxes.** `RoomPlanClasses.boxedByRoomPlan` is
  false: the detector lifts RoomPlan's own categories itself, and the comparison with
  RoomPlan's boxes is wired but off.

## Why

**The scan is where the person is.** A review afterwards asks them to remember the room; a dot
on the object while they stand beside it asks for a tap.

**Riding is the only honest measurement.** Heat, memory and frame rate described by a second
session describe a lookalike. The session log records them for the real scan.

**The licence is unchanged.** The model is private use on the operator's phone; a distributed
build needs an Ultralytics Enterprise License (0295). Compiling the feature only under
`#if DEBUG` is what makes Release carry none of it, and `tools/test_live_boxes_boundaries.py`
pins that, including that the two capture files name the feature only inside `#if DEBUG`.

## What would change this decision

- **A licence that allows distribution** (or a commercially licensed detector with comparable
  measured speed) makes the feature a product choice; the Debug guard and the Release model
  exclusion become a decision about Release.
- **A walk that shows the detector costs the scan something** — RoomPlan ending early, heat
  reaching serious before the room is done, a non-Pro iPhone struggling — would make the
  switch default OFF or the pass rate lower. Those walks are not written down: what this note
  rests on is the synthetic acceptance (0296) and the depth walks, not a measured scan.
