# 0078 — Same-turn RoomPlan co-run attach loses sceneDepth; frame-observed re-assert is the production guard

**Date:** 2026-08-05
**Status:** Decided (conditions decision 0076's Q1 verdict; does not overturn it)

## Context

RP-6 wired 0076's co-run into production `CaptureManager`: production config
runs first with `.resetTracking`, then `RoomCaptureSession(arSession:)`
attaches — in the SAME runloop turn, inside `startCapture()`. The first
hardware capture on this build (`f126714d`, iPhone 16 Pro, iOS 26.5.2)
shipped 268 frames with `frame.sceneDepth` nil on **every one** — not
dropouts, a total loss from t0, discovered only when the uploaded bundle.pb
was parsed server-side (0 of 268 frames carried the depth field; no depth/
or confidence/ blobs existed to upload). July's pre-co-run captures on the
same phone carried 292/293 and 128/128.

The 0076 spike never saw this because it structurally couldn't: its attach
always followed the production run by human seconds (an operator button
tap), and its rp-first mode never ran the production config at all. **Q1's
"co-run does not strip sceneDepth" verdict holds for a settled-config
attach; the same-turn attach is a third condition the spike did not
probe.** The exact mechanism inside RoomPlan's config composition is not
observable from the app; we did not guess at it.

## What we chose

Not a timing fix — a ground-truth guard. `RoomPlanWire.shouldReassertDepth`
(pure, table-pinned) watches actual frames and fires **once** iff a LiDAR
session has NEVER delivered depth after 10 frames (~0.17 s at 60 fps —
past any boot edge, before meaningful coverage is lost). The cure it fires
is 0076's own measured-survivable re-assert probe, verbatim: take the
INSTALLED configuration, re-insert `.sceneDepth`, `run(options: [])` — the
spike measured that a mid-scan re-run neither kills the scan nor the
census, and the room still builds.

Guard shape matters: depth-ever-seen is the latch, so the legal mid-walk
single-frame dropout class (0033; observed again on both post-fix
captures) can never trigger a config re-run, and the one-shot flag means a
genuinely depth-less environment degrades quietly rather than thrashing.

Hardware-verified same day: the next two captures carried 247/249 and
123/124 frames with depth (the missing ones are the pre-re-assert boot
frames plus one legal dropout). Attach-time `frameSemantics` logging and a
keyframes-with-depth stop log now make this failure readable off a console
instead of requiring a server-side bundle parse.

## What we tried / rejected

- **Delaying the attach** (defer RoomCaptureSession to "after the config
  settles"): rejected — there is no observable settle signal to key on, so
  any delay is a guessed constant that would re-break under load variance,
  and the spike's evidence says a later attach works *when it is later*,
  not how late is late enough.
- **Attaching on first frame arrival**: rejected — adds latency to every
  capture to prevent a condition that is directly observable per-frame and
  curable in-place; and it would still be a timing heuristic, just a
  cleverer one.
- **Treating the depth loss as acceptable on the ROOMPLAN tier** (RoomPlan
  feeds itself internally and the room still built): rejected — the tier's
  wire contract is "ARKit + LiDAR sceneDepth + RoomPlan"; depth_fit is the
  measured placement workhorse (16/23 on the first LiDAR capture) and the
  long tail depends on it.

## What would change this decision

- An iOS update changing RoomPlan's config composition re-opens 0076 Q1–Q3
  wholesale (the spike app re-runs in an afternoon); this guard is
  self-verifying either way — if the same-turn attach stops losing depth,
  the guard simply never fires (watch for the `reasserted=true` stop log
  disappearing across captures).
- The guard firing on captures where depth then STILL doesn't arrive
  would mean a different loss mechanism — that is a new investigation, not
  a threshold tweak.
