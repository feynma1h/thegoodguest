# 0364 — every iPhone scans

**Date:** 2026-11-10
**Status:** Decided

Reverses 0072's LiDAR-only client, which rested on 0071's Pro-first fork.

## Context

Since 0072 a phone without LiDAR could install the app and was then turned away
at the root by `UnsupportedDeviceView`. On 2026-11-10 the operator ruled that
the app is for every iPhone, and that Pro phones give the better scan. The
capture stack already records a camera-only tier (`ARKIT_ONLY`), and the server
has always accepted every tier; the gate was on the client only.

## What we tried

Nothing new was measured for this. The camera-only path is the capture stack's
existing tier with the runtime gate removed. The redesign review listed what a
camera-only scan gives up: no RoomPlan, so no live floor plan and no structure
census on the phone; walls are worked out from the photos after the send; sizes
are less exact. And the server's camera-only room path — the `ARKIT_ONLY` shell,
which 0077 calls legacy and fixtures-only — has never run on a real capture.

## What we chose

The gate is gone. `LiDARGate.isSupported` stays as the one runtime check, and it
now decides which way a phone measures and which words the screens use: the
guidance names the phone's sensor, the scan says "Measuring with the camera",
and review says "Measured with the camera" where a LiDAR scan shows its plan.
There is no install-time capability gate (`UIRequiredDeviceCapabilities`), and
there must not be one.

## Why

A product people are asked to try cannot refuse most of their phones. The honest
form of "Pro phones scan better" is a camera-only scan that says what it is, not
a locked door.

## What would change this decision

If camera-only scans turn out too poor to rebuild a room worth opening, the
answer is still not a gate: it is a plain statement before the walk, and a
measured threshold for what the server accepts. The first real camera-only scan
is also the first real run of the server's camera-only shell path, and is the
measurement to take.
