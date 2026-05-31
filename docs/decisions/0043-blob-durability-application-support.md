# 0043 — Capture blob durability: move to Application Support with CAFUFA

**Date:** 2026-06-01
**Status:** Decided — signed off before implementation

## Context

P4 (decision 0040) makes a core guarantee: an upload survives app kill and cold relaunch.
Items 5 and 7 of that decision depend on being able to re-PUT blob files from disk on
relaunch — the persisted `UploadSessionRecord.outputDir` is the path to reconstruct
per-blob file URLs without any in-memory state.

The capture output directory was written to `FileManager.default.temporaryDirectory`
(decision trail: no explicit decision, just `CaptureManager.makeOutputDir`'s initial
implementation). iOS can and does purge `temporaryDirectory` content while the app is not
running — Apple's documentation states contents "may be purged when your app is not
running." Storage pressure, jetsam, periodic maintenance, and cold boot all trigger
tmp purges. The full upload window for a session can exceed 12 hours; a device under
typical use will background-kill and relaunch the app many times in that window.

This bug was initially surfaced as a staleness-guard gap (Check-3, decision 0040 item 6):
the guard refreshes URIs but can't re-PUT blobs that have been purged from tmp. On review,
the scope was widened: **the same bug already undermines P4's core "upload survives kill"
guarantee (item 7), independent of staleness**, because the cold-relaunch resume path
(item 5) also reconstructs blob paths from the record and re-PUTs them. If tmp was purged
between kill and relaunch, those re-PUTs read nonexistent files → silent skip (the
`resourceValues` failure is swallowed in `onSessionExpired`'s re-enqueue loop) →
`bundle.pb` finalizes against holes in GCS. Not a crash, a silently corrupt upload.

## What we chose

Move capture blob output from `temporaryDirectory` to `applicationSupportDirectory`, with:

1. **Path**: `<Application Support>/<Bundle.main.bundleIdentifier>/captures/<bundleIdString>/`
   — The session subdirectory is named after the lowercased bundle UUID so that
   `CaptureStorageSweeper` can look up the matching `UploadSessionRecord` by directory name
   without any additional state.

2. **Protection class**: `NSFileProtectionCompleteUntilFirstUserAuthentication` (CAFUFA),
   set explicitly on directory creation (`.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication`)
   and on all write calls (`.completeFileProtectionUntilFirstUserAuthentication`). Matches
   the session record (decisions 0037/0042) and the same reasoning: background URLSession
   delivery runs while the device is locked; `Complete` evicts the key shortly after lock
   and would silently stall reading. See 0042 for the full protection-class rationale.

3. **isExcludedFromBackup**: set via `URLResourceValues.isExcludedFromBackup = true` on
   the session directory at creation time. Capture blobs are large (50–500 MB per bundle)
   and fully regenerable — including them in iCloud/iTunes backup would waste backup quota
   and slow syncs with zero user benefit.

4. **Cleanup** (Application Support does NOT auto-purge like tmp):

   *Current mechanism — startup sweep only*: `CaptureStorageSweeper.sweep()` runs at app
   launch. It enumerates `captures/`, checks each UUID-named subdir against
   `UploadSessionStore`, and deletes any dir whose record is absent. A 300-second age
   threshold skips dirs created too recently to have a record yet (race guard: capture dir
   exists briefly before POST /upload_session persists the record).

   The sweep covers *abandoned* captures (app killed before POST /upload_session returned;
   no record was ever written). It does NOT currently reclaim dirs for *completed* bundles,
   because `onBundleComplete` is an unbuilt P5 stub and does not delete the record. A
   completed bundle's dir therefore persists in App Support until P5 ships. This is a
   known, bounded gap: one directory per completed capture session, accumulating until P5
   cleanup lands. Disk growth is proportional to completed captures, not unbounded within
   a single launch.

   *Future mechanism — P5 onBundleComplete*: when built, `onBundleComplete` will delete
   the store record and session dir on successful upload. Once the record is gone, the
   next-launch sweep will also reclaim any dir that escaped the eager delete.

## Why

- **App Support survives kill/relaunch**: contents persist as long as the app is installed,
  not subject to storage-pressure purge. The durability contract the session record already
  has (0037: App Support + CAFUFA) now covers the blobs it indexes.
- **isExcludedFromBackup is required**: without it, a 200 MB bundle is included in every
  iCloud backup taken while the upload is pending. This is a known AppStore rejection
  vector (Guideline 2.5.2: excessive device storage).
- **Same CAFUFA rationale as 0042**: the protection class decision is identical. CAFUFA is
  the minimum class compatible with background-while-locked uploads; `Complete` is
  incompatible with the 0040 item 7 guarantee by construction. Aligning blobs with their
  session index (0042) removes the last asymmetry: previously tmp blobs were CAFUFA by iOS
  default but that was incidental, not deliberate.
- **Sweep as current sole cleanup**: `onBundleComplete` is an unbuilt P5 stub that does
  not mutate store state. The sweep provides a deterministic reclaim path for abandoned
  captures that requires no in-flight state and runs at every launch. Completed bundles
  accumulate in App Support until P5 ships — a bounded, known gap (one dir per capture).

## What would change this decision

- If a server-side finalize endpoint were added (e.g., the backend confirms receipt of
  `bundle.pb`), `onBundleComplete` could trigger immediate cleanup on a server callback
  rather than on the client-side URLSession delegate. The sweep would still be useful as
  a safety net.
- If App Store guidelines change the backup-exclusion requirements, `isExcludedFromBackup`
  may need revisiting, but that is unlikely to move toward inclusion.
- If `onBundleComplete` ships as a full P5 feature and is confirmed reliable (e.g., via
  a `bundleComplete: true` flag persisted to the store record), the sweep's deletion
  predicate could be extended to include "record exists and marked complete" as an
  additional terminal condition.

## References

- Decision 0037: upload-session record persistence (App Support + CAFUFA rationale)
- Decision 0040: P4 blob upload design (items 5 — durable gate, 6 — staleness guard,
  7 — locked-device finalize guarantee)
- Decision 0042: session record CAFUFA relaxation (protection-class reasoning and the
  locked-device finalize conflict with `Complete`)
