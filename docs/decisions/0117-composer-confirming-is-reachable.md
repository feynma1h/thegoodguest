# 0117 — the composer's `confirming` phase is reachable, and stays

**Date:** 2026-08-08
**Status:** Decided

## Context

A recorded finding questioned whether the composer reducer's `confirming`
phase (decision 0058) can happen at all. The reasoning behind the doubt was
sound: a server-side model failure can never produce it, because the SSE route
always terminates with an explicit `error` or `done` event, so the "clean end,
no terminal event" that `CONNECTION_LOST` requires never comes from the guest
failing. The previous attempt to reach it was inconclusive — the composer was
already parked in `reoffer` and a synthetic `requestSubmit()` did not advance
the machine, which was flagged as possibly an artifact of driving the form
from JavaScript rather than a product bug.

Deleting a genuinely dead state is a legitimate outcome, so this needed
settling rather than assuming.

## What we tried

**Read the dispatch sites first.** `confirming` is entered only by
`CONNECTION_LOST`, and that is dispatched from three real places, not one:

1. `client.ts:140` — `reader.read()` throws mid-stream (the socket died).
2. `client.ts:157` — the response ENDS with no `done`/`error` event.
3. `Conversation.tsx:205` — `fetch()` itself rejects, before any stream
   exists (offline, DNS failure, CORS failure).

Site 3 is the one that settles the question on its own: a user whose
connection drops between tapping send and the response arriving reaches
`confirming` on an ordinary day. No exotic conditions required.

**Then reproduced it live rather than resting on the reading.** A harness
(`confirming_harness.py`, session scratchpad) serves the room's read
endpoints and, on a message containing "drop", streams three real `delta`
events and then simply ends the response without ever emitting a terminal
event. Verified on the raw wire with `curl | od -c`: three deltas, then the
body ends — no `done`, no `error`. The web app ran in `live-local` mode
against it, and the composer was driven with a **real pointer click** on the
send button (the previous attempt's open question), from a room whose reveal
had already been marked seen.

Observed, with a 100 ms recorder running across the whole turn:

| t | state |
|---|---|
| +6.1 s | `submitting` (real click on the enabled send button) |
| +7.1 s | **`confirming`** — "Making sure that reached the room…", the user's words retained above, composer stood down |
| +7.1 s → +156 s | `GET /conversation` every 4 s — the `client_msg_id` refetch loop at exactly `CONFIRM_POLL_MS` |
| ~+157 s | **`reoffer`** — "That didn't reach the room — your words are kept below.", draft `please drop this stream` live in a re-enabled composer |

## What we chose

Keep `confirming`. It is reachable, its whole documented lifecycle works
end-to-end, and it is doing real work: it is the only state that says "your
turn's fate is unknown" rather than guessing, and it resolves that uncertainty
by asking the server instead of by asserting.

The previous attempt's inconclusiveness IS explained by the driving artifact
it suspected. A real pointer click on the submit button, and real key events
into the controlled input, drive the machine correctly — React state updated
(the send button enabled on its own), the form's `onSubmit` fired, and the
POST reached the server. Nothing about the composer needed fixing.

## Why

The original doubt conflated two different claims. "The production SSE route
always emits a terminal event" is true and remains true — that is why a guest
MODEL failure lands in `reoffer`, which is correct, since a server that
answered with an explicit error has told you the turn did not happen. But
"the route always emits a terminal event" is not the same as "the response
always carries one". A proxy timeout, a killed worker, a Cloud Run instance
recycled mid-stream, a sleeping tab, or a dropped connection all end a
response with no terminal event, and none of them are the route's code
misbehaving. `confirming` exists for the transport, not for the guest.

That distinction also explains why the state is worth its complexity. The
turn may have been persisted server-side even though the client never learned
so — the disconnect shield (0058) deliberately keeps the turn task running
when the client goes away, and Cloud Run has been observed completing a turn
whose client was killed at 2.5 s. So after a transport drop the honest client
position really is "unknown", and `confirming`'s refetch-by-`client_msg_id`
is what turns that into a fact. Collapsing it into `reoffer` would tell users
their words did not reach the room while the room was in fact answering them,
and re-sending would then duplicate a turn that had already been charged
against their daily quota.

## What would change this decision

- If the disconnect shield were removed and a client disconnect always
  aborted the turn server-side, then a transport drop would reliably mean
  "did not happen", and `confirming` could collapse into `reoffer`.
- If the server ever grew a cheap "did turn <client_msg_id> land?" endpoint
  that answered definitively rather than by scanning the turn list, the
  150 s window and its poll loop could be replaced by one question.
- If telemetry ever shows `confirming` resolving to `CONFIRM_FOUND`
  essentially never, the window could shorten — but the state itself would
  still be the honest place to wait.
