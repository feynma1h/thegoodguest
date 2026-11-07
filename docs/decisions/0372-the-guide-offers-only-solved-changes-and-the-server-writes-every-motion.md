# 0372 — The guide offers only solved changes, and the server writes every motion

**Date:** 2026-11-07
**Status:** Decided — `engine.py`, `motion.py`, `guide.py`, `web/player.js`; extends 0131 and 0132

## Context

The operator asked that any move the guide suggests can play in the viewer in
real time with nothing intersecting. 0132 had already split the work: the
guide states intent and a server solver writes positions. Moving pieces live
adds two questions: what the guide may suggest, and who decides how a piece
gets from here to there.

## What we tried

- Letting the guide describe a change and solving it only when the person says
  yes. The guide could then promise a move the room refuses.
- Tweening between the start and end poses in the viewer. Pieces would pass
  through each other on the way, and a spring easing could overshoot into a
  wall.

## What we chose

**Suggestions.** The guide's tools (`look_for_changes`, `move`) return only
proposals the engine has solved and the motion planner has checked. A proposal
whose motion fails is never offered. The guide's own ideas reach the person as
"Show me" cards. A change they ask for plays at once, and putting it back is
always one step.

**Motion.** The server plans every move:
- one unit at a time (a floor piece with what rests on it);
- in an order that never moves a piece into a spot another still holds;
- with a parking spot when two pieces need each other's places;
- each path the first that stays clear: straight, pulled out from its wall
  first, a floor search capped at about a second, or a short lift.

The whole plan is sampled at 60 frames a second and refused if any frame breaks
law 1 or 2. The viewer plays the keyframes with the same smoothstep easing. It
never overshoots, so a check of the path is a check of the screen.

Placement rotation is now solvable in quarter turns and "face X" (amends
0132's translate-only rule). A piece that goes `at` another is seated at its
front, `beside` is carried along, and `over` is re-hung on the new wall.

## Why

The guide can't promise what the room won't take, and the person never sees a
piece pass through another. The viewer stays a player that decides nothing,
which is 0131's rule that the client never writes a transform, extended to
motion.

## What would change this decision

- If people want to watch several pieces move at once, overlapping segments
  would each need checking against each other.
- Pieces outside a proposal can't yet be moved aside to clear a path (moving
  the desk to get the bookcase out). Proposals needing that are dropped today;
  building it means adding temporary moves to the planner.
