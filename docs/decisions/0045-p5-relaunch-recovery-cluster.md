# 0045 — P5 relaunch-recovery cluster design (c/b/a code-complete, OS-kill gate remains)

**Date:** 2026-06-03
**Status:** Decided

## Context

Gate-2b (decision 0044) confirmed the root cause: when the app is force-quit or
OS-killed after bundle.pb is enqueued but before it completes, the recovery path is
unreachable on relaunch. The sole existing trigger (`ContentView.onChange(of:
capture.bundlePath)`) fires only when a new capture stops — not on a bare reopen.
The result is a stranded bundle: `bundle.pb` status `.pending`, record on disk, but
no code path that notices and resumes.

The fix is a three-unit cluster, designed together because the units share an
interface: **(a) launch-time rehydration**, **(b) onFatalBlobError reclassification**,
**(c) idempotency hardening**. Decision 0044 established that (c) is a firm
prerequisite for (a): without idempotent enqueue, the rehydration trigger would
double-enqueue blobs and bundle.pb, corrupting retry state.

This decision records the full cluster design so units (b) and (a) don't re-derive
it. Unit (c) shipped in commit 5bb07c9.

## What we tried

### Fork B — what to persist vs. derive for relaunch correctness

**B1 (chosen):** Persist durable facts; derive volatile ones at runtime.
`UploadPhase` (`uploadingBlobs` / `uploadingBundlePb` / `complete` / `failed`) is
persisted on the record. In-flight/orphaned status is *derived* at runtime via
`getAllTasks` keyed on the kill-surviving `taskDescription` — never stored.
The in-process latch (`bundlePbEnqueueInFlight`) is intentionally in-memory and
per-process: it must die on relaunch, because re-enqueue across process death is
the desired recovery. Only `.complete` (persisted) is permanently terminal.

**B2 (rejected):** Store `.inFlight` or `.orphaned` as blobStatus cases.
Violates the principle: a persisted `.inFlight` lies the instant the process dies
(the task is no longer in-flight from the new process's perspective). It would still
require `getAllTasks` reconciliation to clean up the stale state, adding complexity
without removing any. A persisted latch specifically would block the very recovery
we're trying to build.

One concrete finding that reinforced B1: `bundle.pb`'s `blobStatuses` entry is
initialized `.pending` and *never* advanced to `.uploaded` — `markBlobUploaded` is
never called for `bundle.pb` (by design, to keep the Phase-1 gate clean). This is
why `UploadPhase` exists as a separate field rather than reusing
`blobStatuses["bundle.pb"]`.

### Fork C — onFatalBlobError reclassification strategy (for unit b)

**C1 (chosen):** Classify by root cause. Deterministic fatals
(`http_400`/`403`, `empty_bundle_pb`, `missing_bundle_pb_uri`, `bundle_pb_read_failed`)
→ permanent `.failed`; record poisoned, no retry. `bundle_pb_read_failed` is TERMINAL
from the upload layer: BlobUploadManager cannot regenerate bundle.pb — that is the
capture/BundleAssembler layer. Unit (a) MUST existence-check bundle.pb before routing
to `enqueueBundlePb`; this terminal site is then the should-never-fire-post-(a)
backstop (defense in depth), not a recovery path. Circumstantial `*_no_context` fatals
(`network_no_context`, `308_no_context`) are fatal *only because in-memory context
died on relaunch* — across relaunch, the context can be reconstructed from the
persisted record. These must route to a retriable state, not permanent death. The
`*_no_context` callers are the exact OS-kill route identified in Gate-2b recon.

**C2 (rejected):** Uniform persist-and-retry for all fatals. Can't distinguish
genuinely dead situations (malformed server response, server-side 403) from
recoverable ones (missing in-memory state after relaunch). Retrying a 403 is an
infinite loop; the distinction matters.

Unit (b) must also cancel sibling in-flight blob URLSession tasks when transitioning
to `.failed` — these are in different code paths from the `*_no_context` cluster
and share no common ancestor, so cancellation must be explicit, not structural.

### Fork A — launch-time rehydration trigger (for unit a)

**A1 (chosen):** `.task` modifier on `ContentView` (or a peer `AppDelegate` hook) as
the primary rehydration trigger, reading all persisted records on every launch and
resuming any bundle not yet `.complete`. This is the only option that covers the
*swipe-up force-quit* route: after a force-quit, no `URLSession` drain hook fires —
the app simply relaunches from scratch on next open. `.task` fires on a standard
foreground relaunch.

For the *OS-kill* route (background URLSession events trigger a background
relaunch), `.task` on `ContentView` may also fire if the background-launched
`WindowGroup` instantiates the view hierarchy — this is asserted by prior recon but
**unverified as an on-device gate**: it is a SwiftUI lifecycle claim about whether
`.task` runs when the app is relaunched purely to process background URL session
events and never enters the foreground. This must be proven with a staged on-device
test before unit (a) ships. If `.task` does NOT fire on background OS-relaunch, a
co-trigger via `AppDelegate.handleEventsForBackgroundURLSession` is required as
belt-and-suspenders.

Unit (c)'s idempotency hardening (`bundlePbEnqueueInFlight` latch + `getAllTasks`
reconciliation + `uploadPhase == .complete` terminal guard) makes a second trigger
entirely safe: a drain hook added later is belt-and-suspenders, not the hazard that
decision 0044 feared about double-enqueue.

**AppDelegate OS-kill fallback ordering constraint (if/when built):** If the on-device
gate shows `.task` does NOT fire on background OS-relaunch, the `AppDelegate`
co-trigger is required. When wiring it, rehydration must START its enqueues before
the background-completion handler is handed back to the OS — if `rehydrateAllUnfinishedBundles`
runs after `urlSessionDidFinishEvents` fires, the OS drain races or obviates the
rehydration enqueues. `getAllTasks` reconciliation keeps this SAFE (no duplicate PUTs
regardless of ordering), but wrong ordering makes the rehydration enqueues pointless.
Do not build until the on-device gate confirms the need.

**A2 (rejected):** Trigger only on `scenePhase == .active`. Background OS-relaunches
may transition through `.background` and exit without ever reaching `.active`; the
recovery would never run on the OS-kill route.

**A3 (rejected as sole trigger):** AppDelegate drain hook alone. Covers the OS-kill
background-relaunch route but misses the force-quit/swipe-up route entirely (no
drain event fires after force-quit).

**CAFUFA re-confirmed:** Decision 0042's choice of
`NSFileProtectionCompleteUntilFirstUserAuthentication` for the upload session store
was re-verified this session. CAFUFA allows reading the persisted record while the
device is locked (after first unlock), which is the exact condition for a background
OS-relaunch. `NSFileProtectionComplete` would silently stall reads until the next
unlock — the lock-safe read required by launch-time rehydration depends on CAFUFA
remaining in place.

## What we chose

Cluster design: persist `UploadPhase`, derive in-flight status at runtime, classify
fatals by root cause, trigger rehydration from `.task` on launch (on-device OS-kill
gate verification pending; AppDelegate fallback deferred pending that gate).

### Bounded cross-launch retry (shipped in P5(b))

Fatal call sites are classified into three buckets:

- **TERMINAL** (deterministic; retry can't help): non-410/408/429 4xx, `308_persistent`,
  `308_reput_failed`, `reput_failed`, `empty/missing_bundle_pb/output_dir`,
  `bundle_pb_read_failed`, `expired_no_record/no_remint_provider/no_output_dir`,
  `remint_returned_stale_uris`, `blob_file_missing_at_staleness_remint`,
  `missing_bundle_pb_at_relaunch`, `missing_blob_at_relaunch` (both added by unit (a); see below). Sets
  `uploadPhase = .failed` + `failureReason` on the persisted record; arms an in-process
  `failedBundles` guard; clears `contexts`/latch/counted-set; cancels in-flight sibling
  URLSession tasks.

- **DEFERRED-INTERRUPTED** (`no_context` family — `network_no_context`,
  `308_no_context`): fatal only because in-memory context died on relaunch. Leaves blobs
  `.pending`; logs and returns without mutating the record. Relaunch re-enqueues. No
  strand.

- **DEFERRED-TRANSIENT** (408/429, network/5xx exhausted, remint/persist transients):
  bounded cross-launch retry. 408/429 are definitionally transient — 429 is the server
  explicitly saying retry-later; decision 0038 already anticipated a Retry-After branch.
  Mechanism: new persisted `crossLaunchRetryCount` field; bumped at most once per launch
  (via in-memory launch token + `transientCountedThisLaunch` counted-set, so the bound
  counts launches, not blobs); reset to 0 on blob progress. At `maxCrossLaunchRetries =
  10` escalates to terminal. Re-entry guard drops cancelled-sibling completions that
  arrive after the drain-counter `defer` fires.

**Relationship to settled decisions:** this EXTENDS 0038/0040's in-process bounded-retry
(seconds-scale transport blips) with an outer launches-scale tier. It does not overturn
them. Retry-After honoring remains the 0038 pre-launch gap — deliberately NOT pulled
forward here. The 12h staleness re-mint + the age=1day GCS lifecycle rule backstop the
bounded retry: a zombie capture that exhausts all 10 cross-launch retries is poisoned to
`.failed` and swept on the next launch.

**Unit (c) shipped (commit 5bb07c9):**
- `UploadPhase` enum on `UploadSessionRecord` — Codable legacy-safe; conservative
  decode default never yields `.complete`; `.complete` written on bundle.pb 200/201.
- In-process one-shot latch (`bundlePbEnqueueInFlight`) — synchronous check-and-set
  before the first `await` in `enqueueBundlePb`; cleared on success, 410 re-mint,
  and all fatal early-returns; intentionally dies on relaunch.
- `getAllTasks` reconciliation — cross-process guard in both `enqueuePhasOneBlobs`
  and `enqueueBundlePb`; keyed on `taskDescription` which survives process death per
  Apple docs.
- Context-preserve fix — `enqueuePhasOneBlobs` no longer unconditionally overwrites
  `contexts[bundleId]`, which zeroed `retryCount`/`reputtedPaths` on a second call
  while first-wave tasks were still in flight.
- `enqueuePhasOneBlobs` promoted from `throws` to `async throws` to admit the
  `getAllTasks` await; existing call sites already used `try await` so no callers
  changed.

**Unit (b) shipped (commit cc7aba5):** `onFatalBlobError` reclassification into
TERMINAL / DEFERRED-INTERRUPTED / DEFERRED-TRANSIENT; `.failed` + `failureReason`
written to the persisted record on terminal paths; sibling-task cancellation on
terminal; `crossLaunchRetryCount` persisted and bounded.

**Unit (a) built + verified in suite (commits 658cc4a + test-pin bd8b86f):**
`rehydrateAllUnfinishedBundles()` + `rehydrateBundle(bundleId:record:)` on
`BlobUploadManager`; trigger = a `.task` modifier in `RoomStudioCaptureApp`
(foreground/swipe-up path); record-driven (no live `CaptureManager`). On every
launch: loads all `UploadSessionStore` records via `allBundleIds()` (scans
`upload_sessions/` for UUID-named `.json` files), skips `uploadPhase == .failed`/
`.complete`, routes Phase-2 (`allNonBundlePbBlobsUploaded == true`: `onAllBlobsUploaded`
→ `enqueueBundlePb`) or Phase-1 (blobs pending: `enqueuePhasOneBlobs`) through the
(c)-idempotent path. CAFUFA load failure (pre-first-unlock on background OS-relaunch)
is a silent skip — never routes to `onFatalBlobError`, never mutates state for the
unloadable bundle.

Two new TERMINAL reasons added by (a) — both route to the (b) `onFatalBlobError`
(sets `uploadPhase = .failed`; NOT transient; never bumps `crossLaunchRetryCount`):
- `missing_bundle_pb_at_relaunch`: Phase-2 pre-check in `rehydrateBundle` — `bundle.pb`
  file absent on disk at relaunch time.
- `missing_blob_at_relaunch`: Phase-1 pre-check in `rehydrateBundle` — non-`bundle.pb`
  blob file absent on disk; closes the `enqueuePhasOneBlobs` throw-mid-loop silent
  strand (S0b). The missing-blob → `.failed` persisted → skipped-on-next-relaunch loop
  is assertion-pinned:
  `test_rehydrate_phase1_missingBlob_persistsFailed_andSkippedOnSecondRehydrate`.

The in-process guards (`failedBundles`, `transientCountedThisLaunch`, launch token,
`contexts`) are per-process by design — cross-launch terminal state is carried by the
persisted `uploadPhase == .failed`, which rehydration reads and skips.

**`onBundleComplete` stub intentionally untouched:** record/dir cleanup is the
separate disk-accumulation unit (CLAUDE.md "completed-capture disk accumulation"
gap). It must not be conflated with (a)/(b)/(c).

**Cluster status: code-complete, 162-green in suite.**
(c) `5bb07c9`, (b) `cc7aba5`, (a) `658cc4a`, test-pin `bd8b86f`.
The one remaining close item is the on-device OS-kill hardware gate: stage a
force-quit after all blobs are uploaded and `bundle.pb` PUT is enqueued; reopen;
confirm `bundle.pb` reaches GCS with no user interaction, GCS-authoritative,
verified from Mac during the locked interval. Also verify `.task` fires on background
OS-relaunch. `diag-bundlepb-reason-public` (`5bdd12f`) is the parked tool for
reading the redacted `reason=` on that route — do not delete.

**Code-complete ≠ Gate-2b closed. The hardware gate is the close.**

## Why

The latch dies on relaunch *by design*: a live-process latch that prevents
double-enqueue within a single execution is exactly what's needed for the
`onAllBlobsUploaded` concurrent-task scenario. Across a relaunch, re-enqueue is
the goal. Storing `.inFlight` to survive restarts would require cleaning up stale
persisted state on every launch — more complexity, same outcome as `getAllTasks`.

The `getAllTasks` reconciliation is the right cross-process guard because
`taskDescription` is explicitly documented by Apple as surviving kill/relaunch
(unlike `taskIdentifier`). It requires no extra persistence and is self-consistent:
if a task truly exists in the URLSession, it will complete and call
`handleTaskCompletion`; if it doesn't, the blob is safely re-enqueued.

The conservative Codable default (never `.complete`) ensures that any legacy record
— or any record whose phase field was corrupted — is always re-reconciled rather
than silently assumed done. The cost of an unnecessary re-enqueue attempt is one
`getAllTasks` call; the cost of a false `.complete` is a silently dropped upload.

## What would change this decision

- **On-device repro showing `.task` does NOT fire on background OS-relaunch**: unit
  (a) would need `AppDelegate.handleEventsForBackgroundURLSession` as a co-trigger
  (not a replacement; belt-and-suspenders alongside `.task`).
- **A backend finalize/commit endpoint**: if the server could confirm which blobs it
  has received for a given bundle, recovery could lean on server-side blob-presence
  instead of client heuristics — `getAllTasks` reconciliation would be optional and
  the client-side phase signal could be simplified.
- **Swift strict-concurrency enforcement (Swift 6 errors mode)**: the current
  `Sendable` warning on `CVImageBuffer` across the `DispatchQueue.main.async`
  boundary (flagged in P1, deferred) would need resolving before enabling strict
  concurrency in the iOS target — that pass should be done before (a) ships to avoid
  compounding the surface.
