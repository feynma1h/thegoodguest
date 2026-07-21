# 0063 — SAM 3D layout conventions: measured verdict (systematic ~90°) and the fix candidate

**Date:** 2026-07-21
**Status:** Decided (diagnosis recorded; fix deferred to a controlled probe)

## Context

Decision 0052 shipped placement on two flagged assumptions pending runtime
verification: layout quaternions read as (w,x,y,z), and the layout camera
frame taken as CV (+Z fwd/+Y down → `diag(1,-1,-1)` to ARKit), with the
check signal "systematically large gravity_deviation_deg — degrades
orientation, never crashes". The first completed placement run (scene
`25a14caf` re-driven through the envelope-fix revision) delivered the
signal.

## What we tried

1. **Per-observation measurement** from the ready manifest: deviation of
   the layout-derived world-up from gravity for all 21 observations.
   Upright classes (bed/cabinet/chair/lamp): median 102°, range 60–175.
   All six doors: 90–99°. Overall median 91.7°. Systematic, not noise —
   the exact wrong-frame signature 0052 predicted.
2. **Offline convention A/B** on recorded data (raw layout rotations from
   the manifest + camera poses from the preserved bundle), grid of
   {wxyz, xyzw} × {identity, CV `diag(1,-1,-1)`, pytorch3d `diag(-1,1,-1)`}
   × {canonical up +Y, +Z, −Z}, 13 upright observations:
   - current (wxyz, CV, +Y): **96.9°** median upright
   - best (xyzw, identity, +Y): **21.0°**
   - runner-up (xyzw, CV, +Y): 34.2°; everything else ≥77°.

## What we chose

Recorded the diagnosis; did NOT hot-patch `placement.py` in the envelope
session. The fix candidate: SAM 3D's layout rotation behaves as already
(x,y,z,w) with no CV basis change needed. One documented confound blocks
shipping it blind: our export path calls `gs.save_ply` on the raw
canonical gaussians, while Meta's own `make_scene` (notebook/inference.py)
first applies `_fix_gaussian_alignment` — a Y/Z swap-with-flip — before
composing gaussians with the layout rotation. Part or all of the
systematic ~90° may therefore live between the SPLAT frame and the layout
frame, not in the quaternion-order reading; n=13 upright observations
from one room cannot separate the two hypotheses.

## Why

A convention flip that merely looks right on one room can be mirrored on
the next; each live check costs a full GPU cycle. The fix session should
run a controlled probe: re-drive the preserved capture (or one fresh
known-orientation object) under the candidate AND under the
splat-frame-alignment hypothesis, and require BOTH near-zero upright
deviation and a visually correct rendered splat — the two can disagree
exactly when the splat frame is the culprit. Note the blast radius while
this stays open: on the triangulated (ARKIT_ONLY) path, positions and
scales are rotation-independent — the assembled room stands, objects may
render rotated. The LiDAR `depth_fit` path DOES consume the world
rotation inside the fit, so LiDAR-tier placements should not be trusted
until this closes (that path is hardware-parked anyway, board item 3).

## What would change this decision

The controlled probe closing the diagnosis into a verified convention —
then 0052's placement docstring and `LAYOUT_QUAT_ORDER` /
`_SAM3D_CAM_TO_ARKIT_CAM` get updated together with a regression pin on
real data.
