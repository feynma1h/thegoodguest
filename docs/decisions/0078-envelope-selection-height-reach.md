# 0078 — Envelope-wall selection: height-reach, not classification (a measured amendment to 0077's brief)

**Date:** 2026-07-28
**Status:** Decided and SHIPPED — amends one clause of the envelope-shell
contract designed in decision 0077 (whose build brief was deleted once the work
landed, as it instructed); 0077 is otherwise unchanged. The code is
`services/perception-obj/shell_envelope.py`.

## Context

RP-3's envelope-only degrade shell (the LIDAR_ARKIT fallback) selects
which merged walls form the room envelope. The build brief's contract
specified the candidate rule as **"classification ∈ {wall, door, window}
OR height-reach to the common top"** — the adjudication
(`docs/briefs/lidar-first-rooms-adjudication.md` §2b) had listed
classification, height-reach, and envelope membership as discriminators
that "any of these separates the two populations almost perfectly", and
the brief picked the first two OR-ed together.

## What we tried

The brief's rule, verbatim, as a verify-first probe against BOTH preserved
LiDAR bundles before writing `shell_envelope.py`. It selects the WRONG
envelope on both rooms:

- ARKit classifies several furniture faces **"wall"** (247003de wall_03,
  0.60 × 1.85 m, top 1.32 m — a cupboard face or door leaf; 13bae607
  wall_05/08/10 likewise). The classification-OR admits them, and the
  extreme-offset pick then hands an envelope side to a furniture plane
  (wall_03's offset −3.251 beats the real wall's −1.495).
- Open door leaves and through-opening detections carry **door members**
  (openings), so the door/window clause admits them too (247003de
  wall_07/08/14); wall_08's offset −3.540 displaced the real wall_04.
- Result under the brief's rule: 247003de → a 22.3 m² pentagon-ish
  "envelope" through furniture planes; 13bae607 → 25.2 m². Both wrong.

## What we chose

**Candidate ⇔ detected top reaches the common top
(`SHELL_ENVELOPE_TOP_TOL_M`, default 0.3 m) AND classification ≠ "seat".**
Classification and openings play no admitting role; door/window-carrying
walls that also reach the top still qualify (via reach) and their openings
ship on the rendered envelope walls.

## Why

Height-reach alone separates the populations PERFECTLY on both measured
rooms: envelope walls top out 0.00–0.08 m below the common top; the
tallest furniture plane stops 0.98 m short (247003de: exactly
02/05/09/12 under serving merge knobs — the adjudicated set — rectangle
13.80 m², sides 3.29/3.32 × 4.15/4.20, matching the operator-confirmed
4.20 × 3.29 ± 3–6 cm; 13bae607: exactly 01/03/06/08, 13.52 m²). ARKit
classification, by contrast, over-fires on furniture ("wall" on cupboard
faces) — as an OR-admit it is strictly harmful on this evidence. The
seat-exclusion is belt-and-braces (bed rails are far too short to reach
anyway). Both selections are pinned at achieved values in
`tests/test_shell_envelope.py`, under code-default AND serving merge
knobs.

## What would change this decision

The 0077 re-open clause carries over verbatim: a measured room where
height-reach admits a non-wall (a floor-to-ceiling wardrobe face) — or
misses a real wall observed only at partial height — re-opens the
selection rule with that counterexample. Classification could then return
as a TIE-BREAKER or a demotion signal, but the measured evidence says it
must never be an OR-admit.
