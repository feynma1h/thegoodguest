# 0311 — furniture twins are placed from boxes by rules that record their fixes

**Date:** 2026-11-05
**Status:** Decided

## Context

Replacing a scanned object with a clean model of it needs two things: what the
piece looks like (a spec) and where it stands (a placement). The first
experiments took the placement from RoomPlan's object boxes and from a hand
tool's boxes, then corrected each piece by hand: an offset here, a turn there,
"snap to the wall" on the curtains. Every correction lived in that piece's
spec, with its reason written by whoever made it. That works for one room and
teaches nothing to the next.

## What we tried

- Hand offsets per spec. Quick, but a re-scan moves the box and the offsets
  then push the twin somewhere wrong, and nothing says which offsets were
  compensating for the scan and which for taste.
- A wall-snap flag on flat pieces only. It turned out to be the general case:
  a hand-drawn box is roughly aligned with the room, and a flat piece placed
  from one sits at a slant or inside the wall.

## What we chose

- One input, `<scene>/boxes.json` (id, category, label, centre, yaw, size),
  whoever produced it. Windows and doors come from the shell's openings.
- Placement is code (`tools/furniture_placement.py`): a per-spec rule (floor,
  wall, over another twin, on another twin, opening) and invariants for every
  piece (nothing below the floor or through a wall, no overlaps).
- A move is never silent. Each one a rule makes is written into the twin's
  `fixes` with its reason, a hand correction must carry its own `why`, and what
  the rules cannot settle (a vertical overlap, two immovable pieces) is
  reported by the build rather than guessed.

## Why

The rules are what a person doing the same job would apply every time, so they
belong in code where a re-scan reuses them; the exceptions are the part that
needs a reason, so they are the part that is recorded. Reporting instead of
guessing keeps the check honest: a build that prints no warnings has cleared
the same test the clearance tool applies to the file.

## What would change this decision

If a detector produces boxes with reliable categories, the rule could be chosen
from the category instead of declared in the spec. If the invariants push
pieces more than a few centimetres on real boxes, the boxes (not the rules)
are what to fix.
