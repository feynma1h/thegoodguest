# 0073 — Relaunch recovery is launch-scoped and acknowledgement-aware

**Date:** 2026-07-25
**Status:** Decided

## Context

Activating `RootFlowView` as the app root (decision 0072) would have lost a
behaviour the old root provided: `ContentView`'s `SceneStatusView` scanned the
upload store at launch for a bundle whose upload had finished while the app was
dead, so a user who force-quit mid-upload still saw their room's status on the
next launch. The activation commit restored it as `restoreUnfinishedBundle()` —
adopt the newest non-`.failed` record, render the home re-entry row from it.

The recovery was right. Its scope was not, and the resulting defect was live on
the activated root: tapping "Done" at the doorway returned the user to a home
screen already saying *"One room is on its way — check on it"* for the room they
had just finished with. A server-side scene failure closed the loop completely —
`processingFailed` → "Later" → home → row → `processingFailed`, with no exit.

Two facts combined, neither obvious from the code:

1. **A `.task` on a `@ViewBuilder` switch branch is not launch-scoped.** The
   restore hung off `homeScreen`'s `.task`, and each `stage` change swaps view
   identity, so returning to `.home` re-runs it. Verified with an instrumented
   build on the simulator: one `home → capture → review → home` round trip ran
   the restore **twice**. `endFlight()` clearing `sentBundleId` was therefore
   undone the instant the user arrived home.
2. **A `.complete` upload record is never deleted.** `onBundleComplete` only
   surfaces the completion; reclaiming the record and session dir is the unbuilt
   terminal-state cleanup (the completed-capture disk-accumulation gap). So from
   the first successful capture onward, every launch re-adopted the newest
   completed record — permanently.

The old docstring's claim — *"any terminal exit clears it"* — was the false
statement holding the design up. `onBundleComplete`'s docstring compounded it by
claiming it reclaims the record, which it does not.

## What we chose

**Both halves. Either alone leaves half the defect.**

1. **A launch-scoped latch** (`didRestoreUnfinished`), so returning home never
   re-runs the restore. This closes the immediate contradiction — every terminal
   exit now sticks for the rest of the launch.
2. **A persisted acknowledgement**, written by `endFlight()` — the one place that
   knows the user is done with a bundle — and consulted by the restore. This
   closes the across-launch resurrection, which the latch cannot touch because
   completed records are permanent.

The acknowledgement lives in **`UserDefaults`, not on `UploadSessionRecord`**.
"The user has finished with this room" is a UI-level fact; the record's decode is
strict and its format is shared with the upload machinery, so adding a field
there would be a persistence-format change with real blast radius for something
the upload path never reads. Retention is bounded (50, oldest-first eviction):
the only entry that can ever be lost is one the user finished with long ago, and
losing it costs a stale row, not data.

The choice itself is a pure function (`BundleRestore.pick`) sitting beside its
persistence seam, pinned by tests — the same treatment `WaitFlowState` got, for
the same reason: a decision spread across a SwiftUI view can only be reviewed by
eye, and this one had already been reviewed by eye and passed.

## Why not the alternatives

- **Restore only non-`.complete` records.** Simplest, and it fixes both symptoms
  — but it deletes the feature. A bundle whose upload finished while the app was
  dead is exactly the case the recovery exists for, and it is `.complete` by
  definition.
- **The latch alone.** Fixes the visible contradiction, so it tests clean in one
  session and looks done. It leaves home advertising a finished room on every
  subsequent launch forever.
- **Delete the record on completion.** The correct long-term answer, and it would
  moot the acknowledgement — but it is the unbuilt terminal-state cleanup, which
  is deliberately coupled to the `.recoverable` re-upload design (deleting a
  completed bundle's files too early strands a re-upload that `failed_incomplete`
  would need). Not a change to make in passing.

## Consequences

- `endFlight()` is now the single point that records user-facing finality; any
  new terminal exit must route through it, which was already the rule.
- When terminal-state cleanup ships and completed records are actually reclaimed,
  the acknowledgement set becomes redundant but stays harmless (it can only skip
  ids that no longer exist). Revisit it then, not before.
- `onBundleComplete`'s docstring is corrected to say what it actually does, with
  the explicit warning that store scans must assume completed records accumulate.

## What would change this decision

- Terminal-state cleanup shipping (records deleted on a genuinely terminal
  backend state) would let the acknowledgement set be dropped.
- A real capture-to-doorway walk on hardware is still owed. The acknowledgement
  WRITE has not run on a device: `DismissedBundles` is unit-tested including
  cross-instance persistence, and the latch is runtime-verified on the simulator,
  but the continuous chain *doorway "Done" → acknowledgement written → next
  launch does not re-adopt* has never been observed end to end, because every
  route to a terminal exit needs a real capture or a real poll result.
