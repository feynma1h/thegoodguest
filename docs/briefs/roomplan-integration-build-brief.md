<!--
docs/briefs/roomplan-integration-build-brief.md — implementation brief for
the RoomPlan integration (decision 0077: CapturedRoom JSON verbatim on the
wire, boxes as the object skeleton, census-driven frame selection,
CapturedRoom as the shell geometry source, envelope-only degrade shell).

Produced by the 2026-07-28 board-7 design session. Two verify-first probes
ALREADY RAN in that session (P1 scorer-regime, P2 JSON parse — results in
decision 0077 and gitignored outputs/roomplan-design/); their achieved
numbers become regression-pin tolerances in RP-4/RP-2. Consumer: the Code
session(s) that build it. Chunks RP-0..RP-5 are server/schemas work
verifiable OFFLINE against the spike fixture before any iOS work; RP-6/7
are iOS; RP-8 is the deploy + operator gate. Hand over via WORKFLOW.md's
Prompt B with the usual adjustment: the docs half is ALREADY DONE (decision
0077 + the CLAUDE.md delta land with the design session), so implementing
sessions skip straight to the build.

Delete this file when the build ships — the durable record is decision 0077.
-->

# Build brief — RoomPlan integration (decision 0077)

```
Read CLAUDE.md and .claude/WORKFLOW.md first. Decision 0077 is the design
record; 0075/0076 are its evidence base; do not re-open named rejections
without new facts. The operator acceptance metric is the bar throughout:
per-furniture extent, location, and rotation correct, plus the envelope;
the plane inventory is NOT a quality signal; a plane that doesn't exist in
reality must never render.

Task:        Build the LIDAR_ROOMPLAN tier end-to-end. Server first (all
             offline-verifiable against the spike fixture), then iOS:
             (RP-0) spike-run→CaptureBundle converter tool;
             (RP-1) schemas: RoomPlanModel.json_gcs_path, reserve the
                    summary field;
             (RP-2) roomplan_room.py — the CapturedRoom JSON parser +
                    adapters onto the room_planes query surface;
             (RP-3) shell v3 from CapturedRoom + 0069 materials retarget +
                    envelope-only degrade shell + viewer polygons;
             (RP-4) placement: box association, box-anchored placement
                    with the scored splat-axis correspondence, box-dup
                    suppression, the three long-tail gates;
             (RP-5) census-driven selection + two-pass /process
                    (per-object reconstruction);
             (RP-6) iOS co-run + serialization + tier + review census;
             (RP-7) iOS Good Guest live floor plan (task #13);
             (RP-8) deploy + upload the converted spike bundle + operator
                    /viewer walk scored by the acceptance metric.
             Sequence: RP-0/1 → RP-2 → RP-3/4/5 (server, interleavable;
             RP-4 before RP-5 — selection consumes association) → RP-6 →
             RP-7 → RP-8. RP-6 can start after RP-1 in parallel with
             server chunks (separate session/worktree per CLAUDE.md).

Fixture:     outputs/roomplan-spike/probe-20260728-143602/ — 722 keyframes
             (RGB jpg + depth f32 + confidence u8), keyframes.ndjson (pose
             quat xyzw, gravity, RGB + depth-scaled intrinsics per line),
             captured_room_built.json (the RoomBuilder [.beautifyObjects]
             output; ground truth per decision 0076: 13 walls, floor
             14.98 m², 9 objects operator-verified 9/9), plane_anchors.json
             (incl. the two rejected seat planes), USDZ ×2. One shared
             world frame (0076 Q2). RP-0 turns this into a real
             CaptureBundle so every server chunk runs against it offline,
             and RP-8 uploads it so the live E2E runs on the room with
             known ground truth.

Verify-first (ALREADY RUN in the design session — do not rebuild the
             design on failure, they PASSED; re-run only if the code path
             disagrees with the recorded numbers):
             (P1) Box-frame candidate scoring on 247003de's bed: at a
             box-quality center the two-tier instrument picks the correct
             facing with tier-2 margin 0.15, rejects upside-down by 0.37,
             beats the shipped layout rotation; at the SHIPPED (0.79 m
             off) center the same scorer prefers upside-down — position
             precedes rotation; a 1.4 m close view zeroes tier 1 — skip
             degenerate views. These three numbers become RP-4 pins.
             (P2) The Codable JSON parses server-side with no coreModel/
             USDZ and reproduces every 0076 fact (13 walls up_y=+1.0000,
             3.05 top + four 1.95 segments, floor 14.98 m² 10 corners,
             9 pure-yaw objects, parented doors/windows). Becomes RP-2's
             pin set. Probe scripts: outputs/roomplan-design/.

Constraints: Proto (RP-1): additive ONLY — RoomPlanModel gains
             json_gcs_path; RoomPlanSummary/RoomPlanObject messages are
             deleted and field 3 reserved (zero wire history — no client
             ever emitted RoomPlanModel); schema_version stays "1";
             plane_anchors unchanged and still shipped on every tier;
             regen Python AND Swift via ./tools/gen_proto.sh.
             Server: services/perception-obj/ only. New modules
             (roomplan_room.py, and RP-5's selection module if split out)
             need Dockerfile COPY + the build-time import smoke (the
             missing-COPY trap from board item 1). ONE manifest writer
             (/process); /shell writes shell.json only. The per-frame
             cache contract is FROZEN for existing records; RP-5 may add
             a per-frame `skipped_reason` for masks deliberately not
             reconstructed — additive, never mutating existing shapes.
             room.json is cached to the outputs bucket at first /process
             read (outputs/scenes/{id}/roomplan/room.json) — geometry must
             survive the captures bucket's 1-day sweep (0065 sidecar
             lesson); /shell and warm re-drives read the cached copy.
             Degrade locks, each PINNED by a test: no room.json (or parse
             failure) → LIDAR_ARKIT semantics + structured log + manifest
             note roomplan_parse_failed — NEVER failed_invalid; no census
             → sampler = 0062 verbatim; no plane anchors → chunk D inert
             (existing pin); PLACEMENT_REFINE=0 → bit-parity with today
             (existing pin, must still hold on the merged tree).
             Determinism end-to-end: identical inputs → identical manifest
             bytes; selection is deterministic (fixed order, ties by
             lower frame index) because retries must hit their own GCS
             cache (0062's law).
             iOS (RP-6/7): CaptureManager owns the RoomCaptureSession;
             production config runs FIRST with .resetTracking (0076 —
             RoomPlan never resets tracking; the host owns hygiene);
             copy-out per-frame handling verbatim — NEVER retain ARFrames
             (10 retained = pipeline death in ~1 s, measured);
             stop order: cs.stop(pauseARSession: false) → snapshot plane
             anchors → arSession.pause() → await RoomBuilder
             ([.beautifyObjects], ~1.7 s, ~905 MB transient after pause)
             → JSONEncoder → roomplan/room.json + .parametric USDZ →
             roomplan/room.usdz → bundle assembly. RoomBuilder throw or
             zero surfaces → tier LIDAR_ARKIT, flow unchanged.
             didEndWith(error: worldTrackingFailure) after the 10 s abort
             → end capture gracefully with the partial room (still
             ROOMPLAN tier if it built). Upload sequencing unchanged
             (room.json/usdz are phase-1 manifest blobs, bundle.pb last).
             Mint-scale check: a 722-keyframe walk ≈ 2200 manifest paths;
             verify the parallel mint (UPLOAD_SESSION_MINT_CONCURRENCY=16,
             28.9 s at 385 paths cold) + the client 60 s timeout hold at
             that scale BEFORE the first long-walk capture; bump the env
             knob and/or client timeout if not — an env-only change.
             Web: SplatViewer stays the only three.js module; shell v3
             walls are polygons (triangulate like the floor); no CSP
             change; PositionedSplat unchanged.
             Do NOT touch: Scene state machine / lease machinery; the SAM
             accessors or model-load paths; conversation surfaces
             (scene_facts.py FACTS_VERSION untouched — box extents reach
             facts in the separate facts_version bump per standing plan);
             SHELL_* merge knobs (0075: measured correct — the envelope
             derivation SELECTS walls, it does not re-merge them).

Contract:    Wire: RoomPlanModel { usdz_gcs_path = 1 (optional in
             practice), roomplan_version = 2 (e.g. "ios26.5.2;
             CapturedRoom.v2;beautifyObjects"), reserved 3,
             json_gcs_path = 4 }. Tier LIDAR_ROOMPLAN iff a built
             CapturedRoom with ≥1 wall or floor ships.
             roomplan_room.py (RP-2): parse transforms as COLUMN-MAJOR
             float16 lists; category/confidence are single-key dicts;
             walls/floor carry polygonCorners in LOCAL frame (empty →
             rectangle from dimensions); doors/windows/openings parent
             via parentIdentifier → opening rects in the wall's plane
             frame (normalized rect_uv like 0069); objects carry
             dimensions (x,y,z LOCAL — long axis may be X or Z, do not
             assume), pure-yaw transform, confidence, attributes. Adapt
             into the room_planes dataclass surface so chunk D and the
             sanity gate consume RoomPlan planes UNCHANGED on this tier.
             Pin set = P2's numbers, exact.
             Shell v3 (RP-3): SHELL_VERSION 3, method "roomplan"; walls as
             world polygons + per-surface confidence + openings;
             floor polygon verbatim; materials layer (shell_observation +
             shell_material) unchanged in shape and THE fallback rule
             pinned (below gate/failure → family null → measured-albedo
             matte; no albedo → neutral). capture_expired costs materials
             only (geometry from cached room.json). Envelope-only degrade
             (LIDAR_ARKIT + roomplan-absent ROOMPLAN bundles): select
             envelope walls from anchors by classification ∈ {wall, door,
             window} OR height-reach to the common top, intersect the 4
             best-fit envelope planes for the floor rectangle (the
             adjudication's validated derivation, operator-confirmed
             4.20×3.29 on 247003de); furniture-height/seat/none planes
             are internal evidence, never rendered; method
             "anchor_envelope". Fixtures 247003de/13bae607 re-derive to
             4-wall envelope shells offline as the gate.
             Placement (RP-4): association = project box footprint into
             frame (poses + intrinsics), match SAM masks by footprint
             overlap ≥ PLACEMENT_BOX_MATCH_MIN (default 0.5, one-room
             placeholder like every knob) + label-family compatibility
             (env-overridable map; starting families: bed↔{bed}, table↔
             {table, desk, nightstand}, chair↔{chair, stool, bench},
             storage↔{cabinet, dresser, wardrobe, bookshelf, shelf},
             sofa↔{sofa, couch}, television↔{tv, television, monitor});
             greedy best-match, deterministic. Box-anchored object:
             position/extent/upright/yaw from the box; splat = best
             associated view; axis mapping = enumerate extent-consistent
             assignments (near-equal extents → enumerate all), score the
             facing pair with score_placement AT THE BOX CENTER across
             non-degenerate associated views (skip views where the
             projected box is marginal — P1's f164 lesson); winner needs
             PLACEMENT_AXIS_MARGIN (default from P1's achieved 0.10
             combined, pin at achieved); below margin → extent-best
             mapping + splat_axis_resolved: false; scorer prefers the
             anti-RoomPlan facing → facing_flag: true, ship RoomPlan's
             (flag-only v1). Render scale uniform (median ratio), per-axis
             residuals recorded as box_fit_residual; extent_m_sorted =
             BOX dims sorted (measurement truth — the fit halved the real
             bed's width). Unmatched boxes ship placed: false, reason
             "no_appearance", box geometry carried (honest inventory).
             Suppression: a non-box fused object whose center lands inside
             a matched box's volume with a compatible label → dropped,
             recorded as box_duplicate_suppressed. Long-tail gates:
             (i) label-agnostic containment dedup — extend the
             mutual-singleton rule across labels (the f242 triple:
             pairwise IoS 0.999 under three labels); (ii) mirror
             depth-trust: depth_fit nn_rms > PLACEMENT_DEPTH_TRUST_RMS_M
             (default 0.05; the real mirror measured 0.196 vs 0.007
             typical) → demote to wall-contact prior / ray path;
             (iii) textile silhouette-span: projected-splat extent vs mask
             extent ratio < PLACEMENT_SPAN_MIN (default 0.5) → scale
             suspect, cap-to-silhouette or flag (the 262k px throw that
             shipped at 0.34 m). Manifest additions (additive, v2.x):
             position_source "roomplan_box", roomplan_box {category,
             attributes, confidence, dims, yaw_rad, box_id},
             splat_axis_resolved, facing_flag, box_fit_residual,
             sam_label (provenance when display label comes from the
             box), box_duplicate_suppressed on suppressed entries;
             scene-level roomplan {present, wall_count, object_count,
             parse_ok}.
             Selection (RP-5): two-pass /process — pass 1 segments
             sampled frames (mask cache unchanged) + associates; pass 2
             reconstructs per-box best view(s) + long-tail masks under
             budget admission, priority order: uncovered boxes first,
             then low-margin second views, then long tail by detection
             score. Sampler: box-visibility set-cover (score = projected
             on-frame box area × in-frame fraction, deterministic greedy)
             + pose-diverse FPS residue for the long tail within
             PERCEPTION_MAX_FRAMES; sampling{} records policy +
             per-box frame assignments. Budget admission stays the
             GUARANTEE untouched (0062 decoupling).
             iOS (RP-6): census line at review from the built room;
             tier dispatch + serialization per Constraints; RP-7 the live
             floor plan (walls stroke in, labeled box rects, camera cone,
             instruction relay) behind the existing LiveMeshHost seam,
             reused at review.

Verify by:   RP-0: tools/inspect_bundle.py clean on the converted spike
             bundle; poses/intrinsics/depth spot-checked byte-consistent
             with keyframes.ndjson; room.json attached at
             roomplan/room.json.
             RP-2: P2 pin set exact (13 walls, up_y +1.0 to 1e-4, tops
             {3.05, 1.95}, floor 14.98 m² / 10 corners, 9 objects
             pure-yaw incl. the 40.8° chair, parenting complete);
             adapters satisfy the room_planes query surface (chunk D's
             tests run against RoomPlan-derived planes unchanged).
             RP-3: offline shell.json v3 from the spike fixture matches
             the pin set; zero texture blobs; openings normalized in
             [0,1]; viewer renders the parametric room from a staged dev
             fixture (clean console); envelope-only derivation on
             247003de/13bae607 yields 4-wall shells with the measured
             floor rectangle (pin 4.20×3.29 ± the adjudication's 3–6 cm);
             both degrade legs pinned (roomplan_parse_failed;
             capture_expired = materials-only loss).
             RP-4: P1 pins as regression tests at achieved values (facing
             margin, upside-down rejection, shipped-center failure as a
             pinned NEGATIVE — the scorer preferring upside-down at the
             bad center is the recorded reason box centers are
             load-bearing); association on the spike fixture: box→frame
             projection overlays eyeballed + synthetic-mask unit tests;
             247003de manifests byte-stable with refinement on and no
             room.json present (degrade lock); the three long-tail gates
             each pinned on their measured case (f242 triple collapses to
             one; mirror demoted at 0.196; textile flagged at the span
             ratio).
             RP-5: on the spike fixture all 9 boxes covered in ≤
             PERCEPTION_MAX_FRAMES with ≥1 good view each; determinism
             (two runs → identical selection + manifest); budget
             simulation shows per-object reconstruct counts ≈ box count +
             long tail, not 39; no-census path byte-identical to 0062
             selection.
             RP-6 (hardware, iPhone 16 Pro): capture-to-doorway walk with
             room.json + room.usdz in GCS, tier LIDAR_ROOMPLAN on the
             scene doc, census line at review; forced-abort path (cover
             the sensor 10 s mid-scan) ships the partial room or
             LIDAR_ARKIT gracefully; mint-scale check at the real path
             count. iOS suite green incl. the 4 live tests.
             RP-7: screenshot verification per house AX rules (the suite
             pins logic, screenshots pin rendering); walls/boxes appear
             live during a real scan; instruction relay fires.
             RP-8: deploy perception-obj + api-public (RUNBOOK phases);
             upload the converted spike bundle as a real capture; warm
             re-drive to full coverage; then THE GATE — operator /viewer
             walk scored by the acceptance metric per furniture piece
             (extent / location / rotation each judged, plus the
             envelope), against 0076's 9/9 box ground truth; adjudicate
             the uniform-vs-stretch splat A/B on the real room in the
             same walk. Record achieved per-piece results in the
             housekeeping bullet; they are the tier's baseline numbers.

Convention:  See CLAUDE.md + decision 0077. Tests pin invariants at
             achieved accuracy. ARKit frame end-to-end; meters;
             quaternions xyzw unit-norm on the wire (CapturedRoom
             transforms are column-major matrices at the parse boundary
             only). All new knobs env-overridable with one-room-calibrated
             defaults, named PLACEMENT_* / PERCEPTION_* / SHELL_* by
             owner. Housekeeping at end of every chunk session; expect
             parallel sessions on main — worktrees mandatory (iOS plist
             gotcha in memory), rebase + hand-merge CLAUDE.md bullets,
             renumber colliding decision notes. No merge to main without
             green suites; no push (no remote). The 16 Pro re-sign clock:
             rebuilt 2026-07-28, expires 2026-08-04 — RP-6 sessions check
             it first.
```
