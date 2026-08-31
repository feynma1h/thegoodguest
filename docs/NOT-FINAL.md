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

## 1. Everything IS deployed now — to a new project

Superseded 2026-08-31. The whole stack was migrated to a new GCP project,
`thegoodguest`, and every surface is live and verified:

| surface | state |
|---|---|
| `thegoodguest.web.app` | 200, titled "The Good Guest" |
| `api-public` | 200 |
| `api-internal` | 200 (403 unauthenticated, IAM-gated) |
| `perception-obj` | 200 on L4 GPU, `serving` tag on its image |

Verified as a path rather than as health checks: CORS preflight from the live
origin returns the matching allow-origin, the served CSP names the new API
host, and anonymous sign-up against the shipped web key returns 200.

The old `roomstudio` project is DELETE_REQUESTED and recoverable until roughly
30 September 2026. **There is no fallback environment any more.**

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

## 3. Two routes are now LIVE on a serving revision

**This fired.** The migration deploy exposed both: the serving revision's route
list is `/ /compress /health /process /ready /segment /shell /track`. Neither
had ever served production traffic before; both were previously exercised only
on 0%-traffic candidates, and neither is flag-gated.

They are containment-guarded and cannot corrupt a room — each writes only under
its own probe prefix (`segment_probe/`, `track_probe/`), never under `frames/`
where `/process` reads cache, and neither touches Firestore (0260). That makes
them safe, not finished.

## 4. Built with no caller

`track_selection.py` is `COPY`'d into the image and smoke-imported, but nothing
in the service imports it — only `tools/track_select.py` and
`tools/track_views.py` do. It is dead weight in the container until something
calls it.

## 5. The SAM 3.1 layer, now built once

The Dockerfile downloads the **SAM 3.1 multiplex weights** unconditionally from
`facebook/sam3.1` — a *second* gated HuggingFace repo. This has now been built
once, in the new project, and the token in `hf-token` is verified against both
repos. Any replacement token needs access to **both** or the build fails near
the end of a ~50 minute run.

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

## 8. Linux verification — done once

Superseded 2026-08-31. The 140-commit backlog was pushed and CI ran **green on
both jobs**, which is the first Linux verification this work had. The `python`
job had been red for five days; the fix (declaring Pillow) was among the
commits and is now proven rather than assumed.

The standing point survives the update: **local green says nothing about
Linux.** Push and let CI run before believing a suite count.

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

## 11. Registry

Three images in `thegoodguest`, one per service plus the buildcache. There is
no rollback image for any service: the new project has been deployed once, so
until a second deploy of each there is nothing to roll back to. Recovery from
a bad flip is a rebuild.

The `serving` tag on perception's image is what stops the cleanup policy
reclaiming the image a scale-to-zero GPU service boots from. Never delete it.

## How to re-derive all of this

`python3 tools/punchlist_check.py` re-checks the subset that can be checked.
At parking it read **1 done · 4 open · 5 unknown · 20 manual** across 30
entries. **UNKNOWN is not DONE** — it means the probe could not run.

Everything in section 1 comes from `gcloud run services describe <svc>
--region asia-southeast1` and a `curl` of the live origin. Re-derive rather
than trusting this file after any gap; that is the failure mode this repo has
had repeatedly.
