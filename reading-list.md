```markdown
# RoomStudio — reading progress (173 files · 31,513 ln · ~167h 20m)

## Track 0 — The contract (4h 30m)
- [x] packages/schemas/capture_bundle.proto — 313 ln — 1h 30m
- [x] packages/schemas/roomstudio_schemas/pose_math.py — 147 ln — 1h 10m

**Day 1**
- [-] packages/schemas/room_perception.py — 418 ln — 1h 00m — skipped, pre-VGGT dead code
- [-] packages/schemas/spatial_graph.py — 358 ln — 50m — skipped, pre-VGGT dead code

## Track 1 — iOS capture chain (4h 45m)
- [x] ios/.../RoomStudioCaptureApp.swift — 53 ln — 15m
- [x] ios/.../Capture/KeyframeAccumulator.swift — 65 ln — 20m
- [x] ios/.../Capture/PoseExtractor.swift — 121 ln — 50m
- [x] ios/.../Capture/CaptureManager.swift — 410 ln — 2h 45m
- [x] ios/.../Capture/BundleAssembler.swift — 99 ln — 30m

**Day 1**
- [x] ios/.../Support/ProtoTypeAliases.swift — 13 ln — 5m

## Track 2 — iOS upload chain (16h 05m)
- [x] ios/.../Auth/AuthManager.swift — 112 ln — 40m
- [x] ios/.../Networking/NetworkConfig.swift — 14 ln — 5m
- [x] ios/.../Upload/ManifestBuilder.swift — 83 ln — 25m
- [x] ios/.../Networking/UploadSessionClient.swift — 229 ln — 1h 50m
- [x] ios/.../Upload/UploadSessionRecord.swift — 357 ln — 2h 45m
- [x] ios/.../Upload/UploadSessionStore.swift — 138 ln — 50m
- [x] ios/.../Upload/UploadCoordinator.swift — 215 ln — 1h 30m

**Day 1**
- [x] ios/.../Upload/BlobUploadManager.swift — 1,171 ln — 11h 10m  ⭐ CRUX  [Days 1–2]

**Day 2**
- [x] ios/.../Upload/BlobUploadDelegate.swift — 89 ln — 25m
- [x] ios/.../AppDelegate.swift — 54 ln — 15m
- [x] ios/.../Capture/CaptureStorageSweeper.swift — 126 ln — 40m

## Track 3 — iOS scene polling (5h 35m)

**Day 2**
- [x] ios/.../Scene/SceneStatus.swift — 90 ln — 30m
- [x] ios/.../Scene/ScenePoller.swift — 375 ln — 2h 15m
- [x] ios/.../Scene/SceneStatusView.swift — 256 ln — 1h 35m
- [x] ios/.../ContentView.swift — 205 ln — 1h 15m

## Track 4 — api-core (4h 50m)

**Day 2**
- [x] packages/api-core/roomstudio_api_core/scene.py — 222 ln — 1h 45m

**Day 3**
- [x] packages/api-core/roomstudio_api_core/scene_read_repo.py — 154 ln — 1h 00m
- [x] packages/api-core/roomstudio_api_core/upload_session_repo.py — 268 ln — 2h 05m

## Track 5 — api-public (3h 40m)

**Day 3**
- [x] services/api-public/auth.py — 77 ln — 25m
- [x] services/api-public/public_server.py — 384 ln — 3h 15m

## Track 6 — api-internal (13h 35m)

**Day 3**
- [x] services/api-internal/scene.py — 18 ln — 5m
- [x] services/api-internal/fcm.py — 106 ln — 30m
- [x] services/api-internal/validation.py — 135 ln — 55m
- [x] services/api-internal/blob_validator.py — 186 ln — 1h 15m
- [x] services/api-internal/dispatcher.py — 153 ln — 1h 00m

**Day 4**
- [x] services/api-internal/repository.py — 244 ln — 1h 55m
- [x] services/api-internal/ingest_server.py — 827 ln — 7h 55m  ⭐ HARD

## Track 7 — perception-obj (19h 00m)

**Day 4**
- [x] services/perception-obj/oidc.py — 122 ln — 40m

**Day 5**
- [x] services/perception-obj/receiver_repo.py — 436 ln — 4h 10m  ⭐ HARD
- [x] services/perception-obj/process_receiver.py — 652 ln — 6h 15m  ⭐ HARD

**Day 6**
- [x] services/perception-obj/server.py — 684 ln — 6h 30m  ⭐ HARD
- [x] services/perception-obj/fcm.py — 110 ln — 35m
- [x] services/perception-obj/models/sam3.py — 90 ln — 30m
- [x] services/perception-obj/models/sam3d.py — 58 ln — 20m

## Track 8 — perception-geom, old path (1h 15m)

**Day 6**
- [ ] services/perception-geom/server.py — 155 ln — 45m
- [ ] services/perception-geom/models/vggt.py — 61 ln — 20m
- [ ] services/perception-geom/Dockerfile — 65 ln — 10m

## Track 9 — Infra & config (8h 25m)

**Day 6**
- [ ] README.md — 53 ln — 10m
- [ ] .claude/WORKFLOW.md — 182 ln — 35m
- [ ] .gitignore — 67 ln — 10m
- [ ] .gcloudignore — 58 ln — 10m
- [ ] pyproject.toml — 28 ln — 5m
- [ ] conftest.py — 47 ln — 10m
- [ ] infra/api-public.env.yaml — 13 ln — 5m
- [ ] infra/api-internal.env.yaml — 17 ln — 5m
- [ ] infra/secrets.md — 96 ln — 20m

**Day 7**
- [ ] infra/cloud-tasks-queue.md — 76 ln — 15m
- [ ] infra/cloudbuild/api-public.yaml — 48 ln — 10m
- [ ] infra/cloudbuild/api-internal.yaml — 48 ln — 10m
- [ ] infra/cloudbuild/perception-obj.yaml — 64 ln — 10m
- [ ] infra/cloudbuild/perception-geom.yaml — 40 ln — 5m
- [ ] infra/cloudbuild/pytorch3d-wheel.yaml — 88 ln — 15m
- [ ] infra/build_pytorch3d_wheel.sh — 31 ln — 5m
- [ ] infra/deploy_api_public.sh — 190 ln — 35m
- [ ] infra/deploy_api_internal.sh — 291 ln — 50m
- [ ] infra/deploy_perception.sh — 101 ln — 15m
- [ ] infra/eventarc_setup.sh — 246 ln — 40m
- [ ] infra/RUNBOOK.md — 924 ln — 3h 05m  ⭐

## Track 10 — Tools (15h 42m)

**Day 7**
- [ ] tools/conftest.py — 20 ln — 5m
- [ ] tools/gen_proto.sh — 61 ln — 10m
- [ ] tools/inspect_bundle.py — 178 ln — 55m
- [ ] tools/build_test_bundle.py — 240 ln — 1h 12m
- [ ] tools/CLAIM1_TEST_README.md — 190 ln — 40m
- [ ] tools/claim1_test.py — 162 ln — 50m

**Day 8**
- [ ] tools/smoke_test_e2e.py — 272 ln — 1h 20m
- [ ] tools/upload_test_bundle.py — 1,034 ln — 5h 55m  ⭐ CRUX
- [ ] tools/viewer.html — 281 ln — 40m
- [ ] tools/compose_local.py — 253 ln — 45m
- [ ] tools/inspect_splats.py — 239 ln — 40m
- [ ] tools/fetch_pointmap.py — 104 ln — 20m

**Day 9**
- [ ] tools/call_perception.py — 771 ln — 2h 10m

## Track 11 — Tests: schemas + api-core (4h 55m)

**Day 9**
- [ ] packages/schemas/pyproject.toml — 32 ln — 5m
- [ ] packages/schemas/conftest.py — 12 ln — 5m
- [ ] packages/schemas/tests/test_pose_math.py — 166 ln — 45m
- [ ] packages/schemas/tests/test_capture_bundle.py — 185 ln — 50m
- [ ] packages/api-core/pyproject.toml — 23 ln — 5m
- [ ] packages/api-core/conftest.py — 21 ln — 5m
- [ ] packages/api-core/roomstudio_api_core/test_fixtures/capture_bundle.py — 200 ln — 55m
- [ ] packages/api-core/tests/test_capture_bundle_fixture.py — 193 ln — 55m
- [ ] packages/api-core/tests/test_scene_read_repo.py — 116 ln — 30m
- [ ] packages/api-core/tests/test_upload_session_repo.py — 149 ln — 40m

## Track 12 — Tests: api-public + api-internal (11h 50m)

**Day 9**
- [ ] services/api-public/Dockerfile — 55 ln — 10m
- [ ] services/api-public/pyproject.toml — 26 ln — 5m
- [ ] services/api-public/conftest.py — 40 ln — 10m
- [ ] services/api-public/tests/test_server.py — 111 ln — 30m
- [ ] services/api-public/tests/test_upload_session.py — 291 ln — 1h 20m
- [ ] services/api-public/tests/test_scenes_by_bundle.py — 272 ln — 1h 15m

**Day 10**
- [ ] services/api-internal/Dockerfile — 59 ln — 10m
- [ ] services/api-internal/pyproject.toml — 30 ln — 5m
- [ ] services/api-internal/conftest.py — 33 ln — 10m
- [ ] services/api-internal/tests/test_server.py — 117 ln — 30m
- [ ] services/api-internal/tests/test_dispatcher.py — 79 ln — 20m
- [ ] services/api-internal/tests/test_ingest.py — 515 ln — 2h 20m  ⭐
- [ ] services/api-internal/tests/test_ingest_eventarc.py — 574 ln — 2h 35m  ⭐
- [ ] services/api-internal/tests/test_scene.py — 476 ln — 2h 10m

## Track 13 — Tests: perception-obj + tools (10h 15m)

**Day 10**
- [ ] services/perception-obj/tests/conftest.py — 38 ln — 10m
- [ ] services/perception-obj/Dockerfile — 188 ln — 25m
- [ ] services/perception-obj/pyproject.toml — 33 ln — 5m
- [ ] services/perception-obj/tests/test_oidc.py — 138 ln — 40m

**Day 11**
- [ ] services/perception-obj/tests/test_receiver_repo.py — 456 ln — 2h 05m  ⭐
- [ ] services/perception-obj/tests/test_server_registry.py — 266 ln — 1h 15m
- [ ] services/perception-obj/tests/test_server_routes.py — 206 ln — 55m
- [ ] services/perception-obj/tests/test_process_receiver.py — 668 ln — 3h 00m  ⭐
- [ ] tools/test_smoke_test_e2e.py — 108 ln — 30m
- [ ] tools/test_upload_test_bundle.py — 257 ln — 1h 10m

## Track 14 — Tests: iOS (24h 25m)

**Day 11**
- [ ] ios/.../RoomStudioCaptureTests/RoomStudioCaptureTests.swift — 38 ln — 10m
- [ ] ios/.../RoomStudioCaptureTests/PoseTests.swift — 117 ln — 40m
- [ ] ios/.../RoomStudioCaptureTests/CaptureManagerTests.swift — 131 ln — 45m

**Day 12**
- [ ] ios/.../RoomStudioCaptureTests/ManifestBuilderTests.swift — 182 ln — 1h 00m
- [ ] ios/.../RoomStudioCaptureTests/CaptureStorageSweeperTests.swift — 200 ln — 1h 10m
- [ ] ios/.../RoomStudioCaptureTests/UploadSessionClientTests.swift — 174 ln — 1h 00m
- [ ] ios/.../RoomStudioCaptureTests/UploadBlobStateTests.swift — 444 ln — 2h 30m
- [ ] ios/.../RoomStudioCaptureTests/ScenePollTests.swift — 466 ln — 2h 40m
- [ ] ios/.../RoomStudioCaptureTests/BlobUploadManagerTests.swift — 2,181 ln — 14h 30m  ⭐ CRUX  [Days 12–14]

## Track 15 — Decision docs (14h 10m)

**Day 14**
- [ ] docs/decisions/0000-template.md — 24 ln — 5m
- [ ] docs/decisions/0001-ios-first-pivot.md — 39 ln — 10m
- [ ] docs/decisions/0002-pose-pos-quat-not-matrix.md — 30 ln — 5m
- [ ] docs/decisions/0003-async-perception-dispatch.md — 98 ln — 20m
- [ ] docs/decisions/0004-perception-receiver-semantics.md — 92 ln — 20m
- [ ] docs/decisions/0005-protobuf-version-workaround-in-container.md — 77 ln — 15m
- [ ] docs/decisions/0006-perception-obj-syspath-hack-removal.md — 78 ln — 15m
- [ ] docs/decisions/0007-perception-obj-lazy-model-loading.md — 79 ln — 15m
- [ ] docs/decisions/0008-bake-all-model-weights-at-build-time.md — 102 ln — 20m
- [ ] docs/decisions/0009-gfe-intercepts-healthz-on-cloud-run.md — 78 ln — 15m
- [ ] docs/decisions/0010-every-fastapi-route-needs-a-testclient-test.md — 74 ln — 15m
- [ ] docs/decisions/0011-perception-obj-stuck-scene-lease-semantics.md — 177 ln — 35m
- [ ] docs/decisions/0012-perception-obj-lease-release-on-shutdown.md — 90 ln — 20m
- [ ] docs/decisions/0013-capture-bundle-monotonic-timestamps.md — 119 ln — 25m
- [ ] docs/decisions/0014-ios-upload-auth-architecture.md — 131 ln — 25m
- [ ] docs/decisions/0015-rate-limiting-concurrency-guards-deferred.md — 83 ln — 15m
- [ ] docs/decisions/0016-two-service-api-split.md — 131 ln — 25m
- [ ] docs/decisions/0017-smoke-tool-manifest-and-upload-contract.md — 103 ln — 20m
- [ ] docs/decisions/0018-extend-0015-with-contract-shape-gaps.md — 131 ln — 25m
- [ ] docs/decisions/0019-scene-read-endpoint-and-polling-contract.md — 179 ln — 35m
- [ ] docs/decisions/0020-smoke-tool-failure-mode-flag-semantics.md — 163 ln — 35m
- [ ] docs/decisions/0021-protobuf-runtime-pin.md — 114 ln — 25m
- [ ] docs/decisions/0022-ingest-must-propagate-user-id.md — 71 ln — 15m
- [ ] docs/decisions/0023-eventarc-bucket-filter-and-handler-ignore.md — 86 ln — 15m
- [ ] docs/decisions/0024-phase-0h-liveness-only.md — 52 ln — 10m
- [ ] docs/decisions/0025-synthetic-fixtures-cannot-reach-ready.md — 50 ln — 10m
- [ ] docs/decisions/0026-operator-account-gcp-permission-limits.md — 65 ln — 15m
- [ ] docs/decisions/0027-enum-contract-requires-reader-redeploy.md — 51 ln — 10m
- [ ] docs/decisions/0028-ios-in-monorepo.md — 79 ln — 15m
- [ ] docs/decisions/0029-ios-phase-plan-and-contract-notes.md — 79 ln — 15m
- [ ] docs/decisions/0030-p2-gravity-gate-and-schema-version-rule.md — 93 ln — 20m
- [ ] docs/decisions/0031-schema-version-string-fix.md — 94 ln — 20m
- [ ] docs/decisions/0032-depth-intrinsics-correction.md — 79 ln — 15m

**Day 15**
- [ ] docs/decisions/0033-c-decoupled-from-b-depth-residual.md — 75 ln — 15m
- [ ] docs/decisions/0034-arkit-camera-transform-landscaperight-frame.md — 57 ln — 10m
- [ ] docs/decisions/0035-p3-live-single-sided-contract.md — 42 ln — 10m
- [ ] docs/decisions/0036-user-id-under-anon-auth-and-serialization-order.md — 36 ln — 5m
- [ ] docs/decisions/0037-upload-session-local-persistence.md — 39 ln — 10m
- [ ] docs/decisions/0038-upload-session-retry-policy.md — 38 ln — 10m
- [ ] docs/decisions/0039-firebase-access-before-configure.md — 34 ln — 5m
- [ ] docs/decisions/0040-p4-blob-upload-single-shot-background-urlsession.md — 102 ln — 20m
- [ ] docs/decisions/0041-p4-open-seams-and-on-device-gates.md — 38 ln — 10m
- [ ] docs/decisions/0042-upload-session-record-cafufa.md — 66 ln — 15m
- [ ] docs/decisions/0043-blob-durability-application-support.md — 108 ln — 20m
- [ ] docs/decisions/0044-p4-on-device-verification.md — 56 ln — 10m
- [ ] docs/decisions/0045-p5-relaunch-recovery-cluster.md — 255 ln — 50m
- [ ] docs/decisions/0046-p5a-poll-client-design.md — 88 ln — 20m
- [ ] docs/decisions/0047-p5a-scene-poll-design.md — 119 ln — 25m
- [ ] docs/referrals/perception-obj.md — 72 ln — 15m

## Review milestones
- [ ] After Track 3 — re-trace one capture: CaptureManager → bundle.pb on disk → upload → ScenePoller kicks
- [ ] After Track 7 — re-trace end-to-end: bundle.pb → ingest_server → receiver_repo.claim → process_receiver → ready
- [ ] After Track 15 — note any inconsistencies between decision docs and code
```