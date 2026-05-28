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
  gen_proto.sh                      regenerate Python (and Swift, when iOS exists)
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
- Bundle ingester (ingest path): `POST /ingest` and `POST /ingest/eventarc` live in `services/api-internal/`; `POST /captures/{bundle_id}/upload_session` in `services/api-public/`. Same logic as the previously deployed `services/api/`. The pre-split single-service revision is still live on Cloud Run; redeployment pending.
- **`services/api` two-service split done** (see `docs/decisions/0016`): `services/api-public/` (`--allow-unauthenticated`, Firebase JWT in-app verification, hosts `/upload_session`) + `services/api-internal/` (`--no-allow-unauthenticated`, Cloud Run IAM, hosts `/ingest` + `/ingest/eventarc`) + `packages/api-core/` (shared `UploadSessionRepository` + `gcs_mint_resumable_uri`). Deploy scripts and Cloud Build configs ready; Cloud Run redeployment pending.
- `perception-obj` `/process` receiver: accepts Cloud Tasks HTTP POST (OIDC-verified), claims scenes atomically in Firestore with lease-TTL crash recovery, runs SAM 3 + SAM 3D Objects, writes outputs to GCS, updates Scene state, fires FCM on terminal transitions. System is functional end-to-end locally. Dockerfile, cloudbuild config, and deploy script env vars are all patched (see `docs/decisions/0005`, `0006`). Models are lazy-loaded on first `/process` call: `/health` returns 200 immediately for the startup probe; `/ready` reports per-model load state. DINOv2 weights (~1.13 GB) are pre-cached in the image at `TORCH_HOME=/opt/torch_hub`, eliminating the cold-start runtime fetch. Startup probe targets `httpGet /health`. 165 tests passing across both services.
- **Stuck-scene lease-semantics fix shipped and verified** (revision `perception-obj-00024-89b`, 2026-05-25). The bug from `docs/decisions/0011` and `0012` is fixed: `/process` reclaims stale leases atomically, `EnvironmentalError` eagerly releases the lease, SIGTERM resets held scenes to `queued`, and `holder_id` is checked defensively on all three lease-mutating paths. Verified production trace for scene `561c68ae`: `action=claim` → OOM → `action=release_error` → `action=reclaim_stale` → OOM → `action=release_error` → `action=reclaim_stale` → OOM → `action=release_error` (final, `is_final_attempt`) → scene `failed`. Note: the trace exercised the eager-release optimization path; the load-bearing expiration-check path (stale-but-not-cleared leases) is covered by unit tests only, not this production trace.
- **Smoke tool pass 3 scoping locked** (see `docs/decisions/0017`): manifest derivation, upload sequencing, and PUT semantics are pinned against the current `/upload_session` contract. Recon from a prior Code session covers the handler, request/response schemas, GCS minting, and Firestore session repo.
- **Smoke tool pass 4 scoping locked** (see `docs/decisions/0019`): polling contract pinned against a new `GET /scenes/by-bundle/{bundle_id}` endpoint on api-public. Recon from prior Code session covers the Scene document lifecycle, field population at ingest, idempotency under at-least-once Eventarc delivery, and the existing `SceneRepository` patterns in api-internal.
- **Smoke tool pass 5 scoping locked** (see `docs/decisions/0020`): four-mode CLI shape, `--cleanup` semantics, `--verbose`/`--json` output, and exit-code 2 (misconfig vs. system-under-test failure) pinned.
- **`tools/upload_test_bundle.py` written**: 1008-line substitute iOS client. Four modes (happy-path, skip-blob, duplicate-event, auth-rejection), two-phase upload sequencing per decision 0017, polling per decision 0019, failure semantics per decision 0020. `--cleanup`, `--verbose`, `--json` (NDJSON), exit codes 0–3. 27 unit tests in `tools/test_upload_test_bundle.py`. Verification against a deployed stack pending runbook execution.
- **`packages/api-core/roomstudio_api_core/test_fixtures/capture_bundle.py` added**: `build_capture_bundle()` + `TestBundleArtifacts`. Generates valid `CaptureBundle` protos for all three tiers with configurable per-frame blob kinds. 22 new invariant tests.
- **Deploy runbook preconditions landed**: `infra/eventarc_setup.sh` corrected — `INGESTER_SERVICE` changed from `roomstudio-api` to `api-internal`, `INGESTER_SA` changed to `api-internal-runtime@roomstudio.iam.gserviceaccount.com` (both were stale post-split). `services/api/` confirmed local-only (only gitignored `__pycache__/`) and removed. `upload_sessions.created_at` verified correct (`datetime.now(tz=timezone.utc)`) — TTL semantics match intent, no code change needed.
- **`infra/RUNBOOK.md` written**: 8-phase deploy runbook (Preflight + Phases 1–8) for the two-service iOS upload path (decisions 0014–0020). `eventarc_setup.sh` gains `--lifecycle-only`, `--ttl-only`, `--trigger-only` flags for per-phase invocation.
- **`GET /scenes/by-bundle/{bundle_id}` on api-public built** (board item 1, decision 0019). `SceneReadRepository` + `InMemorySceneReadRepository` + `FirestoreSceneReadRepository` in `packages/api-core/`. Scene model moved to `packages/api-core/roomstudio_api_core/scene.py`; `services/api-internal/scene.py` is now a re-export shim. `SceneRepository` in api-internal extends `SceneReadRepository`; `FirestoreSceneRepository` extends `FirestoreSceneReadRepository` (no duplication of read logic). 233 tests across all packages, all green (25 schema + 48 api-core + 40 api-public + 93 api-internal + 27 smoke tool). Runbook Phase 0 preflight gate now satisfied.
- **Phase 1 deploy infrastructure is live.** GCS lifecycle rule on `gs://roomstudio-captures` (delete after age=1, prefix `captures/`) is configured. Firestore TTL policy is set on `upload_sessions.created_at` (state `ACTIVE`). Automatic single-field index on `scenes.bundle_id` is confirmed unexempt. `infra/RUNBOOK.md` Phase 0 preflight passes (v2 refinements drafted but not yet landed — board item 2).
- **Firebase Auth is configured for the project and usable from the smoke tool.** Firebase added to the GCP project (previously GCP-native only). Web app `roomstudio-smoke-test` registered (`appId 1:502805861152:web:095d7e3b331e0e0ddcbd45`); anonymous sign-in provider enabled; `firebase.googleapis.com` and Identity Toolkit enabled. `tools/upload_test_bundle.py` can obtain valid `idToken` credentials against the real project. ADC quota project set to `roomstudio`.
- **Protobuf gencode/runtime mismatch fixed in both service images** (see `docs/decisions/0021`). Root cause: `pip install packages/api-core/` in Layer 3 triggered proto-plus's `<7.0.0dev` constraint and downgraded protobuf from 7.35.0 back to 6.33.6, undoing the Layer 2 force-reinstall from decision 0005. Fix: api-core install moved to Layer 2 (before the force-reinstall); schemas install remains last. Container-import smoke added to both `infra/cloudbuild/api-internal.yaml` and `infra/cloudbuild/api-public.yaml` (build → smoke → push).
- **Two-service iOS upload path deployed to `asia-southeast1`:** `api-public` (revision `api-public-00001-7wn`, 100% traffic, Firebase verifier wired) and `api-internal` (revision `api-internal-00002-tpl`, 100% traffic, Cloud Run IAM gated). `/health` 200 on both.
- **Eventarc trigger `captures-bundle-pb-finalized` live**, destination `api-internal/ingest/eventarc`. App-side path filtering working (bundle.pb → 200, non-bundle.pb → 400).
- **Decision 0021 verified end-to-end:** layer-swap fix landed cleanly, CI import smoke ran in Cloud Build, no protobuf downgrade recurrence.

## What does NOT work / what we're deliberately not doing

- **No iOS app exists yet.** The bundle synthesizer is the only thing that writes bundles.
- Scene `f077e9ed-d339-4be8-8dbf-37b952abfec2` is intentionally left in `processing` with an expired lease as a canonical stuck-scene reference. Re-enqueue manually if ever needed to verify the expiration-check reclaim path end-to-end.
- **`test_data/photos/` privacy is deferred.** 9 HEIC photos of a real room are tracked by git, used by `tools/build_test_bundle.py` for local synthesis testing. Privacy review (anonymise, replace with synthetic data, or remove from history) is a separate session. Do not act on this until explicitly scoped — it may require a history rewrite.
- **No web app yet.**
- **Pre-launch gaps (nine gaps + one audit item, categorized).** See `docs/decisions/0015` and `0018` for full list and un-defer triggers. Abuse-surface (original 0015 set, trigger: first non-developer user): (a) TOCTOU race on `bundle_id` ownership in `/upload_session`; (b) no per-UID rate limit on `/upload_session`; (c) `expected_size_bytes` optional, defaults to 0. Contract-shape (from pass 3 + pass 4 recon, trigger: iOS development or web app build begins): (F1) `expires_at` not surfaced in `/upload_session` response; (F2) `X-Upload-Content-Type` hardcoded to `application/octet-stream` server-side; (F3) no semantic manifest validation (unknown extensions, tier/path consistency); (F4) `result_url` presigning in `GET /scenes/by-bundle/{bundle_id}` responses (raw `gs://` returned today). Production-hygiene (trigger: launch): (F5) no lifecycle rule on `gs://roomstudio-perception-outputs/scenes/`; (F6) no TTL on Firestore `scenes` collection. Audit item (during launch hardening): verify perception-obj runtime SA identity and storage IAM. All nine gaps close in the same launch-hardening pass.
- The photo-upload composition path (`_compose_scene` in `perception-obj`) has unsolved per-object orientation issues. We are NOT fixing them. The iOS path replaces all of it.
- The pre-VGGT pydantic schemas (`packages/schemas/room_perception.py`, `spatial_graph.py`) are old Layer 1/2 work. Don't touch.
- **`perception-obj` is dead at import time** since 2026-05-16. `/ready` returns 503, `sam3` and `sam3d` both `not_loaded`. Root cause: `FileNotFoundError: '/opt/sam3d/checkpoints/hf/pipeline.yaml'` in `SAM3DModel.__init__`. Container exits at startup. Blocks `happy-path` and `duplicate-event` smoke modes; blocks Phase 8c (iOS code start).
- **Ingest creates scenes with `user_id = None` on the failed-incomplete branch.** `skip-blob` smoke mode surfaced this: `GET /scenes/by-bundle/{bundle_id}` returns 403 `"scene has no owner"` (the diagnostic 403 from decision 0019). Happy-path scenes have `user_id` set correctly via `bundle.user_id`. Root cause: `_handle_failed_incomplete` in `services/api-internal/server.py` creates the scene but never sets `scene.user_id`. Fix: read from `upload_session_repo.get_user_id(bundle_id)`. See decision 0022.
- **Eventarc trigger `captures-bundle-pb-finalized` has no object-path filter and is bucket-wide on `roomstudio-captures`.** `/ingest/eventarc` on api-internal returns 400 for non-`bundle.pb` paths, which Pub/Sub reads as delivery failure and retries; every pixel-blob upload generates redelivery traffic until the message expires. No production impact today (only the smoke tool uploads), but the loop will surface on the first real bundle.
- **`infra/eventarc_setup.sh` does not enable the Eventarc API, does not wait for the Eventarc Service Agent to propagate after enable, does not grant `roles/eventarc.eventReceiver` to the trigger SA, and does not grant `roles/pubsub.publisher` to the GCS service agent.** Current trigger works only because all four were resolved manually or pre-existed.

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

**1 — Fix `perception-obj` checkpoint path / image build** (perception-obj owner)

`SAM3DModel.__init__` raises `FileNotFoundError` for
`/opt/sam3d/checkpoints/hf/pipeline.yaml` at container start. Service exits before
reaching `/health`. Unrelated to the iOS upload path; tracked separately.

**2 — Fix ingest `user_id` propagation on failed-incomplete** (`services/api-internal`)

`_handle_failed_incomplete` creates a scene without setting `user_id`, causing
`GET /scenes/by-bundle/{bundle_id}` on api-public to return 403. Fix: read
`user_id` from `upload_session_repo.get_user_id(bundle_id)` and write to the
scene. Verification: `skip-blob` smoke mode exits 0 with `status=failed_incomplete`.
See decision 0022.

**3 — Land the `infra/RUNBOOK.md` v2 PR** (18 findings: #1–#5, #7–#19; #6 closed by 0021)

Including: deploy-script `--no-traffic` conditional, `eventarc_setup.sh` IAM
completeness (eventReceiver + pubsub.publisher + Eventarc API enable), Phase 0
verifier grep, Phase 0h `/ready` actually-run discipline, runbook redelivery loop on
400 responses (finding #17).

**3a — Cluster A of the v2 PR: Eventarc filter + handler fix** (`infra/`, `services/api-internal`)

Rewrite `infra/eventarc_setup.sh` (enable API, wait for Service Agent, grant
`eventReceiver` + `pubsub.publisher`, narrow retry on trigger creation); change
`/ingest/eventarc` to return 200 on non-`captures/*/bundle.pb` paths with structured
ignore-log; add Phase 0 checks for API + Service Agent + both IAM grants. Closes
findings #12, #13, #14, #15, #17. See decision 0023.
Done when: the two "What does NOT work" bullets added for 0023 are moved to "What works"
(or removed) and the Pub/Sub no-redelivery check passes (delivered count increments, ack
count matches, nack/redelivery count does not move after a non-`bundle.pb` upload).

**4 — Re-run Phase 7 (all 4 modes)** once board items 1 and 2 close. Phase 8c follows.

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
