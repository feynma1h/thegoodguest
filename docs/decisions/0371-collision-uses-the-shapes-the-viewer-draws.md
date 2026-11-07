# 0371 — Collision uses the shapes the viewer draws

**Date:** 2026-11-07
**Status:** Decided — `model.py` (`_parts`, `_reduce`), `web/player.js` (`solids`)

## Context

With every piece treated as its whole box, the engine found no better layout
for the demo room. The desk chair could not tuck under the desk, because two
boxes cannot share space. A desk is a top on legs, and the space under it is
empty. The first plan also needed a special rule: floor may be shared only
under a table.

## What we tried

- Whole boxes, plus an exception for knee space. That is a furniture rule, the
  kind 0370 removes.
- Asking the rules pass to declare open space under a piece. Workable, but the
  scene already has the true answer, in the code that draws it.

## What we chose

The player, running in the diorama viewer, measures each piece's drawn meshes
in the piece's own frame and posts them back. The engine uses those boxes as
the piece's solids:

- each box is trimmed to the piece's scanned size;
- each piece is merged down to at most eight boxes, always merging the pair
  that adds the least empty space, so a desk keeps its top and legs apart while
  a shelf of books becomes one block;
- part pairs are tested only where each part can reach the other piece.

A piece with no export is its whole box. Something lying flat on the floor
(about 3 cm or less) can be stood on and collides with nothing.

## Why

What collides is what you see. On the demo room, real shapes let the chair
tuck in, and the search found the change it could not find with boxes: the
office chair set at the desk, which also opens the side of the bed by the
desk.

## What would change this decision

- If the pipeline publishes part boxes per piece, the browser export can go.
- If the drawn model and the real furniture disagree badly (a builder drawing
  a solid base where the real piece has legs), the fix belongs in the builder,
  not in a rule here.
