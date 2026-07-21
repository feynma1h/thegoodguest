# 0059 — Conversation stage 1: implementation choices not in the design

**Date:** 2026-07-21
**Status:** Decided (implementation notes for 0058; changes nothing in it)

## Context

The 0058 build session made four implementation choices that aren't in the
design note and aren't self-evident from any single file. Recording them so
they aren't re-litigated or accidentally undone.

## What we tried / what we chose

**1. Thinking explicitly disabled on the guest model call.** `claude-sonnet-5`
runs adaptive thinking BY DEFAULT when the `thinking` field is omitted, and
`max_tokens` caps thinking + speech together. With the guest's 250-token beat
budget, an invisible thought would spend the budget and truncate the reply
mid-sentence — the exact failure 0058's "generous backstop" was sized to
avoid. The call passes `thinking={"type": "disabled"}` (accepted on Sonnet 5)
and no sampling params (rejected by the model family).

**2. The prompt-cache floor shaped the charter's length.** Prompt caching has
a minimum cacheable prefix (~2048 tokens for this model class); below it a
`cache_control` breakpoint silently does nothing. The first charter draft
(~1.2K tokens) + a small room's facts block would have sat under the floor and
made 0058's "caching on from day one" silently false. The charter was
deliberately written out to ~2K tokens — all load-bearing voice/honesty
content, no padding — so charter+facts clears the floor. **Do not diet the
charter without re-checking `usage.cache_read_input_tokens` on a second
turn** — cache death from shrinking it produces no error, only 10× input cost.

**3. The third rolling cache breakpoint shipped.** 0058 listed a breakpoint on
message history as "a tunable, not required". It ships on the newest user
message (3 of the 4 allowed breakpoints), so each turn re-reads charter +
facts + prior history at cache-read rates. Measured on both live-local and the
deployed revision: turn 2 read 2268–2330 cached tokens with `input_tokens=2`.

**4. Card animations are entrance-only.** The conversation card originally
swapped states through `AnimatePresence mode="wait"`, which holds the old
child until its exit animation completes. Under throttled rAF (the dev
preview pane; any backgrounded tab) the exit never finishes and the card
freezes on stale content — observed live mid-build. Exit choreography was
removed; new content springs in on a keyed `motion.div`. The design's "all
entrances ride the single SPRING" asks for entrances only.

## Why

1 and 2 are silent-failure traps: nothing errors, the product just gets worse
(truncated beats; 10× input spend). 3 is a measured win worth pinning against
"simplify the breakpoints" cleanups. 4 looks like a style choice in the diff
but is a correctness fix.

## What would change this decision

- A `GUEST_MODEL` change re-opens 1 (thinking semantics and budget
  interaction differ per family — re-run the voice evals either way) and 2
  (cache floors are model-dependent).
- Raising `GUEST_MAX_TOKENS` far above 250 weakens 1's rationale but doesn't
  reverse it — the beat budget is a product choice, not a technical one.
- If motion ships a wait-mode immune to rAF starvation, 4 could revisit;
  nothing today needs exit animations there.
