# 0084 — Terminal-state reclaim (CaptureReaper) + the server-blocked re-upload coordinator

**Date:** 2026-08-07
**Status:** Decided

## Context

Two long-recorded iOS gaps were designed as a coupled pair because CLAUDE.md
records a sequencing trap between them: `onBundleComplete` fires on bundle.pb's
PUT success — client-side, BEFORE the backend's validation can decide
`failed_incomplete` — so a cleanup keyed on upload success would delete the
exact files a `.recoverable` re-upload needs. The charter for this session:
cleanup deletes record + session dir ONLY on a genuinely terminal backend
state (ready / failed / failed_invalid), never on mere upload success; the
re-upload coordinator watches `pollState == .recoverable(missingPaths:)` and
re-drives BlobUploadManager with the missing paths.

## What we tried

### The re-upload coordinator — BLOCKED client-side, by measurement of the mint contract

Two server facts (read from the deployed code paths; no server change made —
that surface belongs to the launch-hardening session):

1. `FirestoreUploadSessionRepository.create_or_get` returns the **stored**
   `session_entries` verbatim whenever the request's path-set matches the
   stored manifest — and the `upload_sessions` doc lives for 7 days (TTL). So
   every client re-mint inside that window hands back the ORIGINAL resumable
   session URIs, including URIs whose sessions were **finalized** by the
   completed upload. A finalized GCS resumable session is single-use: a
   re-PUT is treated as a status query of the finished upload, not a new
   write, and it cannot re-create an object the age=1d lifecycle rule swept.
   The two failure shapes are both bad: a 200-shaped no-op (client believes
   it re-delivered; re-validation fails again; silent loop) or a 410 (routes
   to `onSessionExpired`, whose 410-path loop guard sees identical URIs and
   fatals with `remint_returned_stale_uris`).
2. The ingest half of re-validation **already exists**: on a bundle.pb
   re-delivery, a scene in `FAILED_INCOMPLETE` transitions back to `QUEUED`
   with the same scene_id. Only the mint half is missing.

So a client-only coordinator cannot work today. **Un-defer trigger:** a mint
contract change that vends fresh URIs for consumed/dead sessions (e.g. a
`force` re-mint or server-side session-state awareness) — 0035-contract
territory, flagged for the launch-hardening pass (board 4). The charter's
floor shipped instead: the legacy `SceneStatusView.recoverableView` copy was
made honest (the live `FailureView.recoverable` copy already was), and the
cleanup below RETAINS everything on `failed_incomplete`, so the files are
still there the day the coordinator becomes buildable.

### Cleanup trigger — where "terminal" is observed

**Rejected: reclaim on the poller's terminal publish.** The poll loop
deliberately outlives the wait screen, so `.succeeded` can land while the
user is at home not looking. Reclaiming there destroys the record that the
launch restore needs to re-surface the doorway — the user's room would
vanish without them ever seeing it arrive.

**Rejected: reclaim on upload success.** The trap above; also charter-banned.

**Chosen: reclaim where the outcome has been SEEN.**
- **Flight end** — `RootFlowView.endFlight` consults
  `CaptureReclaim.reclaimsAtFlightEnd(screen:)` with the `WaitScreen` the
  user is leaving: `.doorway`, `.processingFailed`, `.uploadFailed` reclaim;
  `.incompleteUpload` retains; everything else retains. Keying on WaitScreen
  (the routing table's own vocabulary) rather than raw poll state encodes
  "user saw it" directly — and it covers the client-terminal `.uploadFailed`
  case, whose poll state is already `.idle` by then (the screen's onAppear
  resets the poller).
- **Launch scan** — `CaptureReaper.reapAcknowledgedAtLaunch()` sweeps records
  the user already finished with (`DismissedBundles`): `.failed` reclaims
  directly (no scene exists to ask); `.complete` reclaims only after ONE
  confirming GET shows a terminal backend status — no answer (offline, 403,
  404, decode failure) retains. Unacknowledged records are never touched:
  they are `BundleRestore`'s inventory.

Deletion order is record FIRST, then dir: a crash between the two leaves an
orphan dir that `CaptureStorageSweeper`'s existing no-record pass reclaims
next launch. The reverse order would leave a `.complete` record advertising
a room with nothing behind it. `reclaim()` also re-checks the persisted
phase and refuses active records — a future caller bug cannot delete a live
upload.

### Edges settled deliberately

- **notOwned retains.** The 0074 stand-down acknowledges + hides foreign
  records; reclaiming them would destroy backup-migration evidence for no
  user-visible gain. (Consequence on the operator's 16 Pro: the two phantom
  records stay on disk, confirmed-retained by the launch scan's 403 → nil →
  retain path.)
- **acknowledged + later-failed disposal.** A `sendPaused` Leave acknowledges
  a bundle mid-upload; if its cross-launch resume later dies terminally, the
  launch scan reclaims it without the failure banner ever showing. Accepted:
  acknowledgment is the user's "done with this room" (endFlight semantics),
  and the pre-reaper alternative was the opposite pathology — the banner
  resurfacing on EVERY launch forever, which the monitor's docstring had
  always framed as "until terminal-state cleanup exists".
- **Poller flight expectation** (same pass): `sendItHome` declares the
  flight's bundle to ScenePoller; `notifyBundleComplete` drops completions
  for other bundles. This kills the RootFlowView-era survivor of the
  "prior scene's Room ready shows during a fresh upload" finding — an
  earlier capture's resumed upload completing cross-launch mid-wait would
  have started polling the OLD bundle and flashed its doorway over the new
  capture's wait. The dropped bundle's `.complete` record surfaces via the
  launch restore on a later launch instead.

## What we chose

`CaptureReclaim` (nonisolated pure tables: backend-status, flight-end-screen,
launch-scan action) + `CaptureReaper` (actor: record-then-dir deletion, the
acknowledged-launch scan with a single-attempt confirming GET). Wired at
exactly two sites: `endFlight` and a fourth app-launch `.task`. 27 pins
(CaptureReclaimTests 15, CaptureReaperTests 12).

## Why

Every reclaim decision is a table over what the user was shown or has
acknowledged, so the property "no outcome is silently swallowed, and no
recoverable material is deleted" is pinned by tests instead of being an
emergent property of view code. The janitor never trusts a guess: `.complete`
is not terminal, offline launches retain everything, and positive server
confirmation is the only path to deleting a completed capture's files.

## What would change this decision

- The mint contract vending fresh URIs for consumed sessions → build the
  re-upload coordinator on the retained files; `FailureView.recoverable`
  then becomes "send the rest" against `missingPaths` (its docstring already
  anticipates this).
- Scene TTL (gap F6) landing → the confirming GET can start answering 404
  for aged-out scenes; today that retains forever. If real accumulation
  appears from that shape, add an age-based tiebreak to the launch table —
  deliberately NOT built now (a 404 today means "Eventarc still in flight"
  more often than "swept scene", and retaining is the safe answer).
- FCM ready/failed notifications becoming reliable → a background-observed
  terminal could justify a third reclaim site; it must still respect the
  "user saw it" rule (notification tap ≠ doorway shown).
