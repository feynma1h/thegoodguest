# 0075 — LiDAR adjudication: merge knobs measured correct; the defects are admission, closure, and instrument variance

**Date:** 2026-07-28
**Status:** Decided

## Context

The first two LiDAR rooms (247003de, 13bae607) read "very far from reality"
to the operator, and the recorded suspicions pointed at the fusion and shell
merge knobs: `FUSION_CLUSTER_DIST_M` (bed×3/desk×3/rug×3 looked like
under-merge) and `SHELL_WALL_MERGE_*` (14 walls where the reference room
had 7). The knob-tuning temptation was explicit — and 0067 had already
caught one session tuning a threshold when the real cause was structural.

## What we tried

Full offline replication instead of tuning (brief:
`docs/briefs/lidar-first-rooms-adjudication.md`): production's cluster
membership recovered exactly; the footprint-join decisions recomputed with
the repo's own `score_tier1_containment` (0.5998 joined / 0.3144 refused on
the same physical bed); both shells reproduced wall-for-wall from the
preserved bundles under the serving env knobs; every wall pair measured for
normal angle / coplanar offset / lateral gap (the 0066 method); the suspect
detections identified by mask overlay on the capture RGB.

## What we chose

No knob changes. The knobs measured CORRECT on both rooms:

- The "duplicate" objects are mostly distinct physical objects sharing a SAM
  label (stool + folding table both "desk"; three textiles all "rug") — no
  cluster distance should merge them. The one true phantom (an
  edge-truncated bed view) fails the footprint instrument at 0.31 vs the
  0.5 threshold — structural under truncation+occlusion, not a near-miss;
  meanwhile proximity can never bridge visible-region scatter (0.5–1.2 m
  per-view center spread on a 2 m object, in any direction — the recorded
  "near-face" hypothesis corrected).
- The 10 (resp. 6) extra walls sit at coplanar offsets 0.44–3.4 m from the
  envelope planes: genuinely distinct furniture/door planes (bed side rails
  are ARKit-classified `seat` in BOTH rooms). No `SHELL_WALL_MERGE_*`
  setting can merge them, and none should. The actual defects are ADMISSION
  (any vertical anchor ≥ 0.3 m² becomes a wall, ignoring ARKit's own
  classification and height-reach), CLOSURE (furniture-height planes
  inflated to full-height slabs, +2.48 m worst case), and floor CLIPPING
  (compounding half-plane cuts against furniture "walls" ship 12% / 38% of
  the measured floor). The envelope itself is near-perfect — rectangular to
  ≤1.1°, and the envelope-intersection floor plan (4.20 × 3.29 m) was
  operator-confirmed against the real room.

## Why

Tuning `FUSION_CLUSTER_DIST_M` up merges the stool into the folding table;
tuning `PLACEMENT_FOOTPRINT_MIN` down to admit 0.31 admits near-anything;
widening `SHELL_WALL_COPLANAR_TOL_M` to swallow 0.44 m offsets merges real
distinct geometry. Every symptom traces to a mechanism the knobs don't
govern: label-space collapse, instrument blindness under truncation (and to
yaw/sign/in-plane entirely — the operator saw near-global orientation
failure while the tracked min-axis metric read green, median 9.3°),
admission/closure policy, and object-blind frame sampling. Fixes belong to
the board-7 RoomPlan design session (which supersedes the shell subsystem
wholesale) and to instrument work — not to these thresholds.

## What would change this decision

A room where measured same-plane wall patches (coplanar offset ≤ ~0.15 m,
aligned normals) fail to merge across a gap ≤ ~1 m would re-open
`SHELL_WALL_MERGE_GAP_M` specifically — that failure mode was absent in
both rooms here. Likewise, if a future instrument scores truncated views
reliably (crop-aware containment that discounts out-of-frame/occluded splat
mass), the 0.5 footprint threshold should be re-derived against it rather
than kept by inertia.
