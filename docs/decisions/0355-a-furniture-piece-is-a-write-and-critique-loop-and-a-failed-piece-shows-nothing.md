# 0355 — A furniture piece is a write-and-critique loop, and a failed piece shows nothing

**Date:** 2026-11-05
**Status:** Decided — thresholds proposed

## What we chose

`piece_loop.py`: evidence (best frames of the person's box via the package, masked capped crops) -> Claude writes a spec -> the package places it on the box by rule -> the renderer draws it from the evidence frames -> numbers inside the render's own silhouette -> Claude sees photo|render and edits or says done. Three numbers, medians over frames: |dL| after the scene lightness offset (whites render lighter than photos, so the loop is not made to darken everything), the a,b distance (hue and chroma compared exactly), and the gap (1 - IoU of the silhouette's box and the object's projected box). An edit is accepted only if none gets worse by more than 1.0 L / 1.0 / 0.02. The loop ends at 6 edits, 2 rejected in a row, 2 accepted edits gaining under 0.3 L, "done", the deadline, or the spend ceiling, and keeps the best accepted model.

The operator decided that a failed piece shows NOTHING, so there is no stand-in block (the design had one). A piece fails when no frame is usable with people masked out, when Claude gives no valid model after one re-ask, when the first model cannot be placed or rendered (one retry in a fresh renderer), when its silhouette never overlaps the box, or when the first gap is above 0.35 ("placement uncertain": a twin visibly off its object is worse than none). That last threshold is the one most likely to be too strict; it is a constant.

## Why

Keeping the best accepted model means an error late in the loop costs the polish, not the piece.

## What would change this decision

Calibration against real phone-made boxes, whose placement error is unmeasured.
