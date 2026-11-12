# 0377 — The room guide stays on Opus 5.5; Sonnet 5.5 is its measured fallback

**Date:** 2026-11-12
**Status:** Decided — `GUIDE_MODEL` (api-public) and `DEFAULT_MODEL` (`packages/room-guide/thegoodguest_room_guide/gateway.py`) are `claude-opus-5-5`. The eval that measured it is `packages/room-guide/evals/`.

## Context

0360 allows two models to see a room: Opus 5.5 and Sonnet 5.5. The room guide
(0370–0373) had run only on Opus 5.5, tested live on one real room. Sonnet 5.5
costs half as much per token and answers sooner. Whether it could carry the
guide had not been measured.

## What we tried

- **A planted-problem eval** (`packages/room-guide/evals/`). It has thirteen
  rooms built from numbers. Eleven have one realistic problem planted: a chest
  of drawers in a door's swing, a heater 0.2 m from a sofa, a wardrobe in
  front of a mirror, and so on. Two have none.
  - Each room carries an answer key: the needs a careful designer would write.
    Free tests prove each key finds its planted problem and nothing else
    serious.
  - A run is the rules pass plus three fixed turns in every room.
- **Two judges, blind and both ways round.** Opus 5.5 and Sonnet 5.5 each judged
  every room twice, once with each model as A. A room counts as won only when
  both readings pick it. Each judge reads the room as each guide was told it,
  from that model's own needs, beside the answer key. A claim the guide was
  given is therefore not marked as invented.
- **Three live runs on each model.** Runs 1 and 2 found faults in the guide's
  own code:
  - a bond that excused a heater's heat zone;
  - a mirror hidden behind a wardrobe that went unreported;
  - a search that came back empty when a finding was named loosely.

  Each was fixed as a general rule, with a test, before the next run.

| Run 3, the final one | Opus 5.5 | Sonnet 5.5 |
|---|---|---|
| Planted problems found | 11/11 | 11/11 |
| False alarms in the two rooms that work | 0 | 0 |
| A "Show me" card that fixes the problem | 10/11 | 8/11 |
| Turns over the four-sentence limit | 10/39 | 32/39 |
| Cost per room (rules pass and three turns) | $0.13 | $0.06 |
| Seconds per turn | 7.8 | 5.7 |
| Rooms won, both judges (26 readings) | 11 | 9, with 6 ties |

The whole report, with runs 1 and 2, is `outputs/reports/guide-evals.md`
(gitignored).

## What we chose

Opus 5.5 stays the guide's model, for the rules pass and the conversation.
Sonnet 5.5 is the measured fallback. Switching to it is `GUIDE_MODEL` in
api-public, or `--model` in the harness, with no code change.

## Why

The two models find the same problems. They differ in how they speak about
them:
- Opus 5.5 keeps to the guide's length rule.
- It leads with the problem.
- It puts the fix on a card more often.

Sonnet 5.5's misses were all in voice: long turns, and openings that point at
a card before saying what is wrong. With no users yet, how the first rooms read
matters more than about seven cents a room.

## What would change this decision

- **Cost at scale.** With real traffic, $0.13 against $0.06 a room is worth
  measuring again. A fresh run is `python -m evals.run` for each model, then
  the judges.
- **Sonnet's length.** A server-side check could send a turn over four
  sentences back once to be shortened. That would close Sonnet's main gap;
  run the eval again.
- **Harder rooms.** The rooms are synthetic, with four to seven box-shaped
  pieces. A real scan is harder, and a difference between the models may show
  there that this eval cannot.
- **The judges.** Both judges are the models being compared, and each preferred
  its own voice in run 2. The rooms both judges agree on are the steadier
  signal.
