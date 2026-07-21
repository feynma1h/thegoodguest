# 0060 — stranded scenes: platform-queued retries can't reclaim; out-of-band re-enqueue is the cure

**Date:** 2026-07-21
**Status:** Decided

## Context

The 0011/0012 stuck-scene machinery assumes every failure mode ends with a
Cloud Tasks retry REACHING the app, where `claim()` reclaims a stale lease.
Scene `25a14caf` (the first real capture) falsified that assumption: its
first attempt outlived the 900 s Cloud Run request timeout, and because the
service runs `--no-cpu-throttling` with concurrency=1, the handler thread
kept computing after the platform cut the request — holding the single
concurrency slot. All three Cloud Tasks attempts 504'd **platform-side**
(13:04, 13:20, 13:36Z; each exactly ~900 s) without one retry ever reaching
the app. When the zombie instance was idle-reaped ~14:01Z (last log
mid-frame-22; no SIGTERM reset fired — the scene stayed `processing`, so
the reset either never ran or never landed), the scene was permanently
stranded: status `processing`, lease expired 13:15Z, Cloud Tasks queue
empty. Nothing in-band would ever touch it again.

## What we tried

Log forensics only — the state was unambiguous (request log: 3×504;
app log silence after 14:01:34Z; empty `perception-dispatch` queue;
`attempt_count: 0` on the doc). No in-band mechanism was attempted because
none can work: recovery lives at `claim()`, and `claim()` only runs when a
request arrives.

## What we chose

Two-sided fix:

1. **Prevention (in-band):** the request-budget tracker
   (`services/perception-obj/budget.py`, wired through
   `process_receiver.run_perception`) makes every attempt finish INSIDE the
   request window — degraded-but-ready beats a zombie. The zombie route is
   closed for future scenes.
2. **Cure (out-of-band):** `tools/reenqueue_scene.py` — operator tool that
   resets the scene doc to `queued` (transactional; status re-checked inside
   the transaction) and creates a fresh Cloud Tasks task mirroring
   api-internal's dispatcher (OIDC token, dispatch_deadline 930 s). The task
   name gets a timestamp suffix because Cloud Tasks tombstones completed
   task names (~1 h): a bare `{scene_id}` re-enqueue soon after the original
   attempts would be silently deduped into nothing.

Guards in the tool: live-lease `processing` and `ready` scenes refuse
without `--force`; `queued`/`failed`/expired-lease `processing` proceed.
Bundle blob existence is checked first (captures bucket has a 1-day
lifecycle rule; the error message says to re-upload the preserved capture).

## Why

The failure mode is structural, not incidental: any attempt that exceeds
the request timeout on a concurrency=1, always-allocated-CPU service will
consume ALL platform retries without the app seeing one. maxAttempts=3 and
dispatch_deadline=930 s (0003) were designed so retries never overlap a
live attempt — which also means a stuck attempt eats the whole retry
budget. An operator-run re-drive is the only correct lever for scenes
already stranded, and it doubles as the deliberate re-drive path for
preserved captures (`--force` on a `ready` scene).

## What would change this decision

If Cloud Run gains per-request cancellation that actually kills the handler
thread (or the service moves off concurrency=1), the zombie route changes
shape and the prevention half should be revisited. The cure tool stays
useful regardless — any future stranding cause lands in the same
`processing`+expired-lease+empty-queue state.
