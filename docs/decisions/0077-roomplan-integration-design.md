# 0077 — RoomPlan integration: CapturedRoom as room + object skeleton, JSON verbatim on the wire, boxes carry placement

**Date:** 2026-07-28
**Status:** Decided and SHIPPED — the wire, server, co-run, floor plan, and
live drive all merged and deployed by 2026-08-06 (`perception-obj-00036-xer`).
The code is `roomplan_room.py`, `shell_envelope.py`, `box_placement.py`, and
`census_sampling.py` in perception-obj, plus the RoomPlan co-run and live floor
plan in `ios/TheGoodGuest/`. Operator walk verdicts are decision 0080.
Supersedes the shell **geometry source** on the LIDAR_ROOMPLAN tier (0066's
plane-anchor derivation and 0069's closure pass retire there); 0069's
materials layer and the /shell stage architecture survive retargeted.
Supersedes 0062's sampling policy on the LIDAR_ROOMPLAN tier (pose-diverse
FPS stays as the no-census degrade path and on the legacy tiers).

## Context

Board item 7: the operator resolved the 0071 fork to Option A (RoomPlan-only,
Pro-only, assembly-first) and this session designed the execution. Inputs:
the LiDAR adjudication (`docs/briefs/lidar-first-rooms-adjudication.md`,
decision 0075 — measured defect ranking, the operator acceptance metric:
per-furniture extent/location/rotation + envelope, plane inventory is NOT a
quality signal, furniture-face planes must never render) and the co-run
spike (decision 0076 — co-run clean, RoomPlan-native config ⊇ production
config, one world frame, boxes operator-verified 9/9 on position/extent/
FACING, CapturedRoom shell envelope-true with zero furniture-plane walls,
census full by ~27 s, host owns tracking hygiene, never retain ARFrames).

Two verify-first probes ran IN this session against recorded real data
(scripts + results in gitignored `outputs/roomplan-design/`):

- **P1 — discrete-candidate scoring on the real 247003de bed** (splat
  fetched from the outputs bucket; masks/RGB/poses local). Three-stage
  result. (a) At the SHIPPED fused center, the two-tier instrument is
  noise: cross-view winners disagree, and in the source frame it ranks the
  two upside-down candidates ABOVE upright — **the scorer cannot rescue a
  bad center; position must precede rotation scoring.** (b) At a
  box-quality center (emulated from the bed's own measured rail plane +
  floor height), discrimination is decisive: correct facing wins with
  tier-2 margin **0.15** (vs 0068's 0.0007 curtain margin), upside-down
  rejected by 0.37, combined winner margin 0.10, and the box-frame
  candidate BEATS the shipped SAM-3D-layout rotation in its own source
  frame; the winner was verified correct by overlay eyeball (wood mass on
  the photo's headboard). (c) A close-range view (1.4 m from the 2 m bed)
  zeroes tier 1 for offset candidates — degenerate views must be SKIPPED,
  not averaged. Collateral quantifications: the shipped bed is ~90°
  yaw-wrong (its long splat axis lies along the rail NORMAL, |dot| 0.947,
  while its 0.87 m width axis lies along the 2.0 m rail) and its center
  sits ~0.79 m behind the rail-consistent center — the operator's walk
  verdict, made numeric on one object, invisible to every shipped metric.
- **P2 — server-side parse of Apple's CapturedRoom Codable JSON** (the
  spike's `captured_room_built.json`, no `coreModel`, no USDZ): a ~60-line
  numpy parser reproduces every 0076 fact — 13 walls all `up_y = +1.0000`,
  two perpendicular families, 3.05 m common top + four 1.95 m door-height
  segments, floor polygon 10 corners at exactly 14.98 m², 9 pure-yaw
  objects incl. the 40.8° off-axis chair, doors/windows/openings parented
  to walls with dimensions. **The JSON alone is self-sufficient for the
  wire.** Collateral: the RoomPlan bed box is 1.85 × 2.16 m where the
  shipped depth_fit extent said 0.92 wide — the fit HALVED the bed
  (visible-region truncation), so box extents must own measurement truth
  for covered categories.

Grounding constraints carried forward: the 900 s budget reality (0060–
0062), one manifest writer, per-frame cache contract frozen, the degrade
locks (no planes → inert; `PLACEMENT_REFINE=0` bit-parity), and 0075's
standing order — the merge knobs measured correct; do not tune them.

## What we tried / rejected (named rejections — do not re-explore without new facts)

- **Proto-mirror translation of CapturedRoom** (client converts Apple's
  model into our own proto messages) — rejected. The translation is a
  lossy boundary decided at capture time: any field we didn't map (curve,
  completedEdges, a new attribute) is gone forever for that capture. It
  violates the bundle's own convention ("the iOS client emits ARKit values
  directly; it does NOT transform"), couples sampling/placement policy
  changes to app releases, and creates two schemas to keep in sync.
- **USDZ as the server's source of truth** (the pre-spike scaffold's
  assumption) — rejected: parsing USD server-side is a heavyweight new
  dependency; the Codable JSON carries the same geometry PLUS typed
  confidence/attributes/parenting, and P2 proved it self-sufficient. The
  USDZ still ships as an optional debugging/future-viewer artifact (56 KB).
- **A flat RoomPlanSummary proto for dispatch** — rejected; field reserved.
  It duplicates the JSON (drift risk), cannot carry wall/floor polygons,
  and the server opens the JSON anyway. Zero wire history makes the
  restructure safe (no client ever emitted RoomPlanModel).
- **`failed_invalid` on a missing/corrupt room.json** — rejected. Frames +
  depth remain a good capture; the scene degrades to LIDAR_ARKIT semantics
  with a structured log and a manifest note, never a rejection.
- **Dropping `plane_anchors` on the ROOMPLAN tier** — rejected: ~20 KB,
  same session, and they feed chunk D's fallback, the envelope-only
  degrade shell, and the RoomPlan-vs-anchors diagnostics cross-check the
  spike itself used.
- **Apple's stock `RoomCaptureView` for live coverage** — rejected
  (operator fork, 2026-07-28): breaks the Good Guest design language, owns
  the whole screen presentation, and its session coupling under our co-run
  is unprobed. A 3D wireframe overlay was also declined (hardest to read
  and build). Chosen: the custom 2D live floor plan (below).
- **Capture-side object-aware frame selection** — rejected: the server has
  poses + boxes and can compute per-frame box visibility; selection policy
  then iterates by deploy, not app release; and 0062's determinism/cache
  law binds server-side selection to its own GCS cache exactly as today.
- **SAM 3D layout rotation as the orientation source for covered
  categories** — dropped, on P1's measurement (box-frame candidates beat
  the shipped layout in its own source frame; the shipped bed is 90°
  yaw-wrong). Layout rotation survives only on the long-tail path with the
  existing instruments. Rotation averaging stays dead (0065).
- **The appearance scorer as facing AUTHORITY** (auto-overriding RoomPlan
  yaw) — rejected for v1: RoomPlan facing is operator-verified 9/9 (0076);
  the scorer GUARDS (resolves the splat-axis correspondence, flags
  disagreement) per the 0067 lock-6 flag-only precedent.
- **Scoring rotation candidates at fit-derived centers** — rejected by P1's
  negative result (upside-down preferred at the shipped center). Box
  centers are load-bearing, not a nicety; candidate scoring happens only at
  box-quality positions.
- **Keeping the anchor-derived shell on the no-RoomPlan degrade path** —
  rejected (operator fork): the acceptance metric bans rendering planes
  that don't exist, and 0075 measured the slab-wall/floor-collapse damage.
  Chosen instead: the envelope-only shell (below). "No shell at all" was
  declined as strictly worse than the validated envelope.
- **Per-axis splat stretch to box extents** — not rejected, DEFERRED to a
  live A/B at the first re-drive (see brief): v1 renders uniform-scale
  (appearance integrity) while the manifest REPORTS box extents; the
  stretched alternative is one knob away if the narrow-splat-in-true-box
  gap reads worse than mild distortion.

## What we chose

**1. Wire: Apple's CapturedRoom Codable JSON, verbatim, by reference.**
The client serializes the RoomBuilder output (`.beautifyObjects`) with
`JSONEncoder` to `roomplan/room.json` (~200 KB) and exports
`roomplan/room.usdz` (parametric, optional); both are ordinary manifest
blobs. `RoomPlanModel` keeps `usdz_gcs_path` + `roomplan_version` (iOS
version + CapturedRoom `version` + builder options), reserves the summary
field, adds `json_gcs_path`. Tier `LIDAR_ROOMPLAN = 3` (already in the
enum) is set iff a built CapturedRoom with ≥1 wall or floor ships; a
RoomPlan hard failure ships `LIDAR_ARKIT`. `schema_version` stays `"1"`
(additive); `plane_anchors` keep shipping on every tier. `/process` caches
room.json into the outputs bucket on first read (the 0065 sidecar lesson —
geometry must survive the captures bucket's 1-day sweep for warm re-drives
and /shell).

**2. Capture app: co-run inside CaptureManager, exactly the spike's
pattern.** Production config runs first (`.resetTracking` — load-bearing,
0076), then `RoomCaptureSession(arSession:)` attaches and runs; the
per-frame copy-out path is untouched (never retain ARFrames). `didUpdate`
feeds a published census; `didProvide` relays instructions;
`didEndWith(error: worldTrackingFailure)` (the 10 s abort) ends the capture
gracefully with the partial room — still ROOMPLAN tier if it built. Stop
order: `stop(pauseARSession: false)` → snapshot plane anchors → pause the
ARSession → `RoomBuilder` async (~1.7 s, ~905 MB transient, after pause to
minimize overlap) → serialize into the session dir → bundle assembly.
RoomBuilder failure → tier LIDAR_ARKIT. Review gains a census line
("9 objects · 13 walls · 2 doors"); upload sequencing is unchanged
(room.json/usdz are phase-1 blobs; bundle.pb still last).

**3. Live coverage (task #13's shape, operator-chosen): the Good Guest
live floor plan.** A custom 2D top-down minimap rendered from the
`didUpdate` stream in our ink — walls stroke in as detected, furniture
boxes land as labeled rounded rects, camera position + heading cone,
RoomPlan's sparse instructions as the guidance line. The same component
reappears at review as "the room you got". This is H1's product principle
(see coverage, control what's good enough) built on the census RoomPlan
already streams.

**4. Server shell: CapturedRoom is the geometry source; closure retires on
this tier.** A new `roomplan_room.py` parses the JSON (column-major
transforms, single-key category/confidence dicts, polygon corners,
parenting — the P2 parser productionized) and adapts into the same plane
dataclasses existing consumers read. Walls ship as POLYGONS (door-height
segments included) with per-surface confidence; the floor polygon ships
verbatim; doors/windows/openings become wall-parented openings.
`shell.json` bumps to v3, `method: "roomplan"`; provenance is method-level
+ per-surface confidence (no closure ran, so v2's per-edge closure states
don't apply). 0069's materials layer retargets unchanged: shell_observation
projects capture RGB onto the RoomPlan planes (SAM-mask-excluded) for
albedo; shell_material's confidence-gated vision call and THE fallback rule
survive verbatim. Geometry is never hostage to the 1-day RGB window (cached
room.json); an expired capture costs only materials (null family → clean
neutral). The viewer triangulates wall polygons (floor triangulation
already exists) and keeps the floor → walls → objects reveal.

**5. Placement: the box is the skeleton; SAM 3D is appearance only (covered
categories).** Boxes parse at /process. Association projects each box into
each sampled frame and matches SAM masks by footprint overlap + a
RoomPlan↔SAM label-family map; unmatched observations flow to the existing
pipeline untouched. A box-anchored object takes position/extent/upright/yaw
from the box; its splat comes from the best associated view; the splat's
canonical-frame correspondence into the box is resolved by enumerating
extent-consistent axis mappings (the spike bed shows local long can be X or
Z) and scoring the facing pair with the two-tier instrument at the box
center — P1's verified regime — skipping degenerate views. Below-margin →
box yaw ships with the extent-best mapping and `splat_axis_resolved:
false`; scorer disagreement with RoomPlan facing FLAGS, never overrides
(v1). Scale renders uniform (median ratio) with per-axis residuals
recorded; `extent_m_sorted` REPORTS box dims (measurement truth — the fit
halved the real bed). Boxes with no associated splat ship as honest
inventory entries (`placed: false, reason: "no_appearance"`, box geometry
carried). A non-box fused object landing inside a matched box's volume with
a compatible label is suppressed as a box-duplicate (recorded). The long
tail (operator-chosen: ships in v1) keeps depth_fit + contact priors + the
sanity gate, plus three new measured gates: label-agnostic containment
dedup (the f242 artwork/painting/mirror triple), a mirror depth-trust gate
(nn_rms out of family → demote to wall-contact), and a textile
silhouette-span check (the collapse-into-cloud degeneracy). SAM layout
rotation drops out of the chain for covered categories entirely.

**6. Frame selection: census-driven, server-side, two-pass /process.**
Pass 1 segments the sampled frames (mask cache unchanged) and associates
masks to boxes; pass 2 reconstructs per-box best view(s) + long-tail masks
under budget admission, priority-ordered (uncovered boxes first). The
sampler becomes box-visibility set-cover (each box seen well in ≥1 frame)
plus pose-diverse FPS residue for the long tail; deterministic, recorded in
`sampling{}`. SAM 3D passes drop from per-mask-per-frame (39 on capture #1
for ~12 objects) to per-object — the starvation class relieved
architecturally. No census → the 0062 sampler verbatim (degrade lock).
Budget admission remains the guarantee (0062's decoupling).

**7. Tier ladder.** New captures: LIDAR_ROOMPLAN (the app is Pro-only).
LIDAR_ARKIT: the RoomPlan-failure fallback — full placement pipeline, and
(operator-chosen) the **envelope-only shell**: 4 envelope walls selected by
the adjudication's validated discriminators (classification + height-reach)
+ the envelope-intersection floor (operator-confirmed 4.20 × 3.29 m on
247003de) — furniture-slab walls die on this tier too. ARKIT_ONLY: legacy,
fixtures only, untouched. Regression fixtures: 25a14caf / f3d70236
(ARKIT_ONLY), 247003de / 13bae607 (LIDAR_ARKIT), and the spike probe run
converted to a real CaptureBundle — the first LIDAR_ROOMPLAN fixture,
offline-verifiable now and uploadable post-deploy so the live E2E runs on
the very room with operator-verified 9/9 ground truth.

## Why

The acceptance metric is the bar, and every lock traces to it through the
three standing masters. **Honesty made structural:** the box is a
measurement (operator-verified on all three components the metric names);
the splat-axis correspondence ships only with pixel evidence or an explicit
flag; box-less objects are inventory, not guesses; the envelope-only
degrade renders only walls that exist; provenance (method, confidence,
sources) rides every surface. **The budget reality:** per-object
reconstruction spends the GPU where the census says objects ARE; geometry
parsing is CPU-milliseconds; nothing new competes with the frame budget.
**Contract containment:** one manifest writer, per-frame cache frozen,
additive proto only, room_planes' query surface preserved via adapters,
renderer specifics stay in SplatViewer. And the 0065 method carried the
session: both riskiest claims (scorer regime, JSON self-sufficiency) were
MEASURED before the design locked, and P1's negative result (position
precedes rotation) is as load-bearing as its positive one.

## What would change this decision

- An iOS update changing RoomPlan session management re-opens 0076's Q1–Q3
  (the spike app re-runs in an afternoon); a Codable schema change surfaces
  as a parse failure on the `version` field — the parser pins it.
- P1 pins failing on more categories at RP-4 (the scorer discriminating on
  beds but not desks/chairs) demotes facing verification to flag-only for
  those classes — the box still carries yaw; only the guard weakens.
- Association quality on real masks (RP-4's live gate) failing — boxes
  matching the wrong masks at rate — re-opens the label-family map and the
  footprint threshold before anything ships.
- Multi-room / ARWorldMap flows, the 4K video format, or older-OS behavior
  were never probed (0076's clause carries).
- RoomPlan category breadth: if Apple grows the vocabulary (or ships
  per-object meshes/appearance), the long-tail boundary moves; the
  association layer is the seam.
- The uniform-vs-stretch A/B at RP-8 decides the splat-fit knob; either
  outcome keeps box extents as the reported truth.
- A measured room where the envelope discriminators misclassify a real
  wall (height-reach fooled by a floor-to-ceiling wardrobe wall) re-opens
  the envelope-only selection rule with that counterexample.
