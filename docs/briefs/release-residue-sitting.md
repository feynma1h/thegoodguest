# Operator sitting — release-residue hardware gates (one sitting, ~35 min phone-in-hand)

**Delete this brief when the sitting has executed and its results are recorded**
(decision 0085 + CLAUDE.md), per the build-brief deletion convention.

Covers the three phone-required items of the ios-release-residue charter:
terminal-failure UI on hardware (screenshots), Gate 2b (OS-kill / force-quit
relaunch, decision 0045 Fork A evidence), and the launch-reaper real-data
verification. The **rebuild + install is ALREADY DONE** (2026-08-07, signature
expires 2026-08-14) — the phone was reachable over WiFi pairing; installing
over the old app preserved the container (8 historical `.complete` records).

Roles: **[OP]** = operator with phone. **[CC]** = Claude Code on this Mac
(watching GCS via gsutil, Firestore via ADC, pulling device files via
devicectl). Helper scripts live in the session scratchpad `sitting/` dir:
`stage.sh '<json>'` (writes `Documents/rs-staging.json` into the app
container), `pull.sh breadcrumbs|store` (evidence pulls), `scene_status.py
<bundle_id>` (Firestore scene doc). The staging hooks are DEBUG-only,
one-shot (flags are consumed when they fire), and run the REAL machinery —
see `StagingHooks.swift`.

**Phone prep [OP]:** unlocked, on WiFi, notifications visible. Keep the phone
UNLOCKED except where a step says otherwise.

**Live Activity (added by the ios-live-activity branch, 2026-08-08).** The app
now raises a Lock Screen / Dynamic Island card at "Send it home" and ends it
when the flight ends. Three consequences for this sitting, none of which change
a step:

- **On the FIRST send, iOS asks "Allow Live Activities from RoomStudioCapture?"
  on the Lock Screen. [OP] must tap Allow** — declining silences the card for
  every later run (the app is unaffected either way: the card is advisory and
  every ActivityKit call is fire-and-forget).
- Every run's screenshots will now include the card. That is expected, not a
  defect; it is also the only hardware evidence this feature gets, so keep it in
  frame rather than dismissing it.
- The card is keyed on bundle_id, so a run's card must never narrate a previous
  run's capture. If it ever does, that is a real finding — record it.

---

## Run 0 — first launch: launch-reaper real-data verification (~2 min)

Predictions from the pre-install store pull (8 records, all `.complete`):
- `9fbe29b6`, `42bba2b9` (the 0074 phantoms, acknowledged at RP-6 G4): the
  confirming GET answers 403 → no positive answer → **RETAINED**. This is the
  notOwned-retain row on real data.
- Every OTHER record that is acknowledged (doorway-Done during past walks):
  GET → `ready` → **RECLAIMED** (record + capture dir — this is the disk
  accumulation actually being reclaimed: ~1.5 GB of served captures).
- Any unacknowledged record: retained; home may show the re-entry row for the
  newest (pre-existing behavior, not a defect).

1. [OP] Open the app. Wait on home ~15 s (launch tasks run). Note whether a
   re-entry row or failure banner shows.
2. [CC] `pull.sh store` → diff against the pre-install listing. Expect:
   phantoms present, acknowledged-ready records gone. `pull.sh breadcrumbs`
   → expect `app-init` + `app-task-rehydrate-fired`.

## Run A — failed_invalid on hardware (~5 min, one small scan)

1. [CC] `stage.sh '{"corruptFrame": "frames/000000.jpg"}'`
2. [OP] Scan a room SMALL (one slow 15–20 s sweep), Finish → review → **Send
   it home**. Stay on the wait screen.
3. [CC] Watch the bundle in GCS; on bundle.pb landing, `scene_status.py` —
   expect `failed_invalid` within ~10 s (ingest decodability gate).
4. [OP] The dark **"The scan didn't survive the trip."** screen appears —
   **SCREENSHOT #1** (side buttons). Then tap **Later**.
5. [CC] `pull.sh store` — the record must be GONE (flight-end reclaim on
   processingFailed). Record scene id for the report.

## Run B — failed_incomplete on hardware (~5 min, one small scan)

1. [CC] `stage.sh '{"dropBlob": "frames/000005.jpg"}'`
2. [OP] Scan small, Send it home, stay on the wait.
3. [CC] `scene_status.py` — expect `failed_incomplete`,
   `missing=[frames/000005.jpg]`.
4. [OP] The parchment **"The room didn't all make it up"** screen appears —
   **SCREENSHOT #2**. Then tap **Not now**.
5. [CC] `pull.sh store` — the record must STILL EXIST with its files
   (incompleteUpload retains — the coupled-pair rule on hardware).

## Run C — blob-fatal banner + uploadFailed screen (~4 min, one small scan)

1. [CC] `stage.sh '{"fatalBlob": "frames/000003.jpg"}'`
2. [OP] Scan small, Send it home, stay on the wait. Mid-upload the dark
   **"I couldn't get it up to the desk."** screen with `http_404` in mono
   appears — **SCREENSHOT #3**.
3. [CC] Verify sibling cancellation: GCS prefix stops growing; breadcrumbs
   show the fake-404.
4. [OP] Tap **Later** → home. The **UploadFailedBanner** WILL show there
   this launch (the in-memory kick outlives the flight by design) —
   **SCREENSHOT #4** (this is item 2's banner evidence), then dismiss (✕).
5. [CC] `pull.sh store` — record gone (uploadFailed reclaim row). Because
   the record is reclaimed, the banner must NOT return on the next launch —
   run 0 of any later session inherits that check for free.

## Run D — Gate 2b: force-quit with bundle.pb enqueued (~6 min, one small scan)

1. [CC] `stage.sh '{"suspendBundlePb": true}'`
2. [OP] Scan small, Send it home, LEAVE THE PHONE (wait screen showing).
3. [CC] Watch GCS until all frames/ blobs are present and breadcrumbs show
   `bundlepb-enqueued` + `staging suspended bundle.pb PUT` — the on-disk
   state is now exactly "bundle.pb enqueued, not landed". Confirm bundle.pb
   ABSENT in GCS. Tell [OP] "now".
4. [OP] **Force-quit** (swipe up, fling the app away). Lock the phone.
5. [CC] Confirm bundle.pb still absent (~30 s watch).
6. [OP] Unlock, **reopen the app** — touch NOTHING else.
7. [CC] Watch GCS: bundle.pb must land within ~30 s with zero user
   interaction beyond the reopen (rehydrate → phase-2 → re-enqueue; the flag
   was consumed, so the fresh PUT is not suspended). **THIS IS THE GATE.**
   Then `scene_status.py` — the scene should go queued → processing (a real
   capture; it may take minutes on GPU — do not hold the sitting for
   `ready`; [OP] may leave the wait screen).
8. **Free Live Activity check** (costs nothing, and this run is the only place
   it can be observed): the card must SURVIVE the force-quit at step 4 — the
   activity outlives the process by design, as does the background session
   feeding it — and after the reopen at step 6 it must resume moving rather
   than freeze, which is `reconcileOnLaunch` adopting it instead of orphaning
   it. A card that goes dead after the reopen is a real finding.

## Run E — OS-kill / Fork A probe (~8 min, one MEDIUM scan, then hands off)

1. [CC] `stage.sh '{"exitAfterCompletions": 25}'`
2. [OP] Scan MEDIUM (40+ frames — a full slow lap), Send it home, then put
   the phone down screen-on. The app will VANISH mid-upload (staged exit(0)
   after the 25th blob) — that is the test. **Do not reopen the app.** Lock
   the phone and leave it alone 3 minutes.
3. [CC] Watch GCS: remaining blobs keep landing AFTER the process death
   (nsurlsessiond). When the prefix stabilizes, wait 60 s, then
   `pull.sh breadcrumbs` (CAFUFA — readable while locked). Decision table:
   - `appdelegate-handleEvents` present after the `staged-os-kill` line →
     the OS relaunched the app in background.
   - `app-task-rehydrate-fired` ALSO present → **`.task` FIRES on background
     OS-relaunch** → 0045 Fork A: the AppDelegate co-trigger is unnecessary.
     If bundle.pb also landed with no reopen, the full background chain
     completed — record it.
   - handleEvents WITHOUT task-fired → `.task` does NOT fire → Fork A says
     build the AppDelegate co-trigger (0045's ordering constraint applies).
   - NEITHER → no background relaunch observed; re-check after 10 min, then
     record inconclusive + reopen path.
4. [OP] Reopen the app whenever convenient — rehydration finishes the
   upload either way (this is also the swipe-kill-free variant of relaunch
   recovery).
5. **Free Live Activity check — the feature's headline claim, and this is the
   only run that tests it.** With the app PROCESS DEAD and the phone locked,
   the card's count must keep climbing as nsurlsessiond lands the remaining
   blobs (the progress hook runs on the background session, not in a live
   app). [OP]: glance at the Lock Screen during the 3-minute wait and note the
   count; [CC]: compare it against the GCS prefix at the same moment. A frozen
   count with GCS still growing means the background progress hook is not
   firing — record it as a finding; nothing else in the sitting depends on it.

## Wrap (~2 min)

- [OP] AirDrop screenshots #1–#3 to this Mac (→ ~/Downloads; [CC] moves them
  to `outputs/release-residue-sitting/`).
- [CC] Final pulls (store + breadcrumbs), scene statuses for runs A/B/D/E,
  write decision 0085 (Gate 2b + Fork A verdicts), update CLAUDE.md, delete
  this brief.

**Fallbacks:** any staging flag that misfires → `pull.sh breadcrumbs` says
which hook fired; flags are one-shot so a clean retry is just re-staging. If
run D's suspend somehow races (bundle.pb lands before the force-quit), GCS
shows it — degrade to repeating with force-quit DURING Phase-1 (kill while
frames are still uploading; recovery machinery is the same, only the
enqueued-not-landed precondition is weaker; record honestly which variant
ran). `diag-bundlepb-reason-public` (`5bdd12f`) stays parked for reading a
redacted `reason=` if run E surfaces one.
