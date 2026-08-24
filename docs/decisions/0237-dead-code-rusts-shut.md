# 0237 — dead code rusts shut rather than staying ready

**Date:** 2026-08-24
**Status:** Decided

## Context

Decision 0072 activated `RootFlowView` as the app root and kept the previous
root — `ContentView`, plus `SceneStatusView` and `UploadFailureView`, the two
views it alone mounted — compilable but unreferenced, so the pre-Good-Guest
design could be restored if the new one failed on hardware.

That was the right call in July. The design was an 11-screen spec that had
never run on a device, and the cost of the hedge was 719 lines nobody had to
look at.

## What we tried

Keeping it, for thirteen months of product time. The hedge was never exercised.

What it cost instead is measurable. The design absorbed RP-6, RP-7, the Live
Activity, Google linking, the flight stand-down and the scenes client without
anyone reaching for the rollback. Over the same period **four separate lanes
edited the retained path** — because it compiles, so it appears in greps, in
"find usages", and in any sweep that changes a shared type. Decision 0217
applied a real behavioural fix plus a seven-line explanatory comment to
`SceneStatusView.notOwnedView`, a screen no build can reach and no user will
ever see.

The docstrings drifted the same way. Twenty-five sites across fourteen files
described the live flow *by contrast with the dead one* — "KEY BEHAVIORAL
CHANGE vs the old ContentView", "the same seam SceneStatusView uses",
"Mirrors what UploadFailureView does" — so reading the shipping code meant
holding a deleted screen in your head.

## What we chose

Delete it: the three views, `SceneStatusViewTests`, and the four
`newestCompleted` assertions in `ScenePollExpectationTests`, whose only subject
was a static helper on a deleted view. No `project.pbxproj` edit — the targets
use file-system synchronized groups.

The docstrings go in the same commit, each rewritten to say what the code does
rather than what it replaced.

Two comment references survive in `Upload/BlobUploadManager.swift` (lines 1320
and 1474). They are stale and should be reworded, but that file belongs to the
upload-flake lane, which is actively adding a completion seam to it. Handed
back rather than merged into.

## Why

**A rollback path is only a rollback path while someone could actually run it.**
What decays is not the code — it still compiles — but the evidence that it
works. Every shared type it touches moves under it; every fix applied to it is
applied blind, because no build exercises it and no test covers what it renders.
After enough of that, restoring it would be a port, not a revert, and nobody
would choose it under the pressure that a rollback exists for.

So the honest accounting is that the hedge stopped being an asset well before it
was deleted, and continued to charge rent: four lanes' attention, twenty-five
misleading docstrings, and a fix that went to a dead screen while the live one
kept its bug. **Retention has a running cost and a decaying value, and the
crossing point is much earlier than it feels.**

The suite drops **600 → 590**, which is correct rather than a regression:
`SceneStatusViewTests` was 6 tests and the `newestCompleted` table 4. The honest
form is now **584 asserting offline + 2 boilerplate stubs + 4 live integration**.
It is stated here, in CLAUDE.md and in the deleting commit, because two other
iOS lanes re-measure against this number and a bare drop reads as a break.

## What would change this decision

Nothing about the ruling. What generalises is the test: **when a fallback has
survived several waves of change without being exercised, ask what it would take
to actually run it today.** If the answer is "a port", it is not a fallback any
more and should be deleted while the deletion is still cheap. Its content is
recoverable from git; what is not recoverable is the belief that it works.
