# 0047 — P5(a) scene-status poll client: the non-obvious design choices
Date: 2026-06-04  •  Status: Decided

> Companion: 0046 — the "what we tried" history and the separation-of-concerns
> framing of the two start paths. Read alongside this note.

## Context
P5(a) is the (a) split of P5 — the scene-status poll client + status UI —
built independently of the relaunch-recovery cluster (the other front). It
polls `GET /scenes/by-bundle/{bundle_id}` against the frozen, smoke-verified
`api-public-00006-quw` (asia-southeast1), single-sided per the 0035 pattern
(read side is frozen, so single-siding is safe; client still compensates for
known gaps). Landed at commit `4556e44`, suite 191-green (was 162).

This note captures three design calls that are non-obvious enough that a future
session would otherwise re-derive them — or, worse, "fix" them in the wrong
direction. The mechanical facts (file layout, cadence numbers, status→action
map) live in CLAUDE.md; this note is the *why*.

## What we chose

### 1. `failed_incomplete` is a RECOVERABLE TERMINAL, not a transient
The scope doc lumped `failed_incomplete` with `queued`/`processing` under
"transient." That conflates two different kinds of transient:
- `queued`/`processing` are **self-resolving** — the backend will move them with
  no external action. Polling is the right tool: wait and watch.
- `failed_incomplete` is **externally-resolved** — it cannot change until the
  *other* front re-uploads the missing blobs and re-fires Eventarc. Polling it
  is busy-spin against a frozen value: requests physically incapable of
  observing a change, because nothing in *this* front can cause one.

So the poll loop has a three-way taxonomy, not two:
- **Self-resolving transient** (`queued`, `processing`, `unknown(raw)`) → keep
  polling.
- **Recoverable terminal** (`failed_incomplete`) → STOP the loop, surface as a
  distinct recoverable state, leave `start()` re-callable so the other front
  resumes observation after its re-fire.
- **Hard terminal** (`ready`, `failed`, `failed_invalid`) → STOP the loop.

The re-callability of `start()` IS the seam for the other front. Do not collapse
`failed_incomplete` back into "transient" — that reintroduces the busy-spin.

### 2. A-nudge: two entry points, the kick is an accelerator only
The poll has two start paths, by design:
- **The kick** — `BlobUploadManager.onBundleComplete` fires
  `notifyBundleComplete(bundleId:)`, which starts polling **only if the status
  screen is already foreground+visible** (`guard isVisible else { return }`).
  When backgrounded it is a true no-op: no `start()`, zero network.
- **`onAppear`** — the status screen, on appear, independently scans the store
  for the `.complete`-phase bundle and starts polling. This path works with or
  without the kick.

Why not A-direct (kick unconditionally calls `start()`): the kick is delivered
on a *background* URLSession delegate path. `ScenePoller` uses
`URLSession.shared` (foreground-only). An unconditional start would spin up a
foreground poll while the app is backgrounded — exactly the case the
foreground-gate forbids. The `.complete` record is persisted to disk *before*
`onBundleComplete` fires (BlobUploadManager `handleSuccess`), so
poll-eligibility is already recorded without the kick writing anything. That's
what makes the no-op free: a backgrounded kick that loses the race costs
nothing — `onAppear` picks up the persisted record later.

Net: the kick *accelerates* the common "user watching the screen right after
upload" case; `onAppear` is the reliable path. Don't make the kick load-bearing.

### 3. Two timing layers share one honest wall clock (the V2 nuance)
The poller has an INNER per-request layer (one GET attempt: the 0038 shape —
200 / 404=notCreated / 401-refresh-once / 403,400,422-fatal / 5xx+network →
bounded jittered backoff within that one tick, exhausted → `transientFail`) and
an OUTER cadence layer (gap between successful-nonterminal ticks: 2s if
elapsed<30s, 10s if elapsed<5min, else 30s cap; 5-min breakpoint is a named
constant — the soft knob, retune against real perception latencies).

These are kept un-conflated: `startDate` is set once at `start()`, threaded as
an immutable arg, never rewritten (resume reads the preserved value from
`pollState.since`). `transientFail` does not reset it; the inner 5xx loop can't
even see it.

The nuance worth recording so it isn't "fixed" later: inner backoff sleeps
consume real wall-clock, so a tick that burns retries pushes `elapsed` forward
and can tip the cadence tier sooner. **This is correct, not a bug.** The cadence
is a function of real elapsed time since poll start, not of tick count. Freezing
the cadence clock during inner retries would be the actual bug — it would
under-count time that genuinely passed. One honest wall clock, one fixed origin;
the layers are separated by *what they decide* (one GET vs. gap between GETs),
not by running on different clocks.

## Lenient `SceneStatus` decode (cross-ref, not re-argued)
`SceneStatus` decodes unknown wire strings to `.unknown(raw)` via a non-failable
`init(rawValue:)` behind a custom `Decodable init(from:)` that cannot throw on
an unknown string. This is the direct client-side application of 0027 (strict
read-side enum crashed when the writer added a member). Built in now because the
contract is frozen *today* — cheap insurance, not a scramble later. See 0027.

## What this front deliberately did NOT do (seams left, not crossed)
- **No FCM** — push is broken for `ready`/`failed` (perception-obj uses
  `device_id` as if it were an FCM token; only `failed_incomplete` push works).
  Polling is therefore the ONLY completion channel, which is why there is no
  hard give-up while foregrounded (a silent stop would strand the user). FCM is
  backend-gated; tracked, not built.
- **No re-upload / no relaunch-recovery** — the other front. Seams left for it:
  re-callable `start()`, the persisted `.complete` record, and `missing_paths`
  decoded onto the model (surfaced humanized as a count; raw list retained for
  the recovery front).
- **`invalid_blobs`/`InvalidBlobReason` not surfaced** — exists server-side but
  is NOT serialized into this GET response. Backend-gated; the UI shows the
  `failed_invalid` terminal status only.

## What would change this decision
- Backend serializes `invalid_blobs` into the GET response → the recoverable/
  failed_invalid UI can show per-blob detail instead of status-only.
- Real `fcm_token` plumbed at `/upload_session` and FCM fixed for ready/failed →
  polling becomes an accelerator/fallback rather than the sole channel; the
  no-give-up rule can relax.
- Backend adds a seventh `SceneStatus` member → the lenient decode already
  tolerates it as `unknown`→keep-polling; a follow-up maps it to the right
  disposition. (This is exactly the 0027 failure mode, now defused client-side.)
- The 5-min cadence breakpoint is retuned once real perception latencies are
  known — it's a named constant for that reason.
