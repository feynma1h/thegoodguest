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
perception suite reads **1214 passed + 25 skipped** as a result; the 23 skips
are the real-data regressions with nothing to regress against.

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

Two branches remain: `main`, and `backup/pre-trailer-strip` — 515 commits of
pre-history-rewrite state kept as the sole record from before the 2026-08-09
trailer strip. It carries none of the purged HEIC blobs (verified) and costs
almost nothing, being mostly shared objects.

## The one branch that was deleted for its content

`diag-bundlepb-reason-public` was 143 commits of stale May history carrying a
single one-line change, kept for the OS-kill hardware gate (board item 2) so a
fatal blob error's `reason=` survives redaction in the log. The branch is gone;
the line is here:

```swift
// ios/RoomStudioCapture/RoomStudioCapture/Upload/BlobUploadManager.swift
logger.info("[BlobUploadManager] \u{2717} fatal blob error: \(bundleId, privacy: .public)/\(relativePath, privacy: .public) reason=\(reason, privacy: .public)")
```

The only change is `privacy: .public` on `reason`. Apply it temporarily when
you need to read a fatal reason off the device, and do not commit it — that is
why it lived on a throwaway branch rather than on `main`.

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
