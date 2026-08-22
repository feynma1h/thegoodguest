# 0212 — the three flags are one decision

**Date:** 2026-08-22
**Status:** Decided — refine and select flip together; the residue waits

## Context

Mask refinement (0201), arm selection (0204) and the object-aware residue
(0202) were built in that order by two lanes, each measured against a room
with the other two OFF, and CLAUDE.md describes them as "one chain — supply,
selection, repair". The chain was named; what nobody had was a room with more
than one link live at once.

This lane ran all three on rp7 at 0% traffic, in rounds, each round adding one
flag to the last. Every round's frame set, plan and box-view execution order
had been derived offline first and matched live exactly, so the differences
between rounds are attributable.

## What we measured

**Round 1, refine alone.** The detector flagged rp7 f114's desk at 0.403 and
the repair was accepted, reproducing 0198's bench to the pixel — 58,386 →
61,439 mask px, IoU 0.9493. Against its measured box the desk went from
filling **0.321** of its narrowest dimension to **1.122**; the 21 cm slab
became a body. **And the manifest shipped the other arm anyway** — box_02
took frame 7's association, because the shipped arm is the first association
carrying a splat.

**Round 2, + arm selection.** Exactly one object moved, and it was the desk:
`shipped_fill 0.4151 → chosen_fill 1.0644`, `fill_gain 0.5205` against a 0.10
margin.

0204 had measured this same object **keeping** its arm — recorded as "the
opposite-signed half of 0197's walked pair", and the reason arm selection was
described as moving exactly one object across four rooms, none of them rp7's
desk. Nothing about the chooser changed here. **Round 1 changed what it was
choosing between**: 0204 scored the unrefined slab, which loses to anything.

**Round 3, + the object-aware residue.** The sampler's frame set changed as
predicted, seven of twelve frames, with starved boxes going 2 → 0. It bought
the bed a real improvement — an arm overflowing its box at 1.4037 replaced by
one fitting at 0.8817. **And frame 114 is not in the new set**, so the
repaired arm was never a candidate: the desk reverted to frame 7 at 0.4151, and
no refinement fired anywhere in the room.

## What we chose

**Refine and select flip together, as one change, refine first.** Neither is
correctly valued alone, and this is measured in both directions: arm selection
looked inert on rp7 because it was offered a broken arm, and mask refinement
looked cosmetic on rp7 because nothing selected the arm it repaired. A room
with refinement on and selection off ships the repaired arm **nowhere**.

**The residue does not flip yet**, and this is not a negative on 0202 — the
supply change does exactly what it claims, live and to the frame. What it also
does is resample away from the frames the repair depends on, and that
interaction was not in anyone's model.

## Why the interaction is structural, not bad luck

The three flags act at three different stages — the residue chooses *frames*,
refinement changes the *mask* within a frame, selection chooses among the
*arms* those frames produced. Every stage is upstream of the next, so a change
at the earliest stage can silently delete the input the latest one was
improved by. There is no shared state to notice it: the sampler has no idea a
frame carries a repaired mask, and the chooser can only choose among arms that
were sampled.

That is also why rp7 understates the risk. rp7 flags **1 of 12** planned box
views — the lowest of the four preserved captures (rp6g1 3/10, rp6g2 2/5,
spike 4/10, 10 of 37 overall on the cold plan). A room where refinement fires
four times has four times as much to lose to a resample.

The honest scope: **one room, one refined object, one residue trade.** The
coupling is demonstrated; its sign on any other room is not.

## What would change this decision

- **The same three-round comparison on one more room**, spike for preference —
  it has the highest cold flag rate, so the interaction should be largest
  there. Roughly 3 cold drives, ~2,700 GPU-s. That is the cheapest thing that
  turns this from an anecdote into a rule, and until it exists the residue
  should stay off.
- **A sampler that knows which frames carry a repair.** The residue picks
  frames on pose diversity per box; if a frame whose mask was repaired scored
  as more valuable, the trade would not arise. That is a real design, not a
  tweak, and it should not be attempted before the measurement above.
- **An operator ruling that the desk is not actually better.** Everything here
  rests on the repaired arm being an improvement, which is a number
  (fill 0.321 → 1.122) and a picture. The picture is at gitignored
  `outputs/ship/WALK.md`; 0198's amendment is the standing reminder that the
  number can be right while the object is on its side.
