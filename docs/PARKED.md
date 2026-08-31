# Parked — 2026-08-31

The project is parked deliberately. Nothing was abandoned mid-flight: every
worktree was clean and every lane's work was committed before stopping.

This file is for whoever picks it up, including a future me. It records only
what is NOT recoverable from the code, the punchlist, or `docs/decisions/`.

## Two risks that exist only while parked

**1. Twenty-four branches exist on exactly one disk.** `origin` holds `main`
and nothing else, and even local `main` is 7 commits ahead of it. Every lane
below is unpushed. A disk failure loses all of it.

```
git push origin --all
```

That is the whole backup. It was not run at parking time because pushing is
the operator's call, not a session's.

**2. `outputs/` is 9.4 GB, gitignored, and has no copy anywhere.** The
irreplaceable part is listed in CLAUDE.md under "What cannot be remade" —
`real-capture-*`, `device-pull/` (459 MB, reaped from the phone and gone from
GCS), `roomplan-spike/` (496 MB, the source recording), `capture-90eebfc4/`
(174 MB, the 2026-08-25 capture and its 189 frames), and every
`outputs/reports/*.md`. The captures bucket deletes at 24 h, so GCS does not
hold these. Copy that directory somewhere before cleaning this machine.

## Where the work stopped

All measured against `main`. Each branch is committed and clean.

| branch | ahead | what it was doing |
|---|---|---|
| `track-selection` | 47 | frame/track selection |
| `ui-screenshots` | 46 | AX screenshot pass over the iOS screens |
| `sam31-object-map` | 35 | SAM 3.1 migration for a per-object frame map |
| `segment-quality` | 33 | segmentation quality, nested-mask work |
| `ui-organisation` | 32 | iOS app UI reorganisation |
| `perception-segment` | 12 | the `/segment` probe and whole-view frame selection |
| `brand-identity` | 6 | name, mark, icons |

`backup/pre-trailer-strip` (515) and `diag-bundlepb-reason-public` (143) are
long-standing and deliberately not merged; leave both alone.

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
