# roomstudio

A spatial intelligence platform: capture a room with an iPhone, get a per-object 3D-Gaussian-splat scene you can edit in a browser.

This file is the always-current state of the project. Both Claude Code (reads it automatically) and Claude Chat (you upload it) consume it at the start of every session. If something in here is wrong, fix it before doing anything else.

## What we're building

A premium consumer product with three surfaces:

- **iOS capture app** (Swift + ARKit + RoomPlan) — capture-only, no viewer. The app's only job is producing a high-quality capture bundle and uploading it. Users come to the web for everything else.
- **Backend perception pipeline** (FastAPI on Cloud Run, `asia-southeast1`) — ingests bundles, runs SAM 3 segmentation + SAM 3D Objects reconstruction, places objects in the room's gravity-aligned metric frame using ARKit data, generates inpainted scene-3DGS for walls/floor.
- **Web app** (Next.js + WebGPU splat rendering) — the actual product. Browse, edit, replace, share scenes. Capture path is one screen: "Open the iOS app."

Photo-upload (Android, no-iPhone users) is a deferred concern. Until the iOS path is solid we don't build the web-fallback capture.

## Capture bundle — the central contract

Everything between iOS and the backend flows through `packages/schemas/capture_bundle.proto`. The bundle is metadata; pixel data (frames, depth) lives in GCS by reference.

Frame of reference is **ARKit-native** end-to-end: right-handed, +Y up, camera looks down -Z in its local frame. The iOS client does NOT transform; the backend converts to downstream model frames (e.g. SAM 3D's per-object frame) when it has to.

Pose is **position + unit quaternion (x, y, z, w)**, not a 4×4 matrix. ARKit-native, ARCore-native, glTF-native. 7 floats instead of 16. The proto file's docstring carries the full reasoning.

Quaternion math is centralized in `packages/schemas/roomstudio_schemas/pose_math.py`. Any Python that touches a Pose imports from there. Do not re-implement.

## Repo layout

```
packages/schemas/                 capture bundle proto + generated Python + pose math
  capture_bundle.proto              source of truth
  roomstudio_schemas/
    capture_bundle_pb2.py            generated; regen with ./tools/gen_proto.sh
    pose_math.py                     quaternion ops; one place to change
  tests/                              25 invariant tests, all green

packages/api-core/                shared logic consumed by both API services
  roomstudio_api_core/
    scene.py                         Scene model, SceneStatus, DeviceIdSource, state machine
    scene_read_repo.py               SceneReadRepository ABC + Firestore/in-memory read-only impls
    upload_session_repo.py           UploadSessionRepository ABC + Firestore/in-memory impls + gcs_mint_resumable_uri
  tests/                              48 direct unit tests, all green

tools/                            local scripts (run from repo root)
  gen_proto.sh                      regenerate Python and Swift (ios/RoomStudioCapture/RoomStudioCapture/Generated/)
  build_test_bundle.py              synthesize a bundle from test_data/photos
  inspect_bundle.py                 verify a bundle parses + smoke-checks

services/
  api-public/                     client-facing API (--allow-unauthenticated, Firebase JWT verify)
  api-internal/                   internal API (--no-allow-unauthenticated, Cloud Run IAM)
  perception-obj/                 SAM 3 + SAM 3D Objects (deployed)
  perception-geom/                VGGT for the photo-upload path (deployed, photo-path only)

infra/                            Cloud Build configs, deploy scripts
docs/decisions/                   short notes on dead-ends — see "When to write a decision note"
test_data/photos/                 9 HEIC photos of a real room, for synthesis testing
outputs/                          gitignored; generated artifacts
```

## What works right now

- The capture-bundle contract is defined, generated, and tested. `python tools/build_test_bundle.py && python tools/inspect_bundle.py outputs/test_bundle/bundle.pb` runs clean end-to-end.
- The photo-upload pipeline (`perception-obj`, `perception-geom`) is deployed and produces per-object splats from photo uploads. It's the old path; we're keeping it alive but not iterating on it.
- 25 schema + math tests, all passing. Don't break them.
- **`services/api` two-service split deployed** (see `docs/decisions/0016`): `services/api-public/` (`--allow-unauthenticated`, Firebase JWT in-app verification, hosts `/upload_session`) + `services/api-internal/` (`--no-allow-unauthenticated`, Cloud Run IAM, hosts `/ingest` + `/ingest/eventarc`) + `packages/api-core/` (shared `UploadSessionRepository` + `gcs_mint_resumable_uri`). Both services live on Cloud Run `asia-southeast1`; see revision details on line below.
- `perception-obj` `/process` receiver: accepts Cloud Tasks HTTP POST (OIDC-verified), claims scenes atomically in Firestore with lease-TTL crash recovery, runs SAM 3 + SAM 3D Objects, writes outputs to GCS, updates Scene state, fires FCM on terminal transitions. System is functional end-to-end locally. Dockerfile, cloudbuild config, and deploy script env vars are all patched (see `docs/decisions/0005`, `0006`). Models are lazy-loaded on first `/process` call: `/health` returns 200 immediately for the startup probe; `/ready` reports per-model load state. DINOv2 weights (~1.13 GB) are pre-cached in the image at `TORCH_HOME=/opt/torch_hub`, eliminating the cold-start runtime fetch. Startup probe targets `httpGet /health`. 165 tests passing across both services.
- **Stuck-scene lease-semantics fix shipped and verified** (revision `perception-obj-00024-89b`, 2026-05-25). The bug from `docs/decisions/0011` and `0012` is fixed: `/process` reclaims stale leases atomically, `EnvironmentalError` eagerly releases the lease, SIGTERM resets held scenes to `queued`, and `holder_id` is checked defensively on all three lease-mutating paths. Verified production trace for scene `561c68ae`: `action=claim` → OOM → `action=release_error` → `action=reclaim_stale` → OOM → `action=release_error` → `action=reclaim_stale` → OOM → `action=release_error` (final, `is_final_attempt`) → scene `failed`. Note: the trace exercised the eager-release optimization path; the load-bearing expiration-check path (stale-but-not-cleared leases) is covered by unit tests only, not this production trace.
- **Smoke tool pass 3 scoping locked** (see `docs/decisions/0017`): manifest derivation, upload sequencing, and PUT semantics are pinned against the current `/upload_session` contract. Recon from a prior Code session covers the handler, request/response schemas, GCS minting, and Firestore session repo.
- **Smoke tool pass 4 scoping locked** (see `docs/decisions/0019`): polling contract pinned against a new `GET /scenes/by-bundle/{bundle_id}` endpoint on api-public. Recon from prior Code session covers the Scene document lifecycle, field population at ingest, idempotency under at-least-once Eventarc delivery, and the existing `SceneRepository` patterns in api-internal.
- **Smoke tool pass 5 scoping locked** (see `docs/decisions/0020`): four-mode CLI shape, `--cleanup` semantics, `--verbose`/`--json` output, and exit-code 2 (misconfig vs. system-under-test failure) pinned.
- **`tools/upload_test_bundle.py` written**: 1008-line substitute iOS client. Four modes (happy-path, skip-blob, duplicate-event, auth-rejection), two-phase upload sequencing per decision 0017, polling per decision 0019, failure semantics per decision 0020. `--cleanup`, `--verbose`, `--json` (NDJSON), exit codes 0–3. 27 unit tests in `tools/test_upload_test_bundle.py`. Verification against a deployed stack pending runbook execution.
- **`packages/api-core/roomstudio_api_core/test_fixtures/capture_bundle.py` added**: `build_capture_bundle()` + `TestBundleArtifacts`. Generates valid `CaptureBundle` protos for all three tiers with configurable per-frame blob kinds. 22 new invariant tests.
- **Deploy runbook preconditions landed**: `infra/eventarc_setup.sh` corrected — `INGESTER_SERVICE` changed from `roomstudio-api` to `api-internal`, `INGESTER_SA` changed to `api-internal-runtime@roomstudio.iam.gserviceaccount.com` (both were stale post-split). `services/api/` confirmed local-only (only gitignored `__pycache__/`) and removed. `upload_sessions.created_at` verified correct (`datetime.now(tz=timezone.utc)`) — TTL semantics match intent, no code change needed.
- **`infra/RUNBOOK.md` written**: 8-phase deploy runbook (Preflight + Phases 1–8) for the two-service iOS upload path (decisions 0014–0020). `eventarc_setup.sh` gains `--lifecycle-only`, `--ttl-only`, `--trigger-only` flags for per-phase invocation.
- **`GET /scenes/by-bundle/{bundle_id}` on api-public built** (board item 1, decision 0019). `SceneReadRepository` + `InMemorySceneReadRepository` + `FirestoreSceneReadRepository` in `packages/api-core/`. Scene model moved to `packages/api-core/roomstudio_api_core/scene.py`; `services/api-internal/scene.py` is now a re-export shim. `SceneRepository` in api-internal extends `SceneReadRepository`; `FirestoreSceneRepository` extends `FirestoreSceneReadRepository` (no duplication of read logic). 242 tests across all packages, all green (25 schema + 48 api-core + 40 api-public + 94 api-internal + 35 smoke tool). Runbook Phase 0 preflight gate now satisfied.
- **Phase 1 deploy infrastructure is live.** GCS lifecycle rule on `gs://roomstudio-captures` (delete after age=1, prefix `captures/`) is configured. Firestore TTL policy is set on `upload_sessions.created_at` (state `ACTIVE`). Automatic single-field index on `scenes.bundle_id` is confirmed unexempt. `infra/RUNBOOK.md` Phase 0 preflight passes; v2 PR hardening (all 20 findings) landed.
- **Firebase Auth is configured for the project and usable from the smoke tool.** Firebase added to the GCP project (previously GCP-native only). Web app `roomstudio-smoke-test` registered (`appId 1:502805861152:web:095d7e3b331e0e0ddcbd45`); anonymous sign-in provider enabled; `firebase.googleapis.com` and Identity Toolkit enabled. `tools/upload_test_bundle.py` can obtain valid `idToken` credentials against the real project. ADC quota project set to `roomstudio`.
- **Protobuf gencode/runtime mismatch fixed in both service images** (see `docs/decisions/0021`). Root cause: `pip install packages/api-core/` in Layer 3 triggered proto-plus's `<7.0.0dev` constraint and downgraded protobuf from 7.35.0 back to 6.33.6, undoing the Layer 2 force-reinstall from decision 0005. Fix: api-core install moved to Layer 2 (before the force-reinstall); schemas install remains last. Container-import smoke added to both `infra/cloudbuild/api-internal.yaml` and `infra/cloudbuild/api-public.yaml` (build → smoke → push).
- **Two-service iOS upload path deployed to `asia-southeast1`:** `api-public` (revision `api-public-00004-nah`, 100% traffic, Firebase verifier wired) and `api-internal` (revision `api-internal-00007-nic`, 100% traffic, Cloud Run IAM gated; carries the decision 0022 user_id fix). `/health` 200 on both.
- **Eventarc trigger `captures-bundle-pb-finalized` live**, destination `api-internal/ingest/eventarc`. App-side path filtering working (bundle.pb → 200, non-bundle.pb → 200 with structured ignore-log, per decision 0023).
- **Decision 0021 verified end-to-end:** layer-swap fix landed cleanly, CI import smoke ran in Cloud Build, no protobuf downgrade recurrence.
- **Phase 0 verifier check is now a hard gate** enforcing decision 0016's trust boundary: positive grep that `FirebaseTokenVerifier` is wired into api-public (`server.py`), negative greps that it's absent from `services/api-internal/` and `packages/api-core/`. Exits non-zero with a labeled message on any failure. (v2 PR #9, commit d166ec0.)
- **Phase 0h is now a liveness-only gate** consistent with perception-obj's scale-to-zero lazy-load design (decision 0024). `gcloud describe` halts on anything but `Ready True`; `curl /ready` confirms reachability and accepts any HTTP response (200/503/500 all confirm the service is invokable). Broken-model failures are caught downstream by Phase 7 + the container-failed-to-start decision-tree branch from Cluster D.
- **v2 PR RUNBOOK hardening landed** (board item 3): all 20 findings closed. Deploy scripts now conditionally pass `--no-traffic` (only when the service already exists) and tag each revision `candidate` for reliable pre-flip smoke URLs (findings #5/#11/#10). Phase 0a IAM check uses effective-permission tests; Phase 0b Firebase setup and ADC quota-project fully specified (#1/#2/#3). Test collection is invocation-independent via pytest rootdir + conftest path setup (#20). 242 tests green from any CWD.
- **Service modules renamed** `server.py` → `services/api-internal/ingest_server.py` and `services/api-public/public_server.py` (resolves a test-collection module-name collision, #20). Dockerfile CMDs updated to the new entrypoints. Post-rename redeploy complete (revisions `api-internal-00007-nic` and `api-public-00004-nah`); both services boot the renamed entrypoints.
- **Phases 0–7 executed against production** (2026-05-29). Full upload→ingest→reconstruction path exercised end-to-end: bundle upload, Eventarc delivery, Cloud Tasks enqueue, SAM 3D model load (94.6 s from cold), reconstruction pipeline reached. skip-blob and auth-rejection modes confirmed green. happy-path and duplicate-event reach reconstruction but not `ready` (synthetic fixture pixels are non-decodable placeholders — by design; see "What does NOT work").
- **Ingest validation gate shipped and live-verified end-to-end** (board item 1). Validates image decodability pre-GPU at the `/ingest/eventarc` handler; fast-fails bundles with non-decodable image blobs to a new `failed_invalid` Scene state. Serving revisions: `api-internal-00009-bej` (gate) and `api-public-00006-quw` (reader rebuild required by the cross-service enum contract — see `docs/decisions/0027`). Phase 7 is now 4/4 green: happy-path and duplicate-event both reach `failed_invalid` end-to-end (~3–10 s including Eventarc delivery latency; perception-obj never wakes on either, confirming pre-GPU fast-fail). Note: `api-internal-runtime` holds `storage.objectViewer` on `gs://roomstudio-captures` at **bucket scope**, not project scope — a project-level IAM check will not show this binding.
- **iOS capture app P1 complete** (HEAD `9094ed1`, 2026-05-30). `ios/RoomStudioCapture/` Xcode project, iOS 16, SPM-only (SwiftProtobuf). `capture_bundle.pb.swift` generated by `./tools/gen_proto.sh` and committed as source. ARWorldTrackingConfiguration, gravity-aligned, `.sceneDepth` when available. Keyframe accumulation by pose delta (10 cm / 5°); `.limited`/`.notAvailable` tracking states skipped per decision 0028. Per keyframe: JPEG to temp dir (`frames/NNNNNN.jpg`), device-monotonic µs timestamp, `RSPose` + `RSIntrinsics` from ARCamera. Gravity field is a zero-vector stub — formula deferred to P1→P2 gate. Minimal SwiftUI: start/stop + frame counter + tracking-state badge (headless by design — no camera preview). On-device verified: pose-delta filter correct both directions, JPEG writes confirmed end-to-end (88 accepted / 88 written / 0 failures / 88 on-disk), all ARKit tracking states surface correctly. `PoseTests` 4/4 green (simd-only; quaternion unit-norm + component-order). Write observability (`WriteStats` + `do/catch` + `logWriteSummary`) kept as production code for P2.
- **`schema_version = "1"` enforcement gate closed and deployed** (see `docs/decisions/0031`). The ingest handler validates `schema_version == "1"` and rejects non-matching bundles with a `failed_invalid` Scene, structured log, and HTTP 200 (not a bare 400). A check already existed; this fixed the accepted value (`"1.0.0"` → `"1"`) and the rejection mechanism (bare 400 → `failed_invalid` + 200). Deployed: `api-internal-00013-qeg`, `api-public-00006-quw`.
- **iOS P2 chunk B complete** (see `docs/decisions/0032`, `0033`). Full `CaptureBundle` proto assembly: tier dispatch (ARKIT_ONLY/LIDAR_ARKIT), all fields populated including `schema_version = "1"`, `bundle_id` lowercased. Depth intrinsics corrected to scaled-RGB path per decision 0032 (the old `capturedDepthData` reference was wrong and would not have compiled). B-2 bundle_id casing closed. B-3 ARKIT_ONLY verified on-device (iPhone 16e): schema `"1"`, lowercased bundle_id, real-device provenance, clean quaternion norms, sane RGB intrinsics, gravity zero-stub as expected pre-chunk-C. LIDAR_ARKIT capture + inspect deferred pending hardware (decision 0033).
- **iOS P2 chunk C committed** (commit `a90418d`, see `docs/decisions/0030`, `0034`). `PoseExtractor.gravityInCameraFrame` implements R^T·world-down via `simd_quatf.inverse.act(simd_float3(0,-1,0))`. Both Gate-1 conditions met: hand-derived PoseTests at 1e-5 (green) + on-device sign check (floor/ceiling/landscape-horizon/roll, all clean). `#if DEBUG` gravity HUD in CaptureManager/ContentView; release builds unaffected. `ARCamera.transform` is a fixed landscapeRight frame — portrait reads ≈ (±1,0,0) and is correct (not a sign error); see decision 0034. P2 status: chunk A deployed, B code-complete (LiDAR depth residual deferred per decision 0033), C committed — P2 is mergeable.
- **iOS P3 complete — Firebase anon auth + `/upload_session`, live-contract-verified** (2026-05-31). Firebase iOS SDK 11.15.0 (Core+Auth) via SPM; offline-safe anonymous auth (cached UID, sign-in only when `currentUser` nil, never churns the UID — 0036); `UploadSessionClient` POSTs `/upload_session` with the 0038 retry/backoff status→action map; per-bundle session record persisted as an `NSFileProtectionComplete` file in Application Support, not Keychain (0037); Firebase-before-`configure()` ordering trap fixed (0039). Verified against live `api-public-00006-quw` (asia-southeast1) with a real anon idToken: happy-path 200, response mapped by `relative_path` not order, idempotent re-mint (same `session_uri`s for the same path-set); leading-slash manifest path → structured 400 (`invalid_manifest`), confirming 0038's fatal set unchanged; invalid-token 401 against the live `FirebaseTokenVerifier`. Integration tests run only when `RUN_INTEGRATION_TESTS=1` is set, using the `RoomStudioCapture-Integration` scheme — the only scheme in this project; there is no separate default scheme. Tests are run manually via `xcodebuild … -scheme RoomStudioCapture-Integration`; there is no automated CI gate at present. iOS tests: 22 (6 Pose + 10 Manifest + 4 integration + 2 stubs); see "iOS test policy" for honest count and thaw trigger.

## What does NOT work / what we're deliberately not doing

- **Sendable warnings in CaptureManager.swift.** `CVImageBuffer`/`CVPixelBuffer` cross the `DispatchQueue.main.async` boundary without `Sendable` conformance. Warnings in Swift 5 language mode; become errors under strict concurrency. Flagged for P1→P2 pre-flight.
- **iOS P2 LiDAR depth residual deferred** (hardware-gated, ~1–2 months, see `docs/decisions/0033`). B-3 LIDAR_ARKIT on-device capture + inspect not yet run. Covers: `sceneDepth` non-nil, 256×192 depth dimensions, one depth blob per frame, `depthIntrinsics` wrapper values correct on real hardware. No live depth consumer exists yet (P3–P5 unbuilt); deferral is low-risk.
- Scene `f077e9ed-d339-4be8-8dbf-37b952abfec2` is intentionally left in `processing` with an expired lease as a canonical stuck-scene reference. Re-enqueue manually if ever needed to verify the expiration-check reclaim path end-to-end.
- **`test_data/photos/` privacy is deferred.** 9 HEIC photos of a real room are tracked by git, used by `tools/build_test_bundle.py` for local synthesis testing. Privacy review (anonymise, replace with synthetic data, or remove from history) is a separate session. Do not act on this until explicitly scoped — it may require a history rewrite.
- **No web app yet.**
- **Pre-launch gaps (nine gaps + one audit item, categorized).** See `docs/decisions/0015` and `0018` for full list and un-defer triggers. Abuse-surface (original 0015 set, trigger: first non-developer user): (a) TOCTOU race on `bundle_id` ownership in `/upload_session`; (b) no per-UID rate limit on `/upload_session`; (c) `expected_size_bytes` optional, defaults to 0. Contract-shape (from pass 3 + pass 4 recon, trigger: iOS development or web app build begins): (F1) `expires_at` not surfaced in `/upload_session` response; (F2) `X-Upload-Content-Type` hardcoded to `application/octet-stream` server-side; (F3) no semantic manifest validation (unknown extensions, tier/path consistency) — server does independently enforce relative-path **format** (leading slash → structured 400, live-verified 2026-05-31); semantic checks remain client-owned and unverified; (F4) `result_url` presigning in `GET /scenes/by-bundle/{bundle_id}` responses (raw `gs://` returned today). Production-hygiene (trigger: launch): (F5) no lifecycle rule on `gs://roomstudio-perception-outputs/scenes/`; (F6) no TTL on Firestore `scenes` collection. Audit item (during launch hardening): verify perception-obj runtime SA identity and storage IAM. All nine gaps close in the same launch-hardening pass.
- The photo-upload composition path (`_compose_scene` in `perception-obj`) has unsolved per-object orientation issues. We are NOT fixing them. The iOS path replaces all of it.
- The pre-VGGT pydantic schemas (`packages/schemas/room_perception.py`, `spatial_graph.py`) are old Layer 1/2 work. Don't touch.
- **happy-path and duplicate-event smoke modes terminate at `failed_invalid`, not `ready`.** The ingest validation gate fast-fails the synthetic fixture's non-decodable placeholder images pre-GPU (~3–10 s including Eventarc latency). This is the verified, expected terminal state for smoke runs. Reaching `ready` requires real image data from an iOS bundle.
- **24h post-deploy smoke soak not yet run.** Phase 7 verified the gate end-to-end immediately post-deploy (4/4, 2026-05-29), but the RUNBOOK Phase 8c confirmation run — a happy-path re-run ≥24h after deploy, confirming stability under cold steady-state (scale-to-zero cold-start, GCS lifecycle age=1d and Firestore TTL having fired) — has not been run. Deliberately decoupled from iOS-development start; must be green before the iOS app's first real upload. One-command run: `python3 tools/upload_test_bundle.py happy-path … --cleanup` against the production URLs.
- **perception-obj referral P2 (launch-gating):** `/segment` and `/objects` are `--allow-unauthenticated` and each triggers a ~195s GPU cold-start; a sustained-DoS surface against the perception tier. Theoretical now (no users). Distinct from the line-95 SA-audit item (that's outbound runtime SA/storage IAM; this is inbound endpoint auth). Owner-referred; must close before the launch gate.
- **#17 post-deploy verify pending:** Eventarc 200-on-non-match is implemented (0023) but the live Pub/Sub no-redelivery metric check (upload a non-bundle.pb blob; confirm delivered +1, ack matching, nack/redelivery flat) has not yet been run against the deployed system.
- **iOS P3 401 recovery-success leaf unverified.** The live 401 test used a garbage token — exercises refresh→retry→propagate (give-up branch), not the expired→refresh→valid→200 case 0038 actually cites. Mechanism runs; the "refresh yields a working token" leaf is untested. Low risk. The path-violation 400 is confirmed for a leading slash only (`..` not separately confirmed; client emits neither).
- **KNOWN GAP — staleness re-mint missing-file stall (unbuilt terminal state).** When the 12h staleness guard fires and a blob file is absent from Application Support, `onSessionExpired` calls `onFatalBlobError("blob_file_missing_at_staleness_remint")` and returns. But `onFatalBlobError` is an unbuilt stub (observability tracking + print only — no state mutation, no task cancellation, no record update). Consequence: any sibling blobs whose loop iterations completed before the missing-file check are already live background URLSession tasks; they complete normally and get marked `.uploaded` in the record; the missing blob stays `.pending` forever; `allNonBundlePbBlobsUploaded` never goes true (`allSatisfy` requires every non-bundle.pb entry to be `.uploaded`, and the missing blob's entry remains in `sessionEntries`); the bundle stalls permanently with no terminal state, no UI/FCM surface, and no record cleanup. **SAFE:** bundle.pb is never finalized against the hole — the gate cannot read true with any blob stuck `.pending`. **Closure owner:** the real `onFatalBlobError` build (P5-adjacent terminal-state + FCM/UI surface), which must also cancel any in-flight sibling blob URLSession tasks for the bundle. A secondary follow-up (independent of P5) is to move the file-existence check to a check-all-files-first pre-pass before any `task.resume()`, so a missing-file abort starts zero sibling uploads; the current interleaved check-then-enqueue-per-blob means earlier-in-order blobs are already uploading at abort time.
- **KNOWN GAP — completed-capture disk accumulation.** As of decision 0043, blob files live in Application Support (durable, CAFUFA), no longer tmp (which auto-purged). `CaptureStorageSweeper` reclaims ONLY abandoned captures (no `UploadSessionRecord`). Completed bundles keep their record — `onBundleComplete` is an unbuilt P5 stub that does not delete it — so the sweep keeps their directory. Each completed capture leaves one ~50–300 MB directory in Application Support that is never reclaimed until P5 ships. Bound: flat accumulation, one dir per completed capture; not runaway. Pre-launch, no real captures yet. **Closure trigger:** P5's `onBundleComplete`, when built, must delete the store record AND the session dir on successful upload. Do NOT pre-empt it by teaching the sweep to delete completed-bundle dirs — distinguishing "completed, safe to delete" from "completed, may need retry after failed_incomplete" is a P5 design decision tied to terminal-state handling, not a sweep heuristic.

## iOS test policy

The 4 `UploadSessionClientTests` (integration tests) are gated behind `RUN_INTEGRATION_TESTS=1` and call `XCTSkipIf` on normal runs — XCTest reports a skip as passed. **They fail open by design.**

Rationale: there is no CI to set the flag against a known-up backend. Fail-closed would turn every routine unit run red and train operators to ignore red, destroying signal for the 65 unit tests that do assert. The `/upload_session` contract is frozen (decision 0035), so there is no live drift for a fail-closed integration test to catch right now.

**Honest count:** report results as "65 unit (executed) + 4 integration (skipped unless `RUN_INTEGRATION_TESTS=1`)", not a bare total. The bare number overstates what is verified. Current full count is 85 (including the 0043 durability tests); of those, 4 are the skip-pass integration tests, so 81 are always-executed unit tests.

**Thaw trigger:** when the `/upload_session` contract is next changed (launch hardening, or any server-side change), OR when CI is stood up, run the integration tests with `RUN_INTEGRATION_TESTS=1` against a known-up backend. Fail-closed-under-CI becomes worth building at that point. Until then, fail-open is intentional.

## Conventions

- Python 3.11+. Ruff for lint/format (config at `pyproject.toml`).
- Frame of reference: ARKit-native everywhere on the wire. Convert at the boundary, not in transit.
- Coordinates: right-handed, +Y up, meters.
- Quaternions: `(x, y, z, w)`, unit norm within 1e-3.
- GCS paths in the bundle are RELATIVE to the bundle prefix, not full `gs://` URIs.
- File creation: every long-lived file gets a docstring explaining what it's for and who reads it. No "test code anyway" justifications for shortcuts.
- Tests pin invariants, not implementation. They should still pass after a refactor.

## Tooling conventions

Default model for routine work: **Sonnet 4.6**. Switch to **Opus 4.7** for hard reasoning (coordinate-frame conversions, perception-pipeline architecture, anything where a wrong answer propagates). Haiku 4.5 is not in use yet.

Default tool for code work: **Claude Code**. Default for strategy / architecture decisions: **Claude Chat**. See `.claude/WORKFLOW.md` for the full rubric and prompt templates.

## Git conventions

This repo is tracked with git. Local-only as of now; no remote yet.

**Claude Code's role with git:**

- Commit as part of normal work. One commit per logical unit (a feature, a fix, a refactor — not "end of session"). If a session produces multiple distinct changes, that's multiple commits.
- Write descriptive commit messages: what changed and why, not just what. Subject line under 72 chars; add a body if the why isn't obvious from the subject.
- Run `git status` and `git diff` before committing, and surface anything unexpected (e.g. a file changed that wasn't part of the task). Don't `git add -A` blindly.
- Run the relevant test suite after every code change. Show the full test output before proposing a commit. "Relevant" means: tests for the package or service that changed, plus any tests for packages that depend on it. If unsure which tests are relevant, run them all. Never commit untested code. If tests fail, fix and rerun until green; do not commit red, do not commit "mostly green," do not commit with an explanation of why a failure is fine. If a test is genuinely wrong, fix the test in the same commit and explain in the message.
- Do NOT push to remotes. The user pushes manually after reviewing. (As of now there is no remote anyway, but this rule pre-applies for when one is added.)
- Do NOT rewrite history (`git rebase`, `git commit --amend` on already-committed work, `git reset --hard` on commits you didn't make this session) without asking.
- Do NOT delete branches or force-anything.

**Session-end housekeeping commits:** the CLAUDE.md updates and any decision-note additions from session-end housekeeping should land in their own commit, separate from the code changes that prompted them. Message convention: `docs: session housekeeping — <one-line summary of what changed>`.

**What's gitignored:** see `.gitignore`. Notably: `outputs/`, virtualenvs, `.env`, `.claude/cache/` and `.claude/projects/` (Code's session state). Note that `CLAUDE.md`, `.claude/WORKFLOW.md`, and everything under `docs/decisions/` ARE tracked — they're project documentation, not local state.

## When to write a decision note

`docs/decisions/` holds the *why* behind decisions that aren't obvious from the code. One file per decision, filename `NNNN-short-slug.md` (zero-padded). Template at `docs/decisions/0000-template.md`.

The criteria for "is this worth a note?" live in the session-end housekeeping section below.

## Next on the board

When this section gets stale, the project's drifting. Keep it current.

**1 — iOS P4 — background resumable upload, `bundle.pb` last** (decision 0029). Upload blobs per manifest via GCS resumable PUT; upload `bundle.pb` only after all blobs succeed; background `URLSession` so upload survives app backgrounding. **Read-first:** confirm the resumable-PUT contract (Content-Range / 308-Resume-Incomplete semantics, chunk sizing, retry-on-incomplete) before writing client code — same discipline as P3.

**2 — LiDAR_ARKIT on-device capture + inspect** when LiDAR hardware is available. Runs B-3 for the LIDAR_ARKIT tier: verify `sceneDepth` non-nil, 256×192 depth dimensions, one depth blob per frame, `depthIntrinsics` wrapper values sane on real hardware. Closes B's depth residual (decision 0033). Not a blocker for P2 merge; deferred on hardware availability only.

**3 — P5 deferred check: schema-rejected scene readable via api-public.** Verify that a bundle with `schema_version` != `"1"` (a) is rejected to `failed_invalid` by the ingest gate (decision 0031) and (b) the resulting Scene is readable via `GET /scenes/by-bundle/{bundle_id}` on api-public. Closes the read-path leg of the Gate-2 end-to-end smoke.

**4 — #17 post-deploy Pub/Sub no-redelivery verify** on the live system (see What-does-NOT-work).

**5 — Close the nine pre-launch gaps + one audit item (decisions 0015 + 0018)** (before public traffic)

Decision 0018 extended to nine gaps: original three abuse-surface gaps + F1/F2/F3/F4
contract-shape gaps + F5 (no lifecycle rule on `gs://roomstudio-perception-outputs/scenes/`)
+ F6 (no TTL on Firestore `scenes` collection). Plus one audit item: verify perception-obj
runtime SA identity and storage IAM. Abuse-surface trigger: first non-developer user.
Contract-shape trigger: iOS development or web app build begins. Production-hygiene and
audit: launch hardening. All nine gaps close in the same launch-hardening pass.

**6 — test_data/photos/ privacy review** (deferred, low urgency)

9 HEIC photos of a real room are tracked by git and used by
`tools/build_test_bundle.py` for local synthesis testing. Review whether they
should be anonymised, replaced with synthetic data, or removed from history.
Do not act on this until explicitly scoped — it may require a history rewrite.

## Session-end housekeeping (Claude Code: do this before ending any session)

Before the session ends — when the user indicates they're wrapping up, when tests are green and the task is done, or when the conversation is winding down — propose the following without being asked:

**1. CLAUDE.md updates.** Show a proposed diff for:
- **"What works right now"** — add anything that started working this session.
- **"What does NOT work / what we're deliberately not doing"** — add anything broken, half-done, or explicitly deferred. Be honest. Half-done is half-done, not "in progress."
- **"Next on the board"** — replace, don't append. This section reflects the present, not history.

Show the diff and ask for approval before writing. Don't write speculatively.

**2. Decision note candidates.** Identify whether anything this session is worth a `docs/decisions/NNNN-slug.md` note. The bar:

- A path was explored and rejected — write one.
- A non-obvious convention was chosen — write one.
- A workaround was applied that looks wrong without context — write one.
- Routine implementation that's self-evident from the code — skip.
- Strategy already captured in CLAUDE.md — skip.

If the bar isn't met, say so explicitly ("nothing this session rises to a decision note") and move on. Don't write notes just to seem thorough. If the bar IS met, draft using `docs/decisions/0000-template.md`, pick the next number, propose, wait for approval.

**3. If neither applies**, say so and end the session cleanly. Not every session changes the state.

The user can short-circuit this with "skip housekeeping" if the session was trivial (e.g. a one-line fix). Otherwise, run through it.

## How history is preserved

CLAUDE.md is the present. Anything historical — abandoned approaches, the reasoning behind a current convention, "we tried X and it didn't work" — goes in `docs/decisions/`, not here. If you find yourself wanting to add "we used to do Y" to CLAUDE.md, that's a signal to write a decision note instead and keep CLAUDE.md focused on what's true now.
