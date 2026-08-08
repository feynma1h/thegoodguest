# 0111 — The Live Activity had no way to say the send finished

**Date:** 2026-08-08
**Status:** accepted
**Relates to:** 0085 (the walk that saw the card), 0110 (the stall the same card
narrated wrongly), 0072 (the Good Guest surfaces), 0040 (bundle.pb goes last)

## What was observed

Decision 0085, defect 3: a Lock Screen card reading **"Sending your room 331 of
331"** — a completed count still labelled in progress — from a capture that
predated the sitting. 0085 listed mechanism candidates and explicitly declined
to call any of them a diagnosis.

## The mechanism

The card is fed from two places that cannot see each other, and **only one of
them runs while the app is closed**:

| Feeder | Reaches the card when app is closed? | Stages it can publish |
|---|---|---|
| `BlobUploadManager` (background URLSession) | **yes** — `nsurlsessiond` outlives the process | `.sending`, `.paused`, `.failed(.upload)` |
| `RootFlowView` (poller / routing) | no — foreground only | everything else, plus `begin`/`end`/`reconcile` |

`onBundleComplete` — the exact moment the send finishes — **published nothing at
all.** It notified `ScenePoller` and `UploadFailureMonitor` and returned. So on
the happy path with the app closed, the last thing ever published was
`.sending(sent: N, total: N)`, and `RoomActivityVoice` renders that as
"Sending your room" + "N of N". Nothing could move it afterwards:

- `.staleAfter` (45 min) only *dims* a card; it does not correct it.
- `terminalDwell` never applied, because no terminal stage was ever reached.
- `end()` and `noteWaitScreen()` live in `RootFlowView`.

So the card was not stale in the ordinary sense of losing an update. **It was
showing the last true thing the phone told it, forever**, because the vocabulary
had no word for "done" that the background path could reach.

### Why it outlived the capture

`reconcileOnLaunch(restoredBundleId:)` **adopts** the card belonging to the
bundle the launch restore picks, and the restore's inventory is exactly the
`.complete`-but-unacknowledged records. So a launch adopts the finished
capture's card, sets `currentStage = nil`, and then publishes nothing — the
upload is long over and the user never entered the wait flow. Adopted and
abandoned. The adoption is right (its background upload can still be running);
having nothing to say afterwards was the bug.

## What changed

**Two new publishes, one new stage, one new merge rule.**

1. `.finalizing` — published by `enqueueBundlePb` when the `bundle.pb` task is
   created. Every part of the room is up; only the ~51 KB finalize is
   outstanding. True whether that task ships in two seconds or is held twenty
   minutes by the rate limiter in 0110 — which is the point: **the card states
   what is known, it does not predict the OS.**
2. `.queued` — published by `onBundleComplete` when `bundle.pb` lands. The
   capture now exists server-side and is waiting for the pipeline. This is the
   honest end of what a closed phone can know; past it, the poller is required,
   and that boundary was already documented on `RoomActivityAttributes`.
3. The **no-reopening rule** in `LiveActivityPolicy.merge`: a `.sending` never
   lands on a stage already past the upload. Blob completions keep arriving
   after the Phase-1 gate fires (cancelled siblings, redelivered events), and a
   late `.sending(N, N)` would have reopened the upload on a card that had moved
   on — reintroducing the exact defect. The existing sticky rule only guarded
   terminals, and neither `.finalizing` nor `.queued` is terminal.

The card now narrates `preparing → sending → finalizing → queued` with the app
never opened, and `analyzing → ready` once it is.

## Why `.finalizing` rather than reusing `.paused`

`.paused` was tempting: its copy ("I'll pick it up next time you open me") is
almost exactly the remedy for 0110's rate limiter, since foregrounding resets
the delay to zero. It was rejected because **it requires predicting which branch
we are in.** The delay is zero if the user foregrounded recently, so a
background-enqueued finalize often ships immediately; announcing "Paused" and
then completing two seconds later is a lie in the other direction, and we have
no way to read the current delay. `.finalizing` is true in both branches and
names the resetting action without claiming the transfer has stopped.

## Instrumentation

Per the charter, the leaves are now breadcrumbed rather than reasoned about
(`liveactivity-publish`, `liveactivity-drop`, `liveactivity-reconcile`,
`liveactivity-end` — DEBUG only, file-based per the Anomaly-B lesson). Drops are
de-duplicated by signature: a card that is not adopted would otherwise write one
line per blob completion, ~2,170 of them on a long walk.

The drop breadcrumb is the one that matters. `apply` silently discards any
update whose bundle is not the adopted one, which is the invariant protecting
against a card narrating the wrong capture (0074, and the stale doorway before
it) — but it is also the one path that can swallow the new publishes if a
background relaunch enqueues `bundle.pb` before `reconcileOnLaunch` has run.
That race already existed for progress updates and 0085 measured it working
(the card reached 751 of 751 in a background-relaunched process), so it is
recorded and watched rather than redesigned.

## What was verified, and how

Through **real ActivityKit on the simulator**, not through the test seam: an
activity was started and driven to each new stage, then the Lock Screen and
Dynamic Island were screenshotted.

- `.finalizing` on the Lock Screen: "Signing it in / The whole room is up. Open
  me if it sits a while.", rust mark, **no counter**, one line, no truncation.
  The absent counter is the fix — a count here would be the original defect.
- `.queued` in the Dynamic Island after `noteUploadComplete`: rust clock + `···`.

Collateral, and worth recording because it cost a probe: the first attempt
produced **no card at all** despite the widget extension launching. The harness
had lost a race to `restoreUnfinishedBundle`, which on a device with no records
calls `reconcileOnLaunch(nil)` → `endAllOrphans(keeping: nil)` → ends every
activity. That is `endAllOrphans` working exactly as written, and it is the
first time that path has been observed against real ActivityKit.

A copy note from the same pass: the voice tests bound a line at 70 characters,
but the longest line ever shipped is ~49, so the bound had never been exercised
near its limit. The first draft of the `.finalizing` line was 63 and was
shortened rather than trusted to a number no screenshot had backed. The bound's
comment now says so.

## What stays unverified

Whether these publishes reach a real Lock Screen **with the process fully dead**
is still open. 0085's own attempt was confounded (the OS relaunched the app 94 s
in), and the simulator cannot answer it — ActivityKit renders there, but the
background-relaunch path does not occur. The unit tests pin that the publishes
happen and that the merge rule holds; the breadcrumbs are in place for the next
device sitting to pin where they land.

Also unverified: whether `.finalizing` survives the launch race described above
on a real background relaunch, or is dropped because the card has not been
adopted yet. If it is dropped, the card holds `.sending(N, N)` until
`noteUploadComplete` — degraded, but no worse than before, and the
`liveactivity-drop` breadcrumb will say so plainly.
