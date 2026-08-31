# The Good Guest (GCP project id still `roomstudio` — immutable)

**PARKED 2026-08-31 — read `docs/PARKED.md` first, then `docs/NOT-FINAL.md`,
which lists everything in this tree that is not finished and says which parts
of it go live on the next deploy.** The tree is one branch (`main`), one
worktree, and carries no room data: every capture, fixture and cloud scene was
deleted at parking. The one standing risk is that `main` is the single copy of
everything and is ahead of `origin`.

A spatial intelligence product that helps people discover the best version of their home: AI-powered room analysis, conversational redesign, and an immersive 3D representation of *their own* space.

This file is the always-current state of the project. Both Claude Code (reads it automatically) and Claude Chat (you upload it) consume it at the start of every session. If something in here is wrong, fix it before doing anything else.

## What we're building

**The thesis: every home contains a version of itself that its owner has never seen. This product makes that version visible, understandable, and achievable — one conversation at a time.** Every feature decision filters through this. The full founding vision lives at `docs/product/initial-idea-draft.md` (verbatim, with what's superseded vs durable mapped in decision 0055) — read it before making product-surface decisions.

This is NOT an "upload → generate a 3D scene" showcase. The 3D reconstruction is the *medium*; the product is helping people make AI-based decisions about improving their room. Three product layers frame everything: the **AI layer** (understands space structurally — object relationships, traffic flow, light, proportion — with algorithmic spatial analysis before any LLM is invoked, and reasoning traces on every design decision), the **emotional layer** (feels personal, not algorithmic — the experience bar is Linear/Vercel/Figma-tier premium consumer software; conversation is the primary post-reveal interface; the cinematic reveal is the defining moment; design language is Apple-grade restraint — the chrome stays quiet so the room carries the colour — in the warm Good Guest palette of 0057, which SUPERSEDES 0056's neutral-chrome-and-one-sans reading: the app ships parchment and ink with three type roles, the guest's serif for prose and mono for machine data only, and the **social layer** (rooms are identity — sharing, comparison, evolution over time). Direction, not yet commitments: room health scoring, taste graph, lighting simulation, budget-aware shopping, DAG version history. Deliberately out (per the founding draft, still sound): AR overlay, social feed, photorealistic image generation, floor plans, voice input; desktop-first.

**Naming: SETTLED 2026-08-23 as "The Good Guest" (0245)**, forced by the App Store listing when enrollment cleared. It is the register the whole product was built in (0072/0057) and the metaphor the calling card is already named from. Set as a STRING in three places — `web/src/components/Wordmark.tsx`'s `BRAND_NAME`, iOS `RSBrand.name`, and `INFOPLIST_KEY_CFBundleDisplayName` in `project.pbxproj`, which is what the Home Screen shows and which cannot read either constant (`tools/test_gen_mark.py` fails if they drift). **Until 2026-08-26 the Home Screen read "TheGoodGuest"** — the main target had no display name and fell through to `TARGET_NAME`, outside every "the name lives in N places" claim this file ever made. The card no longer prints the name at all: it carries the wordmark, which is a drawing. **The repo, GCP project, buckets and `roomstudio:` localStorage keys deliberately keep the stand-in** — infrastructure, invisible, expensive to rename for no user-visible gain. **The card still prints `roomstudio.web.app`, which is the TRUE hosting URL**: changing that string without moving hosting would print a falsehood on an artifact that leaves the browser. Re-open trigger is commerce, and renaming stays cheap until App Store submission — TestFlight needs only an app record.

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
  perception-geom/                VGGT for the photo-upload path (source only — the service and its image were retired 2026-08-20, decision 0192)

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
describe this tree: perception **1198 + 41**, web **276**, schemas **126**
(`pytest packages/schemas/tests`);
root **844 + 102** by bare `pytest` (which uses `testpaths` in `pyproject.toml`);
root **849 + 102** by `pytest packages services tools
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
  the counts it wanted cannot be obtained (0216). There is deliberately no iOS
  sign-out. `IdentityContinuity` classifies each launch (`continuous` /
  `firstRun` / `credentialLost` / `keychainUnavailable`) and logs it at fault
  level without changing behaviour (0141).
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
copy renders through (0270).

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

### api-public — `api-public-00046-xig`, image `20260825-213937`

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

### api-internal — `api-internal-00023-mek`

`--no-allow-unauthenticated`, Cloud Run IAM gated. Hosts `/ingest/eventarc` and
nothing else. Validates in order: `schema_version`, bundle_id cross-check
against the URI, image decodability (pre-GPU), `device_id` presence, and
declared-blob presence (0105). A rejection is a `failed_invalid` or
`failed_incomplete` Scene with a structured log and HTTP 200 — never a bare 400.
Terminal-failure scenes are stamped with `expire_at`; revival clears it; `ready`
is never stamped.

### perception-obj — `perception-obj-00074-var`, image `sha256:c538f699…`

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
  that hands the box to whoever was photographed first (0274). It does NOT fix
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
- `Wordmark.tsx` draws the two interlocking rings from generated geometry and remains the
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
  `workflow_dispatch`-only on purpose — see the iOS test policy. **Web is green;
  PYTHON IS RED and has been since 2026-08-21** (measured 2026-08-26). The root
  suite dies at COLLECTION with `ModuleNotFoundError: No module named 'PIL'`:
  `tools/test_gen_mark.py` landed that day importing Pillow, which is declared
  only in the two perception pyprojects and so is absent from what the root job
  installs via `tools/ci_deps.py`. The other three jobs pass, so the run fails
  on one red job among four. **Nothing gates on CI, which is why five days
  passed unnoticed** — and it means the root suite has not actually executed on
  Linux since then, however green it is locally. The fix is one declared
  dependency, not a test change.
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
- **The FUSED cloud makes orientation WORSE, and the same-mass rule is dead**
  (0225). Coverage for visibility questions, PURITY for orientation ones. A
  box-clipped cloud accumulated over every keyframe medians a **0.0287**
  axis-assignment margin against 0081's masked single-view **0.15-0.47**,
  clears the shipped 0.10 gate on **1 of 20** boxes, and **7 of 20 winners
  move** under cloud perturbation. That last number refutes the claim
  everything here rested on — that clutter cancels across rotations of one
  splat because the point set is identical. The mass IS common; its COST is
  not, because rotating a table moves its legs relative to a bag that stays
  put. **The 180-degree sign speculation dies with it** and the sign stays
  where 0171 put it. Re-opens only on a per-object cloud accumulated through
  each frame's own SAM mask — a purity mechanism, not more views.
- **The OOM is HEADROOM, not size, and no retry reaches it** (0228). See the
  open-defect entry; the refused half is that **downscale-and-retry is out**
  even though the arithmetic green-lights it (a halved request fits 12 of 12
  box views), because 0197's bidirectionality means an altered input yields
  **a different object under the same identity** with nothing able to detect
  the swap. Generalised: *where a fallback must choose between altering the
  input and not running, it must not run.* **A deferred retry at a frame or
  object boundary is also out** — refuted before implementation, needing no
  measurement: the existing retry already runs after `gc.collect()` +
  `empty_cache()` with no other object in flight, so the queue it would defer
  into is already empty.
- **A tighter floor tolerance inside a box restores FLOOR, not feet** (0232).
  0.08 m looks like a room-scale number misapplied at object scale; it is
  sized for the floor plane's own error. Open floor sits up to **+4.3 cm**
  above RoomPlan's plane, so 0.02 is inside the noise, and 96-100% of the
  restored points vanish by tol=0.06 where a leg would thin out linearly. The
  real fix is a floor level estimated LOCALLY from each box's own depth, and
  it needs its own registered prediction — the numbers to beat are that the
  restored points must NOT collapse between 0.02 and 0.06. **No env switch
  ships**: a control that fires into a defect under a conservative default is
  worse than one that never fires, because the metric it moves reads as
  improvement (the inverse of 0225's unfireable gate).
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

- **The per-box shortlist's overlap score is FLAT, and a repair now has a
  measured route** (0262–0271, capture `90eebfc4`). `mask_overlap_with_hull` is
  precision with no recall term: **31 of 52 candidates score exactly 1.0000** in
  that room and 27% across the four older captures, after which `frame_index` —
  capture order — decides. Where SAM 3 returns one object at two nested extents
  the sort takes the shorter in **9 of 10** pairs that associate to a box;
  **keep the longer** is right **9 of 9** against the operator's rulings and
  needs no gate, no score and no box (0266, which supersedes 0263's gate). The
  desk's NEAR foot lies ~3 cm outside its measured box, which is what costs it
  the pick; the SECOND leg is **100% inside** the box, so the box is not the
  obstacle there. A click placed on the missing part takes second-leg coverage
  **0.1% → 75.0%**, and merging every candidate that kept what it was given
  retains 100% of the seed and near foot. **The keep-the-longer rule is now
  BUILT and OFF** behind `PERCEPTION_KEEP_LONGER_MASK` (0274) — 4 of 25 boxes
  across the four captures change their planned views, three to a longer mask in
  the same frame, none losing an association, byte-identical off. The click
  repair is NOT built: the pointer was a human eye, and no automated search
  found the region. **Read
  `outputs/segment-quality/targets/README.md` before quoting any coverage
  figure**: the denominator is a rectangle that includes floor, so every such
  number understates what was recovered.
- **`90eebfc4` carries LiDAR depth on 1 frame of 189** against 99–100% on all
  four older captures, correlating with iOS 26.5.2 → 26.6.1 on the same phone
  and the same app build (0267). That disables mask refinement, `depth_fit` and
  0231's band detector for the whole room, and **nothing in the pipeline reports
  it** — tier is derived from the RoomPlan room, not from whether depth arrived.
  Cause needs one scan to confirm; a depth-bearing frame count in the manifest
  is the cheap fix and is independent of the cause.
- **The repair and the chooser are RULED ON and flip together, refine first**
  (0198/0201, 0204/0205, 0211/0212; operator sitting 2026-08-23). **Both are
  SERVING** on `perception-obj-00074-var` since 2026-08-25, re-verified from
  `gcloud`; the entry stays here for the measured residue below, not because
  anything is unshipped.
  SAM 3D's input is RGBA with **alpha = the SAM mask** (`models/sam3d.py`), so an
  incomplete mask deletes from the model's input what the photograph actually
  contains. On a 0%-traffic candidate the repair reproduced 0198's bench **to
  the pixel** — 58,386 → 61,439 mask px at IoU 0.9493. `PERCEPTION_ARM_SELECT`
  then moved exactly one object: rp7's desk. **The chooser did not change —
  refinement changed what it was choosing between**, which is why these are one
  decision and why refine goes first (0212). The measured COLD flag rate is
  **10 of 37** planned box views (rp7 1/12, rp6g1 3/10, rp6g2 2/5, spike 4/10),
  against the warm 9 of 25 that 0201 priced from — a warm room understates it.
  **What the sitting measured that the flag report did not:** the headline
  "0.321 → 1.122" is **one axis, and it is the box's HEIGHT** — `arm_fit`'s
  `fill` divides the rendered vertical span by `box.dimensions[1]`, which for
  this box is 0.795 m, not the 0.660 m narrowest axis both this file and the
  throughput charter used to name. In the box's own axes the
  refined desk is 0.734 × 0.877 × 0.665 against a box of 1.291 × 0.795 × 0.660
  — **width falls to 0.569 of the box** and the three-axis error goes
  **0.626 → 0.644 m, marginally worse**. It is not rotated: its longest extent
  is 0.877 m against the box's 1.291 m, so it is a **partial object** — the
  sit-stand desk's right-hand leg assembly plus a stub of top. **The operator
  ruled ON having seen this**, on the merits: class-6 truncation is endemic,
  and an object standing on its measured floor at the right height beats a
  desktop floating 47 cm up. **Do not re-report the width as a fresh defect.**
  The third Chamfer axis (0233) rides `ARM_SELECT` and needs no env of its own
  (`PERCEPTION_ARM_S2C_MIN_CLOUD` is a threshold, not a gate); the
  band-decomposed claim rate (0231) is inert and has no flag.
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
- **`PERCEPTION_VISIBILITY_VETO` is MEASURED and stays OFF — a veto is a
  re-roll, not a filter** (0234, 0236; drive run at review 2026-08-24 on the
  serving revision with both other flags off). 0234's restriction — reject
  only, never rank — is airtight about ORDER and says nothing about how much
  of the answer moves: a vetoed (frame, box) pair leaves its box uncovered, so
  the greedy cover pass spends an extra pick, which changes the seed AND the
  count of the farthest-point residue, and the residue re-rolls. Measured
  offline through production's own selector: **16 of 48 frames change across
  the four captures** — rp7 5/12, rp6g1 8/12, rp6g2 3/12, spike 0/12 — where
  0234 reports a three-frame change. On rp6g1 **one** band-vetoed pair moves
  **8 frames**. The GPU drive then answered 0234's blocker, and
  **answered it mostly favourably** — corpus detections **228 → 250, +10%**
  (rp7 +46%, rp6g2 +10%, spike 0, rp6g1 **−12%**, the only room that falls —
  and there the objects RoomPlan does not box, which is what the residue
  exists to serve, go **33 → 27**). **The check the flag was held on is
  not the check that decides it.** On the output-side instrument it is 0197's
  bidirectionality again — rp7's chair **0.655 → 0.083** and rp6g1 gains a
  box that had no arm at all, against rp7's bed **0.419 → 0.799** and rp6g1's
  nightstand **fill 1.169 → 0.223**. **The sharpest cost is invisible to a
  flags-off run, which is every measurement 0234 took:** the veto removes
  rp6g1 f178 and rp7 f114, which are not those boxes' shipped arms but their
  better ALTERNATIVES — the one walked arm-select switch and mask
  refinement's target. Replayed through `choose_arm` over rp6g1's two
  selections, the nightstand is the whole argument in one row: today it has
  **two** arms and arm selection correctly refuses the bad one (fill 1.169
  kept over 0.223); under the veto it has **one**, so the chooser has nothing
  to choose and **fill 0.223 ships**. **The veto shrinks the candidate set
  arm selection exists to search** — 0212's enable order already puts the
  veto last, and this is the stronger reason for it. A supply change and a
  chooser cannot be evaluated apart. **rp7's bed is the same argument from
  the other side and it indicts 0205 rather than the veto**: both f294 and
  f363 are in the veto's selection, so the chooser HAS the better arm — f294
  wins the three-axis error by 0.38 m — and refuses it, because f294
  overshoots vertically (fill 1.404) where f363 sits at 0.946 and unanimity
  requires both axes. **0205's measured hole now has a price**, which is the
  trigger that note was waiting for. Two follow-ups in 0236: **split the
  flag** (veto 1 removes two frames that produced literally 0 detections and
  is free; veto 2 causes the whole cascade), and **contain the cascade** by
  relaxing a vetoed box's own bar in place rather than buying an extra cover
  pick. Also measured and general: **adding a frame can replace a good arm
  with a worse one on association overlap alone**, which is a property of
  association rather than of this flag.
- **The object→frame map is BUILT and its ids are measurably unstable — the
  tracker survives a visit, not a revisit** (0279). Mean box purity **0.6404**
  over all six RoomPlan boxes — 30 concepts, all 189 frames, 48 instances of
  which 6 are boxed and 42 are not — against bands fixed in `tools/track_map.py`
  BEFORE the first GPU run (0.90 stable, 0.70 marginal), so 0271's instruction
  applies: report the number, do not build on the raw ids. **Coverage is not
  the problem** — 0.73-0.97 of the frames where a box is on screen have
  something claiming it. The failure is re-acquisition: four of six boxes have
  their object arrive as THREE ids in disjoint frame windows
  (`nightstand#1/#2/#3` at frames 15-27, 79-100, 131-142), and 25 of 42
  competing claimant pairs share no frame at all, which rules out the reading
  that two neighbours are arguing over one hull. It is not a clean rule: `bed#0`
  and `cabinet#0` hold one id across 28- and 124-frame absences. **The sting is
  for 0271's plan** — the box is what you would need to REPAIR the tracked
  instances, and the nine unboxed kinds have no such repair. **The obvious
  box-free merge is already measured and insufficient** (0280): pooled
  mask-centroid ray triangulation separates known-same (median 0.182 m) from
  known-different (0.327 m) by only 1.8x with heavy overlap, because a chair
  tucked under a desk is 0.088 m away by that instrument.
- **The SAME-FRAME half of that identity problem IS exactly answerable, and it
  is a different duplication from 0279's** (0281). `/track` runs one concept
  per pass, so one object is claimed by every prompt that fits it in the SAME
  frames — `artwork#0 ≡ painting#1` over 54 shared frames, `monitor#1 ≡ tv#0`
  over 38, a wardrobe's `door` nested inside its `cabinet`. Measured over all
  48 overlapping pairs the split is bimodal with **nothing in the middle**: 14
  pairs at containment 0.996-1.000, then 0.511 (a speaker on a desk), then
  ≤ 0.047. Merging them takes the capture **48 instances → 34 objects** in 11
  groups that all read correctly. **This is why an occlusion rule cannot use a
  bare union of the other masks** — applied literally it reports eight
  instances as ~99% occluded by duplicates of themselves. It does NOT touch
  0279: `nightstand#1/#2/#3` share no frame, so 34 still over-counts what is
  perhaps 15 objects.
- **Nine objects have no uncut view at all, and the border margin is the one
  number that decides it** (0282). Of `track_selection.py`'s three hard
  filters, border rejects **768 of 1,241 detections (61.9%)** against
  too_small's 79 and occluded's 55 — they are not peers, and an argument about
  stage 1 is an argument about one threshold. Even mask-touches-edge with no
  band refuses 57.7%, because 0273's rotation-paced capture runs large
  furniture off the frame. **Two of the three objects 0259 recorded the
  operator naming come back exactly** — `desk#0` → 50 and `chair#0` → 42, from
  tracked masks rather than projected hulls. The bed is the disagreement and
  it is the margin: at 2.5% all 87 of its frames are refused, at 0.5-1.0% it
  keeps four and picks **f0**, the operator's own choice. **The threshold
  ships as specified and was deliberately not tuned to the bed** — tuning to
  the one case that can be checked would stop it being evidence. What is owed
  is the operator's eye on the nine fallback objects.
- **`/track` is bounded by frames × objects on the L4, and the bound is not
  ours to remove** (0278). Every OOM lands in one allocation — the detector
  grounding a batch of frames, 1.27 GiB, with 1.0-1.2 GiB free — and the
  headroom is eaten by per-object tracker state that has nowhere to go: the
  multiplex `init_state` sets no `storage_device` and takes no
  `offload_state_to_cpu`, while `Sam3BasePredictor.start_session` passes exactly
  that argument. `PERCEPTION_TRACK_GROUNDING_BATCH` (default 4; 1 disables
  batching) is the lever, and it is an env var so the next turn costs a revision
  rather than a build. At upstream's 16 the capture OOM'd at 189 frames AND at
  63; at 4 it completes 189 in ~78 s a concept.
- **The shorter of two nested same-label masks is the one without the legs,
  and `/track` only ever offers the shorter one** (0283). Operator-reported
  on the desk and confirmed: SAM 3 returns a legged and a legless reading of
  one object, the shortlist's precision-only sort takes the legless one
  (0261), and SAM 3.1's tracker reproduces that shorter reading on **all 78**
  desk detections — longest tail 100 px against SAM 3's 533. **Cross-label,
  not a desk quirk:** all six nested pairs in the 19 probed frames (desk,
  monitor, door, chair) have the larger instance reaching **+0.111 to +0.288**
  of the frame further toward the floor, never the other way. Two excuses are
  measured dead — a stride-4 round trip costs ≤0.4% of area and a 4 px bar
  survives intact. **This names a candidate mechanism for class 6** via 0198
  (alpha IS the mask), and 0283 carries the ~25 s GPU test that would settle
  it. **The tracker cannot be fixed into carrying both readings** — read from
  SAM 3.1's source, the multiplex VIDEO builder sets `det_nms_thresh=0.1`
  with `det_nms_use_iom=True` and gates new objects on
  `mask_iom >= assoc_iou_thresh=0.1`, while `build_sam3_image_model`
  configures neither. The desk pair sits at containment **0.995**, ~10x both
  gates, so exactly one reading survives and score decides which. **This is
  the video path, not the version.** The knob (raising both thresholds above
  0.995) also disables NMS and would worsen 0279's already-UNSTABLE ids — do
  not reach for it. **Prompting is measured dead too** (0283): of eight
  phrasings on frame 50 only `desk` and `sit-stand desk` ground at all, and
  they return the SAME masks (IoU 0.9954 short, 0.9889 long); `desk with
  legs`, `desk leg` and four others return NOTHING. A compositional phrase
  does not extend a silhouette, and `desk leg` failing also closes the
  prompt-the-part-and-union route. **The resolution is architectural and free: let `/track`
  choose the FRAME and the image path produce the MASK**, which is what
  production already does. **Two traps:** the capture is rotated 90°, so a mask profile taken by
  image ROW measures a horizontal world axis and wrongly reports no
  difference — project gravity first; and do NOT fix this by preferring the
  larger mask, since the door pair jumps 7.62% → 23.15% and that rule takes a
  doorway over a door.
- **Class-6 splat truncation is untouched and has no live route.** Reconstructions
  are missing legs, bases, and backs. Every placement fix to date positions or
  orients an incomplete reconstruction better rather than completing it, and all
  three attacks on the cause are measured dead above. What remains is decision
  0052's standing trigger: a different model — one that consumes several views
  itself, or exposes calibrated metric scale or pose.
- **CUDA OOM is the largest measured loss in the corpus** (0228) — **22 of 163
  detections**, twelve of them box views, and **two boxes lost their only
  compatible mask**. It is **capacity, not scheduling**: the models hold
  ~16.4 GiB, the forward pass PEAKS at 5.23–6.43 GiB, and the card has
  **5.26 left**. Read the peak, not the request: **21 of the 22 failing
  allocations are 0.500–0.861 GiB**, the median box-view shortfall is 133 MiB
  and three cases miss by 16 MiB, so this is headroom rather than object size
  — mask area does not predict it at all (Spearman r = −0.009 over an 84×
  area range).
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
  a room that has been the thin case in every round of analysis.** Re-read
  every prior conclusion drawn from it — including the 53-item budget-starved
  tail and the 0-of-45 colour result — against this. **The cause is settled and
  is NOT the app (0240): the operator's hand covered the lens** for the last
  5.7 s of a 32.8 s capture. The RGB carries 150–250 kB of red-dominant sensor
  noise rather than a blank buffer — a zero-filled YCbCr buffer renders mid
  GREEN, not black — the frames show fingers arriving at f95, and the depth map
  turns at f96 into a plane at 0.39–0.59 m, flat to ~1 cm, that holds its
  distance while the phone walks a metre. **Do not re-open this as a pipeline
  stall**; what would re-open the class is a dark run with *room-scale* depth
  behind it, which is what 0241's logging now makes visible.
  **Measured 2026-08-24 for the `capture-dark` lane:** the two black frames
  the shipped sampler takes, f103 and f119, read mean luma **2.46** and
  **1.88** and produce **0 detections each** — SAM 3 finds literally nothing
  in them, so they consume two of that room's eight cover picks and return
  nothing. That is independent of the veto and true of today's production.
- **An unmatched RoomPlan box has FIVE causes and the two anyone looks for
  are the smallest** (0227). Of nine unmatched boxes across the four
  captures: 2 PLAN_SKIP, 2 DETECTION, 1 OOM, 1 COMPETITION, 1 SAMPLING, 1
  NEVER_FRAMED, 1 LABEL. Four carry family-compatible masks at up to overlap
  **1.0000** and are invisible to association only because `ok=False` — no
  splat, so not an observation. Every failure is recorded faithfully in its
  frame's `objects.json`; nothing aggregates them, which is why four boxes
  had their answer written down and unread. **Two of the declined label
  matches (rp6g1 b04, rp6g2 b09) are NOT label problems** — both have good
  uncontested `cabinet` masks that OOM'd or were policy-skipped. The declines
  stand; do not re-open them as label cases. rp6g2 b07 is confirmed LABEL.
- **A window ships with ~30° in-plane skew.** Near-square planar objects are
  ~90°-ambiguous to the model and no instrument scores in-plane orientation.
- **The "cabinet behind a wall" is not the declip bound** (0104). The declip pass
  never engages: the object's centre projects outside every wall rectangle. Start
  from that fact, not from `PLACEMENT_SPLAT_CLIP_MARGIN_M`.
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
- **Two voice evals are flaky, both measured 2026-08-24 rather than guessed.**
  `TestFacingCorrection::test_a_piece_with_no_second_way_round_is_refused_plainly`
  misses about **1 run in 4** — it asks the guest to turn a rug with no measured
  box and greps its reply for a refusal word, so the miss is phrasing, not
  behaviour. `TestTalkingAboutARoomNotAnInventory::test_a_referent_the_previous_turn_fixed_is_not_re_asked`
  misses about **1 run in 13**, on `main`'s charter and the current one alike.
  Re-run before believing either, and **measure with the rate harness rather
  than by re-running the test and counting pass/fail** — 0215 records why that
  is not a rate. **The other long-recorded flake — "one setup asks about an
  ambiguous wall roughly 1 time in 8" — is probably not a flake and its rate
  was understated.** 0186 measured that setup refused 9 times in 26, and one
  refusal was verbatim "only works if you tell me which wall". Re-measure
  rather than assuming it is gone: 0186's fix took the same setup to 14/14.
- **Rule 10's literal "would" has collapsed — 2/16 against 12/16 when 0174
  measured it** (0215) — while the property the rule states holds at 14/16, so
  the evals now grade the property. **0214 was the obvious suspect and is
  RULED OUT**: on a paired, interleaved A/B of its provenance opening, the two
  arms do not separate (2/16 vs 4/16, p = 0.33) and the arm with the suspect
  clause REMOVED is still far below 0174's rate (p = 0.006). Removing it does
  not bring the word back. The remaining explanation is the model behind
  `GUEST_MODEL`, which is the suite's own trigger 2. **Do not re-open this by
  re-running the test and counting pass/fail** — that method is what made the
  first attempt uninterpretable.
- **The voice evals RAN 2026-08-24 and 0213/0214's deploy gate is CLEARED**
  (26 passed, 1 failed at `PROMPT_VERSION 6`; the single failure was not in
  either of them). They found two defects underneath that work — 0186's charter
  contradiction and 0215's instrument — both now fixed on `main`. **The
  `ANTHROPIC_API_KEY` was never absent**: `anthropic-api-key` has been in
  Secret Manager since 2026-07-21 and the operator's own account can read it;
  nothing had connected it to the harness, and the belief that it was missing
  cost that lane two days.
- **`PROMPT_VERSION 7`'s voice evals are GREEN — 27 passed, 2026-08-24 — so
  the deploy gate is CLEARED.** The run before it read 26 passed, 1 failed on
  `TestTalkingAboutARoomNotAnInventory::test_a_referent_the_previous_turn_fixed_is_not_re_asked`,
  which was measured rather than argued about and is a **pre-existing flake**:
  paired and interleaved against `main`'s charter it reads **19/20 on both
  arms** (33/36 vs 34/35 pooled, p = 0.32). It is a PER-SAMPLE assertion, so
  the test goes red whenever one sample misses. **Do not re-report it as a
  regression, and do not attribute it to 0186 or 0220** — 0220's resolver is
  separately ruled out offline, because in that room `"it"` resolves to
  `unknown_object` with an EMPTY detail before and after, and `"chair"` differs
  only in a tail that is strictly more decisive afterwards.

**iOS**

- **The mark's fill rule is guarded on the Python side only.**
  `tools/gen_mark.py` warns that even-odd across both rings punches holes where
  the bands cross, and `tools/test_gen_mark.py` pins it by building the wrong
  version and asserting ours differs — but nothing pins the Swift or TypeScript
  CONSUMERS. The generator warned, the test passed, and iOS's splash re-made the
  mistake anyway (0255). All six other surfaces that draw the ring pair were
  audited and are correct, so this is a latent gap rather than a live defect:
  the fix is a consumer-side pin, not a better docstring.
- **Notes has no past.** The design gives news an "EARLIER" list of observed
  facts; that needs the phone to remember what it previously saw and diff
  successive fetches, which nothing does today. Deferred by operator ruling; the
  section does not render rather than showing an empty shell. The arrival card
  is deferred with it, since detecting an arrival is the same change detection.
- **The menu peek's two greys are literal hexes**, given by the design brief and
  named in one place in `MenuPeek.swift`. They are the only colours in the app
  outside the token system and will not follow a brand repaint.
- **The pinned-action rule reached ONE screen out of eleven when measured**
  (0253, 2026-08-26) and is now applied everywhere by `RSActions` (0257). Kept
  for the finding, not as an open defect: 0224's
  rule — content scrolls, only the action is pinned — is implemented on
  `HomeView` (action outside the `ScrollView`) and `GuidanceSheet`
  (`safeAreaInset`). Every other screen puts its primary action inside the
  scroll region. **Home itself PASSES**: "Scan a room" wraps rather than
  truncating, so 0224's fix holds — but with all three notices present the
  scroll region above it collapses to roughly one visible notice, and nothing
  says the other two are below. **`RoomsListView` loses its action entirely** —
  the screen ends mid-sentence in its footer and "Scan another room" is off the
  bottom, on the one screen where a scan action and room history already share
  space. **`FailureView` shows no action on arrival** — a fixed 200pt art block
  takes the top third and both buttons are pushed off, on a screen whose copy
  promises "exactly one concrete path". Both are reachable by scrolling, which
  is why the suite is green and why reading did not catch them. **Both named
  screens are now CLOSED and neither by a layout change to itself**: the rooms
  list was replaced by `HouseView`, which carries no scan action at all because
  capture is home's gesture, and `FailureView`'s two buttons moved into a
  `safeAreaInset` and are pinned on arrival at AX5 (photographed 2026-08-28).
  What the finding leaves is the rule, not the two screens.
- **One filled button in the app carries a glyph, and two deliberately do
  not** (0270; photographed, not decided). The guidance sheet's denied CTA is
  `Label("Open Settings", systemImage: "gear")`, while the two buttons that
  START a capture — home's "Scan a room" and guidance's own "Start scanning" —
  ship bare, because at button size the product's own mark collapsed into a
  smudge and Apple's stock viewfinder was worse than nothing. Nobody applied
  that reasoning to the third button. **This is a consistency question, not a
  layout one, and it is ALL that is left of it**: the recorded complaint used
  to be that the label wrapped at AX5 and the gear came to rest beside "Open"
  alone — 0258's control-label clamp fixed that, and the label is one line at
  every size the app renders. Re-photograph before re-reporting the wrap.
- **`WhySignInSheet` is presented by no call site** outside the screenshot
  gallery, so the invitation the rooms count exists to make is never made; its
  checklist also reads "Your 1 rooms stay exactly as they are" while the
  sentence above it correctly reads "one room", the two count words being
  written in different places. **Deliberately NOT fixed**: 0237's rule is that
  dead code accruing unverified fixes rusts shut rather than staying ready, and
  a copy fix to a screen with no route is exactly that. Give it a route or
  delete it; do not tidy it.
- **`RoomRow` centres its thumbnail against wrapped text** (0253). At AX5 the
  derived title and the status line each wrap to two lines and the tile comes to
  rest between them rather than beside the title. Exactly the `.center`-is-the-
  default form the notice components were already top-aligned to avoid; the row
  was missed because it is drawn in a different file from the notices.
- **A keyframe's manifest entry survives its JPEG failing to write** (0240).
  `acceptFrame` appends to `capturedFrames` synchronously while the encode and
  the write happen later on `jpegQueue`; both failure paths log, count, and
  return without removing the entry. So the bundle can declare a frame whose
  file was never written. **This is a MISSING file, not a dark one** — 0105's
  declared-blob check turns it into `failed_incomplete` — and no capture has
  been observed hitting it; the stop-time verification already counts accepted
  vs written vs on-disk but does not reconcile them. Found while ruling the app
  out of the rp6g2 dark tail, deliberately not fixed there.
- **The luminance census has never run against a live camera buffer** (0241).
  It is pinned against the preserved capture's readings and synthetic planes
  only. A real scan on a re-signed device build is the confirmation, and it is
  the operator's. The one thing it would settle that offline work cannot is
  which luma range ARKit vends on this hardware — the code reads the format and
  handles both, so a wrong assumption shows up as a scale error, not a crash.
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
  silent. The web has no sound at all. **The branded-fonts claim was true of iOS
  and false of the web, and is now stated per platform:** the web loads real
  Google faces via `next/font/google` (Instrument Sans, Source Serif 4, and
  JetBrains Mono since 0248); **iOS bundles no font files at all** and
  `RSFont.swift` falls back to the spec's system substitutes — New York, SF Pro,
  `.monospaced` — behind a named bundling seam that says to change only the
  private face helpers. The web lockup no longer needs re-cutting: there is no
  lockup (0248).
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

- **The scene lease expires mid-job on 70% of runs, and what actually prevents
  double-processing is not the lease (0286).** `SCENE_LEASE_TTL_SECONDS`
  defaults to 300 and is unset in the deploy script, while the claim is taken
  after model load and the request may run to 900 s. Measured over 66
  production runs (logs 2026-08-05 → 2026-08-25): lease held **median 613.5 s,
  max 899.8 s, 46 of 66 over the TTL**. Two unrelated guards have been doing
  the work — api-internal's `DISPATCH_DEADLINE_SECONDS = 930` exceeding the
  900 s Cloud Run timeout, and `--max-instances=1 --concurrency=1` — so the
  lease has been wrong throughout with nothing consulting it. **One thing does
  consult it:** `tools/reenqueue_scene.py` uses the lease as its "is a worker
  active?" test, so on an actively-processing scene it says PROCEED without
  `--force` and dispatches a second task. **The fix is one number — TTL 960 s,
  above the request ceiling — and it is not applied.** Nothing would detect a
  violation: `lease_expires_at` is never passed to `_log_lease_action` so it
  logs `none` everywhere, `RECLAIMED` reads identically for an expired and a
  cleared lease, and the holder guard's rejection is a bare `return` after
  which the worker reports 200 "ready" having written nothing.
- **The lease-expiration branch has never run in production, and the reference
  scene for it is gone (0286).** Three `reclaim_stale` events in a month of
  logs, every one preceded by a `release_error` from the same worker — all
  eager release. The load-bearing branch is unit-tested only.
  `f077e9ed-d339-4be8-8dbf-37b952abfec2` was the canonical stuck-scene
  reference and was deleted with everything else at parking; its bundle had
  survived the captures sweep (the lifecycle rule carries
  `matchesPrefix: ["captures/"]` and the bundle sat under `smoke-test/`) and is
  gone too. **`reenqueue_scene.py` could not have run the test anyway** — it
  resets to `queued` before dispatching, which erases the expired lease that is
  the subject. Re-testing now means constructing the state deliberately on a
  fresh capture and dispatching without the reset.
- **The SIGTERM lease-release path has never fired, and may be unable to
  (0286).** 0 of 65 scenes ever carried a `shutdown_release_count`, and nothing
  outside tests reads that field. `run_perception` is a synchronous call from
  the async handler with no `to_thread`, so it blocks the main thread for the
  whole run; Python delivers SIGTERM there at a bytecode boundary, so a signal
  arriving inside a long CUDA or GCS call is lost to the 10 s drain. **A
  cycle-limit gate on `shutdown_release_count` is REFUSED rather than
  deferred** — Cloud Tasks already caps the loop at `maxAttempts=3`. The
  residual failure is a scene left in `queued` forever with no terminal state
  and no FCM, which wants a stale-scene sweep, not a counter.
- **Alerting and monitoring do not exist and the deferral is unrecorded.** An
  unrecorded accepted deferral is indistinguishable from an oversight. Record
  the acceptance or schedule the work.
- **A second, unrestricted Firebase browser key exists** (no referrer
  restriction, 27 APIs). The key the web app ships is properly restricted.
  Closing the gap breaks the live-authed-check path every recent api-public
  deploy uses — ship a replacement first.
- **The `perception-obj` image count sits ABOVE 3 by design, and a high count is the policy working rather than a fault (0190).** The keep rule is *the 3 newest PLUS anything tagged `serving` or `buildcache`* — never "exactly 3", because a lane iterating on builds pushes the live image out of the top three, and exactly-3-by-recency would then delete the image Cloud Run is running on a scale-to-zero GPU service. On 2026-08-20 three undeployed builds landed and the live `20260813-222442` sat **4th, held only by its `serving` tag**; the policy evicted `20260816-050851` automatically when the third arrived, so the count is pinned at 4 (worst case 5) and self-maintaining. **The fix for a high count is to deploy or delete the surplus builds, never to tighten the policy.** Billing confirms the mechanism: ₹420/day at 1,446.7 GiB is ₹0.2903/GiB-day (= AR's $0.10/GB-month), Aug 19's ₹140 implies a 482 GiB daily average as GC drained, and the state after the geom retirement is 154.3 GiB ≈ **₹45/day, 89% below**. Two of those four images are undeployed and untagged, worth ~₹22/day — **untagging frees nothing; deleting the version is what reclaims it.** **Measured 2026-08-31, after the parking cleanup: THREE versions**, which is the steady state rather than a coincidence. `c538f699` is the live image (`20260824-013501` + `serving`), `c45098c5` is `buildcache`, and `b21408a5` is the parked candidate `00093-pav`'s image. **The rollback hold is gone**: `faa005c8` and its `serving-rollback-00062-hum` tag were deleted along with two untagged builds, which 0243 sanctioned once `00074-var` was trusted. The consequence is real and worth stating — revisions `00062-hum`, `00064-taz`, `00065-fab` and `00066-hic` pin an image that no longer exists and cannot boot. They hold 0% traffic, so nothing serving is affected, but **there is no rollback image any more; recovery from a bad flip is a rebuild.**
- **Terms §9–§11 need an Indian lawyer.** Consumer Protection Act 2019 §2(46)
  can void the §11 liability cap against a consumer.
- **Apple Developer Program enrollment CLEARED 2026-08-23** (filed 2026-07-22).
  Gate A, APNs, TestFlight, submission and Apple sign-in on the web are all
  unblocked. **Of the three things that followed, the first is DONE:**
  (1) **the device build is VERIFIED — 2026-08-25.** It built with
  `project.pbxproj` UNTOUCHED, which retires the personal-team
  `CODE_SIGN_ENTITLEMENTS` workaround; both profiles were freshly issued and
  expire **2027-08-25**, so **the 7-day treadmill is over**; and the app
  installed and ran on the 16 Pro. The Team ID `3HU2SP8346` is unchanged from
  every pre-enrollment build, so enrollment kept the team and only extended
  profile validity — meaning the keychain access-group prefix was never a
  variable, which independently corroborates 0138. (2) **check 0115** — the identity-destroying
  defect was flagged as possibly enrollment-gated, and if it persists it was a
  real bug hiding behind the gate and must surface **before TestFlight**;
  (3) **the product name is now live**, forced by the App Store listing.
- **App Store collateral: the icon and the privacy labels are done; the rest
  is two dependencies.** **Screenshots** wait on a verified device build.
  **Age rating and the support URL** no longer wait on the name (settled,
  0245) — they are simply unstarted, and the support URL is expensive to
  change once filed. **The privacy nutrition labels are FILLED IN and TRACED**
  at `docs/product/privacy-nutrition-labels.md` (0242): every Apple category
  answered against the LIVE system rather than the policy, the
  material-inference vision call named explicitly (0089), and eight places
  where the shipped Privacy Policy and the labels disagree flagged rather than
  reconciled — three with drafted corrections. Four things block the filing,
  all listed in its §10: the vendors' own retention/training terms confirmed
  (Privacy Policy operator note 2, open since 2026-08-08), two judgment calls
  ruled, the server-log question ruled, and a **`PrivacyInfo.xcprivacy` landed
  in the app** — it does not exist, it is required for submission, and a
  complete draft plist is in §9 for an iOS lane.

### Deliberately not doing

- **Decision 0072's rollback path is CLOSED and now actually DELETED**
  (operator sitting 2026-08-23; executed 2026-08-24, decision 0237).
  `ContentView`, `SceneStatusView` and `UploadFailureView` are gone — 719 lines,
  plus `SceneStatusViewTests`, four `ScenePollExpectationTests` assertions, and
  25 docstrings across 14 files that described the live flow by contrast with
  the dead one. The escape
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
- **There are no lockups, on either platform** (0248). The fork between mono
  and serif is not resolved, it is DISSOLVED: the mark is the "oo" of the name,
  so setting the two together prints those letters twice. Chrome takes the mark
  alone; the calling card and the OG image take the script wordmark alone; the
  iOS splash is the one place both appear and shows them in sequence. The mark is
  identical everywhere (0193). **Do not re-introduce a lockup as a convenience** —
  `tools/test_gen_mark.py` fails if any of six files draws the mark and renders
  the name.
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
declares `numpy<2`; the shared `.venv` carries **2.4.4**, and perception's 746
tests pass on it. So a green local perception run says less about production
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
github.com/feynma1h/thegoodguest (private), and `main` tracks `origin/main`. The
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
Thirty entries in six gates, in dependency order, written 2026-08-26 from a
full review that RAN every suite and checked the live system rather than reading
this file. Start there for "what should I do next"; this section below is
narrative and historical, and it decays — the punchlist is the part maintained
as a list.

**Its rules are this repo's rules.** An entry that is done or ruled gets
DELETED, never annotated — a punchlist that accumulates closed items becomes the
retired 207-entry tracker again. New entries are added freely in the same shape.
IDs are stable and never reused.

**Eleven of the thirty carry an automated check.** Run
`python3 tools/punchlist_check.py` (add `--offline` to skip the five that hit the
network, or a filter like `G3` for one gate). It re-derives status from the live
system and prints DONE / OPEN / UNKNOWN / MANUAL. **UNKNOWN is never DONE** — a
probe that could not run reports as its own state, because "I could not tell" and
"it is finished" are different answers.

This exists because the failure mode here is documents going quietly out of date
rather than work being forgotten. On 2026-08-26 this file asserted CI was green
while it had been red five days, named three different serving revisions for one
service, and said the phone held no captures when it held five. Each was one
command away. **The checker does not edit the punchlist** — a green check is
evidence for a human deleting an entry, not authority to.

## Next on the board


**READ THIS FIRST. The numbering below is historical and cross-referenced throughout this file; it is not priority order.** As of 2026-08-13 the operator's queue is DONE except external paper (see the queue paragraph below) — the next build session is unblocked on everything it was waiting for: the clip sign is ruled, the walk verdicts are in, the social layer is ruled a commitment, and perception's live gate closed on a real scan. Item **8** — the render-payload P0 — outranks everything else for BUILD, App Store collateral included: people cannot see their rooms yet. Item **9** — conversational redesign — is the product's own definition and runs in PARALLEL as a design session, because design costs no code and touches none of item 8's files. Item **10** holds the backlog an audit of all 103 re-open triggers turned up — fired conditions nothing was scheduling — and it carries one operator RULING that must not be allowed to drift the way item 9 did: **is the social layer a commitment or a direction?** Items 9 and 10 are the standing proof that this section decays in a particular way: nothing was decided about them, they simply stopped being scheduled and became sub-clauses. **When this section gets stale, the project's drifting — and drift here looks like a core feature quietly turning into someone else's dependent clause. Keep it current.**

**ALL FOUR 2026-08-10 LANES MERGED, plus the 0108 mock-string chip; every worktree removed and every branch deleted. As of 2026-08-13 the repo is ONE clean tree at `main`, in sync with origin, with NO sessions in flight.** | lane | worktree · branch | decisions | scope | |---|---|---|---| | clip A/B | REPORTED + MERGED 2026-08-10 (0112; 0113 unused) | done | walk DONE 2026-08-12: measured won, flip shipped (`3755bad`) and deployed to production. | | api-public polish | REPORTED + MERGED + DEPLOYED 2026-08-10 (`api-public-00036-duv`; 0114/0115 later consumed by the phone session) | done | outcomes in 0107/0108/0124. | | iOS Google linking | REPORTED + MERGED 2026-08-10 (0118/0119; suite 535) | done | phone leg + web copy retirement remain — see the What-works bullet and the operator queue. | | ops | REPORTED + MERGED 2026-08-10 (0120; 0121 unused) | done | perception-obj platform-gated, tombstone swept, build cache seeded — all live-verified. | **Held deliberately:** per-room deletion (collides with the api-public lane; product-shaped), 0062 frame coverage (GPU-cost-entangled; the item-7 walk and the next real scan reshape it), the social-layer ruling (operator's). The two lane-B notes are written (0142 `/compress` as a stage, 0143 `extent_axes_m` as a declaration). **THE OPERATOR QUEUE — EXECUTED 2026-08-12/13 (all five steps; session record in gitignored `outputs/operator-queue-2026-08-12.md`).** Closed: the clip-sign walk (measured wins, shipped, deployed to production), the item-7 second walk, the reveal's two questions, the social-layer ruling, and the whole phone session — real scan (perception's live gate), the disruption capture (0114), the identity switch and the reclaim leaf (0115). **WHAT REMAINS ON THE OPERATOR — one short sitting, then paper:** (0) **the clipped-views sitting, the only one pending — SUPERSEDED 2026-08-20, see the clipped-views entry below; the walk pack remains at gitignored `outputs/clipped-views/walk/README.md` (decisions 0197/0198). rp6g1's table is a floating slab today and a table with four legs in a reconstruction that is *already in the bucket*; rp7's desk goes the other way — and the 0198 bench then fixed rp7's desk too, by refining its mask (the pack's bench section shows it). Nothing ships until they answer, and the change it gates computes nothing new. Then: (1) **Apple Developer enrollment is STUCK, not merely pending** — filed 2026-07-22, still unapproved three weeks on against a typical <48 h; worth contacting Apple Developer Support or checking for an unseen identity-verification hold, because it gates Gate A, APNs, TestFlight, submission AND the 7-day re-sign treadmill — and per 0115 it may also be gating a defect that destroys user identity on every device build. (2) App Store collateral: the **app icon is DONE** (`8bf01d4`, decision 0176 — three iOS 18 appearances, device-verified at 60/40/29pt; the site's favicon now cuts from the same geometry, `6af4661`); still **nothing started** on screenshots, support URL and age rating — the **privacy nutrition labels are DONE** (0242, `docs/product/privacy-nutrition-labels.md`), traced against the live system and naming the material-inference vision call per 0089. (3) The Indian lawyer on Terms §9–§11: **not engaged**. (4) The 0115 churn investigation — no longer an operator item at all: its decisive first step ran and killed the entitlements/access-group hypothesis (0138), and the leads that remain are source-level rather than device-level. Parked with named triggers, NO action unless one fires: the material re-bake (0070 wants reference-room re-adjudication first), the second unrestricted Firebase browser key. **Re-sign clock: 2026-08-19 07:15 UTC.** **The clipped-views lane RAN 2026-08-20 and is MERGED (0197/0198).** Probe 1 answered the charter's narrow question with a split — one legless table fixed outright by a view already in the bucket, the other made worse by its own — so the sort key was refused. Three operator-directed GPU bench rounds followed, all on 0%-traffic candidates with predictions registered first; **all three named objects are now fixed by changing what SAM 3D is shown**, and the lever is the MASK, not the crop (0198). Production served `00044-m5p` throughout and all bench state is deleted and verified. **The sitting is superseded**: the operator blessed the spike f142 table live ("much better"), walked the rp7 desk after catching two defects, and holds the chair A/B — no formal A-or-B verdicts were recorded and none are owed. What it leaves is the `object-aware-sampling` lane, whose bottleneck it named: the sampler is object-blind and the chair's good view was never sampled at all. **The ROOM QUALITY session RAN (2026-08-13, decisions 0146–0156); its walk RAN, its two resulting corrections are in, and it is MERGED to `main` and SERVING as `perception-obj-00043-yiz`.** Three defects are closed and committed — contact tilt, the phantom support surface (rp7's monitor was resting on the chair tucked under its desk), and the label fork that split one monitor into two objects — see the What-works bullet for the measurements and the What-does-NOT-work pair for what was refuted. **The walk RAN, the branch is MERGED, and lane C has now SHIPPED it — `perception-obj-00043-yiz`, all four rooms re-driven on it, live reproducing offline at the float64 limit (0163/0164).** **THE THREE BANKED SITTINGS RAN 2026-08-19 and all three are answered** (`outputs/sittings/verdicts.md`; decisions 0177/0178/0183): the facing sign stays OFF and keeps collecting, the seating anchor was no-change-pending-lane-D, which 0166 has now closed without delivering legs, so 0177's question needs a new trigger, and the guest-voice pair became one scheduled charter revision. **Lane D RAN 2026-08-19 and reported a negative (0165/0166) — see the What-does-NOT-work bullet; nothing substantive is unblocked on this board now.** The lane-C pack is at gitignored `outputs/lane-c-walk/WALK.md`, built from LIVE manifests, and carries exactly ONE decision that is genuinely theirs — which face of its measured box an under-filling splat is seated against (0148) — now with the third option built as a `-vfill` viewer variant so the narrow form can be judged rather than imagined. **Two things the session settled that change what comes next.** The capture-side half of the brief is answered NEGATIVE and with numbers: the capture already contains 22–156 good views of every piece of furniture, the pipeline uses one or two, and supply does not predict quality (r = +0.018 across a 40× range) — so per-object capture-sufficiency feedback is NOT built (0150), and the deliberate re-scan is worth running as a TEST of that prediction rather than as an expected improvement. View selection is refuted across seven features and two instruments (0146). **The one line of attack left on class-6 was probed and priced (0151), and has since been MEASURED and refused (0166):** two reconstructions of one object do not already align (centres 0.11–0.78 m apart, frames 10–52°, RMS 0.07–0.42 m), trimmed ICP appears to close all of it, and the scale-drift + mutual-coverage check says it honestly closes 2 of 6 — the bed pairs inflate one cloud 70–90% and end at 5–22% mutual coverage. **RMS is not the acceptance criterion here**, and the next session to reach for this will otherwise reach for it. Worth knowing why it matters: a union of registered reconstructions has honest proportions, and 0081's finding is that extent consistency is misleading *under truncation* — so this is the only route that could reach the rotation ceiling without re-running an instrument already measured dead. **HANDED OFF 2026-08-13 as four lanes — prompts at gitignored `outputs/handoffs/room-quality-next.md`, decision blocks assigned per lane inside it.** A = the facings, scoped as a PRODUCT decision (0133's descoped conversational rotation) rather than a sixth instrument, since five families are now refuted — **DONE 2026-08-13 (0157/0158/0159), MERGED, and SHIPPED 2026-08-14 by the ship-facings lane (0172/0173) — evals green live at PROMPT_VERSION 4, serving as `api-public-00038-qiv`**; B = the selection experiment — **DONE 2026-08-14 (0160/0161/0162), the GPU spent (~17.5 min, two rounds on rp6g1), env reverted and the room restored byte-identically; NOT merged.** Answer is NEGATIVE: a 1.7× sharper view seeing 2.1× more surface reconstructed WORSE, so no selection score was built even behind a flag — see the three What-does-NOT-work bullets. **What D inherits from it:** the budget lever does not widen D's baseline (36.2° vs 35.5°, max 82.5 vs 88.3 — a wider baseline needs different frames, not more views per box), and D's case is strengthened from the other side by 0161's fidelity 0.777 — added surface does survive into the object, so a union has headroom that single-view selection does not; C = deploy — **DONE 2026-08-13**, serving, re-driven, fixtures re-staged, pack built; D = the multi-view union — **DONE 2026-08-19 (0165/0166), NOT built.** An oracle registration against measured truth adds nothing to the union's marginal value (+0.057 vs +0.063 with no registration at all), so registration was never the constraint; a second reconstruction adds +0.06 coverage while adding off-surface mass, 1.76x the points, and — in all three rendered cases including the best by the metric — a visibly doubled object. It also closed the de-occlusion gate as a negative; **E = the facing-sign probe — DONE 2026-08-14 (0170/0171), MERGED, not deployed.** The sign WAS unmeasured rather than unmeasurable: the layout rotation reads it, bimodally, and gets both of the operator's reported failures right and a third object wrong. It ships flag-only; what it owes is one operator sitting (`outputs/lane-e/WALK.md`) and, if they say yes, an env-only `PLACEMENT_FACING_SIGN_APPLY=1` on the next perception deploy. **It also corrects the premise this lane was launched on:** 0169's room-geometry table cannot grade a sign instrument at all. RoomPlan's box local **+Z is the object's front** — 23 of 25 wall-backed boxes across the four rooms present −Z to the wall, p ≈ 1e-5, the two exceptions being chairs at desks whose +Z faces the desk — so every box carries a measured facing DIRECTION; but a direction is not a label, because deciding whether a rotation is right needs the splat-local direction of the splat's own front and the room has no opinion about that. The table grew from 12 rows to 21 and from 5 labels to 5 labels (0170). The session's offline harness lives at gitignored `outputs/room-quality/` — `roomlib.py` is a replica of the production `RefinementContext` over all four preserved captures, **trust-gated to reproduce every shipped view choice and box object exactly — and note what that gate does NOT cover: lane C found the replica handed fusion no room planes, silently killing the single-view contact-prior path and mispredicting three free objects (0163). Fixed; re-read any probe conclusion about free objects.** Plus 18 probes and the walk/fixture builders; read the report's last section before rebuilding any of it. **What remains, in order:** (a) the operator's sitting on the shipped rooms — the deploy is done; (b) **class-6 truncation itself, still untouched by anyone and now with NO live route** — every fix so far places or orients incomplete reconstructions better rather than completing them, and all three attacks on its cause are measured dead: better selection (0162), a measured pointmap (0181), and the multi-view union (0166). What remains is decision 0052's standing trigger — a model that consumes several views itself, or exposes calibrated metric scale or pose — which 0166 sharpens into the reason it is the right trigger: the disagreement between two views has to be resolved INSIDE a model, not downstream between two finished objects; (c) the object-blind residue — **attacked 2026-08-21 and BUILT OFF (0202), with the share corrected**: it is 75–83% of the budget on rp7 and rp6g1 but only 33–42% on spike and rp6g2, because cover picks track box count (3+9 and 2+10 against 7+5 and 8+4). Measured, the shipped residue IS the box-free answer on all four rooms. Spending it on boxes takes starved boxes 14 → 2 and usable views 48 → 60 with no extra frames. 0203's objection — that it buys arms nothing chooses between — is CLOSED by the selection lane (0204/0205, MERGED-pending): the chooser is built, off, and byte-identical off, and both flags now wait on the same operator sitting at gitignored `outputs/selection/walk/WALK.md`.

**ALL THREE PARALLEL LANES MERGED 2026-08-09** (`stage2` → 0135–0137, `perception-emit`, `ios-residue`; worktrees removed, branches deleted). Merged-tree verification: root **724 passed + 10 skipped**, perception **704**, web **204**, iOS **523**, tsc clean, zero conflict markers. **What the lanes left owed, now written:** lane B's two notes are 0142 (`/compress` as a third `/process` stage rather than a sidecar) and 0143 (`extent_axes_m` declared per box, horizontals deliberately unnamed). The `dims` correction is lane C's **0137**, reached independently — there is no third note on it.

**Decision numbers.** **Always derive the free list from `git ls-tree main --name-only docs/decisions/`, not from this paragraph** — it has lagged five times. **And `git ls-tree main` ALONE IS NOT ENOUGH: union `main` with every UNMERGED branch.** Verified 2026-08-23 — `selection-supply` holds **0225–0235** unmerged, so `ls-tree main` reports all eleven free and would cost a collision the same day. **Re-verified 2026-08-24 with five lanes in flight**: 0186, 0215, 0219–0220 and 0239–0242 are live on unmerged branches and invisible to `main`. Scan `refs/heads/` AND `refs/remotes/`. **A merge does not settle this** — `selection-supply` landing moved twelve numbers at once, so re-derive after every merge, not once a day. Not a bare `ls`: that reads the WORKING TREE, and a lane worktree is routinely behind main. Reproduced 2026-08-21 — both live lane worktrees sat four commits back, where `ls` showed 0192 and 0193 as free while both were taken. `git ls-tree main` is correct from any worktree without syncing, and is the form to use. As of 2026-08-25, with selection-supply, ios-surfaces-2, capture-dark, guest-closure and perception-deploy merged: **free are 0083, 0092, 0093, 0113, 0121, 0128, 0134, 0144, 0145, 0167, 0168, 0189, 0194, 0195, 0196, 0246+** — **0083, 0092 and 0093 were never created and are cited nowhere.** **Reserved and UNWRITTEN: 0244 to perception-deploy** — deliberately NOT freed even though that lane has now landed; it may still write it. **0239 is SPENT by upload-flake** (the last decrement fires the gate in its own turn) — **nothing is unmerged now.** **0242 is SPENT by privacy-labels** (a privacy disclosure is measured, not described). **0243 is SPENT by perception-deploy** (the flip is three assertions); **0186, 0215, 0219–0220 by guest-closure**; **0225–0236 by selection-supply**; **0237–0238 by ios-surfaces-2**; **0240–0241 by capture-dark**; **0252, 0258 and 0270 are SPENT by the ui-screenshots lane**; **0253–257 are SPENT by the ui-organisation lane**; **0259–0265 are taken by the two perception lanes**;  **0273-0280 by sam31-object-map** (the SAM 3.1 tracker and the object→frame map); **0281-0283 by track-selection** (same-frame duplication is exactly answerable; the border rule is the whole filter; the short mask is the legless one); **0245 by the name swap**. Everything else through 0245 is used.

Two durable lessons, both learned by collision. **Put a session's number block INSIDE the prompt body**: a block written in a chat heading once reached nobody and two lanes claimed the same numbers, and the room-quality session was handed one stale block in its prompt and a different one in its handoff. When a prompt and this file disagree, **this file and the handoff win** — a prompt is written once, these are maintained. And **two sessions sharing one tree is how a note gets dropped**: decision 0179 was lost by the sam3d-pointmap merge and restored by `546281e`, which is why the Tooling conventions now insist every session gets its own worktree.

**The lesson from running three at once, recorded because it nearly cost a collision:** the coordinator wrote each lane's decision block in a chat heading rather than inside the prompt text, so NO session received one and lane C reasonably took the next free numbers — which were lane A's. Only the fact that A and B had not yet written a note prevented a real clash. **Put the block inside the prompt body, every time.** Second lesson, same session: decision 0130's cross-lane handback never reached the session it was written for — the coordinator is the only relay, and re-derivation was luck.

**1 — Post-conventions placement thread: merge the fix branch, then ARKIT_ONLY position quality + LiDAR variant.** The 0063 convention probe CLOSED 2026-07-23 (decision 0065; see What-works): conventions fixed incl. the basis correction, deployed (`perception-obj-00028-hzq`, carries all branch code), production-verified (upright median 4.1°, sign tests pass, 12/12 frames, room visually corrected). Remaining on this thread: (a) DONE — `perception-layout-convention-fix` is merged (confirmed in `main`'s history 2026-07-23; every branch except the parked `diag-bundlepb-reason-public` is merged); (b) **ARKIT_ONLY placement quality — chunks A–C BUILT + merged 2026-07-23, now SERVING** (branch `placement-quality-build`, merge `3f26fcc`; probe verdicts in decision 0068): the code shipped with the 0069 shell deploy (`perception-obj-00032-km5`, 2026-07-24 — that revision built off main, so it carries chunks A–C too), the placement LIVE gate is now PARTIALLY MET: the whole `PLACEMENT_REFINE` pipeline (chunks A–D + the new room-sanity gate) was live-verified via a warm `/process` re-drive of `f3d70236` on `perception-obj-00033-zfg` (2026-07-24 — 24 objects / 7 placed, the gate demoted exactly the four operator failures; see What-works), so only the operator `/viewer` walk remains — and it is now DEFERRED under the board-item-7 Pro-only pivot (possibly moot). `PLACEMENT_REFINE=0` is the rollback lever. The re-opened in-plane instrument fork for near-square planar objects (0068) still stands (not a deploy blocker). **Chunk D (single-view contact priors) BUILT + merged 2026-07-24** (branch `placement-chunk-d`, commits `724b7a5`/`78e4d2e`; built onto the shared `room_planes.py` 0069 extracted — no anchor-interpretation duplication; offline-verified against `f3d70236`'s real planes, see What-works). Its live gate RAN 2026-07-24: the warm `/process` re-drive of `f3d70236` on `perception-obj-00033-zfg` placed 5 single-view objects on measured surfaces (chunk D) and the total placed count jumped ~2 → 7; only the operator `/viewer` walk confirming furniture-on-floor / wall-objects-on-walls remains, now DEFERRED under the board-item-7 pivot. **Sampling-starvation insight (operator-flagged 2026-07-24):** the thin walls + missing furniture in real outputs are pipeline-side, not capture-side — only 5 of `f3d70236`'s 184 frames completed with masks, and single-view objects can't triangulate; the cures are warm re-drives (complete more frames cheaply), `PERCEPTION_MAX_FRAMES` (placeholder=12), and chunk D's contact priors (place single-view objects from ONE view). VIO-calibrated monocular depth deferred with named re-open triggers; (c) **LiDAR variant of the placement event — parked on Pro hardware** (board item 3 runbook applies first); 0063's don't-trust warning lifted in principle, zero real executions; (d) opportunistic: coverage knobs stay one-capture-calibrated (17/22 single-frame objects can't triangulate — `PERCEPTION_MAX_FRAMES` is one lever; 0067 chunk D's contact priors are the complementary one). (Phase 8c soak: RUN AND GREEN 2026-07-22 pre-dating this session's deploy — the new revision `00027-n8c` has since served the full re-drive successfully, which is its own functional soak; the RUNBOOK 8c one-liner can re-run on the next quiet day if desired. The former ops decision — deleting the pre-split `api` Cloud Run service — was operator-approved and executed 2026-07-21; Cloud Run runs exactly api-internal + api-public + perception-obj — perception-geom was retired 2026-08-20, decision 0192.)

**2 — iOS P5 — OS-kill hardware gate** (decisions 0029, 0044, 0045). Core poll + status UI shipped (P5(a), commit `dbe3188`). **The OS-kill hardware gate is CLOSED and 0045's Fork A is ANSWERED** (0085, 2026-08-08, iPhone 16 Pro): `bundle.pb` reached GCS ~25 s after a reopen with no interaction, and on the `StagingHooks` `exit(0)` route `.task` fired on a background OS-relaunch with the phone locked and the app never reopened — so the AppDelegate co-trigger is **unnecessary** and its ordering constraint is moot. Do not re-stage this by force-quitting: force-quit is not OS-kill and produces zero background relaunches (0114). The `diag-bundlepb-reason-public` branch that carried the redacted-`reason=` one-liner has been deleted; the line itself is preserved in `docs/PARKED.md`, to be re-applied temporarily if a fatal blob error ever needs reading. Remaining: FCM `ready`/`failed` — backend threading is done (cleanup pass: Scene.fcm_token → ClaimResult → notifiers), so what remains is iOS-side FCM registration and passing the real `fcm_token` at `/upload_session`. Cold-start poll recovery is DONE (ios-upload-robustness, 2026-07-21): the cold-launch auth race is fixed (`ec57285`), simulator-verified. NOTE post-activation: relaunch poll recovery lives in `RootFlowView.restoreUnfinishedBundle` + `BundleRestore` (decision 0073); the old root that used to carry it is deleted (0237). The three status-surface honesty findings are CLOSED (branch `ios-status-surface`, 2026-07-21) — no open follow-up on this surface. **Separately, the iOS app DESIGN is built AND ACTIVATED as the app root** (decisions 0072/0073 — the Good Guest capture app: `DesignSystem/` foundation + every screen + the `RootFlowView` navigation coordinator; nine review passes; 288 tests). **The capture-to-doorway walk RAN 2026-07-26 on the 16 Pro — PASS** (two real captures; upload-under-lock, 26897de catch-up, background trip, relaunch restore, doorway exits all green — see What-works). Remaining on this surface: the three terminal-failure UI screens — staged as of 2026-08-07 behind DEBUG `StagingHooks`; the sitting ran and its verdicts, including the 0045 Fork A decision table, are decision 0085; the 0074 HARDWARE VERIFY is DONE (RP-6 Gate 4, 2026-08-05). Then the Live Activity's hardware verification (task #14 BUILT 2026-08-08, simulator-only — folds into the same sitting; task #13 shipped as RP-7) — then the remaining activation follow-ups in `RootFlowView`'s docstring (add-more resume, web-handoff link). Terminal-failure UI (`failed`/`failed_invalid`/`failed_incomplete`, blob-failure banner) has still never rendered on hardware — exercise opportunistically when a real failure occurs or stage one deliberately.

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

**5 — DONE 2026-08-08: the purge ran and the repo has a remote.** `git filter-repo` removed the nine HEIC blobs (verified: zero HEIC objects in history, no commits touching them), `tools/remap_doc_shas.py` remapped the doc SHA citations, and `origin` is `github.com/feynma1h/roomstudio` (private). The slot is kept numbered because it is cross-referenced elsewhere in this file; nothing remains on it.

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
