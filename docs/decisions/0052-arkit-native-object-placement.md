# 0052 — ARKit-native object placement: single-view depth fit + SAM 3D layout prior

**Date:** 2026-07-20
**Status:** Decided (conventions pending runtime verification — see below)

## Context

SAM 3D hands back each object as an origin-centered, unit-normalized Gaussian splat in
its own local frame, and until this session nothing placed those objects into the room:
`run_perception()` read only `frame.rgb_gcs_path` while the CaptureBundle's
`camera_pose`, `intrinsics`, `gravity`, and `depth` were parsed and never touched. The
web app's premise — open it and see your room, assembled — required per-object world
transforms. VGGT-based composition was explicitly off the table (decision 0001: every
VGGT bug was it re-deriving from pixels what ARKit measures directly).

## What we tried

1. **Discarded model output recovered.** Meta's SAM 3D `Inference.__call__` returns
   `rotation` / `translation` / `scale` layout predictions alongside `"gs"` — their own
   `make_scene()` composes objects with exactly these. Our wrapper read only `"gs"`.
   The layout rotation is now the object's orientation prior.
2. **Generic similarity fitting on single-view depth clouds — rejected.** A depth map
   sees only the visible front surface. Measured on a true-visibility synthetic fixture
   (ellipsoid, normal-based cut): the robust-centroid + PCA-extent fit
   (`fit_scale_translation`) carries ~0.4 m translation error (front-surface centroid ≠
   volume center) and ~11% scale error — truncating the along-view extent *reorders the
   principal axes*, so extent ratios pair wrong axes. Not noise; structural.
3. **Iterated NN-ICP from that init — rejected.** Deceptive failure mode: residual RMS
   improves monotonically (0.071 → 0.038) while translation error stalls (~0.26 m) and
   rotation drifts *away* from truth (R_err 0.017 → 0.234). The partial shell slides
   across the full surface into a wrong local minimum.
4. **View-aware fit — adopted** (`placement_math.fit_single_view`). Exploits what one
   view measures correctly: the silhouette is complete (extents transverse to the view
   axis are unbiased — for each transverse position the depth map records the front
   point of the front/back pair), and the near surface is exactly what depth measures
   (low-percentile along-view bands correspond on both clouds). Scale = median
   transverse-extent ratio; transverse translation = band-midpoint alignment; along-view
   translation = near-face percentile alignment. Fixture results: scale to 0.2%,
   translation to ~3 cm; holds under 5 mm depth noise + 3% background-bleed outliers.
5. **NN refinement — kept only as translation-only polish.** From the view-aware init,
   one translation-only NN pass tightens translation (~3 cm → ~1.6 cm) without touching
   scale/rotation; a full Umeyama re-fit slightly *degrades* scale even from a good
   init. Full mode exists in the code but is not wired into the pipeline.

## What we chose

Per frame (LiDAR tiers): back-project the SAM 3 mask through the depth raster's own
intrinsics, lift to world via `camera_pose`, rotation from the SAM 3D layout prior
(lifted camera→world), scale+translation from `fit_single_view`, translation-only NN
polish (env `PLACEMENT_NN_POLISH`). ARKIT_ONLY frames emit a world-space view ray per
object instead. A scene-level fusion pass (`fusion.py`) clusters observations into one
entry per physical object — label + center proximity for depth fits; triangulation-
consistency gating for rays (metric center from the VIO baseline; scale from median
angular-extent × distance against the splat's local extent) — and fuses transforms
(median position/scale, Markley-averaged rotation). Manifest v2 adds the fused
`objects[]` array the viewer renders. Every failure path yields an explicit
`placed: false` with a reason; a guessed transform is never emitted. Gravity is
validation only (`gravity_deviation_deg` quality field), no auto-snapping.

Two correctness guards in fusion, both caught by tests: a cluster takes at most one
observation per frame (one physical object cannot appear twice in a frame), and a
triangulated center must lie in front of every contributing ray — without the latter,
two objects seen from one camera "triangulate" perfectly at the shared camera origin.

## Why

Depth is the metric authority (ARKit/LiDAR measures; the model guesses), but the model
is the orientation authority (a single-view partial cloud cannot fix rotation, and ICP
demonstrably makes it worse). The split — R from layout, s/t from depth, structured by
what a single view actually measures — recovers each quantity from the source that
actually knows it. The evaluation numbers above are pinned as regression tests at
achieved-accuracy tolerances (`test_placement_math.py`), so the reasoning is enforced,
not just recorded.

**Runtime-unverified assumptions, flagged in code** (`placement.py` module docstring):
layout quaternion order taken as **wxyz** (pytorch3d/Meta convention) and layout camera
frame as **CV (+Z forward, +Y down)**, converted via diag(1,−1,−1). No GPU exists in
dev; `sorted(result.keys())` is logged on every reconstruct and wrong assumptions
surface as systematically large `gravity_deviation_deg` — degraded orientation, never a
crash. The verification event is the first real LiDAR capture after the next
perception-obj deploy.

## What would change this decision

- Runtime verification showing different layout keys/conventions → fix the two named
  constants; the architecture is unchanged.
- SAM 3D exposing a calibrated metric scale or camera-frame pose that beats the depth
  fit → layout could graduate from prior to authority for more than rotation.
- Real-room data showing the 0.4 m same-label cluster threshold merges distinct objects
  (or splits one) → per-label adaptive thresholds or appearance-based matching.
- A future multi-view refinement (joint optimization over all observing frames) could
  subsume the per-frame fit + median fusion; today's accuracy didn't justify it.
