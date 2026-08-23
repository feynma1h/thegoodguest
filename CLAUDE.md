# The Good Guest (repo and infrastructure still named `roomstudio`)

A spatial intelligence product that helps people discover the best version of their home: AI-powered room analysis, conversational redesign, and an immersive 3D representation of *their own* space.

This file is the always-current state of the project. Both Claude Code (reads it automatically) and Claude Chat (you upload it) consume it at the start of every session. If something in here is wrong, fix it before doing anything else.

## What we're building

**The thesis: every home contains a version of itself that its owner has never seen. This product makes that version visible, understandable, and achievable — one conversation at a time.** Every feature decision filters through this. The full founding vision lives at `docs/product/initial-idea-draft.md` (verbatim, with what's superseded vs durable mapped in decision 0055) — read it before making product-surface decisions.

This is NOT an "upload → generate a 3D scene" showcase. The 3D reconstruction is the *medium*; the product is helping people make AI-based decisions about improving their room. Three product layers frame everything: the **AI layer** (understands space structurally — object relationships, traffic flow, light, proportion — with algorithmic spatial analysis before any LLM is invoked, and reasoning traces on every design decision), the **emotional layer** (feels personal, not algorithmic — the experience bar is Linear/Vercel/Figma-tier premium consumer software; conversation is the primary post-reveal interface; the cinematic reveal is the defining moment; design language is Apple-grade restraint per decision 0056 — neutral chrome, content carries the color, one sans, mono only for machine data), and the **social layer** (rooms are identity — sharing, comparison, evolution over time). Direction, not yet commitments: room health scoring, taste graph, lighting simulation, budget-aware shopping, DAG version history. Deliberately out (per the founding draft, still sound): AR overlay, social feed, photorealistic image generation, floor plans, voice input; desktop-first.

**Naming: SETTLED 2026-08-23 as "The Good Guest" (0245)**, forced by the App Store listing when enrollment cleared. It is the register the whole product was built in (0072/0057) and the metaphor the calling card is already named from. Set in exactly two places — `web/src/components/Wordmark.tsx` and iOS `RSBrand.name` — plus the card's own `WORDMARK` in `lib/card/layout.ts`, which the card's privacy guard now imports rather than retypes. **The repo, GCP project, buckets and `roomstudio:` localStorage keys deliberately keep the stand-in** — infrastructure, invisible, expensive to rename for no user-visible gain. **The card still prints `roomstudio.web.app`, which is the TRUE hosting URL**: changing that string without moving hosting would print a falsehood on an artifact that leaves the browser. Re-open trigger is commerce, and renaming stays cheap until App Store submission — TestFlight needs only an app record.

Three technical surfaces today:

- **iOS capture app** (Swift + ARKit + RoomPlan) — capture-only, no viewer. The app's only job is producing a high-quality capture bundle and uploading it. Users come to the web for everything else.
- **Backend perception pipeline** (FastAPI on Cloud Run, `asia-southeast1`) — ingests bundles, runs SAM 3 segmentation + SAM 3D Objects reconstruction, places objects in the room's gravity-aligned metric frame using ARKit data (decision 0052), renders the room shell — walls/floor as textured quads from measured ARKit planes (decision 0066; BUILT, deploy pending). This is the modern substrate for the draft's perception + spatial-reasoning layers; the spatial relationship graph and design-generation layers above it are unbuilt.
- **Web app** (Next.js, static export + web splat rendering — WebGL2 via Spark, decision 0053 — hosted on Firebase Hosting) — the product surface: today rooms + viewer; next analysis, conversation, and redesign. Capture path is one screen: "Open the iOS app." Auth: same Firebase identity as iOS — requires upgrading iOS's anonymous auth to a real sign-in linked to the existing anonymous credential (see "Next on the board"); anonymous UIDs don't carry across devices.

Photo-upload (Android, no-iPhone users) is a deferred concern. Until the iOS path is solid we don't build the web-fallback capture.

## Capture bundle — the central contract

Everything between iOS and the backend flows through `packages/schemas/capture_bundle.proto`. The bundle is metadata; pixel data (frames, depth) lives in GCS by reference.

Frame of reference is **ARKit-native** end-to-end: right-handed, +Y up, camera looks down -Z in its local frame. The iOS client does NOT transform; the backend converts to downstream model frames (e.g. SAM 3D's per-object frame) when it has to.

Pose is **position + unit quaternion (x, y, z, w)**, not a 4×4 matrix. ARKit-native, ARCore-native, glTF-native. 7 floats instead of 16. The proto file's docstring carries the full reasoning.

Quaternion math is centralized in `packages/schemas/roomstudio_schemas/pose_math.py`. Any Python that touches a Pose imports from there. Do not re-implement.

## Repo layout

```
packages/schemas/                 capture bundle proto + generated Python + pose/placement math
  capture_bundle.proto              source of truth
  roomstudio_schemas/
    capture_bundle_pb2.py            generated; regen with ./tools/gen_proto.sh
    pose_math.py                     quaternion ops; one place to change
    placement_math.py                depth backprojection, single-view fits, ray triangulation
  tests/                              invariant tests for the proto, poses, and placement math

packages/api-core/                shared logic consumed by both API services
  roomstudio_api_core/
    scene.py                         Scene model, SceneStatus, state machine
    scene_read_repo.py               SceneReadRepository ABC + Firestore/in-memory read-only impls
    upload_session_repo.py           UploadSessionRepository ABC + Firestore/in-memory impls + gcs_mint_resumable_uri
  tests/                              unit tests for the scene model, repos, and manifest validation

tools/                            local scripts (run from repo root)
  gen_proto.sh                      regenerate Python and Swift (ios/RoomStudioCapture/RoomStudioCapture/Generated/)
  gen_mark.py                       the product mark's ONE source — regenerates the three app
                                      icons, favicon.ico, icon.svg, and the geometry both
                                      wordmarks consume
  build_test_bundle.py              synthesize a bundle from test_data/photos
  inspect_bundle.py                 verify a bundle parses + smoke-checks

services/
  api-public/                     client-facing API (--allow-unauthenticated, Firebase JWT verify)
  api-internal/                   internal API (--no-allow-unauthenticated, Cloud Run IAM)
  perception-obj/                 SAM 3 + SAM 3D Objects + placement/fusion (deployed pre-placement)
  perception-geom/                VGGT for the photo-upload path (source only — the service and its image were retired 2026-08-20, decision 0192)

web/                              Next.js static-export web app (decision 0050); Spark splat viewer
                                  contained in src/components/SplatViewer.tsx (decision 0053)

infra/                            Cloud Build configs, deploy scripts
docs/decisions/                   short notes on dead-ends — see "When to write a decision note"
test_data/photos/                 9 synthetic rendered room views, for synthesis testing
outputs/                          gitignored; generated artifacts
```

## What cannot be remade

`outputs/` is gitignored and looks disposable. Most of it is. Roughly 1.3 GiB
of it is not, and **no copy exists anywhere else** — the captures bucket
deletes at age 1 day, so GCS does not hold these:

- `outputs/real-capture-*` — preserved capture bundles; the substrate the whole
  perception thread regresses against.
- `outputs/device-pull/` — three RP-6/7 rooms physically pulled off the 16 Pro's
  app container. The app reaps completed captures (0084), so the phone no
  longer has them either.
- `outputs/roomplan-spike/` — the four-run spike RECORDING, incl. the
  722-keyframe RGB/depth archive. **The source, not a derivative.**
- Every `outputs/reports/*.md`, `outputs/**/verdicts.md`, and the walk packs'
  text. Kilobytes, and they are the operator's own judgments.

**The trap:** `outputs/roomplan-spike-bundle/` is NOT on that list — it is
GENERATED from `outputs/roomplan-spike/` by `tools/convert_roomplan_spike.py`.
The names are one word apart and the sizes are within 2 MiB (494 vs 496 MiB).
One costs a script run to remake; the other is gone forever.

Everything else under `outputs/` is regenerable, and cheaply: the probe
artifacts replay production code over the preserved captures offline, so they
cost CPU and no GPU — **no reconstruction lives here**, they live in the
outputs bucket, which still holds all 12 scene dirs. Their conclusions already
live in `docs/decisions/`; the raw artifacts exist only for re-verification.

**When disk is short, look outside the repo first — that is where the free
wins are.** `~/Library/Developer/Xcode/DerivedData` is pure Xcode build cache
and is routinely the largest single item on the machine (16 GiB at the
2026-08-19 pass, in a dozen per-configuration copies); deleting it does not
touch the app installed on the phone. `npm cache clean --force` and `web/out`
(recreated by every `next build`) are equally free. Two that are NOT free and
want the operator's say-so: a *booted* simulator device holds GiB of installed
apps and seeded state (`simctl erase` reclaims it but wipes the staging — the
8 never-booted devices are 17 MiB each), and a CoreSimulator *runtime* is a
multi-GiB re-download.

Worth knowing while you are in there: `web/public/dev-fixtures` is 3.9 GiB of
real captured homes sitting inside `web/public`, and `next build` copies
`public/` into `out/`, so a full build doubles it. `firebase.json` ignores
`dev-fixtures/**` on deploy, but that is one config line standing between real
rooms and a public origin — 0122 already caught a splat one deploy away.
Moving the fixtures outside `public/` would remove the hazard rather than
guard it.

## What works right now

State, not history. Every claim here is about the live system; the story of how
it got this way is in `docs/decisions/`. Serving revisions and suite counts were
last verified 2026-08-20.

### The contract and shared packages

`packages/schemas/capture_bundle.proto` is the source of truth for everything
between iOS and the backend, at `schema_version = "1"`. Three tiers ship:
`ARKIT_ONLY`, `LIDAR_ARKIT`, `LIDAR_ROOMPLAN`. `PlaneAnchor` (field 12) and
`RoomPlanModel.json_gcs_path` (field 4) are both additive and carried on every
capture that has them. Regenerate both languages with `./tools/gen_proto.sh`.

`pose_math.py` is the one home for quaternion and rotation math (`quat_mul`,
`rotation_angle_deg`); `placement_math.py` holds the geometry primitives —
depth backprojection, single-view fits, ray triangulation, `solve_floor_contact`,
`solve_wall_contact`, `minimal_rotation`, `depth_pointmap`. Do not re-implement
either elsewhere.

`packages/api-core/` holds what both API services share: the `Scene` model and
state machine, the scene read/write repositories, `UploadSessionRepository` +
`gcs_mint_resumable_uri`, semantic manifest validation, and the capture-bundle
test fixtures.

Suites: schemas **120**, root **862 passed + 27 skipped** with
`web/public/dev-fixtures` staged and **787 + 102** without — both measured
2026-08-21, after 0213/0214 added 23 tests. Always say which. re-enqueue **18**.

### iOS capture app — `ios/RoomStudioCapture/`

Pro-only by design (decision 0071): non-LiDAR hardware lands on
`UnsupportedDeviceView`. `RootFlowView` is the app root and the navigation
coordinator, binding the Good Guest design system (decision 0072) to the real
capture, auth, upload, and polling stack. Upload begins on the review screen's
"Send it home", not on `stopCapture`.

- **Capture.** ARKit world tracking, gravity-aligned, `.sceneDepth` where
  available, keyframes accumulated by pose delta (10 cm / 5°). RoomPlan runs
  co-resident on the same `ARSession` (decision 0079) — co-run does not strip
  `sceneDepth`, measured on hardware. Plane detection on every tier; the final
  anchor set is snapshotted at stop. Tier is `LIDAR_ROOMPLAN` iff a built room
  with at least one wall or floor ships.
- **Live floor plan** drawn from the RoomPlan delegate stream, replacing the old
  placeholder sketch. Confidence gates naming: a low-confidence object renders
  unlabelled and the guest hedges.
- **Identity.** Firebase anonymous auth, upgraded in place by linking Apple
  (decision 0051) or Google (0118) — the UID is asserted unchanged on link, and
  a conflict is an explicit switch/keep choice, stated in two alerts with the
  real cost and no counts — the designed conflict screen was deleted because
  the counts it wanted cannot be obtained (0216). There is deliberately no iOS
  sign-out. `IdentityContinuity` classifies each launch (`continuous` /
  `firstRun` / `credentialLost` / `keychainUnavailable`) and logs it at fault
  level without changing behaviour (0141).
- **Upload.** Background `URLSession`, whole-blob PUTs, `bundle.pb` enqueued
  last (0040) and gated on every other blob completing. Honours GCS
  `Retry-After`. Session expiry re-mints; a re-mint that returns identical URIs
  escalates once to `force_remint` (0049). `CaptureRecovery` re-sends a
  `failed_incomplete` scene's missing paths plus `bundle.pb` (0084), and only
  promises that when disk proves it can.
- **Surfaces.** Scene-status polling with a server-anchored elapsed clock, a
  Live Activity on Lock Screen and Dynamic Island, terminal-failure banners, and
  a mint-429 screen that names the reset time rather than sleeping. Declaring a
  new flight stands the previous room's status down, so no surface can narrate a
  finished room over a scan still going up (0217).
- **History.** `ScenesListClient` fetches `GET /scenes` — the caller's own
  rooms, scoped to the token — and `RoomsStore` holds one answer for all three
  surfaces that state a count: the returning-home strip, `RoomsListView`, and
  `WhySignInSheet`'s invitation. The load state is four-way and its accessors
  are Optional, so "no rooms" and "could not ask" cannot be collapsed (0206);
  a failed fetch never renders as zero. Rows offer a tap only where one can
  land — gated on `NetworkConfig.webBaseURL`, which is nil, exactly as the
  doorway's CTA is.
- **The mark.** `DesignSystem/Wordmark.swift` draws the same room corner as the
  app icon, from the generated `MarkGeometry.swift` (0193). `RSBrand.name` stays
  the one-file swap for the name; there is no separate mark glyph.
- **Reclaim.** `CaptureReaper` frees a capture's record and files once the user
  has *seen* the outcome — never on mere upload success.

Suite **600**: 594 asserting offline tests + 2 boilerplate stubs + 4 live
integration tests that require a reachable backend. See the iOS test policy
section — it is the single source of truth for posture and how to run them.

### api-public — `api-public-00042-ruq`, image `20260821-005416`

Client-facing, `--allow-unauthenticated`, with in-app Firebase JWT verification
as the trust boundary (0016). CORS is gated on `CORS_ALLOWED_ORIGINS`.

- `POST /captures/{id}/upload_session` — mints resumable URIs in a bounded
  concurrent pool. Enforces, in order: per-UID daily capture ceiling
  (`UPLOAD_SESSION_DAILY_CAPTURES`, charged once per bundle_id on first claim),
  atomic bundle_id ownership claim, per-UID daily mint quota, and semantic
  manifest validation. `force_remint` vends fresh URIs for a consumed session
  (0116).
- `GET /scenes`, `GET /scenes/by-bundle/{bundle_id}`,
  `GET /scenes/{id}/assets` — the assets response carries the manifest and shell
  verbatim, V4-signed splat URLs for placed objects, and an additive
  `asset_urls_compressed` for the SPZ tier that never narrows the PLY fallback.
- `GET/POST /scenes/{id}/conversation` — the guest, at `FACTS_VERSION 4` and
  `PROMPT_VERSION 6`. SSE with a disconnect shield: the turn completes and
  persists even if the client stops listening.
- `GET/DELETE /scenes/{id}/design_spec` — the arrangement document. Every entry
  carries `measured_transform` beside `proposed_transform`; an entry that cannot
  is unrepresentable.
- `DELETE /account` — deletes every per-user collection and prefix by hand
  (Firestore does not cascade), ordered GCS → Firestore → identity, idempotent
  and resumable.

The guest has hands but not coordinates (0132): `propose`, `revert`, and `turn`
carry no numeric field anywhere. A server-side solver owns geometry and refuses
when it cannot ground an instruction.

### api-internal — `api-internal-00023-mek`

`--no-allow-unauthenticated`, Cloud Run IAM gated. Hosts `/ingest/eventarc` and
nothing else. Validates in order: `schema_version`, bundle_id cross-check
against the URI, image decodability (pre-GPU), `device_id` presence, and
declared-blob presence (0105). A rejection is a `failed_invalid` or
`failed_incomplete` Scene with a structured log and HTTP 200 — never a bare 400.
Terminal-failure scenes are stamped with `expire_at`; revival clears it; `ready`
is never stamped.

### perception-obj — `perception-obj-00062-hum`, image `20260821-010928`

Runs as `perception-obj-runtime@` under least privilege (0090) and is
platform-gated — only `tasks-invoker@` holds `run.invoker` (0106). Scales to
zero with lazy model loading: `/health` answers immediately, `/ready` reports
per-model state.

Three stages, all Cloud Tasks driven:

- **`/process`** — the census two-pass. Pass 1 segments with SAM 3 and writes
  masks; pass 2 reconstructs per a deterministic plan (box best views, then
  weakest-first seconds, then the long tail) under budget admission. Frame
  selection is box-visibility set-cover plus pose-diverse FPS residue. Scene
  claims are atomic with lease-TTL crash recovery; OOM is contained per object.
  Three passes ship behind one env var each, all still OFF by default, each
  with a byte-identical degrade proven against all four preserved captures:
  `PERCEPTION_MASK_REFINE` repairs a mask the frame's own LiDAR shows cut its
  object short (0198/0201), `PERCEPTION_OBJECT_AWARE_RESIDUE` spends the
  residue slots on second views of boxes rather than on pose spread (0202),
  and `PERCEPTION_ARM_SELECT` picks which of an object's arms supplies its
  appearance by placing each one against the object's measured box, rather
  than by mask-hull overlap (0204/0205). **All three have now run live on
  0%-traffic candidates** (0211/0212), and what that measured is that they are
  not three independent switches: refine and select flip TOGETHER, refine
  first, because refinement changes what the chooser is choosing between. The
  residue waits on one more room.
- **`/shell`** — the room envelope. shell.json **v3** on the LiDAR paths:
  method `roomplan` renders CapturedRoom geometry verbatim, method
  `anchor_envelope` is the degrade for LIDAR_ARKIT and roomplan-absent
  captures. ARKIT_ONLY still ships **v2** (`method: arkit_planes`) byte-for-byte.
  Both constants live in `shell_receiver.py`. Every plane carries its measured
  geometry beside the rendered geometry, so closure never mutates measurement.
  Parametric materials come from a confidence-gated vision call over rectified
  evidence crops, with a load-bearing fallback: below the gate family is null
  and the plane ships a clean matte in its measured albedo.
- **`/compress`** — transcodes each PLY to SPZ beside it plus a
  `compressed.json` index. ~5.8× smaller, Gaussian counts preserved exactly.

Placement, in the order it runs: box association and box placement from
RoomPlan (the box is the skeleton), single-view contact priors against measured
floors and walls, multi-view silhouette fitting, LiDAR `depth_fit`, then the
post-passes — cross-label duplicate suppression, wall anchoring and declip,
opening demotion, support-surface snapping, contact-tilt levelling, and the
room-sanity gate. Every failure path yields explicit `placed: false` with a
reason; a guessed transform is never emitted. `splat_clip` declares the volume
the viewer may render, so measurement is never falsified to hide a splat
artifact. `person` is a suppression-only concept — segmented, never shipped
(0089).

Suite **952 passed + 2 skipped** with `web/public/dev-fixtures` staged and
**945 + 9** without (`services/perception-obj/tests`;
903 + 9 before 0204-0205 added 42).

### Web app — `web/`, live at https://roomstudio.web.app

Next.js static export on Firebase Hosting. Routes: `/` (hero), `/rooms`,
`/room?bundle=`, `/new`, `/viewer` (dev workbench, hidden in live mode),
`/privacy`, `/terms`.

- `SplatViewer.tsx` is the **only** module importing three.js or Spark. It
  consumes a renderer-agnostic `PositionedSplat` contract, prefers the SPZ tier
  and falls back to PLY, and plays the reveal score rather than deciding it.
- `lib/reveal.ts` is the choreography as a pure function: the measured boundary
  draws itself, surfaces fade up in place, pieces settle, then a beat of quiet
  before the guest speaks (0097). Objects gate per piece on bytes arriving.
- `lib/viewerKey.ts` splits the renderer into three keys by lifetime, not
  expense: structure rebuilds the renderer, placement and decorations own their
  own effects (0188). A proposal never re-downloads the room.
- `lib/designSpec.ts` overlays the arrangement onto the assembled scene as a
  pure pass, so the renderer never learns a proposal exists. The measurement
  survives on screen as its footprint in the contour's paper tone.
- `Wordmark.tsx` draws the room corner from generated geometry and remains the
  one-file swap for the product name, now "The Good Guest" (0245). It authors
  no paths and no colours: `tools/gen_mark.py` is the mark's one source across
  the app icons, the tab icon, both wordmarks and the share card (0193), and
  `tone` picks only which ink plate it sits on. The tab icon ships twice —
  `icon.svg` answers `prefers-color-scheme`, `favicon.ico` is the legacy
  fallback and is framed, the variant that survives a light tab strip.
- **The calling card** — rung 0 of the sharing ladder
  (`docs/product/social-layer.md` §6), BUILT and undeployed. `lib/card/` is
  measurement → display list → canvas, split the way `lib/reveal.ts` splits the
  reveal: the layout is a pure function so the whole artifact can be pinned
  without a browser, the painter makes no decisions, and the preview IS the
  downloaded file (one canvas, `toBlob`'d). The projection is a uniform
  similarity, so every length is exact by construction rather than by care — it
  reproduces `docs/product/og-card.html`'s hand-placed plan to **0.0055 px on a
  382 px span**, where that file claims 0.7%. It draws the RENDERED boundary and
  prints only DETECTED extents (0222), and rotates the plan flat because an
  ARKit yaw is the phone's start heading rather than a measurement (0223).
  Canvas and not SVG: an SVG rasterized through an `<img>` cannot see the
  document's fonts and would silently set the card in system faces.
  Eligibility is a conservative `created_at` gate against the first
  suppression-armed revision (0221) — a card ships the shell and a person
  contaminates a measured albedo, so this is the rung where 0089 binds hardest.

Suite **276** vitest; lint, tsc, and the static-export build are green.

### Infra and operations

- **Deploy is candidate → smoke → flip** on every service, perception-obj
  included. `infra/RUNBOOK.md` carries the phases. `deploy_perception.sh` moves
  the `serving` registry tag at the flip — do not skip it.
- **Registry cleanup is a policy** (`infra/artifact-cleanup-policy.json`): keep
  anything tagged `serving` or `buildcache`, keep the 3 newest `perception-obj`
  and 10 newest `api-*`, delete the rest at any age.
- **Cloud Build carries a layer cache** (`--cache-from :buildcache`), measured
  at 5.1× on a source-only perception build.
- **Eventarc** trigger `captures-bundle-pb-finalized` delivers to
  `api-internal/ingest/eventarc`, with app-side path filtering.
- **Retention** is configured and live: captures 24 h, failed scenes 90 d,
  upload sessions 7 d, mask intermediates 180 d.
- **CI** (`.github/workflows/`): python and web are push-triggered and green on
  Linux; iOS is `workflow_dispatch`-only on purpose — see the iOS test policy.
- **Tooling.** `tools/upload_test_bundle.py` is the substitute iOS client with
  four smoke modes; `tools/reenqueue_scene.py` is the out-of-band cure for
  stranded scenes and the warm re-drive driver.

## What does NOT work / what we're deliberately not doing

Open problems, measured dead ends, and deliberate non-goals. An item leaves this
list when it is fixed or ruled — not when it is explained. Closed items are
deleted, not annotated; their story is in `docs/decisions/`.

### Measured dead ends — do NOT re-attempt without new evidence

These were tried and refuted with numbers. Each names what would have to change
for it to be worth re-opening. Re-running one of these is the most expensive
mistake available in this repo.

- **View selection does not predict reconstruction quality** (0146, 0152, 0162).
  Seven view features against two mapping-independent instruments: all coin
  flips. The one GPU experiment ran — a view **1.7× sharper** seeing **2.1× more
  surface** reconstructed **worse** on both instruments. Eleven candidate
  measures have now failed. Re-opens only on a validated completeness
  instrument, which no one has.
- **A better-framed photograph is not a better photograph** (0197). Both
  legless tables had a fully in-frame alternative already reconstructed in the
  bucket, so the probe cost a download. Swapping them through production's own
  `build_box_object`: rp6g1's table **0.406 → 1.004** of its measured box height
  — a floating slab becomes a table with four legs — and rp7's desk **0.415 →
  0.356**, stubby legs to none. Nothing on the input side separates them: both
  alternatives are `in_frame` 1.000, ~10× smaller in frame, 2.3–3.3× more
  Gaussians, and they land on opposite verdicts. **The effect is large and
  BIDIRECTIONAL**, so a ranking key that can gain a set of legs or lose the ones
  you had is worse than useless, and none was built. Two traps: the winning view
  is the MORE occluded one (0.714 vs 0.503), and point count picks wrong on rp7
  because Gaussian count tracks how much is visible, not how good the photograph
  is.
- **Raising `PERCEPTION_PLAN_VIEWS_PER_BOX` is inert on a warm room** (0160). A
  cached frame's policy-skipped views are invisible to the planner forever, so
  the plan comes back empty at budgets 2, 4, and 8. The cure is clearing the
  per-frame `objects.json`, not the knob. Corollary: an OOM-failed view is never
  retried by any warm re-drive.
- **The multi-view union does not work** (0166). Given an oracle registration
  production could never have, a second reconstruction adds **+0.057** coverage
  against **+0.063 with no registration at all** — so registration was never the
  constraint. It costs 1.76× the points and renders visibly worse in all three
  cases including the best by the metric. Two reconstructions of one object are
  two different fabricated objects, not two views of one.
- **De-occlusion does not clear its own gate** (0165). Foreign occlusion is a
  median 0.080 of an object's missing surface against a registered bar of 0.25.
  The two named hard cases (the "legless" desk and table) come in at 0.08 and
  0.16 — they run off the frame edge, not behind something.
- **A measured point map does not fix truncation** (0181). SAM 3D accepts a
  LiDAR-derived pointmap and the reconstruction barely moves: the
  pre-registered prediction was refuted at 1.4% of predicted magnitude, wrong
  direction. The layout half is untested.
- **The 180° facing sign has six refuted instrument families** (0081, 0104,
  0156, 0170). Appearance scorers, unioned clouds, per-view aggregation,
  truncation priors, a vision model shown both renders, and the layout-derived
  sign — the last is right 2 times in 3 and ships flag-only because no number it
  reports separates the miss from the hits. The shared cause is measured: a
  single-view reconstruction's unseen half is fabricated, and every one of these
  asks that fabricated half a question. **Settled in conversation instead**
  (0157) — and ruled a concession, not a feature (0183).
- **Capture-time guidance cannot beat selection or multi-view** (0155). One
  viewpoint of a solid object tops out at 0.50 surface coverage by geometry;
  the best single frame already reaches 0.31. Guidance is the only one of the
  three that asks anything of the person holding the phone and has the lowest
  ceiling. **Do not build per-object capture-sufficiency feedback** (0150).
- **Do not tune `FUSION_CLUSTER_DIST_M` or `SHELL_WALL_MERGE_*` to chase
  under-merge symptoms** (0075). Both measured correct on real rooms; the
  symptoms are label collapse and edge truncation.
- **Generic compression buys almost nothing** (0125). Float32 splat data is
  high-entropy: gzip is 1.36×, where the SPZ tier is 5.8×.
- **Spark is not the render bottleneck** (0123). Parse is under 1% of the wait;
  fetch concurrency is flat from 1 to 10 because one GCS connection is capped.

### The strategy those dead ends leave

The dead ends above are not a scattering of failures; together they point one
way, and every perception lane should be read against this.

**1. The model is fixed and single-view.** SAM 3D takes one RGBA image. We do
not train it and cannot make it consume several views — that is 0052's standing
trigger and it waits on the field, not on us.

**2. Everything DOWNSTREAM of the model is measured dead.** Better frame
selection (0162), a measured depth pointmap (0181), and unioning two
reconstructions (0166) are three unrelated mechanisms and three separate
negatives. The shared cause is that a single-view reconstruction's unseen half
is fabricated, so anything that interrogates or combines finished objects is
asking a fabrication a question.

**3. Everything UPSTREAM of it demonstrably works.** All three objects the
operator named were fixed by changing what SAM 3D is *shown* — a better view
for rp6g1's table and rp7's chair, a better mask for rp7's desk (0197/0198).
The mask is the sharpest form of this: alpha IS the mask, so an incomplete mask
deletes from the model's input what the photograph actually contains.

**4. But an input CANNOT be scored in advance.** Eleven view measures have
failed, and 0197 is the sharpest: the same swap gained one table a full set of
legs and cost another the ones it had, with every input measure pointing the
same way on both. **The effect is large and bidirectional, so no sort key is
buildable.**

**So the strategy is: change the input, and judge on the OUTPUT.** Generate
candidate inputs — a different view, a repaired mask — reconstruct, and score
the *result* against the object's measured RoomPlan box. The box is the only
ground truth in this system that is not itself a fabrication: RoomPlan measured
it. That is why the output-side check is the one instrument that has ever
separated good from bad here, and it is what read rp6g1's table at 0.406 →
1.004 of its box height and rp7's desk at 0.212 → 0.655.

**The constraint is economics, not ideas.** Every candidate input costs a
reconstruction. Repairing a mask costs roughly one extra reconstruction per
flagged object — about one per room or two — which is cheap and is why it goes
first. Sampling more views per object costs N extra reconstructions across
every object, on a service where one room already budget-stops with a 53-item
tail. Any proposal here must say what it costs per room before it says what it
gains.


### Open defects

**Perception / room quality**

- **The repair and the chooser are RULED ON and flip together, refine first**
  (0198/0201, 0204/0205, 0211/0212; operator sitting 2026-08-23). SAM 3D's
  input is RGBA with **alpha = the SAM mask** (`models/sam3d.py`), so an
  incomplete mask deletes from the model's input what the photograph actually
  contains. On a 0%-traffic candidate the repair reproduced 0198's bench **to
  the pixel** — 58,386 → 61,439 mask px at IoU 0.9493. `PERCEPTION_ARM_SELECT`
  then moved exactly one object: rp7's desk. **The chooser did not change —
  refinement changed what it was choosing between**, which is why these are one
  decision and why refine goes first (0212). The measured COLD flag rate is
  **10 of 37** planned box views (rp7 1/12, rp6g1 3/10, rp6g2 2/5, spike 4/10),
  against the warm 9 of 25 that 0201 priced from — a warm room understates it.
  **What the sitting measured that the flag report did not:** the headline
  "0.321 → 1.122" is the **narrowest axis only**. In the box's own axes the
  refined desk is 0.734 × 0.877 × 0.665 against a box of 1.291 × 0.795 × 0.660
  — **width falls to 0.569 of the box** and the three-axis error goes
  **0.626 → 0.644 m, marginally worse**. It is not rotated: its longest extent
  is 0.877 m against the box's 1.291 m, so it is a **partial object** — the
  sit-stand desk's right-hand leg assembly plus a stub of top. **The operator
  ruled ON having seen this**, on the merits: class-6 truncation is endemic,
  and an object standing on its measured floor at the right height beats a
  desktop floating 47 cm up. **Do not re-report the width as a fresh defect.**
  The third Chamfer axis rides `ARM_SELECT` and needs no env of its own
  (`PERCEPTION_ARM_S2C_MIN_CLOUD` is a threshold, not a gate); the
  band-decomposed claim rate is inert and has no flag.
- **The object-aware residue is PARKED, and the spike run is refused rather
  than deferred** (0202, 0212; operator sitting 2026-08-23). It hit its
  pre-registered frame set exactly and bought spike's bed a better arm — and
  **cost rp7's desk its repair**, because frame 114 is not in the residue set.
  **This is NOT a negative on 0202**: the prediction landed frame-for-frame and
  the bed improvement is real. **The rp7 framing overstated the cost** — that
  desk's three-axis residual is 0.626 (ships) vs 0.644 (repaired), inside
  noise, so the chooser most likely refuses and the shipped arm survives
  anyway. **The question changed under it:** the residue's core job has moved
  into the cover pass (`68ed282`), and that work had to fix the residue for
  **ignoring the frame vetoes** (`9320099`) — two stages now overlap and
  neither knows what the repair stage needs. So the real question is whether
  this stage should exist separately at all, and it is answerable **on CPU**:
  diff the new selector against cover-pass-plus-residue across all four
  captures (largely agree → retire the flag rather than ship it), and compute
  which frames the residue selects on spike without reconstructing anything.
  **It cannot ship until supply, repair and the vetoes draw from one
  allocator, and it belongs to the throughput charter, not to a parked flag
  with no owner.**
- **Class-6 splat truncation is untouched and has no live route.** Reconstructions
  are missing legs, bases, and backs. Every placement fix to date positions or
  orients an incomplete reconstruction better rather than completing it, and all
  three attacks on the cause are measured dead above. What remains is decision
  0052's standing trigger: a different model — one that consumes several views
  itself, or exposes calibrated metric scale or pose.
- **CUDA OOM is the largest measured loss in the corpus** (0228) — **22 of 163
  detections**, twelve of them box views, and **two boxes lost their only
  compatible mask**. It is **capacity, not scheduling**: the models hold
  ~16.4 GiB, the forward pass needs 5.23–6.43 GiB, the card has **5.26 left**.
  Freeing 1.2 GiB covers 21 of the 22. **The second arm is currently the OOM
  fallback in six of nine affected boxes** (0229) — which is why
  `PERCEPTION_CONDITIONAL_SECOND_ARM` stays OFF until the throughput charter
  closes. **The charter's named option (evicting SAM 3 for pass 2) is mutually
  exclusive with mask refinement, which is now ON** — so the live path is the
  charter's own escape: batch pass 2's refinement calls into their own sub-pass
  so SAM 3 can be evicted after it. That restructure and the frozen-plan retry
  work are **one project, not two**.
- **`b667f891` is budget-starved.** Its census plan carries a 53-item long tail
  against the 900 s request budget, so it budget-stops every round and the
  fusion post-passes never run there. Not a placement defect — the room's
  clutter exceeds one request. **Measured cost, 2026-08-20:** a warm re-drive
  on the colour image still came back `budget_stopped: true,
  refinement_skipped: true`, and the room gained colour on 0 of 45 objects
  while 40 of them had readable splats. The post-passes it loses are not
  abstract.
  **rp6g2 is NOT a representative room** (0235): its last **28 keyframes are
  black**, mean luma 0.13–4.49 against a capture median of 129.5 — **23.4% of
  a room that has been the thin case in every round of analysis.** Poses and
  depth are valid, so this may be an **iOS capture defect** rather than a data
  quirk. Re-read every prior conclusion drawn from it — including the 53-item
  budget-starved tail and the 0-of-45 colour result — against this.
- **A window ships with ~30° in-plane skew.** Near-square planar objects are
  ~90°-ambiguous to the model and no instrument scores in-plane orientation.
- **The "cabinet behind a wall" is not the declip bound** (0104). The declip pass
  never engages: the object's centre projects outside every wall rectangle. Start
  from that fact, not from `PLACEMENT_SPLAT_CLIP_MARGIN_M`.
- **Material family is unstable at the confidence gate** (0100). The
  distribution is bimodal — six answers at 0.85–0.98 and one at exactly the 0.60
  floor — so a re-bake can ship a different family than the operator adjudicated.
  Recommended and NOT applied: raise `SHELL_MATERIAL_MIN_CONF` to 0.75. Applying
  it requires reference-room re-adjudication first (0070).
- **Two same-label objects closer than `FUSION_CLUSTER_DIST_M` (0.4 m) can still
  merge into one** (0052).

**The guest**

- **Object colour ships in three of the four walk rooms, not the fourth**
  (0184/0185; deployed 2026-08-20). rp7 8/16, rp6g1 9/20, spike 14/25 objects
  carry a measured `color` block, and `scene_facts` turns them into spoken
  names — spike's `red chair` is a real production referent. **rp6g2
  (`b667f891`) has 0 of 45 and another re-drive will not change that**:
  `apply_object_colors` runs inside the refinement pass, and that room's
  manifest reports `budget_stopped: true, refinement_skipped: true`, so
  colour is one of the post-passes its long tail costs it. Objects with no
  block inside a coloured room are the confidence gate working, not a
  failure.
- **The guest's tool descriptions are instruction it reads and are NOT under
  `PROMPT_SURFACE_SHA256`.** The pin covers the charter and the arrangement
  block, and the comment above it says why: prose outside the pin can be
  "reworded with no version bump and no eval trigger, which is exactly how
  decision 0174's defect shipped and survived two bumps unnoticed".
  `guest_tools.TOOLS` carries several hundred words of exactly that prose,
  outside the pin. Found 2026-08-21 by the guest lane and deliberately not
  fixed: widening a pin turns other lanes' evals red, which is a scheduling
  call rather than a lane's.
- **Two voice evals carry known flakiness** — one setup asks about an ambiguous
  wall roughly 1 time in 8.
- **`FACTS_VERSION 4` and the ambiguity refusal are MERGED BUT UNPROVEN against
  a live model** (0213/0214, merged 2026-08-21). The voice evals are
  fail-closed-live and need an `ANTHROPIC_API_KEY`; the lane had none and
  neither did the coordinator, so they are **not green and not red — they never
  ran**. The unit suite covers the resolver (370 + 102 in `api-public`), which
  is a different question from whether the guest speaks the refusal well. The
  lane fixed two real harness bugs while in there — both were grading a guest
  production does not ship — and added one eval for the new refusal, so the
  coverage is written and waiting on one run. **This is a deploy gate, not a
  merge gate:** the code is on `main` and must not reach `api-public` until the
  evals run once with a key.
  The `ANTHROPIC_API_KEY` was never absent — `anthropic-api-key` has been in
  Secret Manager since 2026-07-21 and the operator's own account can read it.
  Nothing connected it to the eval harness. Run:
  `RUN_VOICE_EVALS=1 ANTHROPIC_API_KEY="$(gcloud secrets versions access latest --secret=anthropic-api-key --project=roomstudio)" .venv/bin/pytest services/api-public/tests/test_guest_voice_evals.py -v`

**iOS**

- **The OS-kill relaunch gate (2b) has never run on hardware.** The code is
  complete; force-quit provably produces zero background relaunches (0114), so
  `StagingHooks`' `exit(0)` route is the only way to reach it.
- **The Live Activity count freezes when the process is dead** (0114). The word
  stays honest, the count sticks at the moment of death. Only remote push fixes
  it — `LiveActivityController.pushTokenSeam` is named and unbuilt.
- **The anonymous UID churn has happened twice on real hardware** (0139, 0140).
  Mechanism named — the SDK deletes its own Keychain credential on a token
  rejection and the app silently mints a new UID, orphaning that period's rooms.
  Churn 1 is dated and attributed; churn 2 is open. `IdentityContinuity` (0141)
  instruments the next occurrence.
- **Foreign-record stand-down drains one record per launch** (0115), so N
  phantoms need N relaunch cycles. Deliberately not fixed: quieting the symptom
  before the churn's cause is known makes orphaning less visible, not less real.
- **Terminal-failure UI has never rendered on hardware** — server-side scene
  failure and blob-failure banners.
- **The 401 recovery-*success* leaf is untested.** The live test used a garbage
  token, exercising the give-up branch, not expired → refresh → valid → 200.

**Web / product**

- **The hero A/B is open** — the operator's taste call (0122). Variant (b)
  cannot be seen on any deployed origin by design: a real object splat is a
  possession, so its files are gitignored and hosting-ignored.
- **The bridge QR encodes nothing.** No deep-link infrastructure exists; the
  caption says so. It is NOT blocked on the rooms fetch, which is what its
  staged-list entry used to imply — the desk names the room in the link it
  hands over, so a list of the phone's own rooms tells it nothing (0218).
- **`RSSound` is wired at three call sites with no cue files** — the app is
  silent. The web has no sound at all. Branded fonts fall back to system faces.
  The product **name** is settled (0245); the web lockup still needs re-cutting from mono to the serif.
- **There is no per-room deletion** — account deletion is all-or-nothing, which
  is conspicuous for a product whose thesis is that rooms are identity. **It is
  also a hard prerequisite of any hosted share link** (`docs/product/social-layer.md`
  §7): revocation of a share and deletion of a room are one mechanism seen from
  two angles, so shipping the link first would ship a share that outlives every
  means of stopping it. Unshare is not a feature of sharing; it is a precondition.
  Rung 0 — the calling card — is built and needs none of this, because nothing
  leaves our systems; every rung above it is still behind this gap.
- **The card's date gate refuses rooms that are genuinely eligible** — an older
  scene re-driven cold on a suppression-armed revision qualifies and the gate
  still says no, because `created_at` cannot see a re-drive. One-directional by
  construction and the safe direction; the manifest provenance field is the
  durable fix and 0221 carries its trigger. Related and untested: the card has
  never been drawn against a real `anchor_envelope` shell — the v2 mock
  exercises the measured-vs-rendered divergence, a real LIDAR_ARKIT capture
  would be the better test.

**Infra / release**

- **Alerting and monitoring do not exist and the deferral is unrecorded.** An
  unrecorded accepted deferral is indistinguishable from an oversight. Record
  the acceptance or schedule the work.
- **A second, unrestricted Firebase browser key exists** (no referrer
  restriction, 27 APIs). The key the web app ships is properly restricted.
  Closing the gap breaks the live-authed-check path every recent api-public
  deploy uses — ship a replacement first.
- **The registry holds 4 `perception-obj` images, not 3, and that is the policy working (0190).** The keep rule is *the 3 newest PLUS anything tagged `serving` or `buildcache`* — never "exactly 3", because a lane iterating on builds pushes the live image out of the top three, and exactly-3-by-recency would then delete the image Cloud Run is running on a scale-to-zero GPU service. On 2026-08-20 three undeployed builds landed and the live `20260813-222442` sat **4th, held only by its `serving` tag**; the policy evicted `20260816-050851` automatically when the third arrived, so the count is pinned at 4 (worst case 5) and self-maintaining. **The fix for a high count is to deploy or delete the surplus builds, never to tighten the policy.** Billing confirms the mechanism: ₹420/day at 1,446.7 GiB is ₹0.2903/GiB-day (= AR's $0.10/GB-month), Aug 19's ₹140 implies a 482 GiB daily average as GC drained, and the state after the geom retirement is 154.3 GiB ≈ **₹45/day, 89% below**. Two of those four images are undeployed and untagged, worth ~₹22/day — **untagging frees nothing; deleting the version is what reclaims it.** **Updated 2026-08-20 by the colour deploy:** the live image is now `20260821-010928` / `sha256:faa005c8…`, and the count sits temporarily above 4 for two reasons worth recognising rather than "fixing" — the first buildx build published an attestation sibling alongside the image (0200; `--provenance=false` stops that recurring), and the rollback target `d15ca00d…` is deliberately held by a `serving-rollback-00044-m5p` tag, which the Keep rule matches on PREFIX. **That hold is temporary and owed back** — drop the tag once `00062-hum` is trusted, or the image is pinned forever.
- **Terms §9–§11 need an Indian lawyer.** Consumer Protection Act 2019 §2(46)
  can void the §11 liability cap against a consumer.
- **Apple Developer Program enrollment CLEARED 2026-08-23** (filed 2026-07-22).
  Gate A, APNs, TestFlight, submission and Apple sign-in on the web are all
  unblocked. **Three things follow, in order:** (1) **verify the device build**
  — the re-sign clock passed 2026-08-19 07:15 UTC and enrollment ends the
  7-day treadmill only once the operator re-signs and installs, so there is no
  working install until then; (2) **check 0115** — the identity-destroying
  defect was flagged as possibly enrollment-gated, and if it persists it was a
  real bug hiding behind the gate and must surface **before TestFlight**;
  (3) **the product name is now live**, forced by the App Store listing.
- **App Store collateral is unstarted** except the icon, and it is **three
  dependencies rather than one queue**: **screenshots** wait on a verified
  device build; **age rating and support URL** wait on the product name (the
  support URL is expensive to change once filed); **privacy nutrition labels
  wait on NOTHING and should be drafted now** — they are a disclosure
  obligation about sending room imagery to a model and **must name the
  material-inference vision call** (0089), not a form to fill in.

### Deliberately not doing

- **Decision 0072's rollback path is CLOSED** (operator sitting 2026-08-23).
  `ContentView` and the two views it alone mounted are deleted. The escape
  hatch was worth its cost in July when the design was untested on hardware;
  that risk is spent — the design has since absorbed RP-6, RP-7, Live Activity,
  Google linking, the flight stand-down and the scenes client without anyone
  reaching for it. **Four lanes edited a path no build could reach**, and 0217
  applied a real fix plus a seven-line comment to a screen no user will see.
  **Dead code that keeps accruing unverified fixes rusts shut rather than
  staying ready** — it gets less usable as a rollback over time. **Do not
  restore it as a courtesy.**
- **ARKIT_ONLY placement and shell quality investment is parked** (0071). The
  product is Pro-only / LiDAR-first; the shipped ARKIT_ONLY path stays live and
  is strictly better than before, but no further merge-knob grinding. The
  non-LiDAR device is not a test target and must not shape decisions.
- **The two lockups set the NAME differently and the fork is now decided by
  the name itself** — "The Good Guest" is too long for tracked uppercase mono
  beside the corner mark, so the display serif wins by construction (0245). The
  mark is identical everywhere (0193). **What remains is applying it**: the web
  lockup still renders in mono and has not been re-cut to the serif.
- **From the founding vision, still sound:** no AR overlay, no social feed, no
  photorealistic image generation, no floor plans as a product surface, no voice
  input. Desktop-first on web.
- **The ledger is deferred with its vocabulary ban** (0133) — no pin, keep, or
  "put into words" anywhere.
- **Mirror-as-mirror was probed and cut** (0091). The depth-trust gate is not a
  mirror detector (precision 18%); the SAM `mirror` label is. What a mirror
  should look like is a design call, not a build.
- **Free rotation in proposals is out** (0133). Rotation returned as a facing
  *correction* — one half turn, no angle, no direction — and that is a
  concession whose success condition is its own disuse (0183).
- **`expires_at` on mint responses and content-type hardening are won't-build**
  (0087), each with a named re-open trigger.
- **NEVER enable anonymous-user auto-cleanup in Firebase Auth.** It is off and
  must stay off — it would fire the UID-churn mechanism above for every user on
  a schedule. It is a single checkbox in the console.

### Small deferred items recorded nowhere else

These are the only entries here with no decision note behind them. If one is
ever done or ruled, delete it — do not annotate it.

- **A client-ack cleanup path for the `scenes` collection**, layered on the
  existing TTL: the client acks after consuming a terminal result, triggering
  prompt deletion, with the TTL remaining as the backstop for scenes never acked
  (crash, force-quit, uninstall). Explicitly not ack-only — client cooperation is
  not guaranteed. The TTL half shipped in 0086, so this is now a live
  optimization rather than a blocked one. It was the single item in the retired
  207-entry tracker recorded nowhere else.
- **`secondary_hex` is always null** — two-tone material separation was deferred
  as noisy.
- **The floor's rectangular stone pattern is real and detectable** and is the
  first candidate for `material.params` growth. Deliberately excluded from v1: a
  wrong pattern breaks recognition worse than a clean matte (0069).
- **Client wake cadences are untuned placeholders** — blocked 5 s, confirm 4 s,
  rested 15 s; and the scene-poll ladder. Standing trigger is real usage data,
  not a staged failure.
- **`unprompted_proposal` has never been observed in real traffic.** Only real
  usage answers it.
- **RoomPlan's guidance relay has never fired live** — the instruction stream is
  sparse by nature, so it is table-pinned and seeded-screenshot only. Review's
  `thinCoverage` and verdict are deliberately unwired pending an operator copy
  decision, and `didChange`/`didRemove` are deliberately unconsumed.
- **The doorway universal-link handoff, the QR bridge, and push are stubbed at
  named seams** pending associated-domains and APNs entitlements.
- **The `.recoverable` re-upload and add-more resume-with-progress** are built;
  the remaining iOS activation follow-up is the real web-handoff link.

### Standing facts that look like bugs

- **happy-path and duplicate-event smoke modes terminate at `failed_invalid`,
  not `ready`.** The ingest gate correctly fast-fails the synthetic fixture's
  placeholder images pre-GPU. Reaching `ready` requires real capture data.
- **Scene `f077e9ed-d339-4be8-8dbf-37b952abfec2` is deliberately left in
  `processing`** with an expired lease, as the canonical stuck-scene reference.
- **The numpy/Accelerate `IndexError` in `test_shell_observation.py` is not our
  bug** — macOS/arm64 reproduces it, Linux CI passes on the same numpy, and the
  bounds guard is provably correct. **Do not clamp the indices**; that trades a
  loud crash for silently corrupt pixels.
- **`web/public/dev-fixtures` is 3.9 GB of real captured homes inside
  `public/`**, and `next build` copies `public/` into `out/`. Hosting ignores it
  on deploy — one config line between real rooms and a public origin. Moving it
  outside `public/` would remove the hazard rather than guard it.
- **Cold-start coverage is thin by design.** The first `/process` request spends
  its budget on boot and model load; warm re-drives are the coverage recipe.
  Large single objects can transiently exceed the L4's memory even at baseline —
  per-object soft-fail contains it. That is a capacity fact, not a lifecycle bug.

## Python test policy

**The suites must pass with NO cloud credentials available.** This is a hard
property, not an aspiration, and it was violated silently until the first CI
run this repo ever executed (run 31259471685, 2026-08-08) failed 12 tests in
`services/api-public/tests/test_upload_session.py` with
`DefaultCredentialsError` → the endpoint 500s → `assert 500 == 200`. They had
been green locally for months only because the operator's machine carries
ambient ADC from `gcloud auth application-default login`. Every count recorded
in this file before that date is therefore "passed **with ADC present**" — the
root suite's 602 included 12 tests that were quietly resolving real Google
credentials and taking ~4 s each to do it.

Cause and fix (2026-08-08): `public_server.py` binds `gcs_mint_resumable_uri`
by from-import, so the test's `patch("roomstudio_api_core.upload_session_repo.
gcs_mint_resumable_uri", …)` rebound a different name and never took effect —
the handler kept calling the real minter. Fixed by injection, the same seam
pattern `UploadSessionRepository` already uses: `public_server._mint_uri_fn`
(None → the production minter; tests patch the global). **Do not "fix" a
credential failure in CI by supplying credentials** — that turns the tests
green while leaving them non-hermetic, which is the actual defect.

Current: **root 839 passed + 26 skipped** (dev-fixtures staged), verified BOTH with ADC present and
with ADC made unavailable (`GOOGLE_APPLICATION_CREDENTIALS` unset,
`CLOUDSDK_CONFIG` → empty dir, `GCE_METADATA_HOST` → unroutable). The
credential-free run is also 25× faster (1.3 s vs 33 s), which is itself the
tell that the old suite was doing real auth work. Two pins hold the property
(`TestUploadSessionNeedsNoCredentials`): one asserts the handler returns 200
when `google.auth.default` raises, the other asserts the unpatched seam still
vends the REAL minter — the matched pair, because either alone can be
satisfied by a change that breaks the other (defaulting the seam to a fake
would turn CI green and ship an api-public handing clients fabricated URIs).

**The local `.venv` is not the perception container.** `services/perception-obj/pyproject.toml`
declares `numpy<2`; the shared `.venv` carries **2.4.4**, and perception's 746
tests pass on it. So a green local perception run says less about production
than it looks like, and CLAUDE.md's "cannot share an environment" is about the
DECLARED constraints (which is why CI splits the jobs), not about what actually
runs — they do share one here. This also explains why the numpy-1.26
Accelerate failure below does not reproduce locally: nothing local is on 1.26.
A worktree has no `.venv` of its own; lanes use the main tree's interpreter by
absolute path (`/Users/aubrey/projects/roomstudio/.venv/bin/python`), which
still imports the worktree's own modules. Use it rather than the system
`python3`, which has no PIL: four perception test modules import it at
collection time, so a system-python run reports 4 collection ERRORS that look
like a broken branch and are not.

**A worktree's `packages/` edits are INVISIBLE to the shared `.venv`**, which
carries the MAIN tree installed editable — so `import roomstudio_schemas` in a
worktree resolves to `/Users/aubrey/projects/roomstudio/packages/schemas/...`,
and a lane that adds a function there gets `ImportError` from its own service
code while its own `packages/schemas` tests pass (that suite's conftest inserts
the local path). Prefix the run with
`PYTHONPATH=<worktree>/packages/schemas`, which does win over the editable
install — measured 2026-08-16. Same class as the roomlib trap below, and it
bites `services/*` and root runs rather than `packages/*` ones.

  **`selection-supply` repointed `roomlib.REPO` to the worktree** and added an
  explicit `roomlib.DATA` for the captures, which fixes the trap below for that
  branch. **Running that branch's tests needs
  `PYTHONPATH=<worktree>/packages/schemas`** — `trimmed_nn_rms` is new in
  `packages/schemas` and the shared `.venv` resolves to MAIN without it,
  producing 20+ collection errors that look like a broken branch.

**`outputs/room-quality/roomlib.py` hardcodes the MAIN tree at `sys.path[0]`**
(`REPO = Path("/Users/aubrey/projects/roomstudio")`). A worktree session that
imports it loads MAIN's perception modules, not its own — so a trust gate can
silently certify shipped code against itself, and test collection in a worktree
depends on the main tree's state. Measured by lane E, 2026-08-14. Repoint REPO
before trusting any number from it.

**Suite counts depend on whether `web/public/dev-fixtures` is staged**, and two
lanes have now reported numbers that read like regressions and were not:
root is **862+27** with it, and perception is **952+2** with it against
**945+9** without — both re-measured 2026-08-21, which closes the gap this
paragraph carried for weeks (the last fixtures-staged perception figure on
record was 793+0). The seven-test spread IS the fixture-backed set, and it
skips silently, so a worktree lane reporting the lower number is correct
rather than regressed — two lanes have now reported exactly that and been
misread. Always say which invocation a count came from.

Other Python jobs at that CI run: perception-obj **passed on Linux** — the
`test_shell_observation.py::TestMedianSelect::test_closer_frame_outweighs_far`
failure recorded under numpy 1.26.4 did NOT reproduce, so it was macOS/
Accelerate-specific as the workflow comment's second hypothesis predicted.
re-enqueue (18) and ruff (non-gating) passed.

## iOS test policy

The iOS suite is **600 tests total** (was 553; the scenes-client pass added 47 — `ScenesListClientTests` 17, `RoomHistoryTests` 12, `RoomsStoreTests` 11, `RoomsSurfaceTests` 7, for the `GET /scenes` client and the three surfaces it feeds. Before that, 544 → 553; the ios-surfaces pass added 9 — the flight stand-down and the launch-adoption table, both in `ScenePollExpectationTests`. Before that, 535 → 544 from the uid-churn investigation — `IdentityContinuityTests`, the launch continuity table. Before that, 523 → 535 from the Google-linking pass and 482 → 523 from the ios-residue pass. Before that, 463 → 482; the walk-findings pass added 19 — Live Activity narration, failure copy, and the recoverable count. Before that, 391 → 463 from the Live Activity / 429 / guidance pass, which added 76 and relocated 4. Before that, 352 → 391 from the release-residue pass; the release-residue pass added 39 — `CaptureReclaimTests` 15, `CaptureReaperTests` 12, `StagingHooksTests` 7, `ScenePollExpectationTests` 5. Before that, 302 → 352 from RP-6/RP-7; RP-6 added 11 — 9 co-run/wire pins + 2 envelope-edge pins — and RP-7 added 39 — `FloorPlanMathTests` 18, `FloorPlanVoiceTests` 13, `FloorPlanFixtureTests` 8. Before that, 288 → 302 from the 0074 phantom-room pass), run manually via `xcodebuild … -scheme RoomStudioCapture-Integration` — the only scheme in this project (no separate default scheme, no CI gate). That scheme bakes `RUN_INTEGRATION_TESTS=1`, so the 4 `UploadSessionClientTests` **execute live on every run**; they are NOT skipped in practice. They last ran live 2026-08-22 (the scenes-client pass, 600/600) against `api-public-00042-ruq`, the whole suite in ~14 s of test execution.

**What the suite does and does not cover.** It pins flow LOGIC — routing tables, restore selection, deferral scoping, poller visibility — deliberately extracted into pure functions so they are reviewable as tables instead of by reading SwiftUI. It does NOT cover rendering: a green suite is compatible with a screen whose only exit is clipped off-frame at accessibility sizes. **AX5 layout claims must be re-verified by screenshot, never by reading** (`xcrun simctl ui <udid> content_size accessibility-extra-extra-extra-large`, then a temporary app-entry swap to the screen under test); three separate review passes claimed AX coverage they did not have, and the two screens that actually failed — `AccountConflictView` (deleted since, 0216) and `QRBridgeView` (fixed; re-verified by screenshot 2026-08-22) — were both found by screenshot after being read as fine. **The sharpest thing to check is a PINNED action** (0224): home's scan button truncated to "Scan a ro…" because a notice stacked outside `HomeView`'s `ScrollView` took ~370pt at AX5 and the compression landed on the pinned sibling rather than on the scroll area. Content belongs in the scroll area; only the action is pinned. Two shipped surfaces — `UploadFailedBanner` and home's re-entry row — are still stacked in that position and have NOT been screenshotted at AX5 with the action in frame. Second recurring form, same shot: `.center` is `HStack`'s default, so any glyph or button beside prose that wraps to four lines comes to rest in the middle of it — top-align it.

**Posture: fail-closed-live, not fail-open.** Each integration test calls `XCTSkipIf(!RUN_INTEGRATION_TESTS)` — the fail-open default — but because the sole scheme always sets the flag, that skip path is never taken here. With the flag set they hit the live `/upload_session` contract and go **red if the backend is unreachable**. Running the suite therefore requires a reachable backend; an offline run will fail those 4 (expected, not a regression).

**Honest count:** report as "594 asserting offline unit tests + 2 boilerplate stubs (`testExample`/`testPerformanceExample`) + 4 live integration tests (require a reachable backend)", total 600 — not a bare total: the 2 stubs assert nothing and the 4 integration tests carry an external dependency the unit tests don't.

**One known flake, measured 2026-08-22.** `BlobUploadManagerTests.test_gate_lastDecrement_afterDrain_firesHandler` fails roughly **1 run in 15** under full-suite load and **0 in 12** in isolation — so it is a scheduler race, not a regression, and re-running is the correct response to seeing it red once. Measured across 29 full-suite runs (1 failure in 15 on `scenes-client`, 0 in 14 on `0f671fc`), which is why it is recorded as a rate rather than attributed to a change. The cause is visible in the test's own source: a single `await Task.yield()` is the only synchronisation before it asserts that a background-completion handler has run. Fixing it means giving the test a real await, not a longer sleep — but it belongs to whoever owns upload, not to a passing lane.

**Parallel-worktree note:** `GoogleService-Info.plist` is gitignored, so a fresh git worktree lacks it and the 4 live tests fail with a Firebase configure error that mimics a backend failure. Copy it from the main tree (`ios/RoomStudioCapture/RoomStudioCapture/`) before running the suite in a worktree; a rebuild picks it into the app bundle.

**A session working in the MAIN tree on its own branch is the same hazard as
two sessions in one tree.** The operator-sittings session was placed in the main
tree on branch `operator-sittings` because the fixture script and dev server are
main-tree-bound; the coordinator then switched that tree to `main` to merge
another lane, and the session found itself on a different branch with
uncommitted work while its own branch grew commits from elsewhere. It recovered
by moving to a fresh branch rather than committing to `main`, which was right.
**Give every session its own worktree, including main-tree-bound ones — symlink
what is main-bound instead of borrowing the tree.**

**Concurrent sessions MUST use separate worktrees, not the same tree.** Two iOS sessions ran in the main tree on 2026-07-25 and nearly produced a false green: one stashed two files to unblock a branch checkout while the other was mid-edit on them, so for the length of a merge the tree held the pre-edit content. Any build, test run, or `git add` in that window would have silently captured stale source, and BOTH sessions would have reported a green suite for a tree neither of them had. Nothing warns you — the suite passes, the diff looks right, and the commit that lands is whatever happened to be on disk. `git worktree` is the fix (one is already in use for `placement-quality-build`); the plist note above is its one gotcha.

**Contract/CI note:** the `/upload_session` contract is frozen (decision 0035), so the live integration tests assert against a stable shape. (The earlier fail-open rationale — that fail-closed-without-CI trains operators to ignore red — is superseded: the sole-scheme decision already made these intentionally fail-closed-live.)

**CI status (2026-08-08, decision 0099):** `.github/workflows/ios.yml` exists but is **`workflow_dispatch`-only and has never executed**. It is not a gate and is not on a push trigger, deliberately: the sole scheme bakes `RUN_INTEGRATION_TESTS=1`, so an automatic run would charge the per-UID daily CAPTURE ceiling (12, decision 0098) on every push and could lock the operator out of scanning their own rooms. The workflow runs the offline subset via `-skip-testing:RoomStudioCaptureTests/UploadSessionClientTests` (no source change; the device build stays pinned to what is on the phone) and carries a commented-out plist-restore step naming the secret it needs. **The real unblock is a CI-only backend project or a CI service account with its own quota** — that removes the objection entirely and would let the live tests run on every push. Python and web CI ARE push-triggered; only iOS is held back.

## Conventions

**A surface states what it knows.** The calling card counts **placed** objects
rather than everything detected, even though the room's own panel shows a
different number — a surface counts what it can *show*. The scenes client
reports **elapsed** time on a room still rebuilding, never an invented ETA —
the pipeline gives the phone no ETA, and an invented one would also mask the
signal that a 22-minute room means something went wrong. Its failure line
("they're safe where they are") is scoped to a **reachability** failure and
**must never become generic error copy**. **Honesty here is not a tone; it is a
constraint on what a surface may assert** — and it preserves diagnostic signal,
which is why it is not merely stylistic.

**NEVER enable anonymous-user auto-cleanup in Firebase Auth.** It is off
(verified 2026-08-14: the project config carries no auto-delete block) and it
must stay off. Decision 0139 measured the mechanism it would trigger — the SDK
deletes its own Keychain credential when the server reports a user gone, the
app then silently mints a new anonymous uid, and every room captured under the
old one is orphaned. Auto-cleanup would fire that for every user on a schedule.
It is a single checkbox in the console.

**Cloud Run revision numbers are NOT chronological on `perception-obj`.** The service has produced two revisions numbered 00036 (`-xer`, RP-8; `-l9l`, the 0089/0090 security+privacy deploy), one numbered 00038 (`-ses`, the 0081/0082 wave), and `perception-obj-00037-sd9` (image `20260808-200124`, the 0104 walk-classes deploy), which served 100% for two days despite a LOWER number than 00038. Do NOT read a lower revision number as a rollback — check the image tag and the traffic split (`gcloud run services describe perception-obj --region asia-southeast1`), which are the authorities. Serving now: **`perception-obj-00062-hum`**, image `20260821-010928`, digest `sha256:faa005c8…` (the colour deploy, 2026-08-20). Its predecessor `00044-m5p` ran `20260813-222442` / `sha256:d15ca00d…` — the same digest `00043-yiz` shipped — and is the rollback target.

**Old registry images are deleted by policy, and the live one is kept BY NAME
(decision 0190).** `infra/artifact-cleanup-policy.json` is the source of truth
and is applied to the `roomstudio` repository: keep anything tagged `serving`
or `buildcache`, keep the 3 newest `perception-obj` and the 10 newest `api-*`
versions, delete everything else under those prefixes at any age.
`perception-geom` is outside every prefix and cannot be touched by it — which
is inert now that it is retired (0192), and is a hole to close if it is ever
revived. The DELETE carries no age condition on purpose — that is what makes
the steady state exactly 3 + 10 + 10 images rather than "that plus whatever is
recent".

**So `deploy_perception.sh obj` moves the `serving` tag when traffic flips** —
automatically in direct mode, as a printed command beside the flip in
candidate mode. Do not skip it. Recency alone is not enough protection here:
two of the three newest `perception-obj` images today were built and never
deployed (0120's cache seed, 0182's rebuild), so the live image is already
second-newest, and a cleanup policy has no idea what Cloud Run is serving.
Forgetting the tag over-keeps one stale image, which is the safe direction;
the unsafe direction is the registry reclaiming the image a scale-to-zero GPU
service needs to start.

**A perception build that suddenly takes forever: check `PIP_EXTRA_INDEX_URL` first (decision 0182).** `pypi.ngc.nvidia.com` — first in Meta's index line, carried verbatim into our Dockerfile — went NXDOMAIN, and an extra index is consulted for EVERY package, so pip paid five DNS retries with backoff per dependency: **764 retry warnings** in one build, with `pip install -e '.[dev]'` at 25 m 38 s and still resolving when it was cancelled. Dropped 2026-08-16 (dropped, not repointed at `pypi.nvidia.com` — every recent build already resolved from PyPI proper, so removing a dead index changes nothing while adding a live one could change which wheels are selected). **The layer cache is what hid it** — every deploy since 0120 rode the cache, and the first miss fell straight into it. Two adjacent facts from the same session: the cache missed BROADLY (apt, the clone and `mamba env create` all ran) for a reason that WAS undetermined and is now measured — see the cache entry below, which closes it — and **the base image is NOT a suspect** — `condaforge/mambaforge:24.7.1-0` has not moved, verified by `rootfs.diff_ids[0]`, and an apparent difference in *compressed* layer digests is an artefact of Artifact Registry re-compressing on push. Compare diff_ids, never compressed digests, across registries. One more reading trap, which cost a wrong conclusion before the timestamps caught it: in BuildKit's plain progress output the number after a step id is **seconds since the BUILD started**, not seconds into that step.

**The perception layer cache alternated, and no longer does (decision 0199).** Until 2026-08-20 the build used `docker build --cache-from :buildcache` with `BUILDKIT_INLINE_CACHE=1`, and **the inline exporter writes cache records only for layers a build actually EXECUTED**. So a build that rode the cache published one missing every layer it had reused, and the next build rebuilt from `apt-get` down. Seven production builds alternate without a single exception — 58m, 59m, **10m**, 63m, **8m**, 60m, **8m** — and a three-layer probe reproduces it causally in under a minute (cold 27 s, hit 2 s, then **28 s off the hit's own cache**). This is what 0182 above left as "undetermined", and it is why 0163's 10-minute figure and 0182's 58-63 minute figure are both true and neither was predictive. Fixed by building with `docker buildx` on the `docker-container` driver, importing and exporting `type=registry,...,mode=max` at the same `:buildcache` ref — the registry exporter re-publishes records it imported, which is the half inline structurally cannot do. Measured on the real Dockerfile: the switching build missed at **53m58s** (predicted beforehand, and correctly), and the next build off its cache came back **49 of 49 steps CACHED in 40 s**. **Read that 40 s correctly** — it is a no-change build, so even the source `COPY` layers hit; a real source change still rebuilds and pushes from Dockerfile line 187 down, the historical **8-10 minutes**. What the fix buys is that the hit is REPEATABLE rather than every-other-time. **So: expect 8-10 minutes, and treat a 60-minute build as evidence an early layer genuinely changed rather than as the coin-flip it used to be.**

**One build must publish exactly ONE registry version (decision 0200).** buildx attaches a provenance attestation by default, which makes the pushed artifact an **OCI index** over `{real image, attestation}` — the timestamped tag names the index, while Cloud Run resolves it and pins the **child** manifest, which carries no tag. Observed live: the `20260821-010928` build pushed three versions at one instant and the revision pinned the untagged `faa005c8…`. That silently breaks decision 0190, whose whole protection is a `serving` TAG and whose `move_serving_tag` tags the image URI — it would have tagged the index and left the digest a scale-to-zero GPU service boots from untagged and deletable. `--provenance=false --sbom=false` is in the build config for exactly this and is load-bearing, not tidiness. **The tell that it has regressed is one build publishing more than one version at the same timestamp.** Related sharp edge from the same note: the Keep rule matches on tag PREFIX, so any tag beginning with `serving` (e.g. a deliberate `serving-rollback-…` hold) pins an image in the registry until someone removes it.

**perception-obj deploys candidate → smoke → flip like every other service.** `./infra/deploy_perception.sh obj --candidate` holds the new revision at 0% with a tagged URL and prints the smoke and flip commands; without the flag it still goes straight to 100%. The smoke needs an identity token (the service is platform-gated, 0106). Prefer the flag: a revision that fails at run time burns a full 900 s GPU request before anyone finds out, and route registration — the `/shell` and `/compress` stages — cannot be checked locally at all (0142).

- Python 3.11+. Ruff for lint/format (config at `pyproject.toml`).
- Frame of reference: ARKit-native everywhere on the wire. Convert at the boundary, not in transit.
- Coordinates: right-handed, +Y up, meters.
- Quaternions: `(x, y, z, w)`, unit norm within 1e-3.
- GCS paths in the bundle are RELATIVE to the bundle prefix, not full `gs://` URIs.
- File creation: every long-lived file gets a docstring explaining what it's for and who reads it. No "test code anyway" justifications for shortcuts.
- Tests pin invariants, not implementation. They should still pass after a refactor.

**Standards the repo is held to.** No AI attribution anywhere — commit subject,
body, trailer, or file content. No intermediate-dev references, no placeholder
or WIP markers, no comments that narrate a session's process. No claim in a
doc, comment, or decision note that contradicts the code or another doc — when
you find a mismatch, verify against the live system and fix the wrong one
rather than making the text self-consistent. The repo must read as good first
decisions, not as a record of fixing earlier bad ones: the decision lives in
the code and CLAUDE.md, the story of how it changed lives in `docs/decisions/`.

## Tooling conventions

Default model for routine work: **Sonnet 5**. Switch to **Opus 5** for hard reasoning (coordinate-frame conversions, perception-pipeline architecture, anything where a wrong answer propagates). Haiku 4.5 is not in use yet. The escalation rule is the durable part; the names are bindings — update them together with `.claude/WORKFLOW.md` when the model family moves.

Default tool for code work: **Claude Code**. Default for strategy / architecture decisions: **Claude Chat**. See `.claude/WORKFLOW.md` for the full rubric and prompt templates.

**A whole thread — a quality push, an investigation, a migration — is briefed as a CHARTER, not a task list**, per `.claude/WORKFLOW.md`. Its five parts exist because a task-scoped brief produces a session that stops at the first adjacent defect: an outcome with a self-checkable acceptance test, autonomy grants stated POSITIVELY (the part most briefs omit, and the reason sessions stall), named stopping conditions, the batched-judgment protocol when the acceptance test is the operator's eyes, and a scope boundary that is not a file list. A charter loosens scope, never rigour.

**A lane that walks the room page will 404 on `dev-fixtures`** — it is deliberately absent from worktrees (3.9 GB). The cheap fix is `tools/make_synthetic_splat.py` (~14 MB of synthetic rooms, no real capture), and the rule is DELETE THEM AFTERWARDS so nothing real or bulky can reach a build. **Cheaper still, and free, for any lane that draws GEOMETRY rather than splats: `/room?bundle=!hero` serves `web/public/hero/room.json` — the one genuinely captured room this repo ships (0122's fixture, 3.5 KB, already a tracked static file) — and `!v3`, `!old` and the six list rooms need no fixtures at all.** Nothing to generate and nothing to delete; the splat viewer 404s and everything shell-shaped renders. The calling-card lane built its whole surface this way and never staged a fixture.

**The coordinator rotates itself before it degrades, and does not wait to be
told.** A coordinator accumulates every lane's context and is the one session
nobody re-provisions, so it is the most likely place in this project for a
stale premise to survive — which is not hypothetical: on 2026-08-19 a sitting
session was handed a brief whose decision-number block collided with a note
already on disk, whose "report does not exist" claim was false, and whose repo
state had moved twice while the session ran. Each cost real time to discover.

So: when the context is getting heavy, spin up a successor **proactively**
rather than pushing through, and treat the rotation as ordinary hygiene rather
than an admission. The successor's prompt carries only what is NOT durable —
live repo state, which lanes are in flight and where, and the immediate next
action. Everything else it should read from CLAUDE.md and `docs/decisions/`,
because a prompt is written once and those are maintained. Three checks the
outgoing coordinator owes its successor, all cheap and all learned the hard
way: confirm the free decision numbers from `git ls-tree main --name-only
docs/decisions/` rather than the ledger in this file — and not from a bare
`ls`, which reads a working tree that may be behind main — state the actual
branch and HEAD rather than a
remembered one, and name any claim in the handoff that has not been verified
this hour.

**Starting a session is the orchestrator's job to make one paste long.** Whenever
new work should run in its own session, the coordinator delivers a
copy-pasteable prompt AND does the pre-session setup first — provision the
worktree, symlink `web/public/dev-fixtures` from the main tree, run
`npm install` in `web/`, copy the gitignored `GoogleService-Info.plist` for iOS
lanes — so the session's first act is work, not environment repair. Setup traps
that are already known: `outputs/room-quality/stage_fixed_fixtures.py` writes to
an ABSOLUTE main-tree path, so a worktree lane stages fixtures outside itself;
a worktree has no `.venv`, so Python runs via the main tree's absolute
interpreter path (verified to still import the worktree's own modules, not
main's); and **only symlink `dev-fixtures` into a lane that actually views
rooms.** That directory is **3.9 GB of real captured homes**, `next build`
copies `public/` into `out/`, and any lane whose acceptance includes a green
static-export build should not have it present — the deploy is protected by
`firebase.json`'s `dev-fixtures/**` ignore, but the build is not, and 0122
already caught a real room's splat one deploy from a public origin.

**A session's ready report goes to `outputs/reports/<lane>.md`** — gitignored,
like every other artifact under `outputs/` (walk verdicts, operator-queue logs,
adjudication output). Not pasted into a conversation, where it dies with the
session, and not committed, which would put process chatter into history.

**The report is transport; the finding is content.** Any finding another
session needs — a cross-lane handback, a convention correction, a measured
fact that changes someone else's assumptions — must be written to its DURABLE
home by the session that found it: a decision note, or CLAUDE.md. Never left
sitting in a report for a coordinator to relay. Decision 0130's handback was
written down, was correct, and still never reached the session it was for,
because a human bus was the only path between them.

## Git conventions

This repo is tracked with git. The remote is `origin` =
github.com/feynma1h/roomstudio (private), and `main` tracks `origin/main`. The
one branch deliberately not pushed is `diag-bundlepb-reason-public`.

**Claude Code's role with git:**

- Commit as part of normal work. One commit per logical unit (a feature, a fix, a refactor — not "end of session"). If a session produces multiple distinct changes, that's multiple commits.
- Write descriptive commit messages: what changed and why, not just what. Subject line under 72 chars; add a body if the why isn't obvious from the subject.
- Run `git status` and `git diff` before committing, and surface anything unexpected (e.g. a file changed that wasn't part of the task). Don't `git add -A` blindly.
- Run the relevant test suite after every code change. Show the full test output before proposing a commit. "Relevant" means: tests for the package or service that changed, plus any tests for packages that depend on it. If unsure which tests are relevant, run them all. Never commit untested code. If tests fail, fix and rerun until green; do not commit red, do not commit "mostly green," do not commit with an explanation of why a failure is fine. If a test is genuinely wrong, fix the test in the same commit and explain in the message.
- Do NOT put AI attribution in a commit. No `Co-Authored-By` trailer, no generator footer, no tool name in the subject or body. The history is part of the product surface, and it is pushed. Write in the project's voice, as the author.
- Do NOT push to remotes. The user pushes manually after reviewing.
- Do NOT rewrite history (`git rebase`, `git commit --amend` on already-committed work, `git reset --hard` on commits you didn't make this session) without asking.
- Do NOT delete branches or force-anything.

**Session-end housekeeping commits:** the CLAUDE.md updates and any decision-note additions from session-end housekeeping should land in their own commit, separate from the code changes that prompted them. Message convention: `docs: session housekeeping — <one-line summary of what changed>`.

**What's gitignored:** see `.gitignore`. Notably: `outputs/`, virtualenvs, `.env`, `.claude/cache/` and `.claude/projects/` (Code's session state). Note that `CLAUDE.md`, `.claude/WORKFLOW.md`, and everything under `docs/decisions/` ARE tracked — they're project documentation, not local state.

## When to write a decision note

`docs/decisions/` holds the *why* behind decisions that aren't obvious from the code. One file per decision, filename `NNNN-short-slug.md` (zero-padded). Template at `docs/decisions/0000-template.md`.

The criteria for "is this worth a note?" live in the session-end housekeeping section below.

## Next on the board


**READ THIS FIRST. The numbering below is historical and cross-referenced throughout this file; it is not priority order.** As of 2026-08-13 the operator's queue is DONE except external paper (see the queue paragraph below) — the next build session is unblocked on everything it was waiting for: the clip sign is ruled, the walk verdicts are in, the social layer is ruled a commitment, and perception's live gate closed on a real scan. Item **8** — the render-payload P0 — outranks everything else for BUILD, App Store collateral included: people cannot see their rooms yet. Item **9** — conversational redesign — is the product's own definition and runs in PARALLEL as a design session, because design costs no code and touches none of item 8's files. Item **10** holds the backlog an audit of all 103 re-open triggers turned up — fired conditions nothing was scheduling — and it carries one operator RULING that must not be allowed to drift the way item 9 did: **is the social layer a commitment or a direction?** Items 9 and 10 are the standing proof that this section decays in a particular way: nothing was decided about them, they simply stopped being scheduled and became sub-clauses. **When this section gets stale, the project's drifting — and drift here looks like a core feature quietly turning into someone else's dependent clause. Keep it current.**

**ALL FOUR 2026-08-10 LANES MERGED, plus the 0108 mock-string chip; every worktree removed and every branch deleted. As of 2026-08-13 the repo is ONE clean tree at `main`, in sync with origin, with NO sessions in flight.** | lane | worktree · branch | decisions | scope | |---|---|---|---| | clip A/B | REPORTED + MERGED 2026-08-10 (0112; 0113 unused) | done | walk DONE 2026-08-12: measured won, flip shipped (`3755bad`) and deployed to production. | | api-public polish | REPORTED + MERGED + DEPLOYED 2026-08-10 (`api-public-00036-duv`; 0114/0115 later consumed by the phone session) | done | outcomes in 0107/0108/0124. | | iOS Google linking | REPORTED + MERGED 2026-08-10 (0118/0119; suite 535) | done | phone leg + web copy retirement remain — see the What-works bullet and the operator queue. | | ops | REPORTED + MERGED 2026-08-10 (0120; 0121 unused) | done | perception-obj platform-gated, tombstone swept, build cache seeded — all live-verified. | **Held deliberately:** per-room deletion (collides with the api-public lane; product-shaped), 0062 frame coverage (GPU-cost-entangled; the item-7 walk and the next real scan reshape it), the social-layer ruling (operator's). The two lane-B notes are written (0142 `/compress` as a stage, 0143 `extent_axes_m` as a declaration). **THE OPERATOR QUEUE — EXECUTED 2026-08-12/13 (all five steps; session record in gitignored `outputs/operator-queue-2026-08-12.md`).** Closed: the clip-sign walk (measured wins, shipped, deployed to production), the item-7 second walk, the reveal's two questions, the social-layer ruling, and the whole phone session — real scan (perception's live gate), the disruption capture (0114), the identity switch and the reclaim leaf (0115). **WHAT REMAINS ON THE OPERATOR — one short sitting, then paper:** (0) **the clipped-views sitting, the only one pending — SUPERSEDED 2026-08-20, see the clipped-views entry below; the walk pack remains at gitignored `outputs/clipped-views/walk/README.md` (decisions 0197/0198). rp6g1's table is a floating slab today and a table with four legs in a reconstruction that is *already in the bucket*; rp7's desk goes the other way — and the 0198 bench then fixed rp7's desk too, by refining its mask (the pack's bench section shows it). Nothing ships until they answer, and the change it gates computes nothing new. Then: (1) **Apple Developer enrollment is STUCK, not merely pending** — filed 2026-07-22, still unapproved three weeks on against a typical <48 h; worth contacting Apple Developer Support or checking for an unseen identity-verification hold, because it gates Gate A, APNs, TestFlight, submission AND the 7-day re-sign treadmill — and per 0115 it may also be gating a defect that destroys user identity on every device build. (2) App Store collateral: the **app icon is DONE** (`8bf01d4`, decision 0176 — three iOS 18 appearances, device-verified at 60/40/29pt; the site's favicon now cuts from the same geometry, `6af4661`); still **nothing started** on screenshots, support URL, age rating, privacy nutrition labels (which must name the material-inference vision call per 0089). (3) The Indian lawyer on Terms §9–§11: **not engaged**. (4) The 0115 churn investigation — no longer an operator item at all: its decisive first step ran and killed the entitlements/access-group hypothesis (0138), and the leads that remain are source-level rather than device-level. Parked with named triggers, NO action unless one fires: the material re-bake (0070 wants reference-room re-adjudication first), the second unrestricted Firebase browser key. **Re-sign clock: 2026-08-19 07:15 UTC.** **The clipped-views lane RAN 2026-08-20 and is MERGED (0197/0198).** Probe 1 answered the charter's narrow question with a split — one legless table fixed outright by a view already in the bucket, the other made worse by its own — so the sort key was refused. Three operator-directed GPU bench rounds followed, all on 0%-traffic candidates with predictions registered first; **all three named objects are now fixed by changing what SAM 3D is shown**, and the lever is the MASK, not the crop (0198). Production served `00044-m5p` throughout and all bench state is deleted and verified. **The sitting is superseded**: the operator blessed the spike f142 table live ("much better"), walked the rp7 desk after catching two defects, and holds the chair A/B — no formal A-or-B verdicts were recorded and none are owed. What it leaves is the `object-aware-sampling` lane, whose bottleneck it named: the sampler is object-blind and the chair's good view was never sampled at all. **The ROOM QUALITY session RAN (2026-08-13, decisions 0146–0156); its walk RAN, its two resulting corrections are in, and it is MERGED to `main` and SERVING as `perception-obj-00043-yiz`.** Three defects are closed and committed — contact tilt, the phantom support surface (rp7's monitor was resting on the chair tucked under its desk), and the label fork that split one monitor into two objects — see the What-works bullet for the measurements and the What-does-NOT-work pair for what was refuted. **The walk RAN, the branch is MERGED, and lane C has now SHIPPED it — `perception-obj-00043-yiz`, all four rooms re-driven on it, live reproducing offline at the float64 limit (0163/0164).** **THE THREE BANKED SITTINGS RAN 2026-08-19 and all three are answered** (`outputs/sittings/verdicts.md`; decisions 0177/0178/0183): the facing sign stays OFF and keeps collecting, the seating anchor was no-change-pending-lane-D, which 0166 has now closed without delivering legs, so 0177's question needs a new trigger, and the guest-voice pair became one scheduled charter revision. **Lane D RAN 2026-08-19 and reported a negative (0165/0166) — see the What-does-NOT-work bullet; nothing substantive is unblocked on this board now.** The lane-C pack is at gitignored `outputs/lane-c-walk/WALK.md`, built from LIVE manifests, and carries exactly ONE decision that is genuinely theirs — which face of its measured box an under-filling splat is seated against (0148) — now with the third option built as a `-vfill` viewer variant so the narrow form can be judged rather than imagined. **Two things the session settled that change what comes next.** The capture-side half of the brief is answered NEGATIVE and with numbers: the capture already contains 22–156 good views of every piece of furniture, the pipeline uses one or two, and supply does not predict quality (r = +0.018 across a 40× range) — so per-object capture-sufficiency feedback is NOT built (0150), and the deliberate re-scan is worth running as a TEST of that prediction rather than as an expected improvement. View selection is refuted across seven features and two instruments (0146). **The one line of attack left on class-6 was probed and priced (0151), and has since been MEASURED and refused (0166):** two reconstructions of one object do not already align (centres 0.11–0.78 m apart, frames 10–52°, RMS 0.07–0.42 m), trimmed ICP appears to close all of it, and the scale-drift + mutual-coverage check says it honestly closes 2 of 6 — the bed pairs inflate one cloud 70–90% and end at 5–22% mutual coverage. **RMS is not the acceptance criterion here**, and the next session to reach for this will otherwise reach for it. Worth knowing why it matters: a union of registered reconstructions has honest proportions, and 0081's finding is that extent consistency is misleading *under truncation* — so this is the only route that could reach the rotation ceiling without re-running an instrument already measured dead. **HANDED OFF 2026-08-13 as four lanes — prompts at gitignored `outputs/handoffs/room-quality-next.md`, decision blocks assigned per lane inside it.** A = the facings, scoped as a PRODUCT decision (0133's descoped conversational rotation) rather than a sixth instrument, since five families are now refuted — **DONE 2026-08-13 (0157/0158/0159), MERGED, and SHIPPED 2026-08-14 by the ship-facings lane (0172/0173) — evals green live at PROMPT_VERSION 4, serving as `api-public-00038-qiv`**; B = the selection experiment — **DONE 2026-08-14 (0160/0161/0162), the GPU spent (~17.5 min, two rounds on rp6g1), env reverted and the room restored byte-identically; NOT merged.** Answer is NEGATIVE: a 1.7× sharper view seeing 2.1× more surface reconstructed WORSE, so no selection score was built even behind a flag — see the three What-does-NOT-work bullets. **What D inherits from it:** the budget lever does not widen D's baseline (36.2° vs 35.5°, max 82.5 vs 88.3 — a wider baseline needs different frames, not more views per box), and D's case is strengthened from the other side by 0161's fidelity 0.777 — added surface does survive into the object, so a union has headroom that single-view selection does not; C = deploy — **DONE 2026-08-13**, serving, re-driven, fixtures re-staged, pack built; D = the multi-view union — **DONE 2026-08-19 (0165/0166), NOT built.** An oracle registration against measured truth adds nothing to the union's marginal value (+0.057 vs +0.063 with no registration at all), so registration was never the constraint; a second reconstruction adds +0.06 coverage while adding off-surface mass, 1.76x the points, and — in all three rendered cases including the best by the metric — a visibly doubled object. It also closed the de-occlusion gate as a negative; **E = the facing-sign probe — DONE 2026-08-14 (0170/0171), MERGED, not deployed.** The sign WAS unmeasured rather than unmeasurable: the layout rotation reads it, bimodally, and gets both of the operator's reported failures right and a third object wrong. It ships flag-only; what it owes is one operator sitting (`outputs/lane-e/WALK.md`) and, if they say yes, an env-only `PLACEMENT_FACING_SIGN_APPLY=1` on the next perception deploy. **It also corrects the premise this lane was launched on:** 0169's room-geometry table cannot grade a sign instrument at all. RoomPlan's box local **+Z is the object's front** — 23 of 25 wall-backed boxes across the four rooms present −Z to the wall, p ≈ 1e-5, the two exceptions being chairs at desks whose +Z faces the desk — so every box carries a measured facing DIRECTION; but a direction is not a label, because deciding whether a rotation is right needs the splat-local direction of the splat's own front and the room has no opinion about that. The table grew from 12 rows to 21 and from 5 labels to 5 labels (0170). The session's offline harness lives at gitignored `outputs/room-quality/` — `roomlib.py` is a replica of the production `RefinementContext` over all four preserved captures, **trust-gated to reproduce every shipped view choice and box object exactly — and note what that gate does NOT cover: lane C found the replica handed fusion no room planes, silently killing the single-view contact-prior path and mispredicting three free objects (0163). Fixed; re-read any probe conclusion about free objects.** Plus 18 probes and the walk/fixture builders; read the report's last section before rebuilding any of it. **What remains, in order:** (a) the operator's sitting on the shipped rooms — the deploy is done; (b) **class-6 truncation itself, still untouched by anyone and now with NO live route** — every fix so far places or orients incomplete reconstructions better rather than completing them, and all three attacks on its cause are measured dead: better selection (0162), a measured pointmap (0181), and the multi-view union (0166). What remains is decision 0052's standing trigger — a model that consumes several views itself, or exposes calibrated metric scale or pose — which 0166 sharpens into the reason it is the right trigger: the disagreement between two views has to be resolved INSIDE a model, not downstream between two finished objects; (c) the object-blind residue — **attacked 2026-08-21 and BUILT OFF (0202), with the share corrected**: it is 75–83% of the budget on rp7 and rp6g1 but only 33–42% on spike and rp6g2, because cover picks track box count (3+9 and 2+10 against 7+5 and 8+4). Measured, the shipped residue IS the box-free answer on all four rooms. Spending it on boxes takes starved boxes 14 → 2 and usable views 48 → 60 with no extra frames. 0203's objection — that it buys arms nothing chooses between — is CLOSED by the selection lane (0204/0205, MERGED-pending): the chooser is built, off, and byte-identical off, and both flags now wait on the same operator sitting at gitignored `outputs/selection/walk/WALK.md`.

**ALL THREE PARALLEL LANES MERGED 2026-08-09** (`stage2` → 0135–0137, `perception-emit`, `ios-residue`; worktrees removed, branches deleted). Merged-tree verification: root **724 passed + 10 skipped**, perception **704**, web **204**, iOS **523**, tsc clean, zero conflict markers. **What the lanes left owed, now written:** lane B's two notes are 0142 (`/compress` as a third `/process` stage rather than a sidecar) and 0143 (`extent_axes_m` declared per box, horizontals deliberately unnamed). The `dims` correction is lane C's **0137**, reached independently — there is no third note on it.

**Decision numbers.** **Always derive the free list from `git ls-tree main --name-only docs/decisions/`, not from this paragraph** — it has lagged five times. **And `git ls-tree main` ALONE IS NOT ENOUGH: union `main` with every UNMERGED branch.** Verified 2026-08-23 — `selection-supply` holds **0225–0235** unmerged, so `ls-tree main` reports all eleven free and would cost a collision the same day. Not a bare `ls`: that reads the WORKING TREE, and a lane worktree is routinely behind main. Reproduced 2026-08-21 — both live lane worktrees sat four commits back, where `ls` showed 0192 and 0193 as free while both were taken. `git ls-tree main` is correct from any worktree without syncing, and is the form to use. As of 2026-08-21, with the colour-deploy, what-the-model-sees and guest lanes merged: **free are 0083, 0092, 0093, 0113, 0121, 0128, 0134, 0144, 0145, 0167, 0168, 0186, 0189, 0194, 0195, 0196, 0236+** — **0083, 0092 and 0093 were never created and are cited nowhere**, and were absent from this list until 2026-08-21, which is the fourth lag and the first in that direction. **Reserved: 0215 plus 0219–0220 to the guest-closure lane, 0236 to selection-review, 0237–0238 to ios-surfaces-2, 0239 to upload-flake, 0240–0241 to capture-dark, 0242 to privacy-labels, and 0243–0244 to perception-deploy — seven blocks live at once. **0245 is SPENT by the name swap** — 0245 (the name is the register it was built in). guest-closure had NOT started** — those three are written nowhere, and were deliberately KEPT reserved rather than freed on 2026-08-23: the lane is provisioned, was unblocked that day, and one of its three items is a live deploy gate. Never free a block on the belief a lane finished — `git branch --merged` lists a branch with no commits of its own, which is exactly what `guest-closure` is. One block live at once, each also stated inside its own charter body, which is the half that actually reaches the session. **0199–0200 are SPENT by colour-deploy** — 0199 (the inline cache destroys itself by being used), 0200 (the tag must name what Cloud Run pins); **0201–0203 are SPENT by what-the-model-sees** — 0201 (the repair is judged by what it added), 0202 (the residue was never asked where anything is), 0203 (a second arm is not a better object); **0204–0205 are SPENT by selection** — 0204 (the arm that ships is chosen by looking at it), 0205 (fill sees one axis); **0210–0212 are SPENT by ship** — 0210 (a cold room is two deletions and an audience), 0211 (the flag was never in the image), 0212 (the three flags are one decision); **0206, 0218 and 0224 are SPENT by scenes-client** — 0206 (no rooms and could not ask), 0218 (the bridge was never waiting on the fetch), 0224 (a pinned action does not share a column); **0216–0217 are SPENT by ios-surfaces** — 0216 (a count that cannot exist), 0217 (the declaration is the stand-down); **0207–0209 are SPENT by social-layer** — 0207 (a layer is not a feed), 0208 (sharing cuts where the pipeline already cut), 0209 (comparison between people is evidence, not a surface); **0221–0223 are SPENT by calling-card** — 0221 (a room's eligibility is a date, not a field), 0222 (the card draws the boundary and prints the measurement), 0223 (the yaw is not a measurement); **0213–0214 are SPENT by the guest lane** — 0213 (two candidates refuse rather than pick), 0214 (the provenance line describes the room on screen). Spent by clipped-views: **0197** (the uncropped photograph is not a better photograph) and **0198** (the mask is the photograph SAM 3D sees). Spent by geom-retire: **0192** (perception-geom is retired). Spent by the brand-mark pass: **0193** (the mark is generated, not copied). **0225–0235 are SPENT by selection-supply**, unmerged at the time of writing — which is why the union method above exists. Everything else through 0224 is used.

Two durable lessons, both learned by collision. **Put a session's number block INSIDE the prompt body**: a block written in a chat heading once reached nobody and two lanes claimed the same numbers, and the room-quality session was handed one stale block in its prompt and a different one in its handoff. When a prompt and this file disagree, **this file and the handoff win** — a prompt is written once, these are maintained. And **two sessions sharing one tree is how a note gets dropped**: decision 0179 was lost by the sam3d-pointmap merge and restored by `546281e`, which is why the Tooling conventions now insist every session gets its own worktree.

**The lesson from running three at once, recorded because it nearly cost a collision:** the coordinator wrote each lane's decision block in a chat heading rather than inside the prompt text, so NO session received one and lane C reasonably took the next free numbers — which were lane A's. Only the fact that A and B had not yet written a note prevented a real clash. **Put the block inside the prompt body, every time.** Second lesson, same session: decision 0130's cross-lane handback never reached the session it was written for — the coordinator is the only relay, and re-derivation was luck.

**1 — Post-conventions placement thread: merge the fix branch, then ARKIT_ONLY position quality + LiDAR variant.** The 0063 convention probe CLOSED 2026-07-23 (decision 0065; see What-works): conventions fixed incl. the basis correction, deployed (`perception-obj-00028-hzq`, carries all branch code), production-verified (upright median 4.1°, sign tests pass, 12/12 frames, room visually corrected). Remaining on this thread: (a) DONE — `perception-layout-convention-fix` is merged (confirmed in `main`'s history 2026-07-23; every branch except the parked `diag-bundlepb-reason-public` is merged); (b) **ARKIT_ONLY placement quality — chunks A–C BUILT + merged 2026-07-23, now SERVING** (branch `placement-quality-build`, merge `3f26fcc`; probe verdicts in decision 0068): the code shipped with the 0069 shell deploy (`perception-obj-00032-km5`, 2026-07-24 — that revision built off main, so it carries chunks A–C too), the placement LIVE gate is now PARTIALLY MET: the whole `PLACEMENT_REFINE` pipeline (chunks A–D + the new room-sanity gate) was live-verified via a warm `/process` re-drive of `f3d70236` on `perception-obj-00033-zfg` (2026-07-24 — 24 objects / 7 placed, the gate demoted exactly the four operator failures; see What-works), so only the operator `/viewer` walk remains — and it is now DEFERRED under the board-item-7 Pro-only pivot (possibly moot). `PLACEMENT_REFINE=0` is the rollback lever. The re-opened in-plane instrument fork for near-square planar objects (0068) still stands (not a deploy blocker). **Chunk D (single-view contact priors) BUILT + merged 2026-07-24** (branch `placement-chunk-d`, commits `724b7a5`/`78e4d2e`; built onto the shared `room_planes.py` 0069 extracted — no anchor-interpretation duplication; offline-verified against `f3d70236`'s real planes, see What-works). Its live gate RAN 2026-07-24: the warm `/process` re-drive of `f3d70236` on `perception-obj-00033-zfg` placed 5 single-view objects on measured surfaces (chunk D) and the total placed count jumped ~2 → 7; only the operator `/viewer` walk confirming furniture-on-floor / wall-objects-on-walls remains, now DEFERRED under the board-item-7 pivot. **Sampling-starvation insight (operator-flagged 2026-07-24):** the thin walls + missing furniture in real outputs are pipeline-side, not capture-side — only 5 of `f3d70236`'s 184 frames completed with masks, and single-view objects can't triangulate; the cures are warm re-drives (complete more frames cheaply), `PERCEPTION_MAX_FRAMES` (placeholder=12), and chunk D's contact priors (place single-view objects from ONE view). VIO-calibrated monocular depth deferred with named re-open triggers; (c) **LiDAR variant of the placement event — parked on Pro hardware** (board item 3 runbook applies first); 0063's don't-trust warning lifted in principle, zero real executions; (d) opportunistic: coverage knobs stay one-capture-calibrated (17/22 single-frame objects can't triangulate — `PERCEPTION_MAX_FRAMES` is one lever; 0067 chunk D's contact priors are the complementary one). (Phase 8c soak: RUN AND GREEN 2026-07-22 pre-dating this session's deploy — the new revision `00027-n8c` has since served the full re-drive successfully, which is its own functional soak; the RUNBOOK 8c one-liner can re-run on the next quiet day if desired. The former ops decision — deleting the pre-split `api` Cloud Run service — was operator-approved and executed 2026-07-21; Cloud Run runs exactly api-internal + api-public + perception-obj — perception-geom was retired 2026-08-20, decision 0192.)

**2 — iOS P5 — OS-kill hardware gate** (decisions 0029, 0044, 0045). Core poll + status UI shipped (P5(a), commit `dbe3188`). Remaining: **OS-kill hardware gate (cluster close item):** stage on-device: all blobs uploaded, `bundle.pb` PUT enqueued while alive, force-quit, reopen — confirm `bundle.pb` reaches GCS with no user interaction (GCS-authoritative, verified from Mac during locked interval); also verify `.task` fires on background OS-relaunch. `diag-bundlepb-reason-public` (`dc552ab`) is the parked tool for reading the redacted `reason=`. AppDelegate fallback (decision 0045 Fork A) deferred pending this gate. After hardware gate: FCM `ready`/`failed` — backend threading is done (cleanup pass: Scene.fcm_token → ClaimResult → notifiers), so what remains is iOS-side FCM registration and passing the real `fcm_token` at `/upload_session`. Cold-start poll recovery is DONE (ios-upload-robustness, 2026-07-21): the cold-launch auth race is fixed (`ec57285`), simulator-verified. NOTE post-activation: the `SceneStatusView` scan that used to restart polling across launches is no longer in the app — `ContentView` is unreferenced, so that recovery now lives in `RootFlowView.restoreUnfinishedBundle` + `BundleRestore` (decision 0073). The three status-surface honesty findings are CLOSED (branch `ios-status-surface`, 2026-07-21) — no open follow-up on this surface. **Separately, the iOS app DESIGN is built AND ACTIVATED as the app root** (decisions 0072/0073 — the Good Guest capture app: `DesignSystem/` foundation + every screen + the `RootFlowView` navigation coordinator; nine review passes; 288 tests). **The capture-to-doorway walk RAN 2026-07-26 on the 16 Pro — PASS** (two real captures; upload-under-lock, 26897de catch-up, background trip, relaunch restore, doorway exits all green — see What-works). Remaining on this surface, in order: the OS-kill hardware gate + the three terminal-failure UI screens — both staged as of 2026-08-07 behind DEBUG `StagingHooks`; the sitting ran and its verdicts, including the 0045 Fork A decision table, are decision 0085; the 0074 HARDWARE VERIFY is DONE (RP-6 Gate 4, 2026-08-05). Then the Live Activity's hardware verification (task #14 BUILT 2026-08-08, simulator-only — folds into the same sitting; task #13 shipped as RP-7) — then the remaining activation follow-ups in `RootFlowView`'s docstring (add-more resume, web-handoff link). Terminal-failure UI (`failed`/`failed_invalid`/`failed_incomplete`, blob-failure banner) has still never rendered on hardware — exercise opportunistically when a real failure occurs or stage one deliberately.

**3 — LiDAR-tier hardware verification: DONE 2026-07-26** (item number kept — it is cross-referenced throughout this file). The `[LIDAR-UNVERIFIED]` set ran green twice on the iPhone 16 Pro: LIDAR_ARKIT tier dispatch, `captureDepth()`/`sceneDepth`, one depth blob per frame at 256×192 exact bytes, decision-0032 depth intrinsics, and — the raised-stakes half — decision 0052's `depth_fit` consuming real rasters in production (16/23 placed on capture #1). Decision 0033's residual is closed. The **RoomPlan co-run spike is DONE** (2026-07-28, decision 0076 — see What-works; the `sceneDepth`-strip caveat is refuted, the ARFrame-retention issue is quantified at 10 frames = pipeline death, and the co-run architecture is proven clean). Item 3 is fully closed. The **LIDAR_ROOMPLAN tier** itself remains unbuilt — its shape comes out of the board-7 design session, which now has every input.

**4 — Launch-hardening pass: EXECUTED 2026-08-07 (decisions 0086/0087/0088).** All
nine 0015/0018 gaps closed or dispositioned + the audit run — see the What-works
bullet and the "Pre-launch gaps" residue bullet in What-does-NOT-work. Residue on
this thread, in order: (a) operator decision on the flagged `firebase-adminsdk-fbsvc`
tokenCreator grant (0088 recommends revoke + re-grant-per-walk; commands in the
note); (b) delete the stale pre-split `api-runtime@` SA + its captures binding
(operator one-liner, 0088); (c) DONE 2026-08-08 — both perception-cycle
follow-ups shipped on `perception-obj-00036-l9l` (`release_failed` expire_at
stamping per 0086; the dedicated `perception-obj-runtime` SA per 0088/0090);
(d) iOS 429 Retry-After branch (0038's reserved follow-up) — BUILT in the
Live Activity pass and covering BOTH 429 codes, `rate_limited` and 0098's
`capture_limit_reached`, but it is not on the phone (device install blocked —
see the Xcode-account bullet). The abuse-surface gate for the first
non-developer user is now CLOSED server-side, and the person-observation
privacy gap (0070) is CLOSED in the pipeline by decision 0089 — what remains
on that trigger is re-driving existing scenes so they actually gain
suppression (cached frames keep pre-0089 masks) and the complementary
capture-time guidance, whose capture-side copy shipped with the Live Activity
pass.

**5 — DONE 2026-08-08: the purge ran and the repo has a remote.** `git filter-repo` removed the nine HEIC blobs (verified: zero HEIC objects in history, no commits touching them), `tools/remap_doc_shas.py` remapped the doc SHA citations, and `origin` is `github.com/feynma1h/roomstudio` (private). The slot is kept numbered because it is cross-referenced elsewhere in this file; nothing remains on it. `diag-bundlepb-reason-public` stays deliberately local-only.

**6 — Web app: next increment** (decisions 0050, 0052–0057; Good Guest rehaul
live on branch `web-app`, verified against fixtures)

In rough order once board item 1's deploy lands: (a) DONE 2026-07-22 —
standing preview channel live (see What-works; per-PR channel automation
is an optional later add); (b) **Gate B PASSED 2026-08-08** (see What-works) —
0051 BUILT on both sides, 0094 added Google, and the web half is now
live-verified against the operator's real rooms. Remaining on this thread:
enrollment-gated **Gate A** (on-device Apple link, UID unchanged), which is
the iOS half and still waits on Developer Program enrollment; (c) first real assembled room in the PRODUCT
viewer — the dev-workbench half landed 2026-07-21 (scene `25a14caf`
renders at `/viewer` from the staged real-scene fixture in gitignored
`web/public/dev-fixtures/`); the `/room` product flow still needs (b),
and richer scenes need the 0063 convention fix + a warm re-drive for
coverage;
(d) **conversation fast-follows** (stage 1 SHIPPED 2026-07-21, decisions
0058/0059, revision `api-public-00012-ziz`): per-object extents into the
manifest (v2.x, after board item 1's verification event) → unlocks gap/
clearance speech with a `facts_version` bump; a real-browser watch of the
reveal AND the streaming composer at real speed (the dev preview pane
throttles both); tune the client wake cadences against real usage;
(e) interactive surface — per-object selection, the reactive scene, the Design
Specification contract, and conversation stage 2 (mutation) are now **board item
9**, with the dependency chain and the two verify-first probes written out. They
were a dependent clause here and drifted; do not re-bury them under 6;
(f) **room shell — 0066 geometry + 0069
parametric surfaces both SHIPPED and V3-walked** (2026-07-23/24; decisions
0066/0069/0070; see What-works for the full deploy + V3 chain). Remaining
on this surface: nothing — the reveal choreography redesign the RP-8 watch
asked for (0080) is BUILT (decision 0097), pending only the operator's
walk. The person-observation privacy gap is board 4's,
sharpened — 0069 removed baked person pixels but a person can still
contaminate a plane's measured albedo and reach the material-inference
evidence crops (decision 0070; see the privacy bullet).

**7 — RoomPlan tier: the 0085 walk's fixable classes are BUILT; a SECOND operator walk is the open gate.** The consolidated walk RAN (2026-08-08, verdicts in gitignored `outputs/consolidated-walk/verdicts.md`, decision 0085) and its ranked classes were attacked in decision 0104 — see the What-works bullet for what shipped and, just as important, for the four measured refutations that close the rotation thread for now. **THE SECOND WALK RAN 2026-08-12** (verdicts in gitignored `outputs/item7-walk-2026-08-12/verdicts.md`) — every 0104 mechanism confirmed landed, and the reveal's two questions closed positive. **What it leaves, ranked by the operator's own eyes:** (a) **the contact-TILT class, NEW and the top item** — four objects across two rooms (spike speaker, rp7 lamp, rp6g1 lamp, rp6g1 monitor) now sit at the right height but touch at a single point, tilted, because the 0104 support snap is height-only and the splat's residual rotation tilts the body; this is the same rotation ceiling wearing a contact costume, so it is NOT a fifth attack on the rotation DOF but a question about whether contact should level an object it cannot orient; (b) **class-6 truncation in two fresh costumes** — rp7's monitor renders far smaller than the real object, and rp6g1's monitor has NO generated base, so it cannot visually rest on any surface at any height (a floating monitor whose position is correct); (c) rp7's monitor still hovers; (d) the window's in-plane skew, class 5 (re-scoped, see the residue bullet), and `b667f891`'s starvation, all unchanged. **Still NOT to be re-reported as new:** rp7's bed facing and the fronts-to-wall 180° signs — three instrument families are measured dead on that DOF (0104). **Operator product suggestions from this walk — promoted 2026-08-13 to the room-quality session's two starting defects, and both ANSWERED NEGATIVE by it (decisions 0146/0150; mechanisms as stated in `docs/briefs/next-work-directions.md` §1a, whose reading of the code was correct and whose implied fix was not):** per-object *cleanest-frame* selection for SAM 3D ("if we use some frame that doesn't really capture the object, we can't expect the render to look how it actually looks" — adjacent to RP-5's census box-best-view scoring but aimed at reconstruction quality rather than coverage, and pointed straight at class-6), and capture-time per-object sufficiency feedback (touches §3, where RP-7's floor plan deliberately replaced any camera preview — re-opening that is a design argument to make explicitly, and the floor plan may host the same signal). Both were first recorded as "design inputs" in **0075 (2026-07-28)** as live capture-coverage feedback and object-aware frame selection, restated after this walk, and acted on only now — the clearest instance of the drift the outcome-scoping reframe exists to stop. Standing: the `facts_version`-gated scene_facts consumption of box extents. **Re-sign clock now 2026-08-19 07:15 UTC.**

**8 — DONE 2026-08-09/10: the four-surface deploy executed** (revisions in the What-works deploy bullet; the build-gate failure and fix in 0109). The slot keeps its number — it is cross-referenced throughout this file. **Follow-ons, each small and named:** (a) the operator's two-minute production browser leg + the HAR + the white-screen wording (the only legs nobody else can run — see the P0 bullet); (b) CLOSED 2026-08-10 — 0124's filter shipped on `api-public-00036-duv` (22 → 10, A/B-confirmed); (c) CLOSED 2026-08-10 — perception-obj platform-gated (unauth probes can no longer boot the L4) and the tombstone swept; (d) CLOSED 2026-08-10 — layer cache landed and seeded (0120; speedup measured on the next real build); (e) CLOSED 2026-08-10 — 0108 wording + 0107 eval reshape shipped and live-verified (see the stage-2 bullet). **Perception's live gate = the operator's next real scan**, chosen on cost: it proves `extent_axes_m` and the `/process`→`/compress` enqueue end-to-end free. **Re-driving a preserved capture instead costs the GPU but no longer costs a tokenCreator re-grant** — 0164 replaced the mint path with a plain rsync, and 0210 writes down the rest of the cold-room procedure, which the ship lane then executed.

**9 — Conversational redesign (stage 2): MERGED and DEPLOYED — serving since `api-public-00034-zad`, with the language residue closed on `00036-duv`; see the four-surface deploy and stage-2 bullets.** Decisions 0129–0133 executed; 0135/0136/0137 record what building it measured. See the What-works bullet for the whole shape. **What remains, in order:** (a) CLOSED — the v3 evals ran at the four-surface deploy (0107's outcome) and the v4 ones at the facing ship (0172); both green live, both after revising the suite. (b) CLOSED — real turns with the real model have run at every deploy since, `propose` and `turn` included. (c) CLOSED — deployed; the `arrangement` SSE event and both spec routes are live and were exercised end to end on 2026-08-14. (d) **The operator's eyes**, which are the standard (0080/0085): whether a proposed move reads as a proposal rather than as the room being wrong, and whether the contour footprint reads as measurement — 0129 answered the first question with my eyes on nine objects in two already-walked rooms and explicitly flagged that as thin. (e) `0135`'s clip-yaw A/B, which is small, possibly a real quality win on every room, and deliberately left as an operator call. (f) CLOSED 2026-08-14 — rule 10's conditional grammar works with an arrangement in place, and the pin now covers the arrangement block too (0174/0175; see the What-works bullet). The residue it leaves is one composed-case sample in seven, in What-does-NOT-work; the `scene_facts` provenance line is CLOSED (0214). **Deliberately NOT built, each with its trigger:** free rotation in proposals — the trigger 0133 wrote (splat axis resolution) will not fire, and the one that did is that five instrument families are dead, so rotation returned on `lane-a-facings` as a facing CORRECTION rather than a proposal: one half turn, no angle, no direction (0157/0158/0159). Also out: per-object selection and R3F (0133: not prerequisites), the catalog, DAG versioning, and the ledger with its vocabulary ban.

**10 — The fired-trigger backlog: things nobody decided to defer.** Produced by a 2026-08-09 audit of all 103 re-open triggers in `docs/decisions/`, the founding vision's durable list, and the briefs — prompted by item 9, which drifted the same way. **The audit's own method is the point: a trigger whose condition has fired but which nothing schedules is indistinguishable from an oversight.** Two candidates were already closed by the design session before this was written (0133 keeps the ledger deferred WITH its vocabulary ban as a deliberate recorded choice; 0131 carries the reasoning trace 0055 lists as durable) — those are resolved, not pending.

**(a) Fired triggers, nothing scheduled.** **The `i_up` item is CLOSED end to end** — perception declared the up axis as `extent_axes_m` (0143), and the guest now speaks a measured height and footprint from it (0178/0184, branch `guest-voice`). What that chain leaves for whoever wants it: 0133's furniture catalog, whose named re-open trigger this was. Then: frame coverage (0062 — the trigger says real rooms under-covering at 12 frames means raise the default or make it adaptive; `b667f891`'s 53-item tail and 17-of-22 `insufficient_observations` ARE that evidence, and the board currently only calls the knobs "one-capture-calibrated", which reads as posture rather than a fired trigger); the re-mint fatal (0049 item 1 — `force_remint` is serving, so convert `remint_returned_stale_uris` from fatal into ONE forced re-mint; this is SMALLER and SEPARATE from the `.recoverable` coordinator that is already tracked, and easy to assume is covered by it); and 0088's own instruction to record finding 4's outcome in the note — **CLOSED 2026-08-09**: both of that note's fired triggers are now written back into it (finding 4 revoked; remediation 1 shipped as 0090), each verified live rather than restated — the SA has zero bindings and perception-obj runs as `perception-obj-runtime@`.

**(b) RULED 2026-08-12 a COMMITMENT; DESIGNED 2026-08-21 at `docs/product/social-layer.md` (0207/0208/0209).** The layer is defined, and rung 0 of it is built — see the end of this paragraph. What it settles: a feed is where rooms arrive UNASKED, so the draft's feed cut and the commitment ruling never collided — the test is whether a stranger's room can reach someone who did not ask for it, and it is held architecturally because no such route exists (0207). Sharing is a four-rung ladder — card / shell / shell+inventory / splats — cut on the seam the pipeline already has, generalising the cut 0122 made for the landing hero at 3,557 bytes against ~460 MB (0208). Comparison between two people is REFUSED as a surface and designed as an aggregate input to reasoning: every axis the product can measure proxies income more than taste, and a comparison view contradicts the landing copy (0209). Evolution over time is a user-asserted lineage of captures diffed on measurement, which needs no DAG. **The first increment — a generated card, not a hosted link — is BUILT on branch `calling-card` and undeployed** (see the What-works bullet; decisions 0221/0222/0223). It needed no new trust boundary, no new route, no new storage, no licence amendment and no moderation surface, exactly as designed. The 0089 eligibility rule is NOT checkable from a room's own data (no suppression provenance on the manifest — 0122 settled the hero by hand), and the fork was resolved to the **conservative `created_at` gate** on a fact that inverts the obvious: on day one the exact fix refuses strictly MORE rooms than the conservative one, because absence of a field is not proof and no existing room carries it (0221). **What remains on this increment is the operator's eyes and the name** — an eight-item batched-judgment list is at gitignored `outputs/reports/calling-card.md` with renders beside it at `outputs/calling-card/`, and every user-visible string sits in one `COPY` block in `CallingCardSheet.tsx`. Six rulings are the operator's and are listed in §10 of the doc; none of them blocks a build charter for the card. The spatial relationship graph is NOT part of this layer — it is item 9's substrate, which is where 0056 put it.

**(c) Seams built and left empty.** `RSSound.swift` is wired at three call sites with a documented three-cue design and says plainly "the cue files are not yet in the bundle" — the app is silent, and 0055 lists sound as first-class durable. The web has no sound at all, and the founding reveal opens on ambient room tone. Branded fonts (already in the iOS residue) and the product name are the same class: a one-file swap waiting on an asset or a decision.

**(d) Not recorded, which is its own risk.** **Alerting and monitoring appear ZERO times in this file.** The deferral may well be accepted, but that acceptance is not written down anywhere, and an unrecorded accepted deferral is indistinguishable from an oversight to the next session. 0048 named "the launch-hardening pass standing up alerting" as its trigger; that pass ran without it. Record the acceptance or schedule the work — either is fine, silence is not.

**(e) Product gaps found by looking, not by trigger.** No per-room deletion — account deletion is all-or-nothing, and for a product whose thesis is that rooms are identity that is conspicuous (0086 already anticipates it as the trigger for whole-scene GC). And iOS Google linking (0094): not technically fired, but live — the operator's own rooms are split across two identities right now, iOS links Apple ONLY, and Apple is enrollment-gated, so a Google-signed-in web user has no path to unify.

**Negative results from the same audit, recorded so nobody re-checks them:** 0122's hero-fixture swap has NOT fired — a warm re-drive does not re-segment, so `a7e073ae` still carries pre-0089 masks and stays ineligible (this was nearly recorded as fired). 0053's Spark-vs-WebGPU watch condition is measured NEGATIVE — 0123 profiled a real captured room and Spark is not the bottleneck (parse 0.55 s, under 1%). 0015/0018's gaps are closed, and 0073's hardware walk is done.


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
