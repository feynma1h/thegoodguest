# The Good Guest (GCP project id still `thegoodguest` — immutable)

**PARKED 2026-08-31 — read `docs/PARKED.md` first, then `docs/NOT-FINAL.md`,
which lists everything in this tree that is not finished and says which parts
of it go live on the next deploy.** The tree is one branch (`main`), one
worktree, and carries no room data: every capture, fixture and cloud scene was
deleted at parking. **`main` is pushed and `origin/main` matches it** — the
one-disk risk this line used to state was already false when it was written
(see `docs/PARKED.md`).

A spatial intelligence product that helps people discover the best version of their home: AI-powered room analysis, conversational redesign, and an immersive 3D representation of *their own* space.

This file is the always-current state of the project. Both Claude Code (reads it automatically) and Claude Chat (you upload it) consume it at the start of every session. If something in here is wrong, fix it before doing anything else.

## What we're building

**The thesis: every home contains a version of itself that its owner has never seen. This product makes that version visible, understandable, and achievable — one conversation at a time.** Every feature decision filters through this. The full founding vision lives at `docs/product/initial-idea-draft.md` (verbatim, with what's superseded vs durable mapped in decision 0055) — read it before making product-surface decisions.

This is NOT an "upload → generate a 3D scene" showcase. The 3D reconstruction is the *medium*; the product is helping people make AI-based decisions about improving their room. Three product layers frame everything: the **AI layer** (understands space structurally — object relationships, traffic flow, light, proportion — with algorithmic spatial analysis before any LLM is invoked, and reasoning traces on every design decision), the **emotional layer** (feels personal, not algorithmic — the experience bar is Linear/Vercel/Figma-tier premium consumer software; conversation is the primary post-reveal interface; the cinematic reveal is the defining moment; design language is Apple-grade restraint — the chrome stays quiet so the room carries the colour — in the warm Good Guest palette of 0057, which SUPERSEDES 0056's neutral-chrome-and-one-sans reading: the app ships parchment and ink with three type roles, the guest's serif for prose and mono for machine data only, and the **social layer** (rooms are identity — sharing, comparison, evolution over time). Direction, not yet commitments: room health scoring, taste graph, lighting simulation, budget-aware shopping, DAG version history. Deliberately out (per the founding draft, still sound): AR overlay, social feed, photorealistic image generation, floor plans, voice input; desktop-first.

**Naming: SETTLED 2026-08-23 as "The Good Guest" (0245)**, forced by the App Store listing when enrollment cleared. It is the register the whole product was built in (0072/0057) and the metaphor the calling card is already named from. Set as a STRING in three places — `web/src/components/Wordmark.tsx`'s `BRAND_NAME`, iOS `RSBrand.name`, and `INFOPLIST_KEY_CFBundleDisplayName` in `project.pbxproj`, which is what the Home Screen shows and which cannot read either constant (`tools/test_gen_mark.py` fails if they drift). **Until 2026-08-26 the Home Screen read "TheGoodGuest"** — the main target had no display name and fell through to `TARGET_NAME`, outside every "the name lives in N places" claim this file ever made. The card no longer prints the name at all: it carries the wordmark, which is a drawing. **The repo, GCP project, buckets and `thegoodguest:` localStorage keys deliberately keep the stand-in** — infrastructure, invisible, expensive to rename for no user-visible gain. **The card still prints `thegoodguest.web.app`, which is the TRUE hosting URL**: changing that string without moving hosting would print a falsehood on an artifact that leaves the browser. Re-open trigger is commerce, and renaming stays cheap until App Store submission — TestFlight needs only an app record.

Three technical surfaces today:

- **iOS capture app** (Swift + ARKit + RoomPlan) — capture-only, no viewer. The app's only job is producing a high-quality capture bundle and uploading it. Users come to the web for everything else.
- **Backend perception pipeline** (FastAPI on Cloud Run, `asia-southeast1`) — ingests bundles, runs SAM 3 segmentation + SAM 3D Objects reconstruction, places objects in the room's gravity-aligned metric frame using ARKit data (decision 0052), renders the room shell — walls/floor as textured quads from measured ARKit planes (decision 0066; BUILT, deploy pending). This is the modern substrate for the draft's perception + spatial-reasoning layers; the spatial relationship graph and design-generation layers above it are unbuilt.
- **Web app** (Next.js, static export + web splat rendering — WebGL2 via Spark, decision 0053 — hosted on Firebase Hosting) — the product surface: today rooms + viewer; next analysis, conversation, and redesign. Capture path is one screen: "Open the iOS app." Auth: same Firebase identity as iOS — requires upgrading iOS's anonymous auth to a real sign-in linked to the existing anonymous credential (see "Next on the board"); anonymous UIDs don't carry across devices.

Photo-upload (Android, no-iPhone users) is a deferred concern. Until the iOS path is solid we don't build the web-fallback capture.

## Capture bundle — the central contract

Everything between iOS and the backend flows through `packages/schemas/capture_bundle.proto`. The bundle is metadata; pixel data (frames, depth) lives in GCS by reference.

Frame of reference is **ARKit-native** end-to-end: right-handed, +Y up, camera looks down -Z in its local frame. The iOS client does NOT transform; the backend converts to downstream model frames (e.g. SAM 3D's per-object frame) when it has to.

Pose is **position + unit quaternion (x, y, z, w)**, not a 4×4 matrix. ARKit-native, ARCore-native, glTF-native. 7 floats instead of 16. The proto file's docstring carries the full reasoning.

Quaternion math is centralized in `packages/schemas/thegoodguest_schemas/pose_math.py`. Any Python that touches a Pose imports from there. Do not re-implement.

## Repo layout

```
packages/schemas/                 capture bundle proto + generated Python + pose/placement math
  capture_bundle.proto              source of truth
  thegoodguest_schemas/
    capture_bundle_pb2.py            generated; regen with ./tools/gen_proto.sh
    pose_math.py                     quaternion ops; one place to change
    placement_math.py                depth backprojection, single-view fits, ray triangulation
  tests/                              invariant tests for the proto, poses, and placement math

packages/api-core/                shared logic consumed by both API services
  thegoodguest_api_core/
    scene.py                         Scene model, SceneStatus, state machine
    scene_read_repo.py               SceneReadRepository ABC + Firestore/in-memory read-only impls
    upload_session_repo.py           UploadSessionRepository ABC + Firestore/in-memory impls + gcs_mint_resumable_uri
  tests/                              unit tests for the scene model, repos, and manifest validation

tools/                            local scripts (run from repo root)
  gen_proto.sh                      regenerate Python and Swift (ios/TheGoodGuest/TheGoodGuest/Generated/)
  gen_mark.py                       the identity's ONE source — regenerates the three app
                                      icons, favicon.ico, icon.svg, the mark geometry both
                                      platforms consume, and the wordmark (whose traced
                                      lettering is the input at tools/brand/)
  brand/wordmark-traced.json        the lettering, traced. SOURCE, not an output — artwork,
                                      so unlike the mark it cannot be regenerated from numbers
  build_test_bundle.py              synthesize a bundle from test_data/photos
  inspect_bundle.py                 verify a bundle parses + smoke-checks
  punchlist_check.py                re-derive docs/punchlist.md against the live system
  track_frames.py                   dispatch /track via Cloud Tasks (mirrors segment_frames.py)
  track_map.py                      the object->frame map, and the id-stability measurement
  track_views.py                    per-instance contact sheets (candidate_views.py for tracked ids)
  track_select.py                   each tracked object's best frame, over a real capture

services/
  api-public/                     client-facing API (--allow-unauthenticated, Firebase JWT verify)
  api-internal/                   internal API (--no-allow-unauthenticated, Cloud Run IAM)
  perception-obj/                 SAM 3 + SAM 3D Objects + placement/fusion (deployed pre-placement)
                                    plus SAM 3.1's video tracker behind /track — models/sam3_video.py
                                    and track_receiver.py (0274; BUILT, candidate-only, NOT flipped)
                                    and track_selection.py, per-object best-frame choice over the
                                    tracked segments (BUILT, no call site in the service yet)

web/                              Next.js static-export web app (decision 0050); Spark splat viewer
                                  contained in src/components/SplatViewer.tsx (decision 0053)

infra/                            Cloud Build configs, deploy scripts
docs/punchlist.md                 the remaining-work list — see "The punchlist" below
docs/decisions/                   short notes on dead-ends — see "When to write a decision note"
test_data/photos/                 9 synthetic rendered room views, for synthesis testing
outputs/                          gitignored; generated artifacts
```

## What cannot be remade

**Nothing, as of 2026-08-31 — and that is deliberate.** Every preserved capture,
every derived probe artifact, all 16 cloud scene directories and all 392
Firestore documents were deleted when the project was parked, because the next
session starts from fresh captures. `outputs/` now holds only 1.1 MB of written
judgment — the reports, handoffs and walk verdicts — which is the one thing in
there that was never room data.

What this costs, measured rather than estimated: **23 tests**. The perception
suite goes from 1237 passed + 2 skipped to **1214 passed + 25 skipped**; the
real-data suites are `skipif`-guarded and skip cleanly. Most test files that
mention `outputs/` synthesize their own data and are unaffected.

**So the rule this section used to state now runs the other way.** The moment a
new capture is preserved under `outputs/`, it is again the only copy — the
captures bucket deletes at age 1 day, so GCS will not hold it, and
`outputs/` is gitignored so git will not either. Re-read the reaper rule below
before the first launch of any rebuilt app, and copy a capture you care about
off this machine the day you take it.

**The reaper still runs on launch.** `CaptureReaper` frees a capture's record
and files once the user has seen the outcome, so a capture that has been reaped
exists nowhere else. **Pull the container BEFORE the first launch of a rebuilt
app, every time.** That rule cost a capture on 2026-08-25 and is unchanged by
the wipe.

## What works right now

**EVERY Cloud Run revision number below other than the three service headers
refers to the RETIRED `roomstudio` project and no longer exists.** The stack
was migrated to the `thegoodguest` project on 2026-08-31; all three services
are at their first revision there. Read revision numbers in the narrative as
history, and derive live state from `gcloud run services describe <svc>
--region asia-southeast1 --project thegoodguest`.


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

Suites, measured on `main` 2026-08-31 after the three lane merges and after
`web/public/dev-fixtures` and every preserved capture were DELETED at parking —
so these are the fixtures-ABSENT figures, and they are the only ones that
describe this tree: perception **1205 + 34**, web **287**, schemas **126**
(`pytest packages/schemas/tests`);
root **849 + 102** by bare `pytest` (which uses `testpaths` in `pyproject.toml`);
root **867 + 102** by `pytest packages services tools
--ignore=services/perception-obj`, which collects 18 tests `testpaths` does
not. **Those two commands are both called "root" in this repo and differ by
18 tests** — "always say which" was never enough on its own, because the
figures were recorded without the command that produced them. Write the
command. Without fixtures the second form is **811 + 102** (review worktree,
2026-08-24); on `brand-identity` with fixtures ABSENT bare `pytest` read
**822 + 102**, the eleven added being `tools/test_gen_mark.py` growing from 15
to 26 (0248-0251). The fixture-backed set skips silently, so a lower number
from a worktree is correct rather than regressed. re-enqueue **18**.

### iOS capture app — `ios/TheGoodGuest/`

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
- **Frame luminance.** `FrameLuminance` measures mean luma on the luma plane of
  every accepted keyframe, on the queue that already holds the buffer, and
  `CaptureManager` reports the census at stop on **every** capture — a census
  that only prints on trouble cannot be told apart from one that never ran. The
  floor is 16, the video-range black level, and it sits in a chasm: across the
  seven preserved captures the six healthy ones never read below 80.63, while
  rp6g2's covered-lens tail reads 0.13–11.87 (0240/0241). **Reporting only —
  nothing is dropped and nothing is gated on the reading**, deliberately, and
  the durable fix is an additive proto field carrying the statistic on the
  bundle, triggered by the next `capture_bundle.proto` change for any reason.
- **Live floor plan** drawn from the RoomPlan delegate stream, replacing the old
  placeholder sketch. Confidence gates naming: a low-confidence object renders
  unlabelled and the guest hedges.
- **Identity.** Firebase anonymous auth, upgraded in place by linking Apple
  (decision 0051) or Google (0118) — the UID is asserted unchanged on link, and
  a conflict is an explicit switch/keep choice, stated in two alerts with the
  real cost and no counts — the designed conflict screen was deleted because
  the counts it wanted cannot be obtained (0216). **Both providers are
  configured on this project**, verified from the admin API 2026-09-01: Google,
  and Apple with Services ID `com.thegoodguest.signin` and a complete
  `codeFlowConfig` on team `3HU2SP8346`. Apple was created 31 minutes AFTER
  `docs/PARKED.md` said it never had been — read that file's Apple paragraph,
  not its history. **Configured is not verified**: neither link has been
  exercised on a device (punchlist G1-06). There is deliberately no iOS
  sign-out, and **no account deletion either**, which is its own defect below.
  `IdentityContinuity` classifies each launch (`continuous` / `firstRun` /
  `credentialLost` / `keychainUnavailable`) and logs it at fault level without
  changing behaviour (0141).
- **Upload.** Background `URLSession`, whole-blob PUTs, `bundle.pb` enqueued
  last (0040) and gated on every other blob completing. Honours GCS
  `Retry-After`. Session expiry re-mints; a re-mint that returns identical URIs
  escalates once to `force_remint` (0049). `CaptureRecovery` re-sends a
  `failed_incomplete` scene's missing paths plus `bundle.pb` (0084), and only
  promises that when disk proves it can. Launch-time rehydration is
  hardware-verified on both relaunch routes (0085): the `.task` job fires on a
  background OS-relaunch as well as on a foreground open, so no AppDelegate
  co-trigger is carried.
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
- **The mark.** `DesignSystem/Wordmark.swift` draws the same two interlocking
  rings as the app icon, from the generated `MarkGeometry.swift` (0193/0248).
  `RSBrand.name` stays the one-file swap for the name. **The mark and the name
  are never set side by side** — the mark IS the "oo" of "the good guest", so a
  lockup prints those two letters twice; chrome takes the mark alone.
- **The splash.** `SplashView` is the launch, wrapped around `RootFlowView` by
  the app entry point rather than routed to: the name arrives, the word closes
  on its own middle, and the mark is what is left. The only place both appear,
  and they appear in SEQUENCE. Each letter is carried as a rigid body along cuts
  the generator finds by counting how many strokes a column crosses (0251), and
  the morph is exact because the wordmark's rings ARE the mark's (0250).
- **Reclaim.** `CaptureReaper` frees a capture's record and files once the user
  has *seen* the outcome — never on mere upload success.

**The screens were rebuilt to one shape (0254, 0257).** Home holds the claim,
ONE sentence that reports, and the pinned action — nothing else. The sentence
routes by priority (needs-you → Notes, arrival → the doorway, in flight → the
desk, otherwise a standing fact → the house) and cannot stack, which is what
stopped the claim being pushed down the page and what let it stop vanishing
after the first scan. Everything home used to report moved to a screen of its
own, reached from a **contents** screen behind the mark — a table of contents
rather than a tab bar, so the four destinations are stated only when asked.
`HomeLine`, `Contents` and `SurfacePlacement` are the three routing tables, all
pure and table-tested; a test pins that the sentence and the contents sheet
cannot disagree.

**One grid, enforced and checkable.** `RSScreen` holds every shared
measurement, `ScreenHeaderFrame` gives every header the same 44pt band, and
`RSActions` fixes the action block's SHAPE — extras above, one filled button,
then exactly one closing line — so a button's height off the bottom cannot
depend on how many controls a screen has. A block pinned over a scroll region
uses `rsPinnedActions`, which is opaque and full-bleed: `safeAreaInset` lets
content scroll BEHIND what sits there, so a transparent bar is one the body
copy renders through (0287).

`tools/ios_screenshot_gallery.py` photographs **83 states across 17 screens** —
one frame per distinct state rather than one per screen — at both the default
text size and AX5, 166 frames, and `tools/ios_layout_audit.py` measures them and
exits non-zero when an enforced screen deviates. `tools/ios_contact_sheet.py`
turns a pass into one self-contained page for review. Last run 2026-08-28:
**0 of 62 at both sizes**; default margin 25–29pt, header ink 81–89, first
content 140–152, filled button 77–87pt off the bottom at left 26–28 and 346–350
wide. **Two of the audit's five bounds are default-size only and are not
enforced at AX5** — the first content line and the button's offset off the
bottom both move legitimately when the header glyph above one and the closing
line below the other grow (0252).

**Type stops at a CEILING, and tiers stop some of it earlier** (0258). The app
holds Dynamic Type at `RSTypeSize.ceiling` — `.accessibility2`, body 17 → 33pt
— applied ONCE at the app root by `rsTypeCeiling()`. Uniform, so every ratio
between every pair of styles stays exactly where the default size has it: the
accessibility layout is the same layout, larger. Within that, serif titles stop
at **1.4×** (`RSTypeCap.display`), machine data at **1.6×** (`.mono`), and a
control's label is clamped at `xxxLarge` by `rsControlLabel()` so a button keeps
the shape its fixed padding gives it. Reading text scales freely to the ceiling
and is capped by nothing else.

**Machine truth is set in mono, uncontained — and the tracker now is too.**
The capture screen's tracking indicator was a bordered capsule with a coloured
status dot, the only element in the app in that shape; it is a mono readout in
the same idiom as the coverage ticks below it and the desk's status line. Three
things went with it: **the ordinary state is now the quiet one** (`.good` had
carried the component's only glow, so nothing-is-wrong was the loudest thing on
screen, and it is now set in the coverage labels' muted ink), the dot is gone
and nothing replaces it (`.slowDown` and `.finding` share a colour, so it
carried three values where the words carry four), and **the readout reports
STATE while the guest's line keeps the instruction** — "Go a little slower"
became `MOVING TOO FAST`, because an instruction in a status readout duplicates
the channel the app already has for advice. All four strings sit in one switch
in `LiveCaptureView.trackingReadout`.

**Nothing is dropped, reordered or restacked to fit.** The three
`isAccessibilitySize` re-compositions are GONE — home's claim/sentence swap,
the contents row stacking, the house's stamp dropping to its own line. Each was
the right fix for unbounded type and each is dead weight under a ceiling: a
second layout to verify, for no gain. `ContentsRowView` instead gives the title
and the status `layoutPriority(1)` and lets the dot leaders yield, because a
leader is filler — without that, "The house" wrapped to two lines at the ceiling
while "The desk" did not.

**Measured across all 83 states, 2026-08-29:** mean density 10.2% → 14.5%
(**1.42×**), layout audit **0 of 62** at both sizes.
`tools/ios_density_guard.py` bounds it by the arithmetic rather than by taste —
ink area scales with the SQUARE of type size, so the same content at 1.94× is
3.77× denser with nothing wrong, and **0 of 67** screens exceed that. A 2×
target was arithmetically unreachable while showing everything: meeting it
needed type below 1.41× or content removed, and both were ruled out. Read a
ratio well BELOW the square as the interesting signal — it means content is
falling off the bottom of the frame.

**What it costs, plainly:** someone who sets the top step asks for 53pt body
text and gets 33. That is a real reduction for the people the setting exists
for, and it is why the ceiling is ONE constant.

**The splash hands the mark over** rather than cutting to home (0255): the mark
walks to the exact rectangle home publishes as an anchor preference, while home
fades in behind it. Home's mark shows the way in by playing a dotted leader and
the word MENU out from behind itself, once per launch — no caption, and the
plate-and-chevron treatment that preceded it is gone.

Suite **610**: 604 asserting offline tests + 2 boilerplate stubs + 4 live
integration tests that require a reachable backend. See the iOS test policy
section — it is the single source of truth for posture and how to run them.

### api-public — `api-public-00001-pid`, image `20260831-152649`

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
  `PROMPT_VERSION 7`, SERVING since `api-public-00046-xig` (2026-08-25). SSE with a
  disconnect shield: the turn completes and persists even if the client stops
  listening. `PROMPT_SURFACE_SHA256` covers the charter, the arrangement block
  AND `guest_tools.TOOLS`, schema included (0219) — every word the model reads
  is under one digest, enforced by construction rather than by a list.
- `GET/DELETE /scenes/{id}/design_spec` — the arrangement document. Every entry
  carries `measured_transform` beside `proposed_transform`; an entry that cannot
  is unrepresentable.
- `DELETE /account` — deletes every per-user collection and prefix by hand
  (Firestore does not cascade), ordered GCS → Firestore → identity, idempotent
  and resumable.

The guest has hands but not coordinates (0132): `propose`, `revert`, and `turn`
carry no numeric field anywhere. A server-side solver owns geometry and refuses
when it cannot ground an instruction.

### api-internal — `api-internal-00001-hat`, image `20260831-144728`

`--no-allow-unauthenticated`, Cloud Run IAM gated. Hosts `/ingest/eventarc` and
nothing else. Validates in order: `schema_version`, bundle_id cross-check
against the URI, image decodability (pre-GPU), `device_id` presence, and
declared-blob presence (0105). A rejection is a `failed_invalid` or
`failed_incomplete` Scene with a structured log and HTTP 200 — never a bare 400.
Terminal-failure scenes are stamped with `expire_at`; revival clears it; `ready`
is never stamped.

### perception-obj — `perception-obj-00001-dw6`, image `20260831-160150`

**Serving 100%, carrying both ruled-on flags** (flipped 2026-08-25, 0243;
re-verified from `gcloud` 2026-08-25). `perception-obj-00074-var` pins
`sha256:c538f699…` — an image whose layers are the same objects as the ship
lane's `b19434de…`, rebuilt in 39 s off the buildx cache — and its env carries
`PERCEPTION_MASK_REFINE=1` and `PERCEPTION_ARM_SELECT=1`, with all three parked
flags absent. `/health` answers 200 and `/process`, `/shell` and `/compress`
are all registered. The `serving` registry tag moved onto that digest at the
flip (0200), so the image a scale-to-zero GPU service boots from is pinned by
name rather than by recency.

**The revision still carries its `candidate` tag, and that is the normal
post-flip shape.** A candidate deploy names the revision; the flip moves
traffic and does not rename it. So `tag: candidate` sitting beside
`percent: 100` is NOT a parked revision — read the traffic split, which is the
authority, never the tag.

Runs as `perception-obj-runtime@` under least privilege (0090) and is
platform-gated — only `tasks-invoker@` holds `run.invoker` (0106). Scales to
zero with lazy model loading: `/health` answers immediately, `/ready` reports
per-model state.

Three pipeline stages plus a probe, all Cloud Tasks driven:

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
  first, because refinement changes what the chooser is choosing between.
  **Refine and arm-select are RULED ON and SERVING** since 2026-08-25 on
  `perception-obj-00074-var` (0243) — verified from `gcloud` after the flip:
  both flags present, all three forbidden flags absent, and the `serving` tag
  moved onto `sha256:c538f699…`, the digest the revision itself pins rather
  than the timestamped tag (0200). The residue is parked (0202/0212).
  **Two more ship OFF and byte-identical off, from `selection-supply`** —
  `PERCEPTION_CONDITIONAL_SECOND_ARM` skips a box's planned second view when
  its FIRST arm already renders well (0229; 4 of 8 multi-arm boxes, and never
  when tier-1 merely *ran*), and `PERCEPTION_VISIBILITY_VETO` lets frame
  selection REJECT a frame or an (object, frame) pair, never rank one (0234).
  **The enable ORDER is: refine, then arm-select, then
  conditional-second-arm** — 0212's refine-before-select still holds, and
  conditional-second-arm decides using `arm_fit`, whose input refinement
  changes. **The veto is not in that order any more: it is measured and
  refused** (0236, see the open defect below). `PERCEPTION_ARM_SELECT` also
  carries a third axis — trimmed splat→cloud Chamfer, unanimous-or-refuse
  (0233) — which is **structurally incapable of enabling a switch**, only of
  vetoing one, and costs ~400 ms per arm plus one measured cloud per box.
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
- **Nested-mask collapse** rides association rather than being a stage:
  `PERCEPTION_KEEP_LONGER_MASK` (default `0`, on `segment-quality`, unbuilt into
  any image) collapses same-frame same-label nested pairs before the per-box
  shortlist scores them, keeping the LARGER. The survivor competes at its pair's
  best overlap — dropping the loser outright re-ranks it against every
  observation, and on a saturated metric with capture order as the tie-break
  that hands the box to whoever was photographed first (0292). It does NOT fix
  0262's flat metric and a reading that says so is wrong.
- **`/segment`** — a segmentation-only probe, built on `segment-quality` and
  deployed only to 0%-traffic candidates. **The candidate live on 2026-08-31 is
  `perception-obj-00093-pav`** (image `b21408a5`, the SAM 3.1 / `/track` build);
  the earlier `00088-vot` carried `PERCEPTION_SAM3_INTERACTIVE=1` and is
  superseded — read the traffic split from `gcloud`, never this line. **The serving revision does not carry this
  route.** It takes an EXPLICIT frame list, runs pass 1 only and never loads
  SAM 3D — "what does SAM 3 actually see there?" costs ~4 s a frame against
  ~25 s an object, and `/process` cannot answer it, because its request carries
  only `{scene_id, bundle_uri}` and it re-runs the census sampler, so a frame
  the sampler did not pick is unreachable. **Two guarantees keep it unable to
  affect a room a person can see** (0260): it writes exclusively under
  `scenes/{id}/segment_probe/` and never under `frames/`, where a `masks.npz`
  would be read as production cache by the next `/process` — the prefix IS the
  boundary — and it never touches Firestore, so the scene is read-only and a
  probe cannot regress a `ready` room the way a re-drive does. It verifies its
  own OIDC audience (`RECEIVER_URL + "/segment"`) rather than reusing
  `/process`'s, and `tools/segment_frames.py` drives it through Cloud Tasks
  because an operator cannot mint that token — impersonating `tasks-invoker@`
  is denied by design (0090), which is least privilege working rather than an
  obstacle to route around. `PERCEPTION_SAM3_INTERACTIVE` (default `0`) gates
  SAM 3's interactive visual path, which the click-refinement loop needs and
  which loads the tracker onto a card 0228 measured at ~5.26 GiB headroom.
- **`/track`** — SAM 3.1's multiplex VIDEO tracker across a capture's frames,
  producing an object→frame map: per frame, per instance, an `obj_id`, a box, an
  area and a stride-4 mask. **BUILT and exercised on a 0%-traffic candidate;
  NOT flipped, and production has not moved.** It is a different model from
  `/segment`'s, not a newer one — SAM 3.1 publishes only the tracker's
  checkpoint (0274). It carries `/segment`'s two containment invariants for the
  same reasons (writes only under `scenes/{id}/track_probe/`, never touches
  Firestore) and adds two of its own: a suppressed concept is refused before any
  GPU work (0089), and it writes numbers and binary masks, **never imagery** —
  which matters because this capture has a person asleep on the bed in frame 0.
  Ids restart per concept because the session holds one text prompt, so the
  map's key is **(concept, obj_id)** and never `obj_id` alone.

`track_selection.py` is the per-object selector built on that map: given the
frames a tracked object appears in, which single frame is the best photograph
of it. Two stages — three hard filters (the mask reaches the image border, the
mask is under 0.5% of the frame, more than 10% of it is covered by other
objects) and then a weighted score over sharpness, size, solidity,
centeredness and temporal stability, each min-max normalised within that
object's own surviving frames. It needs no box, so it reaches the unboxed nine
(0271), and no GPU, so it runs offline over the whole capture in 27 s.
**BUILT with no call site in the service yet** — `tools/track_select.py` is the
driver, and the module is COPY'd and smoke-imported so 0211 cannot recur.
**It never decides what an object IS**: every detection carries an opaque
`object_key` the caller assigns, because 0279 measured the tracker's ids as
unstable and a selector that hardcoded `obj_id` would silently return three
best frames for one nightstand.

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

**Association's label map and the segmentation prompt are ONE contract**
(0226), and this is the one change `selection-supply` makes that is NOT behind
a flag. SAM 3 returns the prompt term verbatim, so `BOX_LABEL_FAMILIES` and
`DEFAULT_OBJECT_PROMPT` are two halves of one list: eight of seventeen family
members could never be emitted (`table` among them, because the prompt carries
`dining table`/`coffee table`/`side table` and no bare `table`), and five
emittable furniture names sat in no family. Removing the eight is provably
behaviour-identical; adding the five plus `refrigerator:cabinet` takes the four
preserved captures **20/31 → 22/31 boxes matched, 28 → 30 associations**, and an
A/B over all four run at review confirms **no pre-existing association moved** —
both new matches are boxes that previously had none.
`box_placement.vocabulary_gaps` logs `box_vocabulary_gap` once per room so
neither direction can silently re-open, and `DEFAULT_OBJECT_PROMPT` now lives in
`process_receiver.py` because `server.py` imports torch and no GPU-free test
could read it there.

Suite **1119 passed + 9 skipped** on `segment-quality` WITHOUT
`web/public/dev-fixtures` (`PYTHONPATH=<tree>/packages/schemas pytest
services/perception-obj/tests`, worktree 2026-08-30 — the PYTHONPATH is
load-bearing, see the Python test policy). `test_segment_receiver.py` and `test_upstream_pins.py`
contribute **64** of those, measured directly. The last recorded figure on the
same command is `main`'s **1053 + 9** (review worktree, 2026-08-24), which the
64 does not reconcile with by two — `main` has not been re-measured here, and
the branch touches no existing test file, so the two belong to `main` having
moved rather than to this work. The last with-fixtures figure is **1060 + 2**
(2026-08-25); the with-fixtures figure for this branch is owed a measurement
rather than an arithmetic guess, and the spread has been seven tests.

### Web app — `web/`, live at https://thegoodguest.web.app

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
- `Wordmark.tsx` draws the two interlocking rings from generated geometry and remains the
  one-file swap for the product name, now "The Good Guest" (0245). It authors
  no paths and no colours: `tools/gen_mark.py` is the mark's one source across
  the app icons, the tab icon, both wordmarks and the share card (0193), and
  `tone` picks only which ink plate it sits on. The tab icon ships twice —
  `icon.svg` answers `prefers-color-scheme` and is drawn from the 16 px
  master, because a browser draws it at tab size whatever its viewBox says.
  `favicon.ico` is the legacy fallback and cannot answer a media query, so it
  ships three entries on a transparent field — 16 from the 16 px master, 32
  and 48 from the regular one — each the drawing that survives at its size.
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
  document's fonts and would silently set the card in system faces. Since 0248
  the card carries the **wordmark** rather than the mark — it reaches a stranger,
  where a small abstract mark says nothing — which also removed the product name
  from the set of strings its privacy guard has to allow, because the wordmark
  is a drawing rather than text.
  Eligibility is a conservative `created_at` gate against the first
  suppression-armed revision (0221) — a card ships the shell and a person
  contaminates a measured albedo, so this is the rung where 0089 binds hardest.

Suite **276** vitest; lint, tsc, and the static-export build are green
(re-measured on `brand-identity`, 2026-08-26, fixtures absent).

The design tokens are the new identity's (0248): cream `--paper: #f9f2ec`, warm
near-black `--ink: #282723`, terracotta `--accent: #c04d3e`. **There are two
terracottas and the split is load-bearing** — `--accent` is the exact value the
mark is drawn in and reaches only 4.33:1 on the cream, so anything text-sized
uses `--accent-deep` at 5.52:1 instead (0249). Do not set body-sized text in
`--accent`.

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
- **Retention** is configured and live, verified against the buckets and TTL
  policies rather than `eventarc_setup.sh` (0242): captures 24 h, failed
  scenes 90 d, mask intermediates 180 d, and **upload sessions swept within
  about a day, NOT 7 d** — the TTL is on `created_at`, and Firestore deletes
  when that field's value is past, so the record expires as it is written.
  Server request logs (client IP, user agent, URL) sit outside all of it at
  30 d in Cloud Logging `_Default`, and `DELETE /account` does not reach them.
- **CI** (`.github/workflows/`): python and web are push-triggered; iOS is
  `workflow_dispatch`-only on purpose — see the iOS test policy. **Both are
  green** (measured 2026-08-31: the last five `python.yml` runs on `main` all
  succeeded). The root job gets Pillow from the root pyproject's `dev` extra,
  which `tools/test_gen_mark.py` needs at collection. **Nothing gates on CI**,
  so its state has to be checked rather than assumed.
- **Tooling.** `tools/upload_test_bundle.py` is the substitute iOS client with
  four smoke modes; `tools/reenqueue_scene.py` is the out-of-band cure for
  stranded scenes and the warm re-drive driver.

## What does NOT work / what we're deliberately not doing

Open problems, measured dead ends, and deliberate non-goals. An item leaves this
list when it is fixed or ruled — not when it is explained. Closed items are
deleted, not annotated; their story is in `docs/decisions/`.

### Measured dead ends

**Sixteen approaches were tried and measured not to work.** Each carries
`Status: Refuted` and they are listed together in
[`docs/decisions/README.md`](docs/decisions/README.md). One line each here so
nobody re-runs one by accident; **read the note before re-proposing one**, since
the note is where the re-open condition lives. Most of these cost GPU time, and
re-running one is the most expensive mistake available in this repo.

| what does not work | the number that killed it | note |
|---|---|---|
| View selection predicting reconstruction quality | eleven measures failed; a view 1.7× sharper seeing 2.1× more surface reconstructed **worse** | 0146, 0152, 0162 |
| A better-framed photograph being a better photograph | the same swap gained one table its legs (0.406 → 1.004 of box height) and cost another the ones it had — **large and bidirectional**, so no sort key exists | 0197 |
| Raising `PERCEPTION_PLAN_VIEWS_PER_BOX` on a warm room | empty plan at budgets 2, 4 and 8 — cached policy-skips are invisible to the planner forever | 0160 |
| Unioning two reconstructions of one object | oracle registration adds **+0.057** coverage against **+0.063 with no registration at all**, at 1.76× the points | 0166 |
| De-occlusion | foreign occlusion is a median **0.080** of missing surface against a registered bar of 0.25 | 0165 |
| Feeding SAM 3D a measured LiDAR pointmap | refuted at 1.4% of predicted magnitude, wrong direction | 0181 |
| Capture-time guidance | one viewpoint tops out at 0.50 surface coverage by geometry and the best single frame already reaches 0.31 | 0150, 0155 |
| The fused cloud for orientation | median axis margin **0.0287** against a 0.10 gate; 7 of 20 winners move under perturbation | 0225 |
| A vision model shown both renders, for the 180° facing sign | same noise floor as the four instrument families before it | 0156 |
| Tuning `FUSION_CLUSTER_DIST_M` or `SHELL_WALL_MERGE_*` | both measured correct on real rooms; the symptoms are label collapse and edge truncation | 0075 |
| A tighter floor tolerance inside a box | restores FLOOR, not feet — 96–100% of restored points vanish by tol=0.06 | 0232 |
| The confidence threshold as a route to the missing leg | the model is not uncertain about the second leg; it does not see it | 0268 |
| Ray triangulation to merge tracked fragments | separates known-same from known-different by only 1.8× with heavy overlap | 0280 |
| Appearance as the box-free merge | calibrates well on boxed objects, merges the ones that matter | 0284 |
| The SAM `mirror` label's depth-trust gate as a mirror detector | precision 18% | 0091 |
| Generic compression of splat data | gzip 1.36× where the SPZ tier is 5.8× | 0125 |

Two more that are not approaches but standing facts: **Spark is not the render
bottleneck** (parse is under 1% of the wait; fetch concurrency is flat 1→10
because one GCS connection is capped, 0123), and **the 180° facing sign has six
refuted instrument families** — settled in conversation instead, and ruled a
concession rather than a feature (0081, 0104, 0156, 0170, 0183).

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
same way on both.

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

Each entry is what is broken and the measurement that pins it. The reasoning is
in the note; this list exists so nothing is forgotten, not so it can be
re-argued here.

**Perception / room quality**

- **The per-box shortlist's overlap score is FLAT.** `mask_overlap_with_hull` is
  precision with no recall term: **31 of 52 candidates score exactly 1.0000** on
  `90eebfc4` and 27% across the four older captures, after which `frame_index` —
  capture order — decides. Keep-the-longer is right **9 of 9** against the
  operator's rulings and is BUILT and OFF behind `PERCEPTION_KEEP_LONGER_MASK`
  (4 of 25 boxes change planned views, none losing an association,
  byte-identical off). The click repair is NOT built: the pointer was a human
  eye and no automated search found the region. **Read
  `outputs/segment-quality/targets/README.md` before quoting any coverage
  figure** — the denominator includes floor, so every such number understates
  what was recovered. (0261–0269 — the rule itself is 0266 — plus 0288–0289 and 0292)
- **`90eebfc4` carries LiDAR depth on 1 frame of 189**, against 99–100% on the
  four older captures, correlating with iOS 26.5.2 → 26.6.1 on the same phone
  and app build. That disables mask refinement, `depth_fit` and the band
  detector (0231) for the whole room, and **nothing in the pipeline reports it** — tier
  comes from the RoomPlan room, not from whether depth arrived. A depth-bearing
  frame count in the manifest is the cheap fix and is independent of the cause.
  (0267)
- **rp7's desk ships as a partial object, and that was ruled ON on the merits.**
  Mask refinement plus arm selection put it at the right height on its measured
  floor, but in the box's own axes it is 0.734 × 0.877 × 0.665 against a box of
  1.291 × 0.795 × 0.660 — width falls to **0.569** of the box and the three-axis
  error goes 0.626 → 0.644 m. It is not rotated; it is the sit-stand desk's
  right-hand leg assembly plus a stub of top. The operator ruled on it having
  seen this: class-6 truncation is endemic, and an object standing on its floor
  beats a desktop floating 47 cm up. (0198/0201, 0204/0205, 0211/0212)
- **The object-aware residue is PARKED and its question has changed.** It hit
  its pre-registered frame set exactly and bought spike's bed a better arm; the
  rp7 cost was overstated (0.626 vs 0.644 is inside noise, so the chooser most
  likely refuses). But its core job moved into the cover pass, and that work had
  to fix the residue for ignoring the frame vetoes — two stages now overlap and
  neither knows what the repair stage needs. **It cannot ship until supply,
  repair and the vetoes draw from one allocator**, and it belongs to the
  throughput charter rather than to a parked flag with no owner. (0202, 0212)
- **`PERCEPTION_VISIBILITY_VETO` is measured and stays OFF: a veto is a re-roll,
  not a filter.** 16 of 48 frames change across the four captures; on rp6g1 one
  band-vetoed pair moves 8 frames. Corpus detections go 228 → 250 (+10%), but
  the veto removes rp6g1 f178 and rp7 f114 — not those boxes' shipped arms but
  their better ALTERNATIVES. rp6g1's nightstand is the whole argument: today it
  has two arms and the chooser correctly refuses the bad one; under the veto it
  has one, and fill 0.223 ships. **A supply change and a chooser cannot be
  evaluated apart.** Two follow-ups: split the flag (veto 1 is free, veto 2
  causes the cascade), and contain the cascade by relaxing a vetoed box's own
  bar in place. (0234, 0236)
- **The object→frame map's ids are unstable — the tracker survives a visit, not
  a revisit.** Mean box purity **0.6404** against bands fixed before the first
  GPU run (0.90 stable, 0.70 marginal). Coverage is fine at 0.73–0.97; the
  failure is re-acquisition — four of six boxes arrive as three ids in disjoint
  frame windows, and 25 of 42 competing claimant pairs share no frame at all.
  The sting is for the boxless-object plan: the box is what you would need to
  REPAIR the tracked instances. (0279)
- **The SAME-FRAME half of that is exactly answerable, and is a different
  duplication.** One concept per pass means one object is claimed by every
  prompt that fits it: `artwork#0 ≡ painting#1` over 54 shared frames,
  `monitor#1 ≡ tv#0` over 38. Across all 48 overlapping pairs the split is
  bimodal with nothing in the middle — 14 at containment 0.996–1.000, then
  0.511, then ≤ 0.047. Merging takes the capture 48 instances → 34 objects.
  **This is why an occlusion rule cannot use a bare union of the other masks**:
  applied literally it reports eight instances as ~99% occluded by duplicates of
  themselves. (0281)
- **Nine objects have no uncut view, and the border margin is the one number
  that decides it.** Border rejects **768 of 1,241 detections (61.9%)** against
  too_small's 79 and occluded's 55. Two of the three objects the operator named
  come back exactly (`desk#0` → 50, `chair#0` → 42). The bed is the
  disagreement: at 2.5% all 87 frames are refused, at 0.5–1.0% it keeps four and
  picks f0, the operator's own choice. A high rejection rate is the room rather
  than a defect — 0273's rotation-paced capture runs large furniture off the
  frame, and 0259's border measurements stand behind the filter. The threshold
  ships as specified and was
  deliberately not tuned to the bed. What is owed is the operator's eye on the
  nine fallback objects. (0282)
- **`/track` is bounded by frames × objects on the L4, and the bound is not ours
  to remove.** Every OOM lands in one allocation — the detector grounding a
  batch, 1.27 GiB, with 1.0–1.2 free — and the headroom is eaten by per-object
  tracker state with nowhere to go: the multiplex `init_state` sets no
  `storage_device` and takes no `offload_state_to_cpu`.
  `PERCEPTION_TRACK_GROUNDING_BATCH` (default 4) is the lever. (0278)
- **The shorter of two nested same-label masks is the one without the legs, and
  `/track` only ever offers the shorter one.** Reproduced on all 78 desk
  detections — longest tail 100 px against SAM 3's 533. Cross-label, not a desk
  quirk: all six nested pairs reach +0.111 to +0.288 of the frame further toward
  the floor. **The tracker cannot be fixed into carrying both readings** — the
  video builder's NMS gates sit ~10× below the pair's 0.995 containment, so
  exactly one survives. **Prompting is measured dead too**: of eight phrasings
  only `desk` and `sit-stand desk` ground at all and they return the same masks.
  The resolution is architectural and free: let `/track` choose the FRAME and
  the image path produce the MASK. Two traps — the capture is rotated 90°, so
  project gravity before profiling by row; and do NOT fix this by preferring the
  larger mask, since the door pair jumps 7.62% → 23.15% and that rule takes a
  doorway over a door. (0283)
- **Class-6 splat truncation is untouched and has no live route.** Reconstructions
  are missing legs, bases and backs. Every placement fix to date positions or
  orients an incomplete reconstruction better; all three attacks on the cause are
  refuted above. What remains is 0052's standing trigger — a different model, one
  that consumes several views itself or exposes calibrated metric scale or pose.
- **CUDA OOM is the largest measured loss in the corpus** — **22 of 163
  detections**, twelve of them box views, and two boxes lost their only
  compatible mask. It is capacity, not scheduling: models hold ~16.4 GiB, the
  forward pass peaks at 5.23–6.43, the card has 5.26 left. **Read the peak, not
  the request** — 21 of 22 failing allocations are 0.500–0.861 GiB and mask area
  does not predict it at all (r = −0.009 over an 84× range). Freeing 1.2 GiB
  covers 21 of 22. Downscale-and-retry is refused (0197's bidirectionality means
  an altered input yields a different object under the same identity), and so is
  a deferred retry (the existing retry already runs with an empty queue). **The
  second arm is currently the OOM fallback in six of nine affected boxes**, which
  is why `PERCEPTION_CONDITIONAL_SECOND_ARM` stays OFF until the throughput
  charter closes. The third Chamfer axis rides `PERCEPTION_ARM_SELECT` and needs
  no env of its own; it can only veto a switch, never enable one (0233). The
  charter's named option (evicting SAM 3 for pass 2) is
  mutually exclusive with mask refinement, now ON. The live path is batching pass
  2's refinement into its own sub-pass. (0228, 0229)
- **`b667f891` is budget-starved** — a 53-item census tail against the 900 s
  request budget, so it budget-stops every round and the fusion post-passes never
  run. A warm re-drive still came back `budget_stopped`, gaining colour on 0 of
  45 objects while 40 had readable splats. **But rp6g2 is NOT a representative
  room**: its last 28 keyframes are black (mean luma 0.13–4.49 against a capture
  median of 129.5) — 23.4% of the room that has been the thin case in every round
  of analysis. **The cause is settled and is NOT the app: the operator's hand
  covered the lens.** Re-read every prior conclusion drawn from this room. The
  two black frames the sampler takes read luma 2.46 and 1.88 and produce **0
  detections each**, consuming two of eight cover picks. (0235, 0240)
- **An unmatched RoomPlan box has FIVE causes and the two anyone looks for are
  the smallest.** Of nine across four captures: 2 PLAN_SKIP, 2 DETECTION, 1 OOM,
  1 COMPETITION, 1 SAMPLING, 1 NEVER_FRAMED, 1 LABEL. Four carry
  family-compatible masks at up to overlap 1.0000 and are invisible to
  association only because `ok=False`. Every failure is recorded faithfully in
  its frame's `objects.json`; nothing aggregates them. (0227)
- **A window ships with ~30° in-plane skew.** Near-square planar objects are
  ~90°-ambiguous to the model and no instrument scores in-plane orientation.
- **The "cabinet behind a wall" is not the declip bound** — the declip pass never
  engages, because the object's centre projects outside every wall rectangle.
  Start from that fact, not from `PLACEMENT_SPLAT_CLIP_MARGIN_M`. (0104)
- **Two same-label objects closer than `FUSION_CLUSTER_DIST_M` (0.4 m) can still
  merge into one.** (0052)

**The guest**

- **Object colour ships in three of the four walk rooms, not the fourth.** rp7
  8/16, rp6g1 9/20, spike 14/25 objects carry a measured `color` block, and
  spike's `red chair` is a real production referent. **rp6g2 has 0 of 45 and
  another re-drive will not change that** — `apply_object_colors` runs inside the
  refinement pass, which that room's tail costs it. Objects with no block inside
  a coloured room are the confidence gate working. (0184/0185)
- **Two voice evals are flaky, both measured rather than guessed.** The facing
  refusal misses about **1 run in 4** (phrasing, not behaviour — it greps a reply
  for a refusal word); the re-asked-referent test misses about **1 in 13** on
  `main`'s charter and the current one alike. Re-run before believing either, and
  **measure with the rate harness rather than by re-running the test and counting
  pass/fail**. The long-recorded "ambiguous wall 1 time in 8" is probably not a
  flake and its rate was understated — 9 refusals in 26; re-measure rather than
  assuming it is gone. **Do not re-report the re-asked-referent miss as a
  regression and do not attribute it to 0186 or 0220** — paired and interleaved
  it reads 19/20 on both arms. And the `ANTHROPIC_API_KEY` was never absent:
  `anthropic-api-key` has been in Secret Manager since 2026-07-21, and the belief
  that it was missing cost that lane two days. (0215, 0186, 0220)
- **Rule 10's literal "would" has collapsed** — 2/16 against 12/16 when it was
  measured — while the property the rule states holds at 14/16, so the evals now
  grade the property. **0214 was the obvious suspect and is RULED OUT** on a
  paired interleaved A/B. The remaining explanation is the model behind
  `GUEST_MODEL`. Do not re-open this by re-running the test and counting
  pass/fail. (0215)
- **The guest refuses rather than picking when two candidates tie**, and the
  refusal names a handle a person would have used. Both are live behaviour, not
  open work — listed here because the voice evals are the only thing that
  measures them and two of those are flaky above. (0213, 0220)

**iOS**

- **The app cannot delete the account it creates, and that is an automatic App
  Store rejection.** Guideline 5.1.1(v) requires an app supporting account
  creation to let the user INITIATE deletion from within it, and this app
  creates an account the moment an anonymous UID is linked to Apple or Google.
  `DELETE /account` is live and complete on api-public; **no Swift file calls
  it**, so the only deletion route a person has is one they cannot reach from
  the app that made their rooms. **Not the same work as per-room deletion** —
  that is a different gap, does not satisfy this, and is not needed by it. What
  is missing is a call site and a screen to put it on. (punchlist G1-08)
- **The mark's fill rule is guarded on the Python side only.** `gen_mark.py`
  warns that even-odd across both rings punches holes where the bands cross and
  `test_gen_mark.py` pins it, but nothing pins the Swift or TypeScript
  CONSUMERS — the generator warned, the test passed, and iOS's splash re-made the
  mistake anyway. All six other surfaces were audited and are correct, so this is
  a latent gap: the fix is a consumer-side pin. (0255)
- **Notes has no past.** The design gives news an "EARLIER" list of observed
  facts; that needs the phone to remember what it previously saw and diff
  successive fetches. Deferred by operator ruling; the section does not render
  rather than showing an empty shell. The arrival card is deferred with it, since
  detecting an arrival is the same change detection.
- **The menu peek's two greys are literal hexes**, given by the design brief and
  named in one place in `MenuPeek.swift`. The only colours outside the token
  system; they will not follow a brand repaint.
- **The pinned-action rule reached ONE screen out of eleven when measured**, and
  is now applied everywhere by `RSActions`. Kept for the finding: both named
  screens are closed and **neither by a layout change to itself** — the rooms list
  was replaced by `HouseView`, and `FailureView`'s buttons moved into a
  `safeAreaInset`. Both were reachable by scrolling, which is why the suite was
  green and why reading did not catch them. (0253, 0257)
- **One filled button carries a glyph and two deliberately do not.** The guidance
  sheet's denied CTA is `Label("Open Settings", systemImage: "gear")`; the two
  buttons that START a capture ship bare, because at button size the product's
  mark collapsed into a smudge and Apple's viewfinder was worse than nothing.
  **This is a consistency question, not a layout one** — the label-wrap complaint
  was fixed by the control-label clamp. Re-photograph before re-reporting it.
  (0287)
- **`WhySignInSheet` is presented by no call site** outside the screenshot
  gallery, and its checklist reads "Your 1 rooms" where the sentence above reads
  "one room". **Deliberately NOT fixed**: dead code accruing unverified fixes
  rusts shut rather than staying ready. Give it a route or delete it; do not tidy
  it. (0237)
- **`RoomRow` centres its thumbnail against wrapped text.** At AX5 both lines wrap
  and the tile rests between them. Exactly the `.center`-is-the-default form the
  notice components were top-aligned to avoid; missed because the row is drawn in
  a different file. (0253)
- **A keyframe's manifest entry survives its JPEG failing to write.**
  `acceptFrame` appends synchronously while the encode happens later on
  `jpegQueue`, and both failure paths log and return without removing the entry.
  This is a MISSING file, not a dark one — the declared-blob check turns it into
  `failed_incomplete` — and no capture has been observed hitting it. (0240)
- **The luminance census has never run against a live camera buffer.** Pinned
  against a preserved capture and synthetic planes only. The one thing a real
  scan would settle that offline work cannot is which luma range ARKit vends on
  this hardware. (0241)
- **The Live Activity count freezes when the process is dead.** The word stays
  honest, the count sticks. Only remote push fixes it;
  `LiveActivityController.pushTokenSeam` is named and unbuilt. (0114)
- **The anonymous UID churn has happened twice on real hardware.** Mechanism
  named — the SDK deletes its own Keychain credential on a token rejection and
  the app silently mints a new UID, orphaning that period's rooms. Churn 1 is
  dated and attributed; churn 2 is open. `IdentityContinuity` instruments the
  next occurrence. (0139, 0140, 0141)
- **Foreign-record stand-down drains one record per launch**, so N phantoms need
  N relaunch cycles. Deliberately not fixed: quieting the symptom before the
  churn's cause is known makes orphaning less visible, not less real. (0115)
- **Terminal-failure UI has never rendered on hardware** — server-side scene
  failure and blob-failure banners.
- **The 401 recovery-*success* leaf is untested.** The live test used a garbage
  token, exercising the give-up branch.

**Web / product**

- **The hero A/B is open** — the operator's taste call. Variant (b) cannot be seen
  on any deployed origin by design: a real object splat is a possession, so its
  files are gitignored and hosting-ignored. (0122)
- **The bridge QR encodes nothing.** No deep-link infrastructure exists; the
  caption says so. It is NOT blocked on the rooms fetch — the desk names the room
  in the link it hands over. (0218)
- **`RSSound` is wired at three call sites with no cue files** — the app is
  silent, and the web has no sound at all. **Branded fonts are per platform**: the
  web loads real Google faces via `next/font/google`; **iOS bundles no font files
  at all** and falls back to the spec's system substitutes behind a named
  bundling seam. (0248)
- **There is no per-room deletion** — account deletion is all-or-nothing, which is
  conspicuous for a product whose thesis is that rooms are identity. **It is also
  a hard prerequisite of any hosted share link**: revocation of a share and
  deletion of a room are one mechanism seen from two angles, so shipping the link
  first would ship a share that outlives every means of stopping it. Rung 0 — the
  calling card — needs none of this; every rung above it is behind this gap.
- **The card's date gate refuses rooms that are genuinely eligible** — an older
  scene re-driven cold on a suppression-armed revision qualifies and `created_at`
  cannot see a re-drive. One-directional by construction and the safe direction;
  the manifest provenance field is the durable fix. Related and untested: the card
  has never been drawn against a real `anchor_envelope` shell. (0221)

**Infra / release**

- **The scene lease expires mid-job on 70% of runs, and what actually prevents
  double-processing is not the lease.** `SCENE_LEASE_TTL_SECONDS` defaults to 300
  and is unset in the deploy script, while the claim is taken after model load and
  the request may run to 900 s. Over 66 production runs the lease held **median
  613.5 s, max 899.8 s, 46 of 66 over the TTL**. Two unrelated guards have been
  doing the work — `DISPATCH_DEADLINE_SECONDS = 930` exceeding the 900 s timeout,
  and `--max-instances=1 --concurrency=1`. **One thing does consult it**:
  `reenqueue_scene.py` uses the lease as its is-a-worker-active test, so on an
  actively-processing scene it says PROCEED without `--force`. **The fix is one
  number — TTL 960 s — and it is not applied.** Nothing would detect a violation:
  `lease_expires_at` is never passed to `_log_lease_action`, and the holder
  guard's rejection is a bare `return` after which the worker reports 200 "ready"
  having written nothing. (0286)
- **The lease-expiration branch has never run in production.** Three
  `reclaim_stale` events in a month of logs, every one preceded by a
  `release_error` from the same worker — all eager release. The load-bearing
  branch is unit-tested only, and the canonical stuck-scene reference was deleted
  at parking. `reenqueue_scene.py` could not run the test anyway: it resets to
  `queued` before dispatching, erasing the expired lease that is the subject.
  (0286)
- **The SIGTERM lease-release path has never fired, and may be unable to.** 0 of
  65 scenes ever carried a `shutdown_release_count`. `run_perception` is a
  synchronous call from the async handler with no `to_thread`, so a signal
  arriving inside a long CUDA or GCS call is lost to the 10 s drain. A
  cycle-limit gate is REFUSED rather than deferred — Cloud Tasks already caps the
  loop at `maxAttempts=3`. The residual failure is a scene left in `queued`
  forever, which wants a stale-scene sweep. (0286)
- **Alerting and monitoring do not exist and the deferral is unrecorded.** An
  unrecorded accepted deferral is indistinguishable from an oversight. Record the
  acceptance or schedule the work.
- **A second, unrestricted Firebase browser key exists** (no referrer restriction,
  27 APIs). The key the web app ships is properly restricted. Closing the gap
  breaks the live-authed-check path every recent api-public deploy uses — ship a
  replacement first.
- **The `perception-obj` image count sits ABOVE 3 by design.** The keep rule is
  *the 3 newest PLUS anything tagged `serving` or `buildcache`* — never exactly 3,
  because a lane iterating on builds pushes the live image out of the top three
  and exactly-3-by-recency would delete the image a scale-to-zero GPU service
  boots from. **The fix for a high count is to deploy or delete the surplus
  builds, never to tighten the policy.** Measured 2026-08-31 after parking:
  **three versions** — the live image, `buildcache`, and the parked candidate's.
  **The rollback hold is gone**: revisions `00062-hum`, `00064-taz`, `00065-fab`
  and `00066-hic` pin an image that no longer exists and cannot boot. They hold 0%
  traffic, but **there is no rollback image any more; recovery from a bad flip is
  a rebuild.** (0190)
- **Terms §9–§11 need an Indian lawyer.** Consumer Protection Act 2019 §2(46) can
  void the §11 liability cap against a consumer.
- **Apple Developer Program enrollment CLEARED 2026-08-23.** Gate A, APNs,
  TestFlight, submission and Apple sign-in on the web are all unblocked. The
  device build is VERIFIED with `project.pbxproj` untouched; both profiles expire
  **2027-08-25**, so the 7-day treadmill is over. Two follow-ons: **check the
  identity-destroying defect** flagged as possibly enrollment-gated — if it
  persists it must surface **before TestFlight** — and the product name is now
  live, forced by the App Store listing.
- **App Store collateral: the icon and the privacy labels are done; the rest is
  two dependencies.** Screenshots wait on a verified device build. Age rating and
  the support URL are simply unstarted, and the support URL is expensive to change
  once filed. The privacy nutrition labels are FILLED IN and TRACED at
  `docs/product/privacy-nutrition-labels.md` against the live system, with eight
  policy/label disagreements flagged. Four things block the FILING, all in its
  §10 — including a **`PrivacyInfo.xcprivacy` landed in the app**, which does not
  exist and is required for submission. (0242) **Those four are the labels'
  blockers, not the submission's**: read them beside punchlist Gate 1, which is
  the authority for the whole set and carries at least one more that no §10
  covers — the missing account-deletion route above.

### Deliberately not doing

- **Decision 0072's rollback path is CLOSED and DELETED** — `ContentView`,
  `SceneStatusView` and `UploadFailureView`, 719 lines plus their tests and 25
  docstrings that described the live flow by contrast with the dead one. The
  escape hatch was worth its cost in July when the design was untested on
  hardware; that risk is spent. **Four lanes edited a path no build could reach**,
  and one applied a real fix to a screen no user will see. **Dead code that keeps
  accruing unverified fixes rusts shut rather than staying ready.** Do not restore
  it as a courtesy. (0237)
- **ARKIT_ONLY placement and shell quality investment is parked.** The product is
  Pro-only / LiDAR-first; the shipped path stays live and is strictly better than
  before, but no further merge-knob grinding. The non-LiDAR device is not a test
  target and must not shape decisions. (0071)
- **There are no lockups, on either platform.** The fork between mono and serif is
  not resolved, it is DISSOLVED: the mark is the "oo" of the name, so setting the
  two together prints those letters twice. Chrome takes the mark alone; the card
  and the OG image take the wordmark alone; the iOS splash is the one place both
  appear and shows them in sequence. **Do not re-introduce a lockup as a
  convenience** — `tools/test_gen_mark.py` fails if any of six files draws the
  mark and renders the name. (0248)
- **From the founding vision, still sound:** no AR overlay, no social feed, no
  photorealistic image generation, no floor plans as a product surface, no voice
  input. Desktop-first on web.
- **The ledger is deferred with its vocabulary ban** — no pin, keep, or "put into
  words" anywhere. (0133)
- **Mirror-as-mirror was probed and cut.** What a mirror should look like is a
  design call, not a build. (0091)
- **Free rotation in proposals is out.** Rotation returned as a facing
  *correction* — one half turn, no angle, no direction — and that is a concession
  whose success condition is its own disuse. (0133, 0183)
- **`expires_at` on mint responses and content-type hardening are won't-build**,
  each with a named re-open trigger. (0087)
- **NEVER enable anonymous-user auto-cleanup in Firebase Auth.** It is off and
  must stay off — it would fire the UID-churn mechanism above for every user on a
  schedule. It is a single checkbox in the console.

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
- **The numpy/Accelerate `IndexError` in `test_shell_observation.py` is not our
  bug** — macOS/arm64 reproduces it, Linux CI passes on the same numpy, and the
  bounds guard is provably correct. **Do not clamp the indices**; that trades a
  loud crash for silently corrupt pixels.
- **`web/public/dev-fixtures` no longer exists** — 4.0 GB of real captured homes
  deleted at parking 2026-08-31. While it existed, `next build` copied `public/`
  into `out/` and only `web/firebase.json`'s `dev-fixtures/**` ignore stood
  between real rooms and a public origin. **If fixtures are ever re-staged, put
  them OUTSIDE `public/`** — that removes the hazard rather than guarding it.
- **`/track` logs 64 "Missing keys" for `freqs_cis_real`/`freqs_cis_imag` at
  model load, and that is correct.** Those are RoPE frequency buffers computed
  at init from a table the checkpoint DOES carry (`vitdet.py:552-555`), not lost
  weights; `use_rope_real=True` is the entry point's own default.
- **Cold-start coverage is thin by design.** The first `/process` request spends
  its budget on boot and model load; warm re-drives are the coverage recipe.

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
by from-import, so the test's `patch("thegoodguest_api_core.upload_session_repo.
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
declares `numpy<2`; the shared `.venv` carries **2.5.2**, and perception's
1205 tests pass on it. So a green local perception run says less about production
than it looks like, and CLAUDE.md's "cannot share an environment" is about the
DECLARED constraints (which is why CI splits the jobs), not about what actually
runs — they do share one here. This also explains why the numpy-1.26
Accelerate failure below does not reproduce locally: nothing local is on 1.26.
A worktree has no `.venv` of its own; lanes use the main tree's interpreter by
absolute path (`/Users/aubrey/projects/thegoodguest/.venv/bin/python`), which
still imports the worktree's own modules. Use it rather than the system
`python3`, which has no PIL: four perception test modules import it at
collection time, so a system-python run reports 4 collection ERRORS that look
like a broken branch and are not.

**A worktree's `packages/` edits are INVISIBLE to the shared `.venv`**, which
carries the MAIN tree installed editable — so `import thegoodguest_schemas` in a
worktree resolves to `/Users/aubrey/projects/thegoodguest/packages/schemas/...`,
and a lane that adds a function there gets `ImportError` from its own service
code while its own `packages/schemas` tests pass (that suite's conftest inserts
the local path). Prefix the run with
`PYTHONPATH=<worktree>/packages/schemas`, which does win over the editable
install — measured 2026-08-16. Same class as the roomlib trap below, and it
bites `services/*` and root runs rather than `packages/*` ones.

  **The worktree copy of `roomlib` that `selection-supply` landed splits code
  from data** — `REPO` is the worktree and `DATA` is the main tree, which fixes
  the trap below wherever that copy is used. It is a copy, not the tracked
  file: the tracked one still hardcodes MAIN, see below.
  `PYTHONPATH=<worktree>/packages/schemas` is the general form of this and is
  load-bearing whenever a lane adds anything to `packages/schemas` — it is how
  `trimmed_nn_rms` produced 20+ collection errors that looked like a broken
  branch and were the shared `.venv` resolving to MAIN.

**`outputs/room-quality/roomlib.py` hardcodes the MAIN tree at `sys.path[0]`**
(`REPO = Path("/Users/aubrey/projects/thegoodguest")`). A worktree session that
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

The iOS suite is **624 tests total** (was 590; the capture-dark pass added 20 — and 590 was itself 600 before ios-surfaces-2 REMOVED 10 by deleting the 0072 rollback path, so neither lane's own figure is main's — `FrameLuminanceTests`, the mean-luma statistic and its session census, including the preserved rp6g2 capture's own 124 readings as a fixture. Before that, 553 → 600; the scenes-client pass added 47 — `ScenesListClientTests` 17, `RoomHistoryTests` 12, `RoomsStoreTests` 11, `RoomsSurfaceTests` 7, for the `GET /scenes` client and the three surfaces it feeds. Before that, 544 → 553; the ios-surfaces pass added 9 — the flight stand-down and the launch-adoption table, both in `ScenePollExpectationTests`. Before that, 535 → 544 from the uid-churn investigation — `IdentityContinuityTests`, the launch continuity table. Before that, 523 → 535 from the Google-linking pass and 482 → 523 from the ios-residue pass. Before that, 463 → 482; the walk-findings pass added 19 — Live Activity narration, failure copy, and the recoverable count. Before that, 391 → 463 from the Live Activity / 429 / guidance pass, which added 76 and relocated 4. Before that, 352 → 391 from the release-residue pass; the release-residue pass added 39 — `CaptureReclaimTests` 15, `CaptureReaperTests` 12, `StagingHooksTests` 7, `ScenePollExpectationTests` 5. Before that, 302 → 352 from RP-6/RP-7; RP-6 added 11 — 9 co-run/wire pins + 2 envelope-edge pins — and RP-7 added 39 — `FloorPlanMathTests` 18, `FloorPlanVoiceTests` 13, `FloorPlanFixtureTests` 8. Before that, 288 → 302 from the 0074 phantom-room pass), run manually via `xcodebuild … -scheme TheGoodGuest-Integration` — the only scheme in this project (no separate default scheme, no CI gate). That scheme bakes `RUN_INTEGRATION_TESTS=1`, so the 4 `UploadSessionClientTests` **execute live on every run**; they are NOT skipped in practice. They last ran live 2026-08-24 (the capture-dark pass, 620/620) against `api-public-00042-ruq`, the whole suite in ~16 s of test execution.

**A full-suite run does NOT spend the operator's capture quota — that claim was wrong and is corrected here.** `UploadSessionClientTests` does mint a fresh `bundleId = UUID()` per test, and the daily CAPTURE ceiling (12, `UPLOAD_SESSION_DAILY_CAPTURES`, confirmed on the serving revision) is charged on first claim. **But the ceiling is per-UID, and every one of those tests calls `Auth.auth().signInAnonymously()` and signs out in teardown** — so each test runs as a brand-new anonymous user with its own untouched allowance and spends one of ITS twelve. The operator's own quota is never touched. **The evidence is `upload-flake`'s 22 consecutive full-suite runs at 600 tests each**, which could not have happened under a shared 12/day ceiling and is what forced this re-check. The original claim came from live tests failing in a way that reads like quota exhaustion; the likelier cause is the first of the two measurement traps recorded below under **"Two measurement traps"** — `CODE_SIGNING_ALLOWED=NO` leaves Firebase unable to reach the keychain, surfacing as `SecItemAdd (-34018)` underneath and `FIRAuthErrorDomain 17995` at the Firebase layer. Same cause, two codes, and either reads like a backend outage. **What IS true:** each full run creates ~4 orphaned anonymous users, and anonymous-user auto-cleanup must stay OFF (it would fire the UID-churn mechanism), so they accumulate forever. `-skip-testing:TheGoodGuestTests/UploadSessionClientTests` is still worth using for repeat runs — it is faster and it stops the accumulation — but it is not protecting anyone's ability to scan.

**What the suite does and does not cover.** It pins flow LOGIC — routing tables, restore selection, deferral scoping, poller visibility — deliberately extracted into pure functions so they are reviewable as tables instead of by reading SwiftUI. It does NOT cover rendering: a green suite is compatible with a screen whose only exit is clipped off-frame at accessibility sizes. **AX5 layout claims must be re-verified by screenshot, never by reading** (`xcrun simctl ui <udid> content_size accessibility-extra-extra-extra-large`, then a temporary app-entry swap to the screen under test); three separate review passes claimed AX coverage they did not have, and the two screens that actually failed — `AccountConflictView` (deleted since, 0216) and `QRBridgeView` (fixed; re-verified by screenshot 2026-08-22) — were both found by screenshot after being read as fine. **The sharpest thing to check is a PINNED action** (0224): home's scan button truncated to "Scan a ro…" because a notice stacked outside `HomeView`'s `ScrollView` took ~370pt at AX5 and the compression landed on the pinned sibling rather than on the scroll area. Content belongs in the scroll area; only the action is pinned. Both surfaces 0224 named — `UploadFailedBanner` and home's re-entry row — have now been screenshotted in that position, and both DID truncate the scan action; both moved into `HomeView`'s `notice` slot and are re-verified by screenshot (2026-08-24, decision 0238). **That slot now renders in BOTH home variants**, first-time and returning — a slot only the no-rooms branch could show pushes the next caller back outside, rebreaking the rule by following it. **`ScreenGallery` (DEBUG) plus `tools/ios_layout_audit.py` are now the way this is checked** — `-rs.gallery.screen <id>` renders one state from fixtures, composed the way `RootFlowView` composes it, and the audit measures the result, so a claim that the layout is consistent exits non-zero when it is not (0257). **ONE ENTRY IS ONE STATE, NOT ONE SCREEN** (0270): 36 entries for 36 surfaces read as complete and covered a state space of 83, so most screens were photographed in one of the several states they can reach and in none of the others. **Every state is now shot at BOTH sizes and the not-yet-shot list is closed** — 166 frames, 2026-08-28. Photographing the ones that had never been looked at found two defects immediately, both invisible to a green suite: the pinned action bar was transparent, so at AX5 profile drew its closing line letter-on-letter over the body copy (as did the recovery screen and the QR bridge), and a filled button's label truncated to "Scan again fr…" under vertical pressure instead of wrapping. Under Reduce Motion — which the gallery could not set until this pass, because `\.accessibilityReduceMotion` is read-only and it has to come from `com.apple.Accessibility` on the device — the splash showed **no name at all**, then the mark. **A state that can only be reached by hand-assembling a lookalike is not a state the app has**, and that is the finding rather than an entry; where the simulator genuinely cannot produce one (`simctl privacy` has no camera service) the answer is a seam in the screen's own logic, never a second rendering path. Second recurring form, same shot: `.center` is `HStack`'s default, so any glyph or button beside prose that wraps to four lines comes to rest in the middle of it — top-align it.

**Posture: fail-closed-live, not fail-open.** Each integration test calls `XCTSkipIf(!RUN_INTEGRATION_TESTS)` — the fail-open default — but because the sole scheme always sets the flag, that skip path is never taken here. With the flag set they hit the live `/upload_session` contract and go **red if the backend is unreachable**. Running the suite therefore requires a reachable backend; an offline run will fail those 4 (expected, not a regression).

**Honest count:** report as "618 asserting offline unit tests + 2 boilerplate stubs (`testExample`/`testPerformanceExample`) + 4 live integration tests (require a reachable backend)", total 624 — not a bare total: the 2 stubs assert nothing and the 4 integration tests carry an external dependency the unit tests don't. **Measured 2026-08-31, not carried forward**: `-skip-testing:TheGoodGuestTests/UploadSessionClientTests` executes **620**, and that suite holds exactly 4 tests, so the total is 624 and the offline set is 618 once the two stubs come out. The figures this replaced were 610 in one sentence and 620 in the next, and the second did not add up — 604 + 2 + 4 is 610, not 620 — so both were wrong and the arithmetic said so without anyone running anything.

**No known flakes.** The one that was recorded here — `BlobUploadManagerTests.test_gate_lastDecrement_afterDrain_firesHandler` at roughly 1 run in 15 — was a production defect rather than a test defect, and is fixed (0239): the drain gate's last-decrement trigger hopped onto the actor through an unstructured `Task` that nothing held a handle on, so the test's `await Task.yield()` was a guess at how long the hop takes. The decrement is actor-isolated now and fires the gate inside `handleTaskCompletion`'s own defer, so awaiting that call IS the signal. Measured 2026-08-24 by holding the yield-less tests fixed and swapping only `BlobUploadManager.swift`: **2 failures in 16** with the hop, **0 in 22** without it. **A red suite is now a finding, not a re-run.**

**Two measurement traps found alongside it, both cheap to hit.** `CODE_SIGNING_ALLOWED=NO` — which `.github/workflows/ios.yml` passes — makes the 4 live tests fail with `SecItemAdd (-34018) A required entitlement isn't present`: Firebase cannot reach the keychain unsigned, so anonymous auth throws and it reads as a backend outage. Build signed, or skip those 4 the way CI does. And **back-to-back `test-without-building` runs wedge one booted simulator** — 6 of 16 unpaced runs died on `Test crashed with signal kill`, 3 of them before any test ran. `xcrun simctl terminate <dev> com.thegoodguest.TheGoodGuest` plus a 3 s settle between runs removed it across 42 subsequent runs.

**Parallel-worktree note:** `GoogleService-Info.plist` is gitignored, so a fresh git worktree lacks it and the 4 live tests fail with a Firebase configure error that mimics a backend failure. Copy it from the main tree (`ios/TheGoodGuest/TheGoodGuest/`) before running the suite in a worktree; a rebuild picks it into the app bundle.

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

**CI status (2026-08-08, decision 0099):** `.github/workflows/ios.yml` exists but is **`workflow_dispatch`-only and has never executed**. It is not a gate and is not on a push trigger, deliberately: the sole scheme bakes `RUN_INTEGRATION_TESTS=1`, so an automatic run would charge the per-UID daily CAPTURE ceiling (12, decision 0098) on every push and could lock the operator out of scanning their own rooms. The workflow runs the offline subset via `-skip-testing:TheGoodGuestTests/UploadSessionClientTests` (no source change; the device build stays pinned to what is on the phone) and carries a commented-out plist-restore step naming the secret it needs. **The real unblock is a CI-only backend project or a CI service account with its own quota** — that removes the objection entirely and would let the live tests run on every push. Python and web CI ARE push-triggered; only iOS is held back.

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

**Cloud Run revision numbers are NOT chronological on `perception-obj`.** The service has produced two revisions numbered 00036 (`-xer`, RP-8; `-l9l`, the 0089/0090 security+privacy deploy), one numbered 00038 (`-ses`, the 0081/0082 wave), and `perception-obj-00037-sd9` (image `20260808-200124`, the 0104 walk-classes deploy), which served 100% for two days despite a LOWER number than 00038. Do NOT read a lower revision number as a rollback — check the image tag and the traffic split (`gcloud run services describe perception-obj --region asia-southeast1`), which are the authorities. Serving now: **`perception-obj-00074-var`**, digest `sha256:c538f699…` (the refine + arm-select flip, 2026-08-25), re-verified from `gcloud` 2026-08-25 — and note it still carries the `candidate` tag it was deployed under, which is what a post-flip candidate looks like rather than a parked revision. Its predecessor **`00062-hum`** ran `sha256:faa005c8…` (the colour deploy, 2026-08-20) and is the rollback target, held in the registry by a `serving-rollback-00062-hum` tag; it no longer carries its `20260821-010928` tag, so identify it by digest.

**SAM 3.1 is a TRACKER release, and the image path has nowhere to move to (0274).** Its only published checkpoint is `sam3.1_multiplex.pt`; `build_sam3_image_model` hardcodes the 3.0 weights and takes no version argument, so "bump SAM 3 to 3.1" is not an available action for the path `/process` and `/segment` use. `facebook/sam3.1` is a SEPARATE gated HuggingFace repo — access to `facebook/sam3` does not imply it, and the build now downloads both. **Bypassing SAM 3.1's session layer means replicating what it ENTERS, not only what it calls (0276):** `reset_state` carries no decorator and requires its caller to be inside `torch.inference_mode()`, which `handle_request` supplies; `start_session` cannot start a multiplex session at all; and the recommended entry point defaults `use_fa3=True`, a path that imports `flash_attn_interface` and casts to float8 — Hopper only, where this service is an L4. **And torch cannot move to meet it (0277):** the image is torch 2.5.1+cu121 because SAM 3D Objects pins it, so one dtype shim in `models/sam3_video.py` covers the tracker's bool CUDA sort. **A second incompatibility is the signal to split the tracker into its own service, not to add a second patch** — it needs no SAM 3D, pytorch3d, kaolin or gsplat.

**The SAM 3D clone must stay PINNED, and the reason is the layer cache as much as reproducibility.** The shared `:buildcache` is written from the pinned form, so an unpinned `git clone --depth 1` misses at layer 4 and rebuilds the mamba env and both sam3d pip installs — a ~50 minute build instead of ~10. Observed and cancelled on 2026-08-30.

**Give every concurrent lane its own Cloud Run tag (0275).** `deploy_perception.sh --candidate` uses `--tag=candidate`, which is ONE mutable pointer: a second lane's deploy moves it off the first lane's revision silently, and probes still authenticate because `segment_frames.py` and `track_frames.py` pin the OIDC audience to the STABLE url. Pass your own tag and point `CANDIDATE_URL` at it. `/track` now records `K_REVISION` in its output so a mis-addressed probe is detectable after the fact.

**Old registry images are deleted by policy, and the live one is kept BY NAME
(decision 0190).** `infra/artifact-cleanup-policy.json` is the source of truth
and is applied to the `thegoodguest` repository: keep anything tagged `serving`
or `buildcache`, keep the 3 newest `perception-obj` and the 10 newest `api-*`
versions, delete everything else under those prefixes at any age.
(`perception-geom` was outside every prefix; it was retired in 0192 and its
source removed 2026-08-31, so the hole is closed by deletion rather than by
policy.) The DELETE carries no age condition on purpose — that is what makes
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

**Service builds are UNPINNED, so a rebuild is a real variable — and a build can capture a release that is later YANKED (decision 0246).** `packages/api-core/pyproject.toml` carries ranges (`google-cloud-firestore>=2.14,<3.0`) and the transitive set is not pinned at all, so two builds of identical source can install different code. On 2026-08-24 an api-public build picked up `google-api-core` **2.35.0** during the hours it was live on PyPI; it was then yanked for "regression in `path_template.expand`", which encoded the Firestore default database id as `%28default%29` and made every Firestore read and write 500. **The cure was a REBUILD, not a pin** — pip skips yanked releases, so the next build resolved 2.34.0 unaided, and a hand-added `<2.35` would have blocked the eventual upstream fix. **The diagnostic tell:** `pip index versions <pkg>` omits yanked releases while `pip install <pkg>==<version>` still installs them, so a version that installs but is absent from the index listing is yanked; `curl https://pypi.org/pypi/<pkg>/json` carries the reason per release. **And chase the right suspect** — the traceback named `google.cloud.firestore`, which we declare and which had also moved a minor version, and it was innocent. Bisecting the two moved packages cost three `pip install` runs; pinning the obvious one would have shipped and not worked.

**A perception build that suddenly takes forever: check `PIP_EXTRA_INDEX_URL` first (decision 0182).** `pypi.ngc.nvidia.com` — first in Meta's index line, carried verbatim into our Dockerfile — went NXDOMAIN, and an extra index is consulted for EVERY package, so pip paid five DNS retries with backoff per dependency: **764 retry warnings** in one build, with `pip install -e '.[dev]'` at 25 m 38 s and still resolving when it was cancelled. Dropped 2026-08-16 (dropped, not repointed at `pypi.nvidia.com` — every recent build already resolved from PyPI proper, so removing a dead index changes nothing while adding a live one could change which wheels are selected). **The layer cache is what hid it** — every deploy since 0120 rode the cache, and the first miss fell straight into it. Two adjacent facts from the same session: the cache missed BROADLY (apt, the clone and `mamba env create` all ran) for a reason that WAS undetermined and is now measured — see the cache entry below, which closes it — and **the base image is NOT a suspect** — `condaforge/mambaforge:24.7.1-0` has not moved, verified by `rootfs.diff_ids[0]`, and an apparent difference in *compressed* layer digests is an artefact of Artifact Registry re-compressing on push. Compare diff_ids, never compressed digests, across registries. One more reading trap, which cost a wrong conclusion before the timestamps caught it: in BuildKit's plain progress output the number after a step id is **seconds since the BUILD started**, not seconds into that step.

**The perception layer cache alternated, and no longer does (decision 0199).** Until 2026-08-20 the build used `docker build --cache-from :buildcache` with `BUILDKIT_INLINE_CACHE=1`, and **the inline exporter writes cache records only for layers a build actually EXECUTED**. So a build that rode the cache published one missing every layer it had reused, and the next build rebuilt from `apt-get` down. Seven production builds alternate without a single exception — 58m, 59m, **10m**, 63m, **8m**, 60m, **8m** — and a three-layer probe reproduces it causally in under a minute (cold 27 s, hit 2 s, then **28 s off the hit's own cache**). This is what 0182 above left as "undetermined", and it is why 0163's 10-minute figure and 0182's 58-63 minute figure are both true and neither was predictive. Fixed by building with `docker buildx` on the `docker-container` driver, importing and exporting `type=registry,...,mode=max` at the same `:buildcache` ref — the registry exporter re-publishes records it imported, which is the half inline structurally cannot do. Measured on the real Dockerfile: the switching build missed at **53m58s** (predicted beforehand, and correctly), and the next build off its cache came back **49 of 49 steps CACHED in 40 s**. **Read that 40 s correctly** — it is a no-change build, so even the source `COPY` layers hit; a real source change still rebuilds and pushes from Dockerfile line 187 down, the historical **8-10 minutes**. What the fix buys is that the hit is REPEATABLE rather than every-other-time. **So: expect 8-10 minutes, and treat a 60-minute build as evidence an early layer genuinely changed rather than as the coin-flip it used to be.**

**One build must publish exactly ONE registry version (decision 0200).** buildx attaches a provenance attestation by default, which makes the pushed artifact an **OCI index** over `{real image, attestation}` — the timestamped tag names the index, while Cloud Run resolves it and pins the **child** manifest, which carries no tag. Observed live: the `20260821-010928` build pushed three versions at one instant and the revision pinned the untagged `faa005c8…`. That silently breaks decision 0190, whose whole protection is a `serving` TAG and whose `move_serving_tag` tags the image URI — it would have tagged the index and left the digest a scale-to-zero GPU service boots from untagged and deletable. `--provenance=false --sbom=false` is in the build config for exactly this and is load-bearing, not tidiness. **The tell that it has regressed is one build publishing more than one version at the same timestamp.** Related sharp edge from the same note: the Keep rule matches on tag PREFIX, so any tag beginning with `serving` (e.g. a deliberate `serving-rollback-…` hold) pins an image in the registry until someone removes it.

**The deferred-import smoke names every lazily-imported module, and the next perception build pays for it.** 0211's defect was `mask_refine.py` imported unconditionally by `process_receiver` and never COPY'd into the image, which made `main` undeployable while every test passed. The Dockerfile's smoke line carried a SAMPLE of the lazily-imported modules, not all of them, and `mask_refine` was outside it — so `892e2b9` fixed the COPY without guarding the recurrence. Merged 2026-08-25: `mask_refine`, `oidc`, `receiver_repo`, `fcm` and `process_receiver` are now named. **`server` is excluded deliberately and says so in the code** — `server.py:33` imports torch at module level, so naming it would pull torch into a build step whose budget forbids it; `process_receiver` stays torch-free and is safe. **`test_dockerfile_manifest.py` already existed for this exact incident and sat green the whole time the hole was open**, because it pinned only the COPY direction — it now ast-parses the smoke line too, and dropping one module from that line fails three of its five tests. **Editing that RUN line invalidates the layer cache from there down**, so the next perception build rebuilds the node/spz/mamba tail (~8-10 min) and produces a new digest. Expected, not a regression — absorb it on a build that is happening anyway. It changes no runtime behaviour, so it is never worth a build of its own.

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

**Read the vendored upstream before asserting what SAM 3 or SAM 3D does
(decision 0264).** The source we run lives inside the container image, so no
worktree session could read it at any price, and reasoning from our own wrapper
plus priors produced five wrong claims in one session — including two "it is off
by default" and a stale docstring that cost a GPU round trip.
`services/perception-obj/upstream/` holds verbatim copies of the entry points our
wrappers call, with Meta's LICENSE beside them (§1.b.i requires the Agreement to
travel with any copy), and the Dockerfile now fetches both repositories **by
commit** — pinned to the commits the serving image was built from, so the pin
reproduces what runs rather than moving it. `tests/test_upstream_pins.py` asserts
the Dockerfile, the README's table and the vendored files agree, and that the
vendored copy stays unimportable. The `upstream-models` skill and a `PreToolUse`
hook on the wrappers carry the rule to the next session.

**A lane that walks the room page will 404 on `dev-fixtures`** — the directory was deleted at parking and exists nowhere. The cheap fix is `tools/make_synthetic_splat.py` (~14 MB of synthetic rooms, no real capture), and the rule is DELETE THEM AFTERWARDS so nothing real or bulky can reach a build. **Cheaper still, and free, for any lane that draws GEOMETRY rather than splats: `/room?bundle=!hero` serves `web/public/hero/room.json` — the one genuinely captured room this repo ships (0122's fixture, 3.5 KB, already a tracked static file) — and `!v3`, `!old` and the six list rooms need no fixtures at all.** Nothing to generate and nothing to delete; the splat viewer 404s and everything shell-shaped renders. The calling-card lane built its whole surface this way and never staged a fixture.

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
worktree, run `npm install` in `web/`, copy the gitignored `GoogleService-Info.plist` for iOS
lanes — so the session's first act is work, not environment repair. Setup traps
that are already known: `outputs/room-quality/stage_fixed_fixtures.py` writes to
an ABSOLUTE main-tree path, so a worktree lane stages fixtures outside itself;
a worktree has no `.venv`, so Python runs via the main tree's absolute
interpreter path (verified to still import the worktree's own modules, not
main's). **`dev-fixtures` no longer exists to symlink** — it was deleted at
parking, so a lane that views rooms must generate synthetic fixtures with
`tools/make_synthetic_splat.py` and delete them afterwards. Never place real
captures under `public/`: `next build` copies it into `out/`, and only
`web/firebase.json`'s `dev-fixtures/**` ignore protects the deploy — 0122 caught
a real room's splat one deploy from a public origin.

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
github.com/feynma1h/thegoodguest (public), and `main` tracks `origin/main`. The
repo is now a single branch: `main`, tracking `origin/main`.

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

## The punchlist

**`docs/punchlist.md` is the working list of what is left before "finished."**
Entries are grouped into six gates in dependency order, written from a full
review that RAN every suite and checked the live system rather than reading this
file. Start there for "what should I do next" — the punchlist is the part
maintained as a list, and it is the only place in this repo that tracks
remaining work.

**Its rules are this repo's rules.** An entry that is done or ruled gets
DELETED, never annotated — a punchlist that accumulates closed items becomes the
retired 207-entry tracker again. New entries are added freely in the same shape.
IDs are stable and never reused.

**Some entries carry an automated check; the rest say `Check: manual` and name
who decides.** Run `python3 tools/punchlist_check.py` for the counts rather than
trusting a number written here (add `--offline` to skip the ones that hit the
network, or a filter like `G3` for one gate). It re-derives status from the live
system and prints DONE / OPEN / UNKNOWN / MANUAL. **UNKNOWN is never DONE** — a
probe that could not run reports as its own state, because "I could not tell" and
"it is finished" are different answers.

**The checker reconciles itself against the punchlist.** A probe registered for
an entry that no longer exists is never called — it does not fail, it stops
existing while still reading like coverage. Two sat that way for weeks. The tool
now reports them as STALE and exits non-zero, and
`tools/test_punchlist_check.py` pins it, along with the inverse: a `Check:` line
claiming `automated` with no probe behind it.

This exists because the failure mode here is documents going quietly out of date
rather than work being forgotten. On 2026-08-26 this file asserted CI was green
while it had been red five days, named three different serving revisions for one
service, and said the phone held no captures when it held five. Each was one
command away. **The checker does not edit the punchlist** — a green check is
evidence for a human deleting an entry, not authority to.

## Next on the board

**The project is PARKED as of 2026-08-31, so there is no board.** Read
`docs/PARKED.md` for why and for the state of the tree, then `docs/NOT-FINAL.md`
for what in here is unfinished and which parts of it go live on the next deploy.

**`docs/punchlist.md` is the forward list** — 38 entries in six gates, in
dependency order, each carrying a `Check:` line. Start there for "what should I
do next", and run `python3 tools/punchlist_check.py` to have the checkable
subset re-derived against the live system rather than believing any prose. An
entry that is done or ruled is DELETED, never annotated.

**One ruling sizes everything above room quality** (punchlist G5-03). Room
health scoring, taste graph, lighting simulation, budget-aware shopping and DAG
version history are recorded as DIRECTION, not commitment, and none is required
for "finished" unless the operator rules it so. The social layer is the one that
was already ruled a COMMITMENT (2026-08-12) and designed at
`docs/product/social-layer.md`; its rung 0, the calling card, is built and
undeployed.

**Two standing negatives, recorded so nobody re-checks them.** 0122's
hero-fixture swap has NOT fired — a warm re-drive does not re-segment, so the
hero scene still carries pre-0089 masks and stays ineligible. And 0053's
Spark-versus-WebGPU watch condition is measured NEGATIVE: Spark is not the
render bottleneck (0123).

**Keep this section short, and keep the work in the punchlist.** The hazard is
specific and has already happened here: a board that accumulates finished lanes
reads as a plan while being a log, and what falls off it is not what anybody
decided to drop — the conversational-redesign layer and the fired-trigger
backlog both simply stopped being scheduled and became sub-clauses of a numbered
list. **Drift here looks like a core feature quietly turning into someone else's
dependent clause.** An entry with a `Check:` line cannot rot that way; a
paragraph can.

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
