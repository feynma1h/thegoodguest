# 0217 — the declaration is the stand-down

**Date:** 2026-08-21
**Status:** Decided

## Context

The scene status surface could render the previous capture's "Room ready" for
the whole of a fresh capture's upload. `ScenePoller` preserves terminal state
by design — that is what lets a resumed screen render instantly instead of
blanking — and nothing dropped it when the next bundle started going up. The
upload path writes poll state only at its very end, so the window is the whole
upload: about a minute on a real capture.

Worth recording, because CLAUDE.md's residue entry read as though users were
being lied to: **the defect was on the retained rollback path only.**
`SceneStatusView` is mounted by `ContentView`, and `ContentView` is
unreferenced — `RootFlowView` is the app root, and its `sendItHome` already
resets the poller synchronously before the send. So no shipped build could show
this. It was a lie in code kept compilable for a rollback, which is exactly the
code where a lie survives longest, because nobody looks at it.

## What we tried

Three places the drop could live.

- **At each send site**, mirroring `sendItHome`: `reset()` then
  `expectBundle(id)`. Correct, and it is what the shipped root does. But it is a
  rule spelled out per site, in an order that matters — `reset()` clears the
  expectation, so the old doc-comment had to say "call AFTER reset()". A rule
  spelled at each site is a rule the next site can be written without, which is
  how this one came to be missing in the first place.
- **A guard in the view**: refuse to render when `currentBundleId` disagrees
  with `expectedBundleId`. Rejected. With the drop happening at the source the
  guard can never fire, so it is defensive code that is dead by construction;
  and RootFlowView already carries the finding that two surfaces deriving one
  capture two ways is how they come to disagree.
- **In `expectBundle` itself**, which is what shipped.

## What we chose

Declaring a flight for a DIFFERENT bundle drops what the previous one
published. Re-declaring the bundle already in flight does not, and clearing to
nil does not — either would kill the live poll of the room being waited on, and
both are pinned.

`ContentView` now declares the flight and nothing else. `sendItHome` is
untouched: its `reset()` is a full per-send teardown, of which the poller is one
part, and it arrives at the declaration with nothing left to drop.

The same surface's launch scan had a quieter version of the same lie — it
adopted whichever completed bundle `allBundleIds()` listed first, and that order
is not promised — so it now takes the newest by mint time. Still completed-only:
a record still uploading has no Scene document, and polling it reads "Queued for
processing" for the whole upload. That is why it cannot defer to
`BundleRestore.pick`, which admits in-flight records on purpose because the home
re-entry row it feeds is a pointer rather than a claim about progress.

## Why

`notifyBundleComplete` already makes this judgment on the way in: a completion
for a bundle that is not the flight is ignored. The outbound half is the same
sentence — state published for a bundle that is not the flight is the previous
room's — so putting it at the same seam makes one rule instead of two, and
removes the ordering hazard rather than documenting it.

The pins are written to fail against the old code, which is the only reason to
trust them: three of them do, and the two that guard against overreach pass
either way.

## What would change this decision

A surface that legitimately narrates a bundle other than the current flight —
a rooms list, or a history screen showing several captures at once. Those read
scenes rather than the poller, so they do not conflict; but if one ever wanted
the poller for a non-flight bundle, the flight would stop being the right thing
for `expectBundle` to key on.
