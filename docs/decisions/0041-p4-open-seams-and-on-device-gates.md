# 0041 — P4 open seams and on-device verification gates (tracking note)

**Date:** 2026-06-01
**Status:** Open — tracking-only (no decision reversed here)

## Context

P4 (0040) is being built in units. Three code seams are stubbed and two on-device checks
cannot be verified in simulator. This note makes that state durable so a session handoff
(Chat or Code) loses nothing.

## Open code seams (each its own Chat-scoped unit; do NOT wire silently)

- `onAllBlobsUploaded(bundleId:record:)` — bundle.pb finalize. IN PROGRESS (this unit).
- `onSessionExpired(bundleId:)` — 410 Gone → re-mint via `/upload_session` (path-set
  idempotent), persist fresh URIs (0037), restart affected blobs. NOT BUILT.
- `onFatalBlobError(bundleId:relativePath:reason:)` — surface terminal blob failure to
  UI/FCM. NOT BUILT; ties into P5.

## On-device verification gates (MUST pass before the app's first real upload; invisible in simulator)

- **Content-Type wire-check:** confirm `uploadTask(fromFile:)` sends NO `Content-Type`,
  and that `Content-Range` + headers pass GCS validation against a live resumable session
  URI (F2).
- **Discretionary-task check:** a background-session upload enqueued while the app is
  already backgrounded — or re-enqueued on background relaunch (the resume path) — can be
  treated as discretionary regardless of `isDiscretionary=false`, and deferred on
  battery/network heuristics. Confirm relaunch-resumed uploads actually progress, not just
  foreground-initiated ones.

## Also gating first real upload (from CLAUDE.md)

- 24h post-deploy smoke soak (CLAUDE.md "What does NOT work") must be green first.

## What would change this note

Each seam closes when its unit ships (flip the line). Note is deletable once all three
seams are built and both on-device gates have passed on hardware.
