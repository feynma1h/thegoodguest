# 0046 — P5(a) poll client: two independent start paths, lenient status decode

**Date:** 2026-06-04
**Status:** Decided

> Companion: 0047 — the failed_incomplete recoverable-terminal taxonomy and
> the inner/outer timing-layer reasoning. Read alongside this note.

## Context

P5(a) builds a foreground scene-status poller against the deployed `GET
/scenes/by-bundle/{bundle_id}` endpoint. The poller needs to start as soon as
a bundle upload is complete. Two natural trigger points exist: (1) the moment
`BlobUploadManager.onBundleComplete` fires (inside a background URLSession actor)
and (2) `SceneStatusView.onAppear` (when the user is looking at the screen).

A prior crash (decision 0027) established that a strict enum on the client side
would throw on unrecognised wire values when the backend added new status strings.

FCM push for `ready`/`failed` is currently broken (backend sends to `device_id`,
not `fcm_token`). Polling is the sole completion channel while foregrounded.

## What we tried

**Single-entry kick:** wire `onBundleComplete` to call `start(bundleId:)` directly
on `ScenePoller`. Problem: `onBundleComplete` fires from a background URLSession
delegate (inside `BlobUploadManager`, an actor not on MainActor). The app may be
backgrounded when the kick fires. `URLSession.shared` (the foreground poller) must
not be used from a backgrounded app, and starting a loop while the screen is
invisible is wasteful. Foreground-gating inside `start()` was considered but would
blur the responsibility boundary — `start()` must mean "begin polling now; caller
is responsible for visibility."

## What we chose

Two independent start paths, where the kick is an accelerator only:

1. **A-nudge kick** (`onBundleComplete` → `notifyBundleComplete`): one line in
   `onBundleComplete` — `Task { await MainActor.run { ScenePoller.shared
   .notifyBundleComplete(bundleId:) } }`. `notifyBundleComplete` checks
   `isVisible`; if true, calls `start(bundleId:)`. If backgrounded, it is a
   **no-op** — the `.complete` phase is already persisted to `UploadSessionStore`
   by the time `onBundleComplete` fires (see `BlobUploadManager.handleSuccess`),
   so the kick need not write anything.

2. **Independent onAppear path** (`SceneStatusView`): on appear, scans
   `UploadSessionStore.allBundleIds()` for any record with `uploadPhase ==
   .complete`, calls `start(bundleId:)`. This path works regardless of whether the
   kick fired or the app was backgrounded at upload time.

`start(bundleId:)` retains honest semantics: "begin polling now, caller is
visible." The foreground/backgrounded decision lives in `notifyBundleComplete` and
`onAppear`, not buried inside `start`.

For status decode: `SceneStatus` uses a custom `Decodable` that maps any
unrecognised wire string to `.unknown(raw)` and never throws. Unknown values are
classified as `selfResolvingTransient` (keep polling), which is the safe fallback —
if the backend adds a new in-progress state, the client keeps checking rather than
giving up or crashing.

## Why

- **Reliability**: the independent `onAppear` path means polling starts correctly
  even when the kick is missed (app backgrounded, killed before kick fires, etc.).
  The kick is a latency optimisation for the "user watching the screen" case only.
- **Separation of concerns**: `BlobUploadManager` has one outbound reference to
  `ScenePoller` (via `notifyBundleComplete`), unidirectional, leaf-singleton.
  `ScenePoller` knows nothing about upload mechanics.
- **No hard give-up**: FCM is broken, so the outer loop must never stop on transient
  failures while foregrounded. A 5xx backoff within one tick yields `transientFail`;
  the outer loop keeps polling at the 30 s cap, surfacing a soft "connection
  trouble" note rather than a terminal error.
- **Lenient decode**: matches the 0027 lesson. The six known wire values are
  enumerated; anything else becomes `.unknown(raw)` which the classification maps to
  `selfResolvingTransient`. The `Decodable` init never throws on unknown strings.

## What would change this decision

- **FCM works**: when `fcm_token` is plumbed through `/upload_session` and
  perception-obj sends push to the correct token, the poller can become an
  accelerator (FCM fires → immediate tick, then exponential back-off). The outer
  loop cadence constants may be relaxed.
- **Multiple in-flight bundles**: the current design assumes one active bundle at a
  time (the first `.complete` record found by onAppear). If multi-bundle workflows
  are added, the poller will need a bundleId hand-off mechanism rather than a store
  scan.
- **Backend adds new terminal states**: add them to `SceneStatus` known cases and
  update `classification`. The `.unknown → transient` fallback stays as defence.
