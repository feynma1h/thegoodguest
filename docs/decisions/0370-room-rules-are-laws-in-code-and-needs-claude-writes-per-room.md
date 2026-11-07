# 0370 — Room rules are laws in code, and needs Claude writes per room

**Date:** 2026-11-07
**Status:** Decided — `packages/room-guide` (laws.py, needs.py, rules_pass.py, assess.py)

## Context

The guide moves furniture, so something has to say what a move may not break.
The first plan listed rules like "nothing pushed into the air conditioner or the
mirror". The operator pointed out that such a rule is written for one room, and
that any fixed list breaks on the first room needing a rule nobody wrote.

## What we tried

- A list of rules keyed on furniture categories. Every new room type needs new
  code, and a generic rule can't separate a good block from a bad one: a desk
  under a switch board is ideal, a wardrobe in front of it is not.
- Letting Claude judge each candidate layout. The engine checks thousands of
  candidates a second; a model call takes seconds, costs money, and can answer
  the same question two ways, so it can't give a guarantee.

## What we chose

Three layers.

- **Laws, in code, the same in every room.** Solids never overlap. Everything
  stays inside the room and rests on something. Every place a person uses
  something is reachable through a person-sized path. Fixed things stay. The
  scanned room's own breaks are excused only while their pieces stay put.
- **Needs, written by Claude once per room.** They use a closed vocabulary of
  human actions: open, use, get_in, reach, air, heat, see, light, pass and
  other. Each piece also says whether it moves and what it goes with (at,
  beside, over, facing, near). Claude names no sizes: they come from the
  piece's measured parts or from a rulebook keyed by need and posture. Code
  validates the answer and checks it against the scan. The person can relax or
  add needs; laws are not theirs to relax.
- **Preferences, which only score:** task light, back to a wall, seeing the
  door, centring, open floor, balance.

The engine names no furniture type. `tests/test_generic.py` fails if engine
code does.

## Why

Code knows physics and people. Claude knows this room. The person knows their
life. The vocabulary is about actions and processes, not objects, so it does
not grow with new rooms: a piano, an aquarium or a kiln each map onto existing
needs (`test_things_no_rule_has_heard_of`). The demo room's air conditioner
needs no rule at all, because with real shapes a desk at that window runs into
it under law 1.

## What would change this decision

- A recurring need that only `other` can express becomes a new type, through a
  reviewed vocabulary change with an eval.
- If the rules pass's recall of hard needs, once measured live, is too low to
  trust, the critic loop (proposed in the plan, not built) moves from optional
  to required.
