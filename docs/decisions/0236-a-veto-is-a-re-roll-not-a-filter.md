# 0236 — a veto is a re-roll, not a filter

**Date:** 2026-08-24
**Status:** Decided (the flag stays OFF, with a reason rather than a blank)

## Context

0234 built `PERCEPTION_VISIBILITY_VETO` under one restriction, and that
restriction is the whole design: **reject only, never rank.** Eleven view
measures are refuted (0146, 0152, 0162) and 0197 measured the twelfth as
large and BIDIRECTIONAL, so the vetoes answer only "can this frame serve
this object AT ALL", at zero, and — in the module's own words — "every
surviving frame is ordered by exactly what ordered it before".

It shipped off, with its long-tail regression check explicitly unrun:
detection counts need frames that were never segmented, so they need a GPU.
0234 named that a **blocker**, not a deferral. This is the drive, run at
review, plus the offline measurement that should have preceded it.

## What we tried

**First, offline, through production's own `select_frames_census`.** The
restriction on ORDERING is real. What it does not constrain is the SELECTION:

| capture | frames changed | veto-1 rejections | veto-2 pairs |
|---|---|---|---|
| rp7   | **5 of 12** | f147, which was never selected | `f7:box_02` |
| rp6g1 | **8 of 12** | none | `f43:box_03` |
| rp6g2 | **3 of 12** | 9 frames (f99–f121) | none |
| spike | 0 of 12 | none | `f171:box_05` |

**16 of 48 frames across the corpus**, where 0234 reports "3 unusable frames"
and "3 band-vetoed pairs" and nothing about blast radius.

**The mechanism is one line of the cover loop.** A vetoed (frame, box) pair
leaves that box uncovered, so the greedy pass spends an EXTRA cover pick on
it. That changes both the SEED and the COUNT of the farthest-point residue,
and the residue re-rolls entirely. On rp6g1 one pair — `f43:box_03` — added
one cover frame (f136) and moved **7 of 10 residue frames**. The veto never
ranked anything. It did not have to.

**Then the drive**, on the serving revision (`00062-hum`, both new flags
off), with each room's bundle trimmed to the veto's own 12-frame selection so
the whole-bundle path reproduces it without the flag being in the image.

**Detections, which is the check 0234 owed** (from `masks.npz`, complete for
every selected frame even on a budget-stopped run):

| capture | shipped | with vetoes | |
|---|---|---|---|
| rp7   | 39 | **57** | +46% |
| rp6g1 | 49 | **43** | **−12%**, past 0234's own ≤10% bar |
| rp6g2 | see below | | |
| spike | 38 | 38 | the veto changes nothing there |

**And the output-side instrument** — three-axis error against the box
RoomPlan measured, which is the one instrument that has ever separated good
from bad here. rp7, all six box views complete before the budget stop:

| box | shipped | with vetoes | |
|---|---|---|---|
| chair | f7, **0.655** | f115, **0.083** | −0.572 |
| bed | f294, **0.419** | f363, **0.799** | **+0.380** |
| cabinet, desk, nightstand | | unchanged | |

## What we chose

**The flag stays off, and this is why rather than a blank.** Not because the
vetoes are wrong — veto 1 is unarguable, see below — but because the switch
as built cannot be enabled without accepting a whole-selection re-roll whose
measured effect is one large win and one large loss on the first room that
ran.

## Why

**Rejecting is not a small intervention in a greedy selector.** The design
reasoned about ORDER, and order is genuinely untouched. But set-cover is
sequential: removing one candidate changes which frame wins a round, and
every later round is conditioned on that. The residue then compounds it,
because farthest-point sampling is seeded from the cover picks. So a
restriction that is airtight about ranking says nothing at all about how much
of the answer moves.

**The two vetoes have opposite risk profiles and one switch.** Veto 1,
whole-frame usability, fires only on rp6g2 — and the two frames it removes
from that room's COVER pass, f103 and f119, produced **0 detections each**
(mean luma 2.46 and 1.88, 0235's black tail). A frame that yields nothing was
holding box coverage; removing it cannot cost anything. Veto 2, per-(object,
frame) lower-band visibility, fires on the other three rooms, one pair each,
and is what triggers the cascade above. **They should not share a flag.**

**The bed is the sharpest single finding, and it is not about the veto.**
f294 is in BOTH selections. The veto ADDED f363, whose bed mask has a higher
association overlap, and association is greedy on overlap, so with
`PERCEPTION_ARM_SELECT` off — production today — the new arm ships and fits
its measured box **90% worse**. **Adding a frame can replace a good arm with
a worse one, on overlap alone.** That is a property of association, not of
the veto; any change that widens the candidate set inherits it, and arm
selection is the mitigation, which is one more reason 0212's enable order
puts arm-select before anything that touches supply.

**rp7 gaining 46% more detections is not a defence.** 0197 measured point
count picking the wrong view; detection count is the same kind of number.
The room gained detections and lost its bed.

## What would change this decision

**Split the flag.** Veto 1 alone is measured free on the only room that
triggers it and should be judged on its own.

**Contain the cascade.** If a vetoed pair relaxed that box's own bar in place
— the `VETO_RELAX_STEPS` machinery already exists, and today it only runs for
a box the vetoes would otherwise ORPHAN — rather than buying an extra cover
pick, the residue's seed and count would be unchanged and the change would be
as local as the design intended. That is the version worth measuring next,
and the number to beat is 16 of 48 frames moved.

**Arm selection ON.** The bed regression is invisible to it, and the veto's
losses should be re-measured once the chooser is live rather than against
greedy-on-overlap.
