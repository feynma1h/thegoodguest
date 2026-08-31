# Parked — 2026-08-31

The project is parked deliberately. Nothing was abandoned mid-flight: every
worktree was clean and every lane's work was committed before stopping.

This file is for whoever picks it up, including a future me. It records only
what is NOT recoverable from the code, the punchlist, or `docs/decisions/`.

## Two risks that exist only while parked

**1. `main` exists on exactly one disk.** `origin` holds `main` at a commit
132 behind local. Every lane below was merged into `main` and its branch
deleted, so `main` is now the single copy of all of it. A disk failure loses
everything.

```
git push origin --all
```

That is the whole backup. It was not run at parking time because pushing is
the operator's call, not a session's.

**2. The room data is gone, on purpose.** `outputs/` held 9.4 GB and now holds
1.1 MB — the reports, handoffs and verdicts only. Every preserved capture, the
16 cloud scene directories, both GCS buckets' contents and all 392 Firestore
documents were deleted at parking, because the next session starts fresh. The
perception suite reads **1198 passed + 41 skipped** and root reads
**844 + 102** as a result; the skips are the real-data and fixture-backed
regressions with nothing left to regress against. Nothing fails.

Do not go looking for `roomstudio-preserved` or `outputs/real-capture-*`. They
were deleted deliberately, not lost.

## Where the work stopped

All seven lanes were merged into `main` on 2026-08-31 and their branches
deleted; the work is in `main`, not on a branch. What each lane was:

| lane | what it built |
|---|---|
| `track-selection` | per-object frame selection over the SAM 3.1 track map |
| `ui-screenshots` | the Dynamic Type ceiling and the AX screenshot pass |
| `sam31-object-map` | the SAM 3.1 video tracker and `/track` |
| `segment-quality` | nested-mask collapse, vendored upstream source and pins |
| `ui-organisation` | the iOS screen reorganisation |
| `perception-segment` | the `/segment` probe and whole-view frame selection |
| `brand-identity` | the name, mark and icon geometry |

New perception behaviour ships behind env flags that default OFF, so merging
these changed no runtime behaviour. Nothing here is deployed.

**One branch remains: `main`.** `backup/pre-trailer-strip` — 515 commits of
pre-history-rewrite state, described here as the sole record from before the
2026-08-09 trailer strip — **no longer exists**, and no ref preserves that
history. Whether it was dropped deliberately at parking or by accident is not
recorded; verified 2026-08-31 that `refs/heads` holds `main` alone.

## The one branch that was deleted for its content

`diag-bundlepb-reason-public` was 143 commits of stale May history carrying a
single one-line change, kept for the OS-kill hardware gate (board item 2) so a
fatal blob error's `reason=` survives redaction in the log. The branch is gone;
the line is here:

```swift
// ios/TheGoodGuest/TheGoodGuest/Upload/BlobUploadManager.swift
logger.info("[BlobUploadManager] \u{2717} fatal blob error: \(bundleId, privacy: .public)/\(relativePath, privacy: .public) reason=\(reason, privacy: .public)")
```

The only change is `privacy: .public` on `reason`. Apply it temporarily when
you need to read a fatal reason off the device, and do not commit it — that is
why it lived on a throwaway branch rather than on `main`.

## Before you treat anything as finished

`docs/NOT-FINAL.md` lists everything in this tree that is not in final form,
checked against the live system on 2026-08-31 rather than read off CLAUDE.md.
The one item that will not announce itself: **`/segment` and `/track` are
registered routes and are not flag-gated**, so the next `perception-obj` deploy
exposes both. Everything else the merges added is off by default.

## Recreating the environment

`.venv` was deleted at parking (296 MB, fully regenerable). CI's recipe is the
authoritative one — `tools/ci_deps.py` reads each component's own pyproject, so
the dependency list cannot rot:

```bash
python3 -m venv .venv && .venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install $(.venv/bin/python tools/ci_deps.py \
  pyproject.toml packages/schemas/pyproject.toml packages/api-core/pyproject.toml \
  services/api-public/pyproject.toml services/api-internal/pyproject.toml --extra dev)
.venv/bin/python -m pip install -e packages/schemas -e packages/api-core
```

Perception needs its own environment in principle — its pyproject declares
`numpy<2` while the shared venv carries 2.x — but in practice one venv has
served both here, which is why CI splits the jobs and local runs do not.

`web/node_modules` is also gone: `npm install` in `web/`.

## Where to start when you come back

`docs/punchlist.md` — 29 items in six gates, dependency-ordered. Run
`python3 tools/punchlist_check.py` first: it re-derives status against the live
system rather than trusting this file or CLAUDE.md, and reports UNKNOWN
separately from DONE. Expect several entries to have rotted; that is what the
checker is for.

Do not trust dates or serving revisions in any document here without
re-deriving them. The recurring failure in this repo is documents going quietly
out of date, and parking guarantees more of it.

## What still costs money

The GCP project keeps billing while parked. Artifact Registry was the largest
line at roughly ₹45/day; Cloud Run scales to zero and costs nothing idle. If
the park is long, deleting the undeployed `perception-obj` images is the one
worthwhile cleanup — keep anything tagged `serving` or `buildcache`, which is
what `infra/artifact-cleanup-policy.json` already encodes.
