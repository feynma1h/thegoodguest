# 0114 — Force-quit is not OS-kill: the background-relaunch race cannot occur on the path we kept testing

**Date:** 2026-08-13
**Status:** Decided — measured on hardware (iPhone 16 Pro, iOS 26.5.2)

## Context

Two open items assumed the same staging recipe. Decision 0111 shipped a
`.finalizing` stage plus a no-reopening merge rule so a late `.sending`
could never land on a stage past the upload — a guard whose whole purpose
is a race between the foreground process and a **background-relaunched**
one. Board item 2 separately owed the OS-kill hardware gate. Both were
described as "verify with the app not running", and the obvious way to get
the app not running is to force-quit it.

## What we tried

A 583-path LIDAR_ROOMPLAN capture (`8e903997`) was sent home, then
force-quit ~90 s into the upload with the phone locked and left untouched
for 30+ minutes. The server side was polled throughout; afterwards the
`StagingHooks` breadcrumb file was pulled off the device
(`devicectl … --domain-type appDataContainer`), which is the evidence
channel 0084 built precisely because os_log buffers under suspension.

Measured:

- **554 of 583 blobs uploaded with no app process alive.** The daemon
  completed every task the foreground process had already created.
- **Zero background relaunches.** The breadcrumb log's last line is
  `06:22:17Z liveactivity-publish sending 8e903997` — the publish from
  before the force-quit. Nothing was appended for the entire window, so no
  `app-init`, no `app-task-rehydrate-fired`, no delegate callback ran.
- The ~28 never-created tasks (27 frames + `bundle.pb`) simply did not
  exist, so the upload could not finish.
- The Lock Screen card read **"Sending your room 35 of 582"** — the word
  honest, the count frozen at the moment of death.
- One foreground open finished everything: buffered completions
  burst-delivered, reconciliation created the missing tasks, `bundle.pb`
  landed and the scene was `queued` within ~2 minutes.

## What we chose

Record the distinction rather than treat the run as a failed gate:
**force-quit and OS-kill are different states, and only OS-kill produces
background relaunches.** iOS deliberately does not relaunch a
user-terminated app for background URLSession events; the user's swipe is
read as intent. So the `.finalizing`-across-background-relaunch race is an
**OS-kill-only** phenomenon and cannot be staged by force-quitting. Board
item 2's OS-kill gate keeps its `StagingHooks` route (`exit(0)` after N
completions, which is a kill, not a user termination) as the only way to
reach it.

## Why

The evidence is decisive in a way a partial observation would not have
been: the breadcrumb file is written by *our* code on every publish and
every launch, so its silence is positive evidence that no process ran —
not merely that we failed to notice one. That converts an ambiguous
"nothing happened" into a measured fact about iOS behaviour, and it means
any future session that force-quits to test the race would be testing
nothing while believing otherwise.

It also correctly scopes the Live Activity finding. The frozen count is
not the 0111 gap resurfacing — 0111 closed the case where the app *does*
run and the card's last word is wrong. Here no process exists to hear the
519 remaining callbacks, and no local mechanism can fix that. The cure is
the already-named `LiveActivityController.pushTokenSeam` (remote push
updates), which now has its first hardware measurement attached rather
than being a theoretical nicety.

## What would change this decision

- **A background relaunch is ever observed after a genuine force-quit**
  (an `app-init` breadcrumb with no user action) — that would contradict
  the documented contract and reopen everything here.
- **The push seam ships**: the count stops depending on a live process,
  and the "honest word, frozen count" compromise stops being the ceiling.
- **A future iOS changes the force-quit contract.** Apple has moved this
  boundary before; the breadcrumb channel is the instrument that would
  detect it, so re-run this exact recipe on a major OS bump.
