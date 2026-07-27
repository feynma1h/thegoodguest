# First LiDAR rooms — quality adjudication (scenes 247003de, 13bae607)

**Status: measured sections final; operator walk verdict recorded (§4) —
global fidelity failure, itemized ranking declined as not meaningful.**

Opening exhibit for the board-7 RoomPlan integration design session. Adjudicates
the first two LIDAR_ARKIT captures ever processed (iPhone 16 Pro, 2026-07-26;
serving stack `perception-obj-00033-zfg` / `api-public-00018-xay`), against the
recorded suspicions in CLAUDE.md's "First LiDAR placement-quality signal":
the bed×3/desk×3/rug×3 under-merge suspicion and the 14-wall shell. Method:
offline measurement from the recorded per-frame observations + preserved
bundles (no deploys, no knob changes, no re-drives); production behaviour
replicated bit-for-bit where cited. Analysis artifacts in gitignored
`outputs/lidar-adjudication/` (scripts, JSONs, mask overlays, floorplans.png);
both rooms staged for walking at `/viewer?fixture=scene-247003de` and
`/viewer?fixture=scene-13bae607` (dev server, fixtures in gitignored
`web/public/dev-fixtures/`).

The rooms: 247003de — 293 keyframes, 12 sampled/12 processed, 23 fused objects,
16 placed (all `depth_fit`), 14-wall shell. 13bae607 — 128 keyframes, **3 of 12
sampled frames processed** (round-1 budget stop; coverage is thin as recorded),
9 fused, 6 placed, 10-wall shell.

---

## 1. What "16 placed objects" actually is (247003de)

Cluster membership was recovered exactly (median + best-member matching, error
0.0 on all 16), then every suspect detection was identified by mask overlay on
the capture RGB. The label-grouped listing reads "bed×3, desk×3, rug×3" — but
the physical identifications dissolve most of it:

| manifest | physical object (from mask overlays) | verdict |
|---|---|---|
| bed obj_001 (2 views) | the bed | correct merge — incl. a 0.95 m footprint join |
| bed obj_002 | the same bed, f173 edge-truncated view | **the one true under-merge phantom** |
| bed obj_003 | a folded mattress leaning on the far wall | real, distinct object |
| desk obj_008 | the study desk | real |
| desk obj_009 | a red plastic stool | mislabel ("desk") |
| desk obj_010 | a wooden folding table | mislabel ("desk") |
| rug obj_019 | small floor mat | real |
| rug obj_020 | throw blanket ON the chair (center y −0.13, elevated) | mislabel + scale suspicion |
| rug obj_021 | small mat on the wooden bench | real |
| artwork obj_000 / painting obj_018 | ONE small (~0.3 m) framed item, triple-detected | cross-label duplicates |
| mirror obj_017 (2 views) | the real mirror (1.68 m) + that same small frame | wrong-pair merge |
| cabinet ×2, chair ×2 | plausibly distinct (walk to confirm) | — |

So: 16 placed ≈ 12 physical objects, and the user-facing inventory would say
"3 beds, 3 desks, 3 rugs" for a room with one bed, one desk, and (probably) one
rug. Three distinct mechanisms, measured below — only one of them is fusion
under-merge.

### 1a. The one true under-merge: bed obj_002 (frame-edge truncation)

- 5 bed observations across 4 frames. f173's two (IoS 0.98 nested pair) were
  correctly deduped to one (obj_002 `deduped_observations: 1` — the 0067
  mutual-singleton dedup works on LiDAR data; same for the f267 desk pair,
  IoS 0.977, `obj_008 deduped: 1`).
- Production's footprint-join decisions replicated exactly with the repo's own
  `reproject.score_tier1_containment` (threshold `PLACEMENT_FOOTPRINT_MIN=0.5`):
  - f164 obs vs cluster {f129}: **0.5998 → joined** (rescued a 0.95 m
    displacement between partial views).
  - f173 obs vs cluster {f129, f164}: **0.3144 → refused** → obj_002. Scored at
    its own fitted center it is still 0.3792 — **not a threshold near-miss and
    not a reference-position artifact**. The f173 view sees only a corner of
    the bed at the frame edge (mostly out-of-frame, partly occluded); most of
    the projected full-bed splat cannot land inside that mask anywhere.
- Displacement decomposition of the three views' depth_fit centers vs the fused
  center (bed extent 1.99 × 0.92 × 0.48 m): f129 −0.28 m along-view (toward
  camera) + 0.38 lateral; f164 +0.33 along (away) + 0.34 lateral; f173 1.10 m
  LATERAL of 1.15 total.

**Mechanism, corrected from the recorded suspicion:** depth_fit anchors to the
*visible region*, not specifically the near face — per-view centers scatter
0.5–1.2 m in any direction on a 2 m object. `FUSION_CLUSTER_DIST_M=0.4`
proximity can structurally never bridge that on large objects; the footprint
instrument is the only bridge, and under truncation+occlusion its score swings
across the 0.5 line (0.60 pass vs 0.31 fail on the same physical bed). The
split is structurally forced at the instrument level, not a knob miss —
raising the cluster distance would merge distinct same-label objects (the
stool sits 0.98 m from the folding table), and lowering the footprint
threshold to 0.3 would admit essentially anything.

### 1b. Label-space collapse (not a fusion defect)

SAM's vocabulary maps stool→"desk", folding table→"desk", throw/mat→"rug",
folded mattress→"bed". Fusion is label-keyed, so these can never merge (good —
they're different objects), but the inventory reads as duplicates and the
manifest invites a false under-merge diagnosis. This is the second time a
label-grouped reading misled a recorded suspicion (0067's bed was the first).

### 1c. Cross-label triplication (dedup blind spot)

f242's masks m0/m1/m2 are the SAME ~20k px region (pairwise IoS 0.999) under
three labels — artwork, painting, mirror. The 0067 dedup is same-label only,
so all three shipped: three overlapping splats at one position. At 2.5 m, a
20k px mask is a ~0.3 m object — consistent with all three fits (scales
0.26/0.29/0.34, nn_rms 7–12 mm). Cheap pipeline fix (label-agnostic containment
dedup), independent of RoomPlan.

### 1d. Mirror depth is untrustworthy (specular)

The real mirror's own fit (f73, 1.68 m extent) has **nn_rms 0.196 m — 28×
worse** than this scene's typical good fit (~0.007 m): LiDAR through mirror
glass returns virtual/garbage depth. obj_017 then merged the real-mirror obs
with the small-frame obs 0.56 m away (both labeled "mirror"). Mirror-class
objects need special handling regardless of shell source.

### 1e. Textile scale suspicion (walk to confirm physical sizes)

The throw blanket's mask spans 262k px (~a meter of fabric over the chair),
yet ships at extent 0.34 m with nn_rms 7.9 mm from 4,604 depth points. A small
splat *inside* a large depth cloud scores excellent one-directional NN rms —
the collapse-into-cloud degeneracy. All five small-scale fits in this scene
(three textiles + the frame ×2) land in a suspicious 0.26–0.34 band. If the
walk confirms meter-scale textiles, depth_fit needs a bidirectional coverage
term (or silhouette-span check) for thin/soft objects.

---

## 2. The 14-wall shell (and 13bae607's 10-wall sibling)

Production reproduced offline from the preserved bundles' anchors with the
serving knobs (`SHELL_WALL_MERGE_GAP_M=1.0`, `SHELL_WALL_NORMAL_TOL_DEG=15`,
coplanar 0.12 default): **14 and 10 walls, exactly matching production**
(anchor→wall mapping in `analysis_shell.json`).

### 2a. The envelope is near-perfect — the LiDAR tier's headline win

Both rooms produce a clean 4-wall rectangular envelope: 247003de walls
02/05/09/12 (4.36/4.57/4.22/3.64 m wide, all reaching the 3.05 m common top;
opposite pairs parallel to 0.0–1.1°, adjacent pairs perpendicular to 0.2–0.8°;
room ≈ 4.2 × 3.3 m), 13bae607 walls 01/03/06/08 likewise. The 0071-era
complaints (non-perpendicular walls, pentagon floor) do not reproduce on this
tier — that ceiling was the non-LiDAR anchors, and it is gone.

### 2b. The other 10 (resp. 6) walls are NOT under-merge — they are furniture

The 0066-style pairwise table (normal angle / coplanar offset / lateral gap,
all pairs, in `analysis_shell.json`) shows every small↔large near-parallel pair
fails on **coplanar offset 0.44–3.4 m** — genuinely different planes standing
inside the room, not same-plane patches split by a gap. No `SHELL_WALL_MERGE_*`
setting can or should merge them. Identifications (walk to confirm the
physical objects): 247003de wall_11 is the bed's side rail — 2.00 × 0.53 m,
ARKit-classified **`seat`** (13bae607's wall_00, also `seat`, 1.55 × 0.65 m, is
its bed too); walls 00/01/03/04/06/10 sit 0.55–1.6 m proud of envelope planes
at furniture heights (1.2–2.0 m tops) — wardrobe/cupboard faces and door
leaves; wall_07 is the only near-coplanar case (0.21 m off wall_05,
door-leaf-sized, carries an opening); walls 03/08 + 13bae607's 02/04/07/09
lie partly OUTSIDE the envelope — through-opening detections of the adjacent
space. ARKit's own classifications on the small walls' members: mostly
none/seat (8 of 10 on 247003de) — the signal exists at admission time and is
currently unused (admission is area ≥ 0.3 m² + vertical, nothing else).

### 2c. Closure inflates furniture planes into full-height slabs

8 of 14 (247003de) and 6 of 10 (13bae607) walls have top extensions > 0.5 m —
worst case the bed rail rendered from 0.53 m measured height to a 3.06 m
floor-to-ceiling slab (**+2.48 m of invented wall**) across the middle of the
room. Measured geometry is preserved (measured_quad honest); the *rendered*
room is where the damage is.

### 2d. Floor collapse — the single biggest rendered defect

The floor bounding pass Sutherland–Hodgman-clips the snapped floor against
EVERY surviving wall's interior half-plane (`shell_geometry.py` pass 2). A
furniture plane's "interior" side is just wherever the camera stood, so each
interior slab cuts the floor at its own plane, and the cuts compound:

- 247003de: floor measured 13.1 m² → **rendered 1.5 m² (12%)**
- 13bae607: floor measured 13.2 m² → **rendered 5.0 m² (38%)**

Most of both rooms has no floor; objects float on the void. The degenerate-clip
guard (keep-unclipped when < 3 vertices survive) only prevents total collapse,
not compounding. This also retroactively explains part of the "mostly-empty
room" reading on the reference room walks. See `floorplans.png` — the rendered
floor is a small quad in a correct large envelope.

**Shell verdict: not a knob problem.** Admission (any vertical anchor ≥ 0.3 m²
becomes a wall) and closure/clipping (extend everything, clip floor against
everything) are the defects; the merge knobs measured correct on both rooms.
The available-but-unused discriminators today: ARKit classification
(wall/door/window vs seat/none), height-reach (envelope walls hit the common
top; furniture stops 1–2 m short), and envelope membership (interior planes
sit off the floor-boundary walls). Any of these separates the two populations
almost perfectly on both rooms — but see §3: RoomPlan makes this whole
subsystem moot.

---

## 3. What RoomPlan would and wouldn't fix (per finding)

RoomPlan's `CapturedRoom` (LiDAR-only, the 0071 Option-A source) returns
merged, squared walls with doors/windows/openings embedded, a floor polygon,
and furniture as category-tagged oriented bounding boxes (bed/table/storage/
sofa/…). It does NOT place our SAM 3D splats — `depth_fit` stays regardless.
Category coverage/fidelity claims below should be re-verified in the board-3
co-run spike before the design session commits to them.

| finding | RoomPlan effect |
|---|---|
| §2b furniture planes as walls | **Fixed by construction** — furniture returns as objects, walls are walls. The entire admission problem disappears. |
| §2c closure inflation | **Fixed** — CapturedRoom walls arrive full-height and squared; our closure pass (and most of `shell_geometry`) retires. |
| §2d floor collapse | **Fixed** — floor polygon comes from RoomPlan; no half-plane clipping against furniture. |
| §2a envelope | Already near-perfect from raw anchors; RoomPlan keeps it and adds openings-in-walls natively. |
| §1a under-merge phantom (visible-region scatter) | **Not fixed by the shell** — but RoomPlan's object boxes offer a per-category anchor: one `bed` box → one bed cluster (associate observations to boxes before/instead of center clustering, for covered categories). Design decision: are RoomPlan boxes the object skeleton, a fusion prior, or unused? |
| §1b label collapse (stool→desk, textiles→rug) | **Not fixed** — SAM vocabulary is ours. RoomPlan categories could cross-check the covered subset (a `storage`/`table` box disagreeing with a "desk" splat). |
| §1c cross-label triplication | **Not fixed** — pipeline fix (label-agnostic containment dedup), cheap, independent of the pivot. |
| §1d mirror depth | **Not fixed** — specular LiDAR is bad for RoomPlan too (mirrors are a known RoomPlan failure class). Needs its own flag either way. |
| §1e textile scale | **Not fixed** — depth_fit instrument work. |
| §4 H1 live capture-coverage feedback | **Native** — RoomPlan's live room-model feedback is its core capture UX (RoomCaptureView, or custom UI off RoomCaptureSession updates); task #13's real-mesh render becomes this. |
| §4 H2/H3 object-blind frame sampling | **Enabled, not automatic** — CapturedRoom.objects provides the furniture census to drive object-aware frame selection (successor to 0062's pose-diverse FPS under Option A); the selection policy itself is ours to design. |
| door demotion erasing wardrobe faces (§4 walk item) | **Reframed** — `represented_as_shell_opening` currently keys on the SAM label alone, and f222 shows SAM labels cupboard doors "door" (four of them). With RoomPlan, demote only detections lying ON a RoomPlan wall plane; wardrobe doors then stay objects. |

The strategic reading: RoomPlan cleanly kills the §2 defect class (the biggest
rendered damage in both rooms), while §1's object-side defects — the actual
placement/fusion frontier — are untouched by the shell source and become the
quality ceiling after the pivot. The design session should treat "what do we
do with CapturedRoom.objects" as a first-class fork, not a footnote.

---

## 4. Operator walk — verdict (recorded 2026-07-27)

The operator walked both rooms and returned a GLOBAL verdict rather than an
itemized ranking — and that is itself the finding:

> "It is very difficult for me to judge the rooms since they look very far
> from what is reality. I can try and list the things that are correct but
> that would be a minimal set."

Fidelity is so far below recognizability that per-object ranking stops being
meaningful; the correct set is smaller than the wrong set. (The reveal-pacing
watch was skipped accordingly.) The operator raised three hypotheses, each
resolved against this doc's measurements:

**H1 — "the capture wasn't good enough (headless, no live feedback)":
attribution REFUTED, product principle CONFIRMED.** The captures were good:
#1 carried 293 keyframes with depth on 292, tracking normal; #2 carried 128.
The pipeline sampled 12/293 (4%) and completed 3/12 on #2 (budget stop);
the two visually dominant defects (§2 furniture-slab walls, 12%/38% floor)
are anchor-interpretation bugs that a perfect capture would reproduce. But
the principle — the user should SEE coverage while capturing and control
what's good enough — stands, is already tracked as task #13 (the current
capture screen's mesh is a decorative placeholder), and is something RoomPlan
ships natively (live growing-room-model feedback is core RoomPlan UX).

**H2 — "we downsample before SAM and lose/truncate furniture": CONFIRMED,
measured.** `PERCEPTION_MAX_FRAMES=12`, pose-diverse and object-blind
(0062); partial-extent renders are single-view visible-region anchoring
(§1a) plus per-object OOM soft-fails; cross-capture furniture differences
are which views survived sampling + budget. The operator independently
re-derived the recorded sampling-starvation insight, now confirmed on the
LiDAR tier.

**H3 — "census the furniture first, then pick the best frame(s) per object
for SAM": NEW design-session input, and the pivot's convergence point.**
RoomPlan's `CapturedRoom.objects` IS the on-device furniture census
(category + oriented box per piece, before SAM runs). Object-aware frame
selection — maximize per-box visibility instead of pose diversity — is the
natural successor to 0062 under Option A, and the same boxes could anchor
fusion (one bed box → one bed cluster, §3 table). Open architecture
question for the design session: SAM 3D fusion currently wants MULTIPLE
views per object, so "best frame per object" needs to mean best-few, not
best-one — or single-great-view placement (chunk-D-style) has to carry
more weight.

**Additional walk finding — orientation: "whatever furniture was rendered,
almost all of it wasn't oriented properly." The tracked metric is green
while the human sees near-total failure — an instrument gap, the 0065
lesson generalized.** This scene's `min_axis_to_vertical_deg` median is
9.3° with only 4/16 placed objects above 15° — by the axis-line metric,
orientation looks fine. But that metric only certifies that SOME axis
points up. It is blind to the three rotations humans actually see: **yaw**
(which way the bed/desk faces — unscored by ANY current instrument),
**sign** (face-up vs face-down — scored only when the mirrored-twin gate
fires; `sign_flag` on 1/16 here), and **in-plane spin** (`in_plane_resolved:
false` on 13/16 — the 0068 re-opened fork). depth_fit rotations come from
single-view SAM 3D layout on partial views, where yaw error is cheap.
Design-session hook: RoomPlan object boxes carry a horizontal orientation
for covered categories — a candidate yaw prior/scorer that no current
instrument provides.

**Follow-up questions, answered with measurements:**

*"What causes the floor plan to be inaccurate?"* The dashed outline is the
floor ANCHOR's observed-coverage boundary, which is a coverage artifact by
construction: furniture occludes floor (the boundary bites inward under the
bed/wardrobe), observed floor spills through open doorways into the next
space, and ARKit's boundary polygons are coarse incremental fits. It is not
the room's architecture — the architecture lives in the WALL anchors.

*"Is this the best floor plan ARKit can give?"* No, on two levels. (1) From
the SAME anchors, TODAY: intersecting the four envelope walls yields
**4.20 × 3.29 m, opposite sides agreeing to 3–6 cm, 13.8 m²** (247003de;
green dashed on `floorplans.png` — it also closes the corners the anchors
never observed). **The operator confirmed 4.2 × 3.3 m roughly matches the
real room's dimensions** — the envelope derivation is validated against
ground truth. The current pipeline never does this — it bounds the floor
by the coverage polygon and then clips it against furniture planes (§2d),
which is how 13.1 m² became 1.5 m². (2) The platform ceiling is RoomPlan
itself: merged squared walls + floor polygon + openings from Apple's own
LiDAR pipeline — the polished version of exactly this derivation, already
chosen by Option A.

**Operator-defined acceptance metric (post-walk, 2026-07-28)** — recorded as
the design session's quality-bar seed: judge a room by **per-furniture
extent, location, and rotation being correct, plus the envelope** — never by
the plane inventory ("a plane that doesn't exist in reality" must not appear
in the final view; furniture-face plane anchors are internal evidence at
most, not renderable geometry). This bar directly indicts the current
instrument family: yaw — the rotation component the operator judges first —
is unscored by anything we ship today. Corollary the operator converged on
independently: one-object-one-reconstruction (a furniture box as the object
skeleton, best view(s) per box through SAM) makes duplicates impossible by
construction for covered categories — with the architectural consequence
that the BOX carries placement and SAM 3D carries only appearance, and the
practical consequence that SAM passes drop from per-mask-per-frame (39 on
capture #1 for ~12 physical objects) to per-object, relieving the budget
starvation class entirely. Precision note for the session: the boxes are
RoomPlan's (`CapturedRoom.objects`), not raw ARKit's — raw ARKit supplies
only the classified plane anchors and mesh we consume today; RoomPlan's
category list covers large furniture, so the small-item long tail (frames,
mirrors, textiles) still needs SAM detection + label-agnostic dedup.

Walk closed 2026-07-28: no defect classes raised beyond this doc's catalog;
the 13bae607 warm re-drive adjudged moot for the design session; the
reveal-pacing watch skipped under the fidelity verdict.

---

## Appendix — reproduction

All under `outputs/lidar-adjudication/` (gitignored): `analyze_undermerge.py`
(observation table + cluster recovery), `replicate_footprint.py` (the 0.5998 /
0.3144 replication), `analyze_masks.py` (IoS + overlays in `overlays/`),
`analyze_shell.py` (wall reproduction + pairwise table), `plot_floorplan.py`
(`floorplans.png`), `stage_fixtures.py` (the /viewer staging). Scene artifacts
mirrored in `247003de/` + `13bae607/` (manifests, shells, per-frame
objects.json + masks.npz). Bundles read from `outputs/real-capture-*/`
(never mutated). Production knob values confirmed from the serving revision's
env (`gcloud run services describe perception-obj`).
