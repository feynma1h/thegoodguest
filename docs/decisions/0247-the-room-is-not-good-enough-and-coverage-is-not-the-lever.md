# 0247 — the room is not good enough, and coverage is not the lever

**Date:** 2026-08-26
**Status:** Decided

## Context

Nothing in this project had ever asked whether a whole room, rendered in the
viewer and seen by a person, is good enough to ship. Every walk to date answered
a narrower question — a placement class, a facing, a clip sign — on an older
pipeline. The punchlist gained that question as G6-05 the same day this note was
written, and the operator answered it.

Two facts made the moment worth spending a GPU on. `perception-obj-00074-var`
carried 100% of traffic and had served **zero** `/process` requests, so no room
had ever been produced by the code that was actually live. And the operator
captured a fresh room — 189 frames, 4 walls, 6 RoomPlan boxes — which the
pipeline reconstructed end to end for the first time.

## What we tried

**The cold run.** 238s of the 900s budget went to model load (SAM 3 112.4s,
SAM 3D 123.7s), leaving 661.9s. It budget-stopped at 15 of 69 planned object
views with 83.0s remaining, and shipped **8 placed objects, 5 carrying a measured
colour block**, over a complete `roomplan` v3 shell.

**Every object came from exactly one frame** — `deduped_observations: 0` on all
eight. The operator looked and said the objects are not whole.

**The warm re-drive**, with this prediction registered in
`outputs/redrive-2026-08-26/prediction.md` BEFORE it ran: coverage improves, the
ceiling fan gets placed, at least one object gains a second arm, and *the
truncation does not visibly change*.

| | cold | re-drive |
|---|---|---|
| object views reconstructed | 15 | **27** |
| placed | 8 | **12** |
| multi-view objects | 0 | **0** |
| colour blocks | **5** | **0** |
| `refinement_skipped` | False | **True** |

The operator looked again: *"I see no good changes. Just more objects, the
previously placed objects look as bad."*

## What we chose

**The 3D representation is not production-ready, and the cause is the
single-view model — not coverage, not budget, and not selection.** The re-drive
was reverted; the room was restored to the cold-run manifest, because 5 colour
blocks are worth more than 4 objects that add nothing.

## Why

The prediction held on the only clause that mattered. An 80% increase in
reconstructions changed *how many* things were in the room and did not change
*what any of them looked like*. That is the strongest available confirmation of
0166 — a second reconstruction of an object is a second fabrication, not more of
the first — measured this time on a whole room in front of the person whose
judgment is the standard, rather than on an instrument.

It also closes off the cheapest remaining hope. Before this run it was still
arguable that the rooms looked poor because the pipeline was starved. It was
starved — and unstarving it bought nothing visible.

Three things were measured on the way that are worth keeping.

**Coverage and the post-passes compete for the same budget.** The cold run
finished with 83.0s spare and ran refinement; the re-drive finished with 68.0s
and skipped it, losing every colour block. Fifteen seconds separated a room with
colour from one without. This reproduces `b667f891`'s pathology on a second room
and reframes "warm re-drives are the coverage recipe" as a TRADE — more objects
can cost the pass that makes them look right.

**The OOM is deterministic to the byte.** Both runs failed on the same two
objects at the same two frames requesting the same bytes with the same free
memory: nightstand at frame 86 (512.00 MiB, 457.12 free) and cabinet at frame 45
(768.00 MiB, 479.12 free). Re-driving will never recover them. This supports
0228's headroom reading and rules out retry-as-strategy.

**0160's corollary is narrower than it reads.** "An OOM-failed view is never
retried by any warm re-drive" holds only for frames whose `objects.json` was
written. A budget-stop leaves most frames uncached — 11 of 12 here — and those
views ARE retried. Frame 124, the one cached frame, was the only one skipped
(`Frame 124 cache hit`). That is also WHY re-drives recover coverage at all.

**Arm selection never got to work.** Five box second-views were planned in both
runs and no object ever reached `deduped_observations > 0`, so the newly-serving
chooser had nothing to choose between on either pass. Why planned second views
do not become second arms is unexplained and unexamined. It would not have
fixed truncation — choosing between two truncated objects yields a truncated
object — but it means 0204/0205 shipped without ever being exercised on a real
room.

## What would change this decision

Decision 0052's standing trigger, unchanged and now the only route: a model that
consumes several views itself, or exposes calibrated metric scale and pose. 0166
sharpened why it must be the model — the disagreement between two views has to
be resolved INSIDE it, not downstream between two finished objects.

Do NOT re-open this with more coverage, a bigger budget, better frame selection,
a measured pointmap, or a union of reconstructions. Those are 0162, 0181 and
0166, and this room is now the fourth refutation and the first one a person
looked at.
