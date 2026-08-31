# 0292 — collapsing a nested pair must not re-rank it against everything else

**Date:** 2026-08-30
**Status:** Decided and built, behind `PERCEPTION_KEEP_LONGER_MASK` (default off)

## Context

[0266](0266-keep-the-longer-mask.md) decided the rule: when SAM 3 returns one
object at two nested extents, keep the longer. It was measured by RESCORING nine
operator-ruled pairs — asking, of each pair, which member the shortlist should
have taken. It scored 9 of 9, beating every gate 0263 built for the job.

Building it exposed something rescoring pairs cannot see. A pair does not
compete only against itself.

## What we tried

The obvious implementation drops the shorter member from the observation list
before `associate_observations` scores anything — the defect 0266 names is
ordering, so move the decision in front of the sort. Measured against the
planner's own observation set on the four preserved captures, with a
pre-registered prediction of "on the order of nine boxes move, every one short
to long":

| | |
|---|---|
| nested pairs collapsed | 9 |
| boxes whose planned mask moved | 2 |
| short → long | 1 |
| **long → SHORTER** | **1** |

**spike box 0 got worse.** Off, it plans frame 398 mask 4 — 415,585 px at
overlap 1.0000. On, it plans frame 354 mask 4 — 111,070 px, a different frame
and a quarter the size. Meanwhile the 824,005 px mask the rule existed to
promote sat on the same box's shortlist at rank 2, unused.

**The cause is not the rule; it is the ranking underneath it.** Dropping an
observation changes its position against EVERY other observation, not against
its partner. The sort is `(-overlap, frame_index, mask_index)` over 0262's flat
metric, so deleting a candidate that scored 1.0000 promotes whatever scored next
— and where the metric saturates, "next" is decided by capture order. The
collapse had removed box 0's best-scoring candidate and handed the box to an
unrelated earlier frame.

The first diagnosis was wrong and worth recording: the obvious suspect is that
the survivor got claimed by a different box, since association is greedy and
global. Measured, it did not — the survivor stayed on box 0 the whole time and
merely fell to rank 2.

## What we chose

**The survivor competes at its PAIR's best overlap.** The collapse records what
each survivor absorbed, and `associate_observations` scores a survivor as
`max(its own overlap, the absorbed members')`. The pair then enters the sort as
one object, which is what it is.

Re-measured on the same corpus:

| | before | after |
|---|---|---|
| boxes whose planned views moved | 2 | **4 of 25** |
| short → long | 1 | **3** |
| long → shorter | **1** | **0** |
| lost or gained an association | 0 | **0** |

All three promotions are now **within the same frame** — mask 11 → 14, mask 4 →
1, mask 7 → 4 — where before they crossed frames. The fourth box is spike box 5,
which loses its second planned view because both of its two budget slots held
the same object at two extents in one frame; 0266 already recorded that pair,
and freeing the slot is the fix working rather than a cost.

**Flag off is byte-identical**, proven rather than argued: HEAD's
`box_placement` and the working tree's were imported side by side and every
association on all 25 boxes of the four captures compared to twelve decimal
places, with the flag off. Zero differences.

## Why

**Rescoring a pair and re-ranking a list are different experiments, and only the
second one ships.** 0266's 9-of-9 is not wrong — every one of those pairs still
resolves the way it ruled. It simply could not observe what removing the loser
does to the rest of the list, because it never built the rest of the list. A
decision measured on pairs needs re-measuring on the corpus before it is code.

**And the flat metric is load-bearing in a way that is easy to miss.** 0262
recorded saturation as a defect in how the winner is chosen. This is the same
fact acting as a hazard on any change that REMOVES a candidate: where 31 of 52
candidates score exactly 1.0000, the runner-up is capture order, so anything
that deletes a leader hands the room to whoever was photographed first.

## What would change this decision

**The tie limit is real and is pinned as a test.** Inheriting the pair's best
overlap decides the pair; it does not flatten the metric. Where an unrelated
observation ALSO scores 1.0000, the tie-break is still `frame_index` and the
earliest frame wins. Nothing here fixes 0262, and a reading of this note that
says otherwise is wrong.

**The flip is a candidate deploy, not a merge.** Four boxes across four captures
change what gets reconstructed, and three of those are objects whose splat the
operator has walked before. The acceptance test is the same as every placement
flag since 0198 — a 0%-traffic candidate, a re-drive, and the operator's eyes on
the objects that moved — not a green suite.
