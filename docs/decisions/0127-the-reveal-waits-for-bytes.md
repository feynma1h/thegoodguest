# 0127 — the reveal waits for bytes; fetch order is not the lever

**Date:** 2026-08-09
**Status:** Decided

## Context

Compression alone does not make the room appear. Measured on the reference
scene, same client, back to back: PLY 87–93 s, SPZ **14–19 s** — against a
reveal (0097) that runs **9.06 s** for that room. So even compressed, the
choreography would still narrate a room that had not arrived.

The render-payload brief framed this as an honesty problem and it is the same
one this project refuses everywhere else: a piece shown before its bytes exist
is a guessed transform in a different costume. It also flagged a tension —
the reveal's order is largest-first, which is the worst order for
time-to-first-pixel.

The operator chose progressive loading with the reveal waiting.

## What we tried

**The tension was measured, and it does not bind.** Fetching the room in
reveal order at concurrency 1, 2, 3, 4 and 10, three runs:

| concurrency | first piece | all bytes |
|---:|---:|---:|
| 1 | 4.76 / 11.72 / 5.95 s | 43.6–53.9 s |
| 4 | 2.82 / 4.85 / 5.18 s | 10.1–11.2 s |
| 10 | 5.23 s | 7.55 s |

Time-to-first-object is **flat at ~5 s at every concurrency**, while total time
improves 4–5× with parallelism. The reason is in 0123's own numbers: a single
connection to `storage.googleapis.com` is capped at 6.8–11.2 Mbps, so the
opening 5.81 MB file is *per-connection* limited, not bandwidth limited, and
its nine siblings barely slow it. Narrowing the fetch window buys nothing and
costs everything else.

So no fetch scheduler was built. The browser keeps fetching everything at
once, exactly as it does today, and the only change is when the reveal is
allowed to believe a piece exists.

## What we chose

`revealHoldMs` in `lib/reveal.ts` — pure, monotonic, pinned by 9 tests.

Movements 1 and 2 play immediately: the contour and the surfaces need **zero
splat bytes** (the shell is 3.5 KB), so several seconds of honest stage exist
before any splat is required. The object wave then gates per piece. When a cue
comes due and its splat has not landed, the whole remaining wave holds until
it does — `objT` pins to that cue's scheduled start, so it begins the moment
the bytes arrive and the spacing after it is exactly what the score asked for.

**Holding the whole wave, rather than letting a ready piece overtake a late
one, is the decision.** The order is the narrative — largest first, the
leading pieces named — and filling dead time by reordering would break the
thing the order is for.

Both closing beats (`captionsDoneMs`, `doneMs`) ride the object clock, so the
guest cannot speak over a room still arriving.

Verified in a real browser against a throttled server, not only in unit tests:
at 4 Mbps the floor and walls stand alone on stage with no objects, where
before the change the screen was a skeleton for ~94 s. At 15 Mbps, 14.25 s in,
the instrument read `objT 5220, hold 9032, arrived 3/10` — `objT` pinned to
exactly seq 1's scheduled start — with the bed, whose cue had already fired,
alone in the finished shell. Then the room completed.

## Why

Because the alternative is a reveal that lies, and because the measurement
removed the only reason not to keep the score exactly as designed. Above
~10.5 Mbps the opening piece is on time and the choreography plays as written
with no reordering at all; below it, the wave stretches and nothing pretends.

A failed splat counts as arrived on the reveal path — one broken piece must
not freeze the wave behind it forever; it simply never shows. The non-reveal
path keeps its existing await-all semantics, where a load failure is the
room's error state. That asymmetry is deliberate and recorded rather than
hidden: the reveal path is the product path and should degrade, and changing
the settled path was out of scope.

## What would change this decision

- **The pacing is unjudged.** The automation browser runs zero rAF frames
  while idle, so only single forced frames could be sampled — the hold was
  observed, the *feel* of a stretched wave was not. That is the operator's
  walk, as 0097's own pacing question already is.
- If a room ever ships enough pieces that the tail is long, holding the whole
  wave behind one late piece could feel stalled rather than deliberate; a
  bounded "hold at most N seconds, then continue without it" would be the
  first thing to try, and would need the same honesty argument re-made.
- If splats ever become streamable (progressive decode of a partial file),
  "arrived" stops being binary and the gate would want a threshold instead.
- The non-reveal path still waits for every byte. At 14–19 s that is now
  tolerable; if it stops being so, the same gate applies with an immediate
  plan and needs no new machinery.
