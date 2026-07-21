<!--
docs/briefs/room-shell-build-brief.md — implementation brief for the room
shell (decision 0065: walls + floor from measured ARKit planes, baked
real-pixel textures, a second perception stage).

Produced by the 2026-07-22 room-shell design session (branch
room-shell-design), which locked the forks in decision 0065. Consumer: the
Code session(s) that build the shell — the chunks below are separable
(chunk A is capture-side and can ride an iOS session; B and C are backend/
web). Hand over via WORKFLOW.md's Prompt B with one adjustment: the docs
half is ALREADY DONE (decision 0065 and the CLAUDE.md delta land with the
design branch), so implementing sessions skip straight to the build.

Delete this file when the shell ships — the durable record is decision 0065.
-->

# Build brief — room shell (decision 0065)

```
Read CLAUDE.md and .claude/WORKFLOW.md first. Decision 0065 is the design
record; do not re-open its named rejections without new facts.

Task:        Build the room shell: (A) ARKit plane anchors captured on-device
             and carried in the CaptureBundle; (B) a /shell Cloud Tasks stage
             on perception-obj that assembles floor+wall quads from the
             anchors, bakes textures from the capture's own RGB with SAM 3
             masks excluding furniture, inpaints occluded regions, and writes
             scenes/{scene_id}/shell.json + textures; (C) the assets endpoint
             serving shell + signed texture URLs, and the web viewer rendering
             the shell as the stage under the existing reveal. Suggested
             commit split: (1) proto + regen + schema tests; (2) iOS capture +
             assembly + tests; (3) shell geometry/texture modules + tests;
             (4) /shell route + enqueue + Dockerfile/infra; (5) api-public;
             (6) web.

Verify-first (do these BEFORE building the dependent parts; each kills the
             design's largest open risk in its area):
             (V1) Spark depth compositing: in the /viewer dev workbench, add
             a temporary hardcoded depthWrite:true single-sided textured quad
             behind/under the staged real-scene splats and confirm correct
             occlusion both ways (splat in front of wall, wall behind splat).
             The grid today is depthWrite:false — mixed depth compositing is
             UNPROVEN in our tree. If it fails, stop and re-open 0065's
             representation fork (synthesized-splat shell) before any bake
             work; the bake pipeline is identical either way.
             (V2) Inpainting model selection: pick the LaMa-class model
             (constraints: texture-continuation not generative, permissive
             license, CPU-capable at 1-2 s per 512px tile, deterministic,
             weights bakeable per 0008). Record the choice + license in the
             module docstring.
             (V3) After chunk A builds: on-device plane-anchor walk of the
             real room — anchor count, wall coverage, extent quality — before
             tuning SHELL_* defaults. Plane detection quality is the design's
             main empirical unknown (0065 records the re-open condition).

Constraints: Chunk A: packages/schemas/capture_bundle.proto (additive field
             ONLY — no schema_version bump; the ingest gate is untouched),
             ./tools/gen_proto.sh regen (Python + Swift, commit both), iOS
             changes confined to Capture/ (CaptureManager configuration +
             final-anchor capture at stop; BundleAssembler serialization) —
             no new screens, no upload-machinery changes. Note: device builds
             currently need the 0051 entitlement workaround or post-
             enrollment provisioning (see CLAUDE.md's 0051 bullet).
             Chunk B: services/perception-obj/ only (+ optional
             tools/reenqueue_scene.py --shell flag for operator re-drives).
             New modules deferred-import like placement/fusion; Dockerfile
             gains their COPYs AND the build-time import smoke lines (the
             missing-COPY trap from board item 1 — placement.py passed every
             probe while absent from the image). Do NOT touch: the Scene
             state machine or receiver lease machinery (shell never writes
             Scene status), manifest.json (single writer stays /process),
             sampling/budget/placement/fusion behavior, the SAM accessors
             (the /shell path must never trigger a model load).
             Chunk C: api-public assets route + web. Manifest stays verbatim
             in the response (0054) — shell is a SIBLING field. Web: shell
             types are renderer-agnostic (0053 containment — three.js stays
             inside SplatViewer.tsx); no CSP change (textures come from
             storage.googleapis.com, already in connect-src; confirm img/
             texture fetch uses fetch/XHR paths covered by it). No
             conversation changes anywhere: guest_prompt.py, scene_facts.py,
             and the charter's "walls on their way" line are untouched —
             shell-derived facts are a later facts_version bump.
             Everywhere: no invented geometry. A bundle without planes
             degrades to unavailable; walls that don't close a loop ship as
             detected; nothing fake renders.

Contract:    Proto (additive): message PlaneAnchor {Pose pose (world_from_
             anchor; anchor-local +Y = plane normal); float center_x/y/z
             (anchor space); float extent_width/extent_height; float
             rotation_on_y_rad; enum PlaneAlignment {UNSPECIFIED, HORIZONTAL,
             VERTICAL} alignment; string classification (ARKit verbatim,
             empty when unavailable); repeated float boundary_xz (optional
             anchor-space polygon, x,z pairs)}. CaptureBundle gains
             `repeated PlaneAnchor plane_anchors = 12` — the session's FINAL
             anchor set, serialized at capture stop. iOS enables
             planeDetection = [.horizontal, .vertical] in the ARWorldTracking
             configuration (CaptureManager); anchors read from the session at
             stop time, world frame identical to camera poses (same session).

             /shell task: enqueued by /process's success path AFTER
             release_ready, fire-and-forget (enqueue failure logs, scene
             stays ready; the client's grace window handles absence). Same
             queue + OIDC invoker pattern as /process; audience
             RECEIVER_URL + "/shell"; payload {scene_id, bundle_uri}; task
             name "shell-{scene_id}-{ts}" (Cloud Tasks tombstones names ~1h
             — 0060; a bare name would silently dedupe re-drives). IAM
             prerequisite (folds in CLAUDE.md's audit item): identify the
             perception-obj runtime SA, then grant it
             roles/cloudtasks.enqueuer on the queue and
             roles/iam.serviceAccountUser on the Cloud Tasks invoker SA.
             Handler: OIDC-verify; no scene lease (idempotent single-blob
             PUT; concurrent runs benign); request-entry deadline via the
             existing budget pattern; PoisonError-class outcomes and
             completed runs return 200 (drain), environmental failures 5xx
             (Cloud Tasks retries, maxAttempts=3). Reads: bundle proto
             (poses, gravity, plane_anchors), manifest.json read-only (the
             complete-frame list = frames[] entries without budget_stopped),
             masks.npz per complete frame, RGB from the captures bucket.
             Writes: scenes/{scene_id}/shell.json +
             scenes/{scene_id}/shell/textures/*.png. NEVER manifest.json,
             NEVER Firestore.

             shell.json (shell_version 1, deterministic for identical inputs
             — no timestamps in the body): {shell_version, scene_id, status:
             "ready"|"unavailable", reason: null|"no_geometry_source"|
             "capture_expired", method: "arkit_planes" (ladder per 0065:
             "arkit_planes+depth", "roomplan" later), floor: {quad: [[x,y,z]
             x4], y, texture_gcs_uri, observed_fraction, inpainted_fraction,
             source} | null, walls: [{wall_id, quad: [[x,y,z] x4] wound
             inward (front face toward room interior), texture_gcs_uri,
             observed_fraction, inpainted_fraction, source, classification |
             null}], quality: {planes_in_bundle, frames_used, ...}}.
             IMPORTANT distinction the client relies on: shell.json ABSENT =
             not yet (keep grace window); status "unavailable" = never
             coming (stop waiting, keep the grid). Unavailable is a WRITTEN
             file, not an error.

             Geometry assembly semantics: floor = lowest cluster of large
             horizontal anchors, coplanar-merged; its polygon (anchor
             boundaries/extents union, clipped by walls where present) is
             carried in the floor texture's ALPHA channel — the client
             renders only quads. Walls = vertical anchors, coplanar-
             overlapping anchors merged, height = detected extent (no
             extrapolation). Textures: per-plane orthographic texel grid
             (~2 cm/texel, long edge ≤ 2048 px, PNG w/ alpha; env knobs
             SHELL_METERS_PER_TEXEL, SHELL_TEXTURE_MAX_PX); samples from
             complete frames only, excluded under any SAM 3 mask, incidence/
             distance-weighted, median-blended; per-texel observation counts
             → observed_fraction; holes inpainted by the V2 model →
             inpainted_fraction; observed_fraction below
             SHELL_MIN_OBSERVED_FRACTION → the plane ships untextured with
             source "unobserved" + a neutral treatment client-side.

             Assets endpoint: fetch scenes/{id}/shell.json (path derived
             from result_uri's directory); response gains sibling field
             shell: <shell.json content> | null; shell texture gs:// URIs
             join the signed asset_urls walk (same TTL). Web:
             assembleScene → {splats, shell: ShellPlane[] | null,
             unrenderable}; ShellPlane = {kind: "floor"|"wall", corners:
             [x,y,z][4], texture_url, observed_fraction, inpainted_fraction}
             (renderer-agnostic); SplatViewer gains shell?: ShellPlane[] —
             single-sided textured meshes (dollhouse cutaway from winding),
             floor shape via texture alpha, shell precedes objects in the
             reveal (floor → walls → largest-first objects; reduced motion:
             everything at once). Room-page handoff: on ready, if shell is
             absent (not "unavailable") the page may hold the reveal or
             refetch briefly (bounded backoff, then proceed with the grid) —
             pacing tunable at the real-browser watch CLAUDE.md already
             schedules; narration promises a shell only when one is coming.
             Mock parity: tools/make_synthetic_splat.py grows a synthetic
             shell fixture (quads + generated PNGs) so mock/dev-fixture
             rooms exercise both shell and no-shell states offline.

Verify by:   Python (per-directory, per CLAUDE.md's testpaths note): shell
             assembly unit tests on synthetic fixtures with known ground
             truth — floor selection + coplanar wall merge invariants; mask
             exclusion honored in the bake; observed/inpainted fractions;
             alpha-polygon correctness; degrade paths (no planes →
             unavailable/no_geometry_source; missing RGB →
             capture_expired); byte-identical shell.json on identical
             inputs; budget refusal path; /shell TestClient tests per 0010
             (OIDC reject, drain vs retry classification, no Firestore
             writes). Schemas: gen_proto.sh regen both languages, suite
             green; api-core fixture builder optionally grows plane_anchors
             (fixture self-tests stay green). iOS: unit tests for anchor
             serialization (world-frame pose passthrough, alignment/
             classification mapping); on-device: capture the real room,
             tools/inspect_bundle.py shows plane_anchors with sane count/
             extents (the V3 walk). Web: vitest for assembleScene shell
             mapping + the absent/unavailable distinction; lint +
             static-export build green. Live E2E (after A+B+C deploy, order
             matters — iOS build first so a fresh capture carries planes):
             fresh on-device capture → ready → shell task completes in one
             request → shell.json + textures in the outputs bucket → assets
             response carries shell + fetchable signed texture URLs → /room
             renders floor+walls under the placed objects; screenshot as
             proof. Degenerate regression: re-drive the preserved 25a14caf
             bundle (re-upload; it predates plane anchors) → /shell writes
             a clean unavailable/no_geometry_source and the room page keeps
             today's grid — the honest-degrade path proven live.

Convention:  See CLAUDE.md and decision 0065. Tests pin invariants, not
             implementation. Every FastAPI route gets TestClient tests
             (0010). ARKit frame end-to-end; meters; quads in world frame.
             Housekeeping at end (expect the 0063-probe session's commits on
             main — rebase, and hand-merge the CLAUDE.md bullets). No merge,
             no push — report the branch ready.
```
