# 0321 — the phone writes the boxes it kept when the capture stops

**Date:** 2026-11-05
**Status:** Decided

## Context

Decision 0320 gave the bundle a place for the person's boxes. Something has to
fill it, and the boxing feature is Debug-only and stays out of Release builds
until the detector is licensed (0295), while `BundleAssembler` and
`CaptureManager` compile into every build.

## What we tried

- Having `BundleAssembler` read the live-boxes session. That would pull a
  Debug-only type into code every build compiles; the boundary test
  (`tools/test_live_boxes_boundaries.py`) exists to forbid exactly that.
- Pushing the boxes into the capture manager every time they change. The
  current box keeps easing toward the detector's fit, so a pushed copy would
  be stale at stop unless it were pushed on every pass.

## What we chose

- `KeptBox` and `PersonBoxWire` (`Capture/PersonBoxes.swift`) are plain,
  always-compiled code that know nothing of live boxes. `CaptureManager` has a
  `keptBoxes` closure that is nil unless the Scan screen's camera layer sets it;
  at `stopCapture()`, before the session pauses, it reads the closure once and
  hands the result to `BundleAssembler`.
- The camera layer answers with `LiveBoxesPresentation.kept(...)`: exactly the
  boxes the screen draws (the finished box, a table reaching to its top), so a
  box the person removed, or that fusion merged away, is not sent. The label is
  the detector's own name for the track, not the vocabulary's label.
- The writer leaves out, never repairs, a box with a non-finite number or a
  side outside 0.05–6 m; keeps the first of a repeated id; and keeps the
  earliest 40 boxes. Left out, not rejected: a bundle that fails loses the
  whole scan. Times are written as microseconds since capture start (0298).

## Why

The seam is the type-free closure, so the Release build contains none of the
feature and the boundary test stays true by construction. Reading at stop gives
the final fit in the poses' own world frame.

## What would change this decision

If the person can keep boxing after pressing Finish (for example in the review),
the read moves to wherever the set is last editable. A licensed detector in
Release builds changes nothing here: the closure is simply set.
