# 0081 — Box splat-axis mapping: appearance scoring refuted, cloud alignment adopted

**Date:** 2026-08-07
**Status:** Decided

## Context

RP-8's dominant visible failure (decision 0080 class 1): every box
placement shipped `splat_axis_resolved=false` — live axis margins
0.0018–0.089 vs the 0.10 gate, ~1 scoreable view per box — so extent-best
default mappings shipped, and tables rendered lying on their sides, beds
90/180° off. The charter named two candidate mechanisms to probe on the
recorded RP-8 data before building: (A) census second-view planning
guaranteeing ≥2 non-degenerate scoring views per box, and (B) a stronger
scorer than masked NCC.

## What we tried

An offline harness over the recorded spike scene (local 722-frame bundle,
GCS mask/objects caches, the shipped splats) that first REPLICATED the six
live box objects' margins bit-for-bit through the production code paths
(0.0124/0.0267/0.0055/0.0052/0.0018/0.0891 — the trust gate), then swept:

* **Truth determination**: all-24-candidate contact-sheet renders against
  the real RGB (plus dispute renders from second views). Corrected one
  operator-walk reading: the office chair's true mapping is the 90°-swapped
  assignment — five independent instruments agreed against the initial
  truth label, and the photos are unambiguous. Final truth table: bed
  {(0,2,1)}, both tables {(0,2,1)}, monoblock chair {(1,2,0)}, office
  chair {(0,2,1)}.
* **Candidate B (stronger scorers)**: current combined, tier-1-only,
  NCC@256, gradient-magnitude NCC, LiDAR depth-MAP agreement, depth+NCC
  blends. **All failed**: margins stayed 0.005–0.03 with wrong winners on
  the known-wrong cases. Mechanism: a truncated splat scored at the BOX
  center misaligns its visible-region content from the photo under EVERY
  rotation — crop-space comparison is structurally noise-bound.
* **Candidate A (more views)**: top-3 angular-diverse census-quality views
  over all 722 frames, with box-footprint evidence (no SAM dependency).
  **No rescue**: same wrong winners, margins unchanged. Extra views of a
  dead instrument stay dead.
* **Candidate C (discovered)**: rank candidate rotations by
  translation-fitted trimmed-NN RMS against the observation's own LiDAR
  cloud (production's `refine_similarity_nn`, translation mode, 2 passes;
  score = exp(−rms/0.05)). World-space, so translation-nuisance-fitting
  absorbs the truncation offset (the fixed-at-box-center control MISSES the
  bed — translation freedom is the load-bearing half). Alone: 4/6 correct
  but one thin-shell near-cube cheats by tipping.
* **The layout prior's up**: filtering candidates by the layout rotation's
  up direction fixed the tip-cheat but imported a SIGN error (a real table
  would ship upside-down — the layout's up AXIS measured trustworthy 6/6,
  its SIGN wrong on 1/6). Sign-agnostic AXIS-line filter (45°) is the
  correct form.

## What we chose

The composite, measured 5/5 on the corrected truth table and shipped in
`box_placement.py`:

1. With a layout rotation: enumerate ALL six assignments, filter to those
   mapping the layout's splat-up to within 45° of the vertical AXIS LINE
   (both signs). Without one: the pre-0081 extent-tolerance enumeration,
   byte-identical (pinned).
2. Score survivors with the cloud instrument against the observation's own
   depth cloud (`get_depth` joins RefinementContext, captures-bucket
   sourced like `get_rgb`).
3. The margin gate keeps its value (0.10) and meaning (refuse coin flips)
   but gates the ASSIGNMENT — the DOF the instrument measures. Achieved:
   bed RESOLVED 0.160, office chair 0.206, storage 0.466, table 0.147;
   the near-cubic table/chair refused at 0.014/0.002 with correct
   defaults.
4. The 180° sign leaf ships the fixed (+,+) convention (5/5 measured; the
   cloud is near-degenerate on sign twins — bed spread <0.02, pinned so a
   future sign instrument is a good pin failure). The appearance
   facing_flag clause is unchanged.

Candidates A and B are REFUTED as posed and not built. Census cover stays
1-cover; the appearance instrument keeps only the facing-flag role (its
P1 pins on 247003de stand — they pin the instrument, not the policy).

## Why

The probe measured the failure's mechanism, not just its magnitude: no
crop-space scorer can be rescued by resolution, gradients, measured depth
maps, or more views, because the comparison itself is misaligned for
truncated splats. The cloud instrument compares in the one frame where
truncation is harmless (world space, translation-fitted) using the tier's
own superpower (LiDAR), and the layout prior contributes exactly the bit
0065 proved trustworthy (the up axis) and nothing it didn't (the sign).

## What would change this decision

- A sign instrument that separates 180° twins on real data (beats the
  pinned bed near-tie) would let the sign leaf ship on evidence instead of
  convention — the facing_flag records where it would matter.
- If SAM 3D stops truncating visible regions, crop-space scoring becomes
  viable again and candidate B could be revisited (cheaper than clouds on
  swept-capture re-drives, where the cloud instrument degrades to the
  up-filtered default).
