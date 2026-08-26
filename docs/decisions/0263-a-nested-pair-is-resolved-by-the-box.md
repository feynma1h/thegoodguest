# 0263 — a nested mask pair is resolved by the box, not by which one is bigger

**Date:** 2026-08-27
**Status:** Decided (measured; no behaviour change)

## Context

0261 measured SAM 3 returning two `desk` masks of one desk in each of three
frames, at 99.5–99.8% mutual containment, with the shortlist taking the shorter
one every time by 9–12 points. It read the longer mask as the correct extent,
proposed a sibling-gated precision as the likely fix, and named three checks.
This note runs them. Two answers hold and one inverts.

## What we tried

All three offline, over the 19 preserved probe frames.

**Check 3 — how often does this happen?** On `90eebfc4`: 129 detections,
**28 same-label pairs, 6 of them nested**, in 4 of 19 frames, across 4 labels.
Run again over the four preserved captures, on production's own masks under
`outputs/room-quality/cache/`: 194 detections over 48 frames, **93 same-label
pairs, 15 of them nested**, in all four rooms (`cabinet`, `door`, `chair`,
`desk`). So **21 nested pairs across five captures** — recurring, not a
curiosity.

Containment is **bimodal with almost nothing in between, and it stays bimodal
across both corpora**: of 121 same-label pairs, 21 sit at >= 0.989 and 99 at
<= 0.003, with **exactly one** in the whole middle (spike frame 398, `door`,
0.155). Identifying a nested pair needs no threshold judgement, which is the
useful half of this number.

**Check 1 — does the bias hit other objects?** Of `90eebfc4`'s 6, four
associate to a RoomPlan box and **the sort takes the shorter mask in 4 of 4**.
Of the corpus's 15, six associate and the sort takes the shorter in **5 of 6**.
So across both: **9 of 10, spanning `chair`, `desk` and `cabinet` in three
rooms** — not a desk story.

The pairs that do NOT associate reach the long tail, where *both* members are
planned and fusion can reconcile them. The bias is specific to box-associated
objects, which is 0261's "the budget pre-empts the reconciliation" seen from the
supply side.

**Check 2 — what should a recall-aware metric pick?** This is where it inverts.
Measuring what each longer mask *adds*, against the object's own projected box:

| frame | label | box | added region | inside the box | what the longer mask adds |
|---|---|---|---|---|---|
| 50 | chair | box_03 | 24,560 px | **95.1%** | both armrests and the base spokes |
| 50 | desk | box_02 | 58,676 px | 45.7% | a cantilevered arm |
| 51 | desk | box_02 | 48,548 px | 47.1% | the same arm |
| 109 | desk | box_02 | 25,441 px | 30.4% | the same arm |
| 45 | door | — | 432,798 px | — | **100% of it is the separately-detected `cabinet`** |
| 45 | monitor | — | 56,215 px | — | **99.7% of it is the separately-detected `tv`** |

**On the desk — 0261's own example — the shortlist is right.** What the longer
mask adds is a thin arm cantilevered off the desktop, and 54–70% of it lies
outside the measured table. Verified by eye against the drawn hull, not only by
the ratio. 0261 recorded the operator confirming there is no adjoining *surface*,
which is true and is not the same claim: the arm is not a surface.

**On the chair the shortlist is wrong, and expensively.** The shorter mask is an
office chair with no armrests and no base, and 95.1% of what it drops is inside
the chair's own box. It won by **0.0057**.

**And 0261's proposed fix would have made the desk worse.** A sibling gate that
strikes any mask contained by a same-label sibling strikes the shorter one every
time — which is right for the chair, wrong for all three desk frames, and wrong
for the door and monitor pairs if they ever associated.

**The same measurement over the corpus separates just as cleanly, and overrules
the sort in three more places.** Of the six corpus pairs that associate:

| room | frame | label | box | short / long overlap | added region inside the box | |
|---|---|---|---|---|---|---|
| rp7 | 162 | cabinet | box_03 storage | 1.0000 / 0.9856 | **98.0%** | sort is wrong |
| rp7 | 162 | cabinet | box_03 storage | 0.9859 / 0.9856 | **98.6%** | sort is wrong |
| rp6g1 | 178 | chair | box_01 chair | 1.0000 / 0.9930 | **95.4%** | sort is wrong |
| spike | 171 | desk | box_05 table | 0.9387 / 0.9583 | 99.4% | sort already right |
| spike | 398 | cabinet | box_00 storage | 1.0000 / 0.7536 | 50.4% | sort right |
| rp6g2 | 0 | chair | box_00 chair | 0.9262 / 0.8005 | 43.5% | sort right |

**Pooled across both corpora the ten containment values are 30.4, 43.5, 45.7,
47.1, 50.4 | 95.1, 95.4, 98.0, 98.6, 99.4** — five below 51% and five above 95%,
with nothing between, measured on two independent sets of rooms.

## What we chose

**Resolve a nested pair by where the added region falls, not by which mask is
bigger.** When two same-label masks in one frame are nested, keep the longer only
if what it adds lies inside the object's measured box; otherwise keep the
shorter. It is inert when there is no sibling, which is 25 of 29 candidate rows
here.

Composed with 0259's border disqualification and ordered by how much of the box
footprint survives, over all 19 probed frames this picks **bed frame 0, table
frame 50, chair frame 42** — the operator's own picks for all three objects they
named, chosen without reference to their list. It changes the other two boxes
too (`box_01` frame 24 -> 94, `box_05` frame 24 -> 33), in both cases from a view
the metric could not distinguish from ten others.

**Nothing ships on this.** The code change is not written. What it would gain is
**four objects across three rooms** — `90eebfc4`'s chair, rp6g1's chair and rp7's
cabinet twice — each getting a demonstrably more complete mask, and it would
leave the other six pairs exactly as they are.

## Why

**The box is not a silhouette, and that cuts both ways.** 0261's reasoning was
that the box is a bound, so a mask correctly covering an object wider than its
box is penalised for being right. That is a real hazard and it is what makes
precision-only wrong for the chair. But the same fact makes the box *informative*
about the opposite case: a region lying well outside the measured volume is
evidence the mask has reached past the object, and here it had — onto an arm the
table's box does not contain.

**The two errors are opposite, so no size rule can catch both.** Prefer-longer
fixes the chair and breaks the desk; prefer-shorter is what ships and does the
reverse. The discriminator has to be something other than size, and containment
in the measured box is the only quantity available that is not itself a
fabrication — the same argument 0104 and 0148 make for trusting the box, applied
to a question the box can actually answer.

**This is not a ranking key, so 0197 does not retire it.** It makes no prediction
about what SAM 3D will do with either mask. It asks where pixels are, against a
volume RoomPlan measured. That is the same standing 0259's three
disqualifications have, and the reason both survive a corpus of eleven refuted
view measures.

**The chair matters more than the desk.** Alpha IS the mask (`models/sam3d.py`),
so a chair mask without armrests or a base deletes them from what the model is
shown. That is class-6 truncation with a cause that is upstream, visible, and
fixable — as against every attack on class 6 so far, which has been downstream of
a model whose unseen half is fabricated.

## What would change this decision

**The threshold is not the load-bearing part; the margin is.** Four cases split
95.1% against 30.4–47.1%, so any cut between roughly 0.6 and 0.9 gives the same
answer. That gap is what makes the rule safe here, and it is four cases. A fifth
that lands mid-range means the containment ratio is not the discriminator it
looks like, and the rule should not ship on a coin flip.

**Containment is measured against a hull whose tightness varies.** The chair's
box projects loosely from close range and encloses part of the desk; the table's
projects tightly. So a loose hull inflates the ratio. It did not change any
verdict here, and it is the first thing to check if one looks wrong.

**Frequency is settled and the answer is "often enough".** 21 nested pairs in
67 frames across five captures, 10 of them associating to a box. That is no
longer the open question it was; what stays open is whether a more complete mask
reconstructs into a better object, which is 0197's question and only SAM 3D can
answer it. The cheapest test is one reconstruction of `90eebfc4`'s chair from
frame 42 against the shipped frame-24 arm, ~25 s of GPU, prediction registered
first.

**The flat tie-break in 0262 is still the larger prize** and the two are
independent: this rule fires on 10 candidate pairs, that one decides a fifth of
all boxes.
