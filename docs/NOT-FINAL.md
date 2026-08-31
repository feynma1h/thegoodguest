# What is NOT in final form

Written 2026-08-31 at parking, from a sweep of the merged `main` and the live
system — not from reading CLAUDE.md. Every claim here was checked against
`gcloud`, the deployed origin, or the source on this commit.

**Read this before treating anything in `main` as finished.** The merges on
2026-08-31 brought seven lanes in at once. Most of what they added is inert by
construction, but not all of it, and the difference is not visible from the
code alone.

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

## 8. Registry residue

Six `perception-obj` versions, against a documented steady state of 3 + holds:

- `c538f699` — `serving`, the live image
- `b21408a5` — the parked candidate's image
- `c45098c5` — `buildcache`
- `faa005c8` — held by `serving-rollback-00062-hum`; **owed back** once
  `00074-var` is trusted, per 0243
- `13ef11bb`, `5729d84d` — untagged, awaiting eviction

Untagging frees nothing; deleting the version is what reclaims storage.

---

## How to re-derive all of this

`python3 tools/punchlist_check.py` re-checks the subset that can be checked.
At parking it read **1 done · 4 open · 5 unknown · 20 manual** across 30
entries. **UNKNOWN is not DONE** — it means the probe could not run.

Everything in section 1 comes from `gcloud run services describe <svc>
--region asia-southeast1` and a `curl` of the live origin. Re-derive rather
than trusting this file after any gap; that is the failure mode this repo has
had repeatedly.
