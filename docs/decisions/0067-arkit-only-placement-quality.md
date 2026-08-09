# 0067 — ARKIT_ONLY placement quality: pixel-footprint correspondence, silhouette fitting, measured-plane contact priors

**Date:** 2026-07-23
**Status:** Decided and SHIPPED — chunks A–C merged 2026-07-23, chunk D
2026-07-24, serving since `perception-obj-00033-zfg`. The code is
`services/perception-obj/reproject.py`, `contact_priors.py`, and `fusion.py`'s
`PLACEMENT_REFINE` path. Build verdicts, including the one probe that failed,
are decision 0068.

## Context

Position quality is the post-conventions frontier: 0065 closed rotation
conventions, and the operator's real-room walk ranked what remains on the
real scene `25a14caf`. Three failures, in the operator's order: (1) the
curtain's triangulated center sits ~0.5 m into the room and interpenetrates
the bed; (2) the one physical bed splits into two fused clusters ~1.2 m
apart; (3) the curtain fabric is turned ~90° in-plane, and no instrument
scores in-plane orientation. This design session re-measured each failure
against the recorded data (manifest v2, cached `masks.npz`, the preserved
bundle) before locking anything — the 0065 method:

- **The bed split is structurally forced, not threshold-tunable.** Frame 28
  carries TWO "bed" detections (mask 3, score 0.766; mask 5, score 0.695),
  and mask 5 is 100% contained in mask 3 (intersection-over-smaller =
  1.000, measured from the cached masks.npz) — a nested duplicate detection
  of one bed. Fusion's frame-uniqueness guard ("one physical object appears
  at most once per frame") reads the pair as proof of two objects: the
  greedy pass must open a second cluster, and the merge pass must refuse to
  close it (it requires disjoint frame sets). One duplicate detection in
  any single frame permanently forks the object, at any threshold setting.
  The resulting fragment cluster (obj_004: 2 obs, scale 0.39) sits 1.26 m
  from the main bed (obj_003: 5 obs, scale 1.15).
- **Centroid rays on large objects don't correspond to any fixed 3D
  point.** The curtain subtends 0.74–1.3 rad across its 7 observations (up
  to ~74° of view); under viewpoint change and frame-edge cropping the mask
  centroid wanders across the physical object, so its rays genuinely don't
  meet: the cluster triangulates at RMS 0.287 m — grazing the 0.3 m gate —
  and the least-squares point lands off the fabric plane, into the room.
  The bed rays behave the same (RMS 0.264). Contrast the compact table
  lamp: RMS 0.007 m. Triangulation isn't broken; it is the wrong instrument
  for objects that are large in the view. The ray-path scale estimate
  (`angular_extent × distance`) also leans on a small-angle approximation
  that is meaningless at 1.3 rad.
- **In-plane orientation has no runtime instrument.**
  `min_axis_to_vertical_deg` is a line metric — it reads 5.6° on the
  visibly-wrong curtain (satisfied); the 0065 sign pins don't constrain
  spin about the plane normal. 0065's closing lesson — classify every
  instrument by what it CANNOT see; hold at least one instrument per error
  dimension — currently fails for the in-plane dimension at runtime.

Grounding facts the design leans on: fusion runs inside `/process` after
the frame loop, and the manifest is rebuilt wholesale each run (single
writer; warm re-drives recompute fusion over cached per-frame results).
Cached per-frame `objects.json` records already carry each observation's
view ray, per-observation world rotation, and splat extent; `masks.npz` is
cached per complete frame in the outputs bucket (persists; F5's lifecycle
gap notwithstanding) while RGB lives in the captures bucket behind a 1-day
lifecycle — and the full 126-frame capture is additionally preserved
locally at `outputs/real-capture-25a14caf/`. 17 of 22 fused objects are
single-observation and cannot triangulate at all. 0066 puts measured ARKit
plane anchors on the wire (additive proto field; NEW captures only — every
existing bundle has none). The budget reality is 0060–0062's: a 900 s
window the GPU work already fills; anything added here must be CPU-cheap
and skippable.

## What we tried / rejected (named rejections — do not re-explore without new facts)

- **Raising the cluster/merge thresholds** (`FUSION_RAY_RMS_M`,
  `FUSION_CLUSTER_DIST_M`) — the bed split survives ANY threshold (the
  frame-uniqueness guard forks it structurally), and looser gates merge
  genuinely distinct same-label objects. The correspondence signal is
  wrong, not the number.
- **VIO-calibrated monocular depth into `depth_fit`** — DEFERRED, not
  adopted (it was one of the named candidate levers). It puts a heavyweight
  model inside a budget that already can't fit 12 object frames, and its
  output is a guessed metric field wearing depth_fit's metric-authority
  clothes — an honesty hazard the measured-input path doesn't have.
  Re-open triggers: multi-view objects still failing on position after
  silhouette fitting ships (narrow-baseline depth ambiguity), or
  single-view coverage for no-prior classes becoming product-critical.
- **Full joint optimization** (poses + objects + planes, bundle-adjustment
  style) — ARKit poses are the trust anchor (0001); we never re-optimize
  what the device measured. Per-object fitting against fixed poses is the
  whole job.
- **ICP variants for position** — measured-rejected in 0052 (residual
  improves monotonically while the pose walks away from truth); nothing
  new. Silhouette fitting works in image space, where cropping is explicit
  instead of a hidden outlier field.
- **Learned appearance re-ID / embeddings for cross-frame correspondence**
  — a new model dependency to solve a problem geometric footprint overlap
  solves at room scale. Re-open if two physically identical adjacent
  same-label objects (twin chairs) become a measured merge failure.
- **Rotation averaging across observations** — stays dead (0065: canonical
  frames are per-reconstruction arbitrary). In-plane resolution operates on
  the best member's own frame only.
- **Auto-snapping rotations to gravity or Manhattan axes** — 0052's
  "gravity is validation only" stands. Aligning to a MEASURED surface a
  specific object attaches to (a detected wall's normal, the detected
  floor), gated by pixel evidence and recorded, is adopted below; snapping
  to an assumed convention without evidence is not. The line between the
  two is measurement.
- **Running refinement as a separate stage or service** (a /shell-style
  second pass) — the manifest has one writer (0066 reaffirmed it), and
  every input refinement needs (masks, splats, rays, poses) is in hand
  inside `/process` at fusion time. A second stage would re-fetch
  everything in order to earn a read-modify-write race.
- **Inferring walls from fitted object planes** (the curtain's fitted plane
  as a wall estimate) — 0066's rejection, mirrored: geometry nobody
  measured. Walls come from ARKit anchors or not at all; a fitted curtain
  is evidence about the curtain.
- **Server-side re-segmentation to fix duplicate detections** — re-running
  SAM 3 with tweaked prompts/thresholds spends GPU minutes to fix what a
  containment test fixes for free at fusion time.

## What we chose

**1. One physical invariant replaces the per-frame guard: an object
explains all of its pixels.** Fusion correspondence moves from
centroid-ray geometry to pixel-footprint evidence. (a) Same-frame
same-label observations whose masks are nested (intersection-over-smaller
above threshold; measured 1.000 on the real bed) are duplicate detections:
dedup before clustering, keep the better mask, record the absorption in
fused quality. (b) Cluster join and cluster merge become footprint tests —
project the cluster's current volume estimate into the candidate's frame
and require mask-overlap consistency. The merge guard's "no shared frames"
rule relaxes to: shared-frame masks must themselves be same-object
evidence (nested/overlapping), else the merge stays refused — the old
rule's intent (two DISJOINT same-label masks in one frame are two objects)
is preserved; its false reading of duplicate detections is not. Both
fusion paths get this (the LiDAR path's 0.4 m proximity heuristic and its
documented two-objects-merge limitation are superseded by the same
signal).

**2. A runtime reprojection-scoring instrument, two tiers.** For a
candidate placement (splat + world transform) and an observing frame:
project into that camera; **tier 1** scores silhouette agreement against
the SAM mask (soft IoU at low resolution, crop-aware at frame edges);
**tier 2** renders the splat crudely (colors + opacity read from the PLY;
deterministic numpy point-splat at ~128 px — no GPU, no new dependencies)
and scores appearance agreement (masked NCC) against the RGB crop when the
capture's pixels are still fetchable (1-day lifecycle; tier 1 alone
otherwise, tiers-used recorded). Uses: fusion best-member selection
(today's selector is detection score — a segmentation confidence that says
nothing about placement quality); in-plane candidate ranking (lock 4);
sign-flip auto-flagging (0065's identity-twin episode institutionalized as
a runtime check); and a per-object `reprojection_score` in the manifest —
the missing instrument-per-error-dimension, made permanent.

**3. Multi-view silhouette fitting is the ARKIT_ONLY position/scale
authority for clusters with ≥2 views.** Optimize scale + translation
(rotation held fixed from the best member's layout, as 0065 requires) of
the best member's splat so it jointly explains every member's mask under
that frame's measured pose — whole-mask evidence instead of a centroid
point, with frame-edge-truncated mask regions handled one-sidedly.
Triangulation is demoted to initializer and cluster seed (it remains
excellent for compact objects — the lamp's 0.007 RMS); where it is
degenerate for a large object, a coarse deterministic depth sweep along
the best member's centroid ray initializes instead. This is 0052's
"exploit what the view actually measures" reasoning applied to the
no-depth tier: on ARKIT_ONLY, the silhouette IS the measurement.

**4. In-plane resolution for planar classes.** For planar objects (thin
canonical axis), generate the in-plane candidates about the plane normal
(90° steps — the ambiguity class SAM 3D exhibits on near-square planar
objects) and rank them with the instrument: tier 1 discriminates when the
in-plane extents differ (aspect breaks the tie); tier 2 decides when the
silhouette is near-square — the curtain case, where only the pleat texture
knows which way is up. A winner must beat the alternatives by a margin;
otherwise the layout rotation stands and the manifest says so
(`in_plane_resolved: false`).

**5. 0066's plane anchors feed placement as measured contact priors —
through one shared interpretation module.** A single `room_planes.py` in
perception-obj (anchor filtering, floor-plane selection per 0066's
semantics, wall-plane set, coplanar merge, ray/point-to-plane queries)
serves BOTH the shell's quad assembly and placement — one interpretation
of the measured room, two consumers; whichever build lands second
refactors onto the first's module (the shell build is in flight in
parallel — coordination noted in both briefs' orbit). Placement uses:

  - **Floor contact** for floor-standing classes: multi-view fits gain a
    bottom-touches-floor regularizer; single-view observations become
    SOLVABLE — bottom-on-measured-floor closes the depth/scale ambiguity
    as a deterministic 1-D root-find along the view ray.
  - **Wall attachment** for wall-mounted classes: position from the ray's
    intersection with a DETECTED wall behind the object (offset by the
    thin extent), normal aligned to the wall's measured normal;
    single-view wall objects (5 doors, 3 artwork, 2 paintings, the mirror
    — most of the 17 unplaced) become solvable. No detected wall on the
    ray → no prior, honestly unplaced.
  - **A conservative class→prior map** over the fixed SAM 3 prompt
    vocabulary, three buckets (floor / wall / none), pinned in the brief.
    Ambiguous classes (table lamp, speaker, plant, clock) map to NONE and
    stay unplaced on single view. The map is policy, not measurement, and
    every prior-touched object records `position_source` +
    `constraints_applied`.
  - **The evidence rule:** a prior may select among evidence-consistent
    solutions or close an under-determined DOF; it may never override
    pixels. A constrained solve that scores materially worse than the
    unconstrained one (tier 1) drops the prior and records the conflict.
    This is how "a guessed transform is never emitted" survives priors: a
    prior-closed transform ships only when the surface is measured, the
    class mapping is conservative, and the record says exactly what was
    assumed.
  - **Degrade honestly without planes:** every existing capture (including
    `25a14caf`) carries no anchors — contact priors simply never activate;
    locks 1–4 still work in full (they need only masks + poses). Mirrors
    0066's degrade lock; no tier is gated.

**6. Where it runs, and the cache contract it must not touch.** Everything
lands in the fusion phase inside `/process` — CPU work, bounded by env
knobs (scoring resolution, candidate counts, a per-scene refinement time
cap inside the existing budget tracker), and skipped whole under budget
pressure with `refinement_skipped` recorded rather than half-run. With
refinement disabled (`PLACEMENT_REFINE=0`) the pipeline reproduces today's
behavior — the rollback lever. The per-frame cache contract is deliberately
untouched: all new computation reads existing cached records + masks.npz +
the bundle; nothing new is written per frame, so every prior capture stays
fully warm-re-drivable and old cached records stay valid (the 0065 sidecar
lesson, applied prospectively).

**7. The manifest stays v2 with additive fields.** Fused objects gain
`reprojection_score`, `position_source`, `constraints_applied`,
`in_plane_resolved`, and `extent_m_sorted` (physical dimensions as a
frame-free sorted triple — the fit computes them anyway, and they are
exactly what the extents fast-follow needs; facts/charter consumption
stays the separate `facts_version` bump per the standing plan). Per-frame
records: unchanged.

## Why

The same three masters as 0066. **Honesty made structural:** correspondence
and position move onto evidence that was measured (masks from real pixels,
poses from VIO, planes from ARKit); priors are labeled, evidence outranks
them, single-view placement exists only where a measured surface closes
the equation, and the no-instrument dimension gets an instrument that
ships in every manifest. **The deployed budget reality:** no new models,
no GPU cost, no new stage or service — bounded CPU refinement inside the
window with a recorded skip path and a clean off switch. **Contract
containment:** one manifest writer, per-frame cache shape frozen, additive
manifest fields only, and one plane-interpretation module shared with the
shell instead of two readings of the same anchors.

The 0065 method carries forward on both ends: every diagnosis above was
measured on recorded real data before it became a lock (the containment
number, the RMS-versus-angular-size contrast, the lamp counterexample),
and the build brief's verify-first probes run offline against the same
recordings — the instrument must prove it can discriminate on the real
failures before any pipeline code is written around it.

## What would change this decision

- A verify-first probe failing (the numpy render can't separate the
  curtain's 90° candidates; footprint overlap can't merge the real bed
  without also merging the real doors) re-opens the instrument design
  before any build — that is what verify-first is for.
- SAM 3 exposing per-mask instance embeddings (or SAM 3D a calibrated
  camera-frame pose) upgrades correspondence/selection near-free — the
  re-ID rejection is about adding a model, not about using signals already
  paid for.
- Real plane-anchor captures showing wall detection too sparse to catch
  the walls objects actually hang on (0066 records the same empirical
  unknown) demotes wall attachment to opportunistic and re-ranks the
  monocular-depth deferral.
- A tier with real per-pixel depth (LiDAR, board item 3) makes `depth_fit`
  the position authority wherever depth exists — this design's machinery
  stays as the instrument layer and the ARKIT_ONLY path.
- Twin adjacent identical objects failing footprint correspondence
  re-opens appearance re-ID (see above).
- Extents/facts work consuming `extent_m_sorted` may want per-category
  refinement of the in-plane margin and class map — the manifest keeps
  enough provenance to recompute offline.
