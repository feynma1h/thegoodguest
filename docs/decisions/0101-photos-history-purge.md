# 0101 — Purging the real room photos from git history

**Date:** 2026-08-08
**Status:** Decided; working-tree half shipped; **history purge PREPARED AND
REHEARSED BUT NOT YET EXECUTED** — it must run before the repo's first push

> **OPEN — the nine HEIC blobs are still reachable in this repo's history.**
> The purge command below was blocked by a tooling permission guard on
> history-rewriting operations and needs the operator to run it (or to grant
> the permission). Everything it depends on is done and verified; the two
> commands in "What we chose" are the whole remaining operation. **Do not push
> this repo to any remote until they have run.**

## Context

`test_data/photos/` held nine HEIC photographs of a real bedroom, added in the
repo's first commit (`6f19946`) and present in every tree since. They fed
`tools/build_test_bundle.py`, which synthesizes a `CaptureBundle` for
contract-level backend testing without a phone.

Board item 5 had deferred a decision on them since May with the note "may
require a history rewrite". The release-hygiene pass forced it: the repo was
about to get its first git remote, and a history rewrite after a remote exists
is a materially worse operation than one before.

**What made it urgent rather than merely tidy:** the photographs carry GPS EXIF.
`mdls` reports latitude 26.4459, longitude 80.2957 on every file — a precise
home location — alongside the capture device model and timestamps. The privacy
concern was never only "pictures of a room"; it was a geolocated home address
sitting in a git object, about to be uploaded.

## What we tried

Four options were put to the operator with the cost of each measured first.

1. **Purge from history + synthetic replacement.** Chosen.
2. **Remove going forward only** (`git rm`, history untouched). All commit SHAs
   survive, but the geotagged originals stay reachable forever — acceptable only
   if the repo stays private permanently and never gains a collaborator. That is
   a promise about the future that nobody can make.
3. **Strip EXIF, keep the imagery.** Identical SHA cost to a full purge for
   strictly less benefit: it removes the coordinates but leaves photographs of
   the operator's home in history.
4. **Defer again.** Explicitly the most expensive option once a remote exists.

**The measured cost of (1), which is what made it decidable:** the documentation
in this repo is unusually SHA-dense — CLAUDE.md and `docs/decisions/*.md` cite
commits constantly. 105 distinct short SHAs in tracked docs resolve to real
commits. A naive rewrite would leave the entire written record pointing at
commits that no longer exist, which is arguably worse than the problem being
solved. That is why `tools/remap_doc_shas.py` exists, and why the cost estimate
presented to the operator included the remap rather than pretending the
citations did not matter.

## What we chose

A **targeted glob purge**, not a path purge:

```
git filter-repo --path-glob 'test_data/photos/*.HEIC' --invert-paths --force
python tools/remap_doc_shas.py
```

`--path-glob '…/*.HEIC'` rather than `--path test_data/photos` matters: the
directory also holds `README.md` and now the synthetic JPEGs, and purging the
whole path would erase those from history too and leave the fixture directory
with no recorded past. Only the nine offending blobs are excised.

The replacement is `tools/make_synthetic_photos.py` — nine rendered views of a
plain synthetic bedroom, committed so the documented smoke path works from a
fresh checkout with no generation step.

**The whole operation was rehearsed on a throwaway clone before touching the
real repo**, and the rehearsal is the reason this note can state outcomes rather
than intentions:

- 0 HEIC blobs reachable afterwards; all 434 commits preserved (a glob purge
  removes file content, not commits).
- `README.md` and the synthetic JPEGs survive in history, as intended.
- The remap rewrote 155 SHA citations across the docs, and **105 seven-character
  citations resolve to real commits in the rewritten repo** — the same 105 that
  resolved before.
- Every unresolved hex token was checked against the pre-rewrite repo: **zero
  were real commits.** The 43 unresolved tokens are scene ids (`09684dde`),
  image tags (`20260721`), UUID fragments, and a Google `sub` — correctly left
  alone.
- `build_test_bundle.py` → `inspect_bundle.py` runs clean in the rewritten
  repo: 9 frames, quaternion norm error 0.000000, gravity-vs-pose error 0.0000.

## Why

The replacement is not merely a safe substitute — it is a **better fixture**,
and that is worth recording because it inverts the usual "synthetic data is a
compromise" intuition.

`build_test_bundle.synthesize_pose` invents a camera trajectory: nine poses on a
2.5 m arc at 1.4 m height, looking inward. The real photographs knew nothing
about that arc. The bundle therefore paired images of one room with poses from
an unrelated imaginary one — internally inconsistent from the day it was built.
`make_synthetic_photos.py` imports `synthesize_pose` from `build_test_bundle`
itself and renders each view **from that exact pose**, through the exact
intrinsics the bundle records (`fx = fy = max(w, h)`, principal point centred,
rendered at 1024×768 so the downscale never runs and `fx` is exactly 1024).
Frame *i* is now genuinely what a camera at pose *i* would see.

What was lost is real and should be stated: photographic texture. Flat-shaded
boxes will not exercise SAM 3. That loss costs nothing here because
`build_test_bundle` was never a perception fixture — it is a contract smoke
test, and the real-room regression data lives in `outputs/real-capture-*/`,
gitignored and never committed.

Timing note: the rewrite was paused mid-session when a second lane turned out to
be live in the `roomstudio-0074` worktree with uncommitted work. Rewriting all
refs under an in-progress edit is disruptive, and nothing was lost by waiting —
with no remote, the operation stays exactly as cheap. It ran once that lane had
committed.

## What would change this decision

- **If the smoke test ever needs real photographic texture** — say
  `build_test_bundle` grows into a perception fixture — the answer is a
  purpose-shot, consented, EXIF-stripped set, not the restoration of these.
- **If a future fixture needs committing**, the rule this establishes is:
  synthetic by default; anything camera-originated gets its EXIF checked before
  it is added, because phone photos carry location by default and git is
  forever.
- `tools/remap_doc_shas.py` is deliberately generic. If another rewrite is ever
  needed, it should be re-used rather than the citations abandoned.
