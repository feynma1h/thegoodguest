# 0110 — The bundle.pb stall is iOS's background-launch rate limiter, not our defect

**Date:** 2026-08-08
**Status:** accepted
**Relates to:** 0040 (bundle.pb goes last), 0044/0045 (background assertion,
relaunch recovery), 0085 (the walk that observed it), 0111 (the Lock Screen
honesty that answers it)

## What was observed

Decision 0085, defect 2. A `bundle.pb` PUT was enqueued at 08:25:39 by a process
the OS had relaunched **in the background** 22 seconds earlier. It did not reach
GCS until **08:45:48** — 20 minutes 9 seconds — and it went the moment the
operator foregrounded the app. No scene existed for that whole window and
nothing server-side knew the capture existed.

0085 recorded it as "consistent with system deferral of discretionary tasks" and
left the mechanism open. The charter for this session made diagnosing it the
deliverable, because the answer decides the fix: a scheduling flag, a
user-facing honesty change, or both.

## The diagnosis

**It is documented iOS behaviour, and there is no flag that turns it off.**

Apple's *Downloading files in the background* describes a rate limiter applied
when the system resumes or relaunches an app: a task **started while the app is
in the background** does not begin until a delay expires, and **that delay grows
with each background resume or relaunch**. The delay resets to zero when the
user foregrounds the app, and also resets if it elapses without another
background relaunch. The same page states that when a transfer is initiated
while the app is in the background, `isDiscretionary` is treated as `true`
regardless of what the configuration says.

Source: <https://developer.apple.com/documentation/Foundation/downloading-files-in-the-background>

Every observed fact follows from that, with nothing left over:

| Observation | Explained by |
|---|---|
| Task created 08:25:39 by a background-relaunched process | rate limiter applies — the task was *started while in the background* |
| `isDiscretionary = false` (BlobUploadManager.swift:190) did not help | documented inert on this path; treated as `true` |
| Stalled ~20 minutes | the delay had escalated across the sitting's several background relaunches |
| Released **by foregrounding**, not by waiting | the documented reset-to-0 on foreground |

### The natural experiment that rules out our code

The strongest evidence is inside the same run, and it is a controlled
comparison we did not have to design — 0085 recorded it while proving Fork A:

- Tasks created by the **foreground** process before the force-quit uploaded
  **479 blobs (25 → 504) with no app process at all**, between 08:23:52 and
  08:24:52.
- The one task created by the **background-relaunched** process stalled 20
  minutes.

Same device, same network, same `nsurlsessiond`, same background session, same
minute. The only variable is the state of the process that created the task.
That eliminates "the transfer mechanism is broken", "the app must be alive", and
any defect in our enqueue path: all three would have stopped the 479 too.

### Why this lands on `bundle.pb` specifically

Not bad luck — structural. Decision 0040 requires `bundle.pb` to be enqueued
**after every other blob completes**, because its arrival in GCS is the
backend's ingest signal. On a real walk that is minutes to an hour after the
user put the phone down, so the task most likely to be created by a
background — or background-relaunched — process is precisely the one task whose
absence means the capture does not exist server-side. The ordering guarantee and
the rate limiter select for each other.

## What we are NOT doing

**No scheduling flag, because none exists.** `isDiscretionary` is already
`false` and is documented to be ignored here. `earliestBeginDate` only moves a
task later. `URLSessionTask.priority` is an HTTP/2 stream hint within a session,
not a scheduler input. There is no API surface for the rate-limiter delay.

**Not enqueuing `bundle.pb` earlier to dodge it.** That would trade a latency
problem for a correctness one: ingest would fire against an incomplete capture.
0040's ordering is load-bearing and stays.

**Not treating it as data loss.** It self-heals two ways — the delay expires on
its own, and any app open resets it to zero. The existing relaunch rehydration
(0045) already re-enqueues correctly. Nothing is lost; the capture is late.

`isDiscretionary = false` stays as it is. It is correct and load-bearing for the
foreground-initiated blob PUTs, which are the overwhelming majority of transfer
bytes. Only its comment was wrong — it claimed the flag buys prompt upload,
which is true foreground and false on exactly the path that hurt.

## What we did instead

The defect the user actually experiences is not the 20 minutes — it is that
**every surface claimed motion during them**. The Lock Screen card read
"Sending your room N of N" for the entire window. That is decision 0111, and
fixing it is the whole fix here.

The in-app wait screen needs nothing: it is foreground-only, and a foreground
app has a zero delay by definition. Reproducing the stall while the wait screen
is visible is impossible — the act of looking at it is the documented cure. The
Lock Screen was the only surface that could lie, and it did.

## What stays unverified

The 20-minute figure is one observation of a delay the documentation says is
variable and escalating; we have no measurement of its floor, its ceiling, or
its growth curve, and no way to read the current value. A capture sent from a
phone that has not been opened in a while may wait longer than 20 minutes. The
honesty fix is written not to care: it names the action that resets the delay
rather than predicting when the delay ends.

We did not reproduce the stall on device this session. The documentation plus
the in-run controlled comparison is stronger evidence than a single repro would
have been, and a repro would have cost 20+ minutes of waiting to observe a
number we already cannot generalise from.
