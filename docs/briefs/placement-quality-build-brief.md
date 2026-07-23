<!--
docs/briefs/placement-quality-build-brief.md — implementation brief for
ARKIT_ONLY placement quality (decision 0067: pixel-footprint fusion
correspondence, multi-view silhouette fitting, the reprojection-scoring
instrument, and 0066 plane anchors consumed as measured contact priors).

Produced by the 2026-07-23 placement-quality design session (branch
placement-quality-design), which locked the forks in decision 0067.
Consumer: the Code session(s) that build it — chunks A–C are separable and
verifiable today against the preserved real capture; chunk D is gated on
the shell build's chunk A (plane anchors on the wire) plus a fresh
capture. Hand over via WORKFLOW.md's Prompt B with one adjustment: the
docs half is ALREADY DONE (decision 0067 and the CLAUDE.md delta land with
the design branch), so implementing sessions skip straight to the build.

Delete this file when the build ships — the durable record is decision 0067.
-->

# Build brief — ARKIT_ONLY placement quality (decision 0067)

```
Read CLAUDE.md and .claude/WORKFLOW.md first. Decision 0067 is the design
record; do not re-open its named rejections without new facts.

Task:        Build the placement-quality pass: (A) the reprojection-scoring
             instrument (two tiers: crop-aware silhouette soft-IoU; crude
             deterministic numpy splat render + masked NCC against the RGB
             crop) wired into fusion best-member selection and the
             manifest's quality fields; (B) pixel-footprint correspondence
             (same-frame nested-duplicate dedup, footprint-based cluster
             join/merge with the relaxed shared-frame rule) plus multi-view
             silhouette fitting as the ARKIT_ONLY position/scale authority
             for ≥2-view clusters; (C) in-plane resolution for planar
             classes via scored 90° candidates; (D) plane-anchor contact
             priors through a shared room_planes.py — floor contact,
             wall attachment, single-view prior-closed placement, the
             conservative class map, the evidence rule. Suggested commit
             split: (1) placement_math primitives + tests; (2) instrument
             + selection + manifest fields; (3) dedup + footprint
             correspondence; (4) silhouette fit + init; (5) in-plane
             resolution; (6) room_planes + priors + single-view solves.

Verify-first (offline probes on the RECORDED data, BEFORE building the
             dependent parts; every input is already on disk or one fetch
             away — bundle + all 126 frames at outputs/real-capture-
             25a14caf/ in the main checkout, splat PLYs staged in
             web/public/dev-fixtures/, masks.npz per complete frame in the
             outputs bucket, raw observations in the manifest):
             (V1) Discrimination probe — gate for chunks A and C: render
             the real curtain splat (real_obj_009_curtain.ply) under the
             four in-plane candidates (and a sign flip) into its observing
             cameras with the crude numpy renderer; score both tiers
             against the recorded masks + RGB crops. The true candidate
             must win by a clear margin on tier 2 (tier 1 is expected to
             tie — that near-tie IS the design's motivation for tier 2).
             Also confirm tier 2 ranks the bed's known-correct rotation
             above its 0065 identity-twin (the sign-flag use case). If no
             margin exists, STOP and re-open the instrument fork in 0067
             before building anything on it.
             (V2) Correspondence probe — gate for chunk B: run containment
             dedup + footprint join/merge offline over the recorded
             observations. Must-pass set: the seven bed observations
             become ONE object (frame 28's nested pair — inter/min
             measured 1.000 — dedups); the curtain stays one cluster; the
             six door observations do NOT collapse (the five single-frame
             doors are genuinely distinct doors/frames — check against
             the frame images); no cross-label mixing.
             (V3) Silhouette-fit probe — gate for chunk B's authority
             swap: fit (s, t) for the curtain cluster offline; the fitted
             center must leave the bed volume and tier-1 score must
             improve over the shipped triangulated placement across all 7
             member frames. Record achieved numbers; they become the
             regression-pin tolerances (pin at achieved accuracy, per
             standing test policy).

Constraints: Chunks A–C: services/perception-obj/ (fusion.py,
             placement.py, new reproject.py; keep policy/orchestration
             here) + packages/schemas/roomstudio_schemas/placement_math.py
             (pure geometry primitives only: pixel projection, soft IoU,
             mask containment, contact solves — the schemas package stays
             free of pipeline policy) + their test dirs. Chunk D adds
             services/perception-obj/room_planes.py — THE single
             anchor-interpretation module (floor selection per 0066's
             semantics, wall set, coplanar merge, ray/plane queries),
             shared with the shell build (0066 chunk B): whichever build
             lands second refactors onto the first's module — check the
             shell branch's tree state at build time; do NOT duplicate
             anchor interpretation.
             Do NOT touch: the per-frame cache contract (objects.json /
             masks.npz shapes and write conditions are FROZEN — all new
             computation happens at fusion time from existing cached
             inputs + the bundle; nothing new is written per frame); the
             SAM accessors or any model-load path; sampling.py/budget.py
             behavior (refinement runs INSIDE the existing budget tracker
             as bounded CPU work with a skip path); the Scene state
             machine / receiver lease machinery; manifest writer count
             (one writer: /process); the proto (chunk D READS 0066's
             plane_anchors field — added by the shell build — and adds
             nothing); the web viewer contract (PositionedSplat unchanged;
             better transforms, same shape); conversation surfaces
             (scene_facts.py, guest_prompt.py, FACTS_VERSION untouched —
             extent_m_sorted lands in the manifest but facts consumption
             is the separate facts_version bump).
             Dockerfile: COPY any new module + extend the build-time
             import smoke (the missing-COPY trap from board item 1).
             Env knobs, all PLACEMENT_*-prefixed, with PLACEMENT_REFINE=1
             as the master switch: PLACEMENT_REFINE=0 must reproduce
             today's behavior exactly (the rollback lever; pin with a
             test). Determinism required end-to-end: fixed iteration
             budgets, no RNG — identical inputs must produce identical
             manifests.

Contract:    Dedup (fusion pre-pass): same frame_index + same label +
             intersection-over-smaller ≥ PLACEMENT_DEDUP_CONTAINMENT
             (default 0.8) → absorb the lower-score observation; fused
             quality records deduped_observations. Masks come from the
             frame's masks.npz (fetched at fusion time; cache-hit frames
             included).
             Footprint correspondence: cluster volume = best member's
             splat under the cluster's current transform estimate;
             project into the candidate observation's frame; join/merge
             requires footprint agreement ≥ PLACEMENT_FOOTPRINT_MIN
             (containment-style, crop-aware). Shared-frame merge rule:
             allowed iff the shared frame's two masks themselves pass the
             dedup containment test; disjoint same-frame masks keep the
             merge refused (two real objects). Applies to ray clusters
             AND placed (depth_fit) clusters — supersedes the 0.4 m
             proximity heuristic's documented merge limitation.
             Silhouette fit (≥2-view ray clusters): minimize mean
             crop-aware tier-1 disagreement over member frames w.r.t.
             (s, t), rotation FIXED from the best member (0065);
             deterministic coarse-to-fine (init from triangulation when
             valid, else a bounded depth sweep along the best member's
             centroid ray); ships method: "silhouette_fit",
             position_source: "silhouette_fit". Triangulation stays as
             init/seed and as the shipped path when refinement is off,
             budget-skipped, or the fit degrades (fit must beat the
             init's tier-1 score to ship; else keep triangulated values
             and record why). Ray-cluster scale: fit's scale replaces
             angular_extent×distance when the fit ships.
             Instrument: score_placement(splat, transform, frame) →
             {tier1: float 0..1, tier2: float 0..1 | null, tiers_used}.
             Tier 2 requires the frame RGB (captures bucket, 1-day
             lifecycle; locally-preserved fixtures in tests) — absent RGB
             → tier1-only, recorded. Best-member selection: rank by
             instrument score (tier2-weighted when present), detection
             score as tiebreak only; detection score stays recorded.
             Sign-flag: score the best member's rotation against its
             mirrored twin; twin materially better → sign_flag: true in
             quality (flag only — rotation correction is 0065's domain).
             In-plane (planar classes = thin-axis splats): 4 candidates
             about the plane normal; winner needs margin ≥
             PLACEMENT_INPLANE_MARGIN on the deciding tier; ships
             in_plane_resolved: true/false (+ scores). No margin → layout
             rotation stands.
             Plane priors (chunk D): read bundle.plane_anchors via
             room_planes; floor = 0066's floor semantics; walls =
             merged vertical planes. Class map (pinned start, env-
             overridable): floor = {bed, sofa, chair, table, desk,
             nightstand, cabinet, dresser, bookshelf, rug}; wall = {door,
             window, curtain, artwork, painting, mirror}; none =
             everything else (incl. table lamp, lamp, speaker, clock,
             plant). Multi-view + prior: contact regularizer, subject to
             the evidence rule — constrained tier-1 score within
             PLACEMENT_PRIOR_MAX_DROP of unconstrained, else drop the
             prior and record the conflict. Single-view + prior: wall
             classes → ray ∩ nearest detected wall behind the mask
             (position offset by half the thin extent; normal from the
             wall; scale solved from the silhouette at that depth);
             floor classes → 1-D root-find in depth s.t. the transformed
             splat bottom touches the measured floor plane; method:
             "single_view_wall_contact" / "single_view_floor_contact".
             No plane / no mapped class / no wall on the ray →
             insufficient_observations stays, honestly. No planes in the
             bundle → priors inert, chunks A–C results identical (pin
             this).
             Manifest (stays v2, additive on fused objects):
             reprojection_score, position_source ("triangulated" |
             "silhouette_fit" | "depth_fit" | "single_view_wall_contact"
             | "single_view_floor_contact"), constraints_applied [],
             in_plane_resolved, sign_flag, extent_m_sorted [3],
             deduped_observations, refinement_skipped (scene-level under
             sampling{} when budget-skipped). frames[] entries:
             byte-unchanged.

Verify by:   Offline probes V1–V3 first (each gates its chunk; achieved
             numbers become pin tolerances). Python per-directory (root
             testpaths exclude perception-obj — run per-dir): schemas
             suite for the new primitives (projection round-trips, soft
             IoU, containment, contact solves on synthetic ground truth
             with known transforms); perception-obj suite for fusion
             invariants — a nested same-frame duplicate must NOT fork a
             cluster (the structural regression), disjoint same-frame
             masks must still refuse to merge, dedup provenance recorded,
             PLACEMENT_REFINE=0 bit-parity with today's fusion, budget
             skip path, determinism (same inputs → identical manifest
             bytes). Real-data regression pins (0065 pattern, new test
             file on the recorded observations + local frames): ONE fused
             bed; curtain fitted center outside the bed volume at the
             V3-achieved margin; curtain in-plane winner = pleats-vertical
             at the V1-achieved margin; doors stay separate; lamp
             triangulation unchanged (0.007 RMS class — compact objects
             must not regress). Live: warm re-drive 25a14caf
             (tools/reenqueue_scene.py --force; multi-round per the 0060
             recipe) → manifest shows one bed, curtain off the bed,
             in_plane_resolved on the curtain, reprojection_score
             populated on every placed object; operator /viewer walk as
             the human instrument (0065: at least one instrument per
             error dimension, including the eyeball; browser-pane note:
             verify orientation via offline renders, pane controls are
             inert). After chunk D (requires shell chunk A shipped + a
             fresh on-device capture with plane_anchors): new capture →
             placed count jumps (most of the 17 single-frame objects
             place via contact priors), doors/artwork on walls, furniture
             on the floor, every prior-placed object carrying
             position_source + constraints_applied; then re-drive
             25a14caf once more to prove the no-planes degrade (priors
             inert, A–C results unchanged).

Convention:  See CLAUDE.md and decision 0067. Tests pin invariants at
             achieved accuracy, not implementation. ARKit frame
             end-to-end; meters; quaternions xyzw unit-norm. Housekeeping
             at end; expect parallel-session commits on main (shell
             build) — rebase, hand-merge CLAUDE.md bullets, renumber a
             colliding decision note if one appears (precedent:
             0065→0066). No merge, no push — report the branch ready.
```
