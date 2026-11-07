# 0373 — The guide sees the semantic room, and quotes every number it says

**Date:** 2026-11-07
**Status:** Decided — `brief.py`, `analyzer.py`, `prompts.GUIDE_SYSTEM`; amends 0058, 0096, 0132 and 0159 for rooms that have a diorama scene

## Context

The guest's charter (PROMPT_VERSION 7) forbids it walls, windows, facings,
shapes, materials and light, because the scans it was written for carried none
of them. The diorama scene carries them all. The operator also asked for a
guide that gives advice like an interior-design expert. A designer who can't
see the window can't say the screen faces it.

## What we chose

- For rooms with a diorama scene, the guide reads THE ROOM:
  - the walls, named by what is on them;
  - every piece with what it needs and goes with;
  - the analyzer's findings, with the standard each is measured against;
  - the questions the scan can't answer;
  - what the person has said, and what is on their screen;
  - and a plan drawn from the model, never a camera frame.
- The honesty rules carry over unchanged in kind:
  - every number is worked out by the room, rounded down to 5 cm and framed
    ("about 0.7 m");
  - the guide quotes numbers and never makes one;
  - a standard is said as guidance ("guides usually allow ...");
  - a proposed change takes "would";
  - the person is the authority on what a scan can't know;
  - no compass directions, since the scene's sun is staged.
- A reply carrying a measurement found nowhere in the brief, the tool results
  or the person's words is logged (observe-only).
- Only `claude-opus-5-5` and `claude-sonnet-5-5` may see a room, as in 0360.
  The gateway refuses any other model and asks for no server-side fallback that
  could route the room elsewhere.

Rooms without a diorama scene keep today's guest unchanged.

## Why

Expert advice needs the room's structure. Quoting honestly needs every number
to come from the room. Moving the arithmetic into the analyzer gives both:
the guide talks about light, flow and fit like a designer, and every figure it
says was measured or computed by code.

## What would change this decision

- The live guide reaching for numbers the brief does not hold (the flag
  measures this). The fix is a finding that carries the number, not a looser
  rule.
- Sharing (0131's trigger) would make the remembered facts a question of whose
  room it is.
