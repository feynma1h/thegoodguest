# 0239 — the last decrement fires the gate in its own turn

**Date:** 2026-08-24
**Status:** Decided

## Context

Decision 0044's drain gate holds the system background-session completion
handler until three conditions are met: `urlSessionDidFinishEvents` observed,
the pending-completions counter at zero, and a handler stored and unfired.
Three call sites route through `fireCompletionHandlerIfReady` — the drain, the
handler-stored-late path, and the last decrement of the counter.

`BlobUploadManagerTests.test_gate_lastDecrement_afterDrain_firesHandler` was
carried in CLAUDE.md as a known flake at roughly 1 run in 15 under full-suite
load and 0 in 12 in isolation, measured across 29 full-suite runs. Its only
synchronisation before asserting that the handler had run was a single
`await Task.yield()`.

## What we tried

The counter's decrement was `nonisolated`, and on reaching zero it hopped onto
the actor through an unstructured `Task { await self.fireCompletionHandlerIfReady() }`.
Nothing held a handle on that task — not the caller, not the test, not
production. The other two trigger paths are already actor-isolated and fire
before their own call returns; this was the only one that did not.

The test's yield was the visible half of the same fact. It is not a signal that
the hop finished; it is a guess that one scheduling slot is long enough. The
hop's task is enqueued while `handleTaskCompletion` still holds the actor, so
it must be scheduled once to reach its `await`, then again to acquire the actor
once the defer releases it. The test's own continuation is racing those two
steps on the same cooperative pool. Under low load the enqueue order usually
holds, which is why the flake vanishes in isolation and why a synthetic
pool-starvation harness could not force it either — starving the pool delays
both sides equally and preserves their order.

Two shapes were rejected before the one below. A longer sleep or a retry makes
the race rarer without making it absent, which converts a flake you know about
into one you do not. An `XCTestExpectation` fulfilled by the spy would be a real
signal, but it introduces a wall-clock deadline into a test that needs none.

## What we chose

`decrementPendingCompletions` is actor-isolated, and the last decrement calls
`fireCompletionHandlerIfReady` directly. The increment stays `nonisolated`.

The six drain-gate tests lost their `await Task.yield()`; awaiting
`handleTaskCompletion` is now the signal, because the fire happens inside that
call's own defer.

## Why

The hop bought nothing. The decrement's sole caller is `handleTaskCompletion`'s
defer, which already runs in the actor's isolation — so the call that had to
reach the actor was already on it. The increment is different and must stay
nonisolated: `BlobUploadDelegate` calls it on the URLSession delegate thread
before spawning its `Task`, and that is exactly what keeps the counter non-zero
when `urlSessionDidFinishEvents` arrives.

Two things follow. The gate's three trigger paths become uniform — each fires
before its own call returns — so the handler is called in the turn that satisfies
its last precondition rather than at an unbounded later point, inside a
background-execution window the OS time-boxes. And the ordering the tests depend
on becomes a property of the seam instead of an artifact of same-priority FIFO
scheduling, which is the difference between an assertion and a coin flip that
usually lands heads.

## What we measured

Baseline on `iPhone 17 Pro`, signed build: **600 tests, 0 failures**, the four
live integration tests included.

The change was isolated by holding the yield-less tests fixed and swapping only
`BlobUploadManager.swift`:

| production code | full-suite runs | `test_gate_lastDecrement_afterDrain_firesHandler` |
|---|---|---|
| hop through an unstructured Task | 16 | **failed 2×** — `XCTAssertEqual failed: ("0") is not equal to ("1")` at `BlobUploadManagerTests.swift:1233` |
| fires in the defer | 22 | 0 failures, 22 consecutive green |

Removing the yield raises the exposure — 2 in 16 against the recorded 1 in 15 —
which is the point: the yield was hiding the race rather than closing it.

## What would change this decision

A caller of `decrementPendingCompletions` from outside the actor. There is none
today, and adding one forces the hop back. If that happens, the hop needs a
handle a caller can await — not a yield, and not a longer one.

## What this turned up next to it

Three findings from the same measurement, none of them this seam's:

- **`CODE_SIGNING_ALLOWED=NO` fails the four live tests**, with
  `SecItemAdd (-34018) A required entitlement isn't present` — Firebase cannot
  reach the keychain unsigned, so anonymous auth throws. It reads as a backend
  outage and is not one. The CI workflow's `-skip-testing` on those four is
  what stands in for this.
- **`test_networkExhausted_deferredTransient_bumpsCounter_notFatal` sleeps
  ~8.8 s of real wall clock**, because it takes `makeManager` rather than
  injecting a sleeper. That is over half of a ~15 s suite, and it was the test
  the host was executing for 3 of 6 kills below. `makeRetryScheduleFixture`
  already carries the `setSleeper` pattern.
- **Back-to-back `test-without-building` runs wedge one booted simulator.**
  Six of sixteen unpaced runs died on `Test crashed with signal kill`, three of
  them before any test ran at all. Terminating the leftover test host and
  settling three seconds between runs removed it across 38 subsequent runs.
