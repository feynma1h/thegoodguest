# 0354 — Hints and colour corrections are kept only when rendering them improves the match

**Date:** 2026-11-05
**Status:** Decided — thresholds are proposed and must be calibrated on the cloud renderer

## What we chose

`gates.py` and `finish_pass.py`. Each hint group (baseboard, wainscot, floor, door, window) is rendered ALONE on top of the measured finish and compared to the same photos with `finish_compare.calibrate`. It is kept only if the summed |dL| over regions measurable in both renders falls by at least 0.5 L and no region worsens by more than 1.0 L. The wainscot also has to claim a height within 5 cm of the edge the atlases show (and not further from it than the measurement alone). Up to two rounds of colour fold-in follow, each step clamped to 4 L and 3 in chroma and kept only if the residual falls. The result records what was rejected and why, and the residual before and after. The scene's `lightness_offset` (median signed dL after calibration) is stored for the furniture gate.

## What is not done

Structure overlap is checked only for the wainscot; baseboard, floor slabs, door panels and window glass pass only if a colour region they touch improves, so a true baseboard hint can be rejected as "not measurable" (the safe error: measured finish stays). The dollhouse-view lightness regression check is not implemented.

## Why

The finish is allowed to be wrong only by being plainer. Rendering one hint at a time attributes the change to the hint.

## What would change this decision

Calibration on 2-3 scenes with SwiftShader (the design's GL-backend noise is up to ~1 L).
