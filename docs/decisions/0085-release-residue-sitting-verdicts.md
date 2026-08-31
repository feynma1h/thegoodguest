# 0085 — Release-residue sitting: Gate 2b closed, Fork A answered, and three defects the runs surfaced

**Date:** 2026-08-08
**Status:** accepted
**Supersedes / relates to:** 0044, 0045 (relaunch recovery), 0084 (terminal-state
reaper), 0036/0051/0074 (identity), 0072 (Good Guest failure surfaces)

> Number 0085 was reserved for this sitting by the release-residue pass. The
> sitting executed on the iPhone 16 Pro with the operator present for its whole
> length. The script it followed was a build brief, removed once the sitting
> ran and its verdicts landed here.

## What was gated

Three phone-only items nothing else could reach: the three terminal-failure
screens (never rendered on hardware), Gate 2b (OS-kill / force-quit relaunch, and
0045's Fork A decision), and the launch-reaper's behaviour against the device's
eight real historical records.

## Verdicts

### Gate 2b — CLOSED (open since 0044)

```
08:16:54Z bundlepb-enqueued 8c05fa72
08:16:54Z staging held bundle.pb PUT unstarted
          [force-quit + locked; bundle.pb ABSENT at 08:17:46 / 08:18:02 / 08:18:17]
08:18:49Z app-init
08:18:49Z app-task-rehydrate-fired
08:18:50Z bundlepb-enqueued 8c05fa72          (re-enqueued by rehydration)
08:18:50Z bundle-complete 8c05fa72
08:19:01Z bundle.pb PRESENT
```

`bundle.pb` reached GCS ~25 s after the reopen with **zero interaction beyond
opening the app**. Idempotency held in the same run: GCS went 336 → 337, exactly
one object, so P5(c)'s `bundlePbEnqueueInFlight` latch and `getAllTasks`
reconciliation did their job against a task that already existed.

### 0045 Fork A — ANSWERED: the AppDelegate co-trigger is UNNECESSARY

```
08:23:52Z staging staged-os-kill after 25 completions
08:25:17Z app-init
08:25:17Z appdelegate-handleEvents com.thegoodguest.capture.blobUpload
08:25:18Z app-task-rehydrate-fired
08:25:18Z reaper-scan ids=12 acked=10
```

Phone locked, app never reopened. `handleEvents` present (the OS relaunched the
app in the background) **and** `app-task-rehydrate-fired` present — so `.task`
fires on a background OS-relaunch. Per Fork A's own decision table that closes
the fork against building the co-trigger. Its ordering constraint is moot.

Collateral, proven hard: GCS went from 25 blobs at the kill to **504 by 08:24:52,
before the 08:25:17 relaunch** — transfers are owned by `nsurlsessiond` and
proceed with no app process at all.

## THE HARNESS DEFECT THAT NEARLY COST THE GATE

`StagingHooks.suspendBundlePb` was written as `task.resume()` followed by
`task.suspend()`. **That does not hold on a background `URLSession`**: the
transfer is performed out of process by `nsurlsessiond`, which ignores an
in-process suspend. Measured — `bundle-complete` fired in the **same second** as
the `staging suspended` breadcrumb, so the gate's precondition never existed and
the first attempt scored nothing while appearing to run correctly.

Fixed this session by **withholding `resume()`** when the flag is set: the task is
created but never transfers, which *is* "enqueued, not landed", and it holds
indefinitely instead of for a sub-second window no human can hit. Release builds
are unaffected (`stagedHold` is `false` outside DEBUG, so `resume()` always runs).

The operator proposed Network Link Conditioner before this was understood, and
was talked out of it on a false premise (that the hook had removed the race).
Recorded because the instinct was right and the reasoning against it was wrong:
throttling *would* have widened the window. It would not have been sufficient on
its own either — `bundle.pb` is ~51 KB and is enqueued the instant the last frame
completes, so any profile slow enough to stall it also stalls the frames that must
finish first. Withholding `resume()` is the correct instrument.

## The identity churn — the reaper is exonerated, the device is orphaned

The launch scan reclaimed nothing on real data. Instrumenting it (breadcrumbs at
every decision point) showed every routing decision correct and every confirming
GET returning **403**:

```
reaper-scan ids=8 acked=7
reaper-action 893663fd phase=complete acked=true -> confirmViaServer
reaper-get    893663fd code=403 decoded=false          ... and six more
reaper-action ea40c579 phase=complete acked=false -> skip
```

Cause, measured rather than inferred:

```
cHfMlULde2WO…  validSince : 2026-08-07 22:26:55Z   (all prior tokens revoked)
device app-init            : 2026-08-08 07:16:00Z
new anon uid j9UJyV6szd…   : 2026-08-08 07:16:01.736Z
```

Gate B set a verified email on the operator's uid via the Admin SDK, which
revokes outstanding refresh tokens. The phone's cached credential predated the
cut, so the next cold launch signed out and `signInIfNeeded()` minted a fresh
anonymous user — doing exactly what it is written to do. Operator confirmed the
new uid on the profile screen.

Consequences:

- **"403 → retain" is the conservative rule working**, not a bug. The reaper
  refused to delete rooms it could not get a positive answer on.
- The launch scan's *server-confirmation* path was later verified anyway, during
  Gate 2b: `reaper-get 8f55b71f code=200 status=failedIncomplete` → **retained**,
  correctly preserving the files a future re-upload needs.
- The **acknowledged + 200 + terminal → reclaim** leaf remains unexercised: Runs A
  and C were reclaimed at *flight end* before any launch scan could see them.
- The eight historical records (~1.5 GB) are now **permanently unreclaimable** —
  the confirming GET will 403 forever under the new identity, and the app has no
  sign-in path back (iOS sign-out is deliberately absent; Apple linking is
  enrollment-gated).

**The durable lesson:** an admin-side account mutation silently orphans every
capture device holding that identity. 0036's invariant covers the app's own
behaviour; nothing covers a server-side token revocation. Any future admin
mutation of a real user needs the device re-linked deliberately, or the device
must be treated as a new user from that moment.

## Defects the runs surfaced

1. **The recoverable screen shows no missing-file count.** Run B's server sent
   `missing_paths: ['frames/000005.jpg']`; the screen said nothing about it.
   `FailureView.Kind.recoverable` carries no associated value, so it structurally
   cannot render one. The superseded `SceneStatusView:229-232` did
   ("1 file needs re-uploading."). The count was lost in the 0072 redesign, and
   CLAUDE.md's "recoverable humanised to file count" describes that dead surface.
   Whether to restore it is a design call: the view's comment argues for vagueness
   because there is "no honest partial to render", but that concerns partial
   *coverage*, and a count of missing *files* is a separable claim.

2. **`bundle.pb` enqueued during a background relaunch stalls.** Enqueued
   08:25:39, did not ship until **08:45:48** (`gsutil stat` creation time), when
   the app was foregrounded — 20 minutes fully uploaded with no scene and nothing
   server-side aware the capture existed. Consistent with system deferral of
   discretionary tasks enqueued by a background-launched process. Self-heals on
   next open, so it is a latency-and-honesty problem rather than data loss — but
   a user who sends a room and does not reopen the app waits indefinitely while
   the wait screen implies motion.

3. **A Live Activity card persisted from an earlier capture**, reading
   "Sending your room 331 of 331" — a completed count still labelled in progress.
   331 matches none of this sitting's captures, so it predates them. Mechanism
   candidates, explicitly **not** a diagnosis: `LiveActivityController.apply` and
   `.end` are both gated on `bundleId == currentBundleId`, which is in-memory and
   nil after a process death until `reconcileOnLaunch` re-adopts exactly that id.
   Pinning the leaf needs an instrumented session, the way the reaper got one.

## Product judgements the operator delegated

- **`http_404` shown raw in mono on the upload-failed screen: leaking plumbing.**
  The design system uses mono machine-data for things a user might relay or
  verify (a UID as identity proof, a scan census). An HTTP status is neither, and
  it is wrong-flavoured honesty — a 404 on an upload URL means *our* session went
  stale, so naming a code invites the user to suspect themselves. Keep the machine
  reason; demote it behind a deliberate tap-to-reveal or copy-for-support.
- **The failure banner on home after the failure screen was dismissed: told
  twice.** The banner earns its place when the failure happened while the user was
  elsewhere; it does not when they just dismissed the dedicated screen for that
  same bundle. Suppress it for a bundle acknowledged this session — the same
  "has the user SEEN this outcome" predicate `reclaimsAtFlightEnd` already encodes.

## What is verified vs still open

Verified on hardware: `failed_invalid` (180 ms, pre-GPU, correct file named),
`failed_incomplete` (record + files retained), blob-fatal (sibling cancellation
beat every in-flight PUT — no GCS prefix was ever created), Gate 2b, Fork A,
F5/F6 TTL stamping on a fresh scene, and the Live Activity reaching 751 of 751
with the app never reopened.

Still open: the launch-scan reclaim leaf; whether the Live Activity updates while
the process is *fully* dead (the OS relaunched the app 94 s into Run E, so the
observation is confounded); and the stale-card mechanism.
