# What is NOT in final form

Written 2026-08-31 at parking, from a sweep of the merged `main` and the live
system — not from reading CLAUDE.md. Every claim here was checked against
`gcloud`, the deployed origin, or the source on this commit.

**Read this before treating anything in `main` as finished.** The merges on
2026-08-31 brought seven lanes in at once. Most of what they added is inert by
construction, but not all of it, and the difference is not visible from the
code alone.

**The three that will not announce themselves**, if you read nothing else:
`/segment` and `/track` are registered routes and are NOT flag-gated, so the
next perception deploy exposes both (§3); nothing here has ever run on Linux,
because CI is 136 commits behind and was already red (§8); and the Dockerfile
now needs a HuggingFace token with access to a second gated repo (§5).

---

## 1. The live system is BEHIND `main` — nothing here is deployed

Every lane merged on 2026-08-31 is unshipped. What is actually serving:

| service | serving | note |
|---|---|---|
| `perception-obj` | `00074-var`, image `c538f699` (2026-08-23) | predates **all** merged perception work |
| `api-public` | `00046-xig` | |
| `api-internal` | `00023-mek` | |
| web | `roomstudio.web.app` | serves `<title>roomstudio</title>` |

**The web is the sharpest drift.** The repo sets the product name to
"The Good Guest" in both places that own it (`Wordmark.tsx:66`,
`Wordmark.swift:43`); the deployed origin still serves the old name. The web
has not been deployed since the name landed.

**A 0%-traffic candidate is parked:** `perception-obj-00093-pav`, image
`b21408a5` (2026-08-30) — the SAM 3.1 / `/track` build. It costs nothing
idle (scale-to-zero) but it is a reachable URL with the same flags as
production.

## 2. Flag-gated behaviour — inert, and safe

Eight behaviour flags, every one defaulting to `0` in code. Merging them
changed no runtime behaviour, which is the whole point of the discipline:

`PERCEPTION_BOX_WHOLE_VIEWS`, `PERCEPTION_KEEP_LONGER_MASK`,
`PERCEPTION_VISIBILITY_VETO`, `PERCEPTION_OBJECT_AWARE_RESIDUE`,
`PERCEPTION_CONDITIONAL_SECOND_ARM`, `PERCEPTION_POINTMAP`, plus
`PERCEPTION_MASK_REFINE` and `PERCEPTION_ARM_SELECT` — which default `0` in
code and are set to `1` by the production environment, verified on the serving
revision.

**`PERCEPTION_VISIBILITY_VETO` is measured and REFUSED**, not merely off
(0234/0236). Do not read "off by default" as "untried and promising" for that
one.

## 3. Two routes that go live on the NEXT deploy — the actual trap

`server.py` registers **`/segment`** and **`/track`** beside `/process`,
`/shell` and `/compress`. Neither has ever served production traffic; both were
exercised only on 0%-traffic candidates. **They are not flag-gated.** The next
`perception-obj` deploy exposes both.

They are containment-guarded and cannot corrupt a room — each writes only under
its own probe prefix (`segment_probe/`, `track_probe/`), never under `frames/`
where `/process` reads cache, and neither touches Firestore (0260). That makes
them safe, not finished.

## 4. Built with no caller

`track_selection.py` is `COPY`'d into the image and smoke-imported, but nothing
in the service imports it — only `tools/track_select.py` and
`tools/track_views.py` do. It is dead weight in the container until something
calls it.

## 5. A build change no image has been made from yet

The Dockerfile now downloads the **SAM 3.1 multiplex weights** unconditionally,
from `facebook/sam3.1` — a *second* gated HuggingFace repo. Not flag-gated. The
next image build therefore pulls ~3.5 GB more than the last one and needs a
token with access to both `facebook/sam3` and `facebook/sam3.1`. Budget the
time and check the token before assuming a slow build is broken.

## 6. iOS seams wired to nothing

- **The app is silent.** `RSSound` is wired at three call sites; **0 cue files
  exist in the bundle** (verified by search). `play(_:)` is a no-op.
- **The app has no route to the web.** `NetworkConfig.webBaseURL` is `nil` by
  deliberate design, so every room row and CTA that would open a room is
  correctly disabled. A person who captures a room cannot reach it from the
  phone. The QR bridge encodes nothing for the same reason.
- **`LiveActivityController.pushTokenSeam`** is named and unbuilt — the Live
  Activity count freezes when the process dies, and only remote push fixes it.
- **`PrivacyInfo.xcprivacy` does not exist** (verified). App Store submission
  requires it; a complete draft is in
  `docs/product/privacy-nutrition-labels.md` §9.

## 7. Never run on hardware, or never observed live

Green tests do not cover these:

- The OS-kill relaunch gate (2b) — code complete, never run on a device.
- Terminal-failure UI — the `failed` / `failed_invalid` / `failed_incomplete`
  screens and the blob-failure banner have never rendered on hardware.
- The frame-luminance census has never seen a live camera buffer — it is pinned
  against a preserved capture and synthetic planes only.
- The 401 recovery-**success** leaf is untested; only the give-up branch has run.
- `unprompted_proposal` has never been observed in real traffic.
- RoomPlan's guidance relay has never fired live.

## 8. NOTHING here has been verified on Linux

**CI has never seen any of this work.** `origin/main` is at `bc56f9a`
(2026-08-25); local `main` is **136 commits ahead**. The last CI run was on the
old `origin/main`, so every merged lane is verified only on this Mac.

**And CI was already red.** The `python` job has failed on every run for five
days — the documented cause being `tools/test_gen_mark.py` importing Pillow,
which the root job did not install. **That fix is now in `main`**
(`pyproject.toml:22` declares `pillow>=10`), but it arrived on a merged branch
and has never run on Linux. So "CI is red" describes `origin/main`, and whether
the fix works is untested.

Push before believing any of it: the first CI run after a push is the first
Linux verification these 136 commits have had.

## 9. Test suites that do NOT run in a normal invocation

A green local run does not cover these:

- **The guest voice evals** — `services/api-public/tests/test_guest_voice_evals.py`
  is gated on `RUN_VOICE_EVALS=1` plus an `ANTHROPIC_API_KEY`, and makes real
  model calls. It is skipped by default and was skipped in every count above.
- **The 4 iOS live integration tests** — they need a reachable backend, and the
  sole Xcode scheme always sets `RUN_INTEGRATION_TESTS=1`, so they go red when
  the backend is down. Offline runs fail them by design.
- **18 tests are never collected by the default command.** `pytest` uses
  `testpaths`, which collects **946**; `pytest packages services tools
  --ignore=services/perception-obj` collects **964**. Both are called "root" in
  this repo. Always write which command produced a count.

## 10. Broken by the parking cleanup, deliberately

Deleting the captures and `web/public/dev-fixtures` left two things pointing at
nothing. Neither is a defect to fix — they are waiting for fresh captures:

- **`/viewer` will 404.** The dev workbench fetches `/dev-fixtures/<dir>/assets.json`
  or `/dev-fixtures/manifest.json`; both are gone. `/room?bundle=!hero` still
  works — `web/public/hero/room.json` is a tracked 3.5 KB file and needs no
  fixtures, which is the cheap way to walk a room page.
- **23 perception tests skip**, plus most of root's 102 skips, all
  `skipif`-guarded on absent fixtures.

Regenerate fixtures with `tools/make_synthetic_splat.py` (~14 MB, synthetic,
no real capture) and **delete them afterwards** — `next build` copies
`public/` into `out/`.

**One path correction while here:** the hosting config is at
**`web/firebase.json`**, not the repo root. Its `dev-fixtures/**` ignore is
present and intact (verified) — the guard CLAUDE.md describes is real, the
path it implies is not.

## 11. Registry — cleaned, and the rollback path is gone

Three `perception-obj` versions remain, which is the documented steady state:

- `c538f699` — `serving`, the live image `00074-var` boots from
- `b21408a5` — the parked candidate `00093-pav`'s image
- `c45098c5` — `buildcache`

**There is no rollback image any more.** `faa005c8` and its
`serving-rollback-00062-hum` hold were deleted 2026-08-31, along with two
untagged builds. That was sanctioned by 0243 once `00074-var` was trusted, and
it means revisions `00062-hum`, `00064-taz`, `00065-fab` and `00066-hic` can no
longer boot — they pin an image that is gone. They hold 0% traffic, so nothing
serving is affected, but **if `00074-var` ever fails there is nothing to fall
back to.** The cure would be a rebuild, not a rollback.

The `serving` tag on `c538f699` is what stops the cleanup policy from
reclaiming the image a scale-to-zero GPU service needs. Never delete it.

## How to re-derive all of this

`python3 tools/punchlist_check.py` re-checks the subset that can be checked.
At parking it read **1 done · 4 open · 5 unknown · 20 manual** across 30
entries. **UNKNOWN is not DONE** — it means the probe could not run.

Everything in section 1 comes from `gcloud run services describe <svc>
--region asia-southeast1` and a `curl` of the live origin. Re-derive rather
than trusting this file after any gap; that is the failure mode this repo has
had repeatedly.
