# 0162 — the better frame did not reconstruct better

**Date:** 2026-08-14
**Status:** Decided — settles the experiment 0153 and 0154 both named

## Context

0153 measured the frame a box was reconstructed from at a median 0.50 of the
best available sharpness; 0154 measured it seeing a median 0.48 of the
surface the best available frame does. Both notes ended at the same caveat,
and it is the reason this experiment exists: *"the measurement stops at 'a
much sharper frame existed'. It does not show that reconstructing from it
produces a better object, because none of those frames was ever segmented."*

The operator granted the GPU to find out.

## What we tried

rp6g1 re-driven with `PERCEPTION_PLAN_VIEWS_PER_BOX` at 4 and its per-frame
`objects.json` cleared so the planner could see the views it had previously
policy-skipped (0160 explains why clearing them is necessary — the raised
budget alone is inert). Splats and masks retained, so the cost was the new
reconstructions only. Two rounds, converged, `budget_stopped=False`, plan
`{box_best_views: 5, box_second_views: 8, long_tail: 35, policy_skipped: 0}`
— exactly the plan the offline replica predicted.

Restricted to the 12 sampled frames the room went from 40 ok / 3 skipped to
**43 ok / 0 skipped**: the three previously-skipped views, reconstructed for
the first time, and nothing else changed.

**Those three views are markedly better on both axes.** Against the views
their boxes already had:

    sharpness (0153)      new median 0.368   old median 0.216   1.7x
    surface seen (0154)   new median 0.143   old median 0.067   2.1x

**Their reconstructions are not better.**

    fidelity at one voxel  new median 0.639   old median 0.780
    shape error            new median 0.153   old median 0.181

The decisive case is the one picked in advance as the strongest test in the
whole dataset. rp6g1's bed had two reconstructions, from frames seeing 0.038
and 0.098 of its surface at sharpness 0.339 and 0.218. Frame 43 sees
**0.297** of it — three to eight times more — at sharpness **0.512**, the
sharpest view of that box anywhere in the capture. Reconstructed, it scores
fidelity 0.639 against the incumbents' 0.801 and 0.740, and shape error
0.161 against 0.038 and 0.129. Worse on both instruments, from much the
better photograph.

Across the four boxes with more than one reconstruction, sharpness picks the
best view in **2 of 4** and surface seen in **2 of 4**.

## What we chose

No selection score, and none built even behind a flag — the measurement that
would justify one came out against it.
`PERCEPTION_PLAN_VIEWS_PER_BOX` reverted to 2 (0160), rp6g1 restored
byte-identically to its pre-experiment manifest.

0153's and 0154's gaps are real as gaps. What this adds is that they do not
convert: feeding the reconstruction a sharper frame that sees twice as much
of the object did not produce a better object. Eleven view-quality measures
have now failed to predict reconstruction quality, and this one is different
in kind from the other ten — it is the only one tested on views that were
actually reconstructed rather than correlated over views the pipeline had
already chosen.

The mechanism 0146 proposed survives intact and now has a second
demonstration: the variance between two reconstructions of one object is
dominated by SAM 3D's own behaviour, not by which camera took the picture.
0146's evidence was two reconstructions from a single frame differing 3x;
this is the same point from the other side.

## Why this does not read as "selection is worthless"

0161 measured the reconstruction carrying a median 0.777 of the surface its
own view showed it, so surface fed in does mostly survive into the object.
That is not contradicted here: what fails is the claim that a single better
frame is reachable by ranking. Both facts point the same way — 0155's third
row, a union of several views, is the option with headroom left, and 0151 is
where it lives.

## What we did not learn, stated plainly

**n is small and one room.** Three new reconstructions, four boxes with more
than one view. This is the first direct test, not a decisive one.

**The completeness instruments are not validated.** 0161 records that
neither surface coverage nor fidelity separates the operator's named-broken
objects from the rest. "Worse" here means worse on instruments that have not
earned trust, which is the same caveat 0146 and 0152 carry.

**The added views are confounded with their rank.** They are rank 2 or later
by footprint overlap, so they are the weakest-associated views of their
boxes by construction. "Sharper but more obliquely associated" is not the
same experiment as "sharper, all else equal", and this cannot separate them.

## What would change this decision

A sampler that puts genuinely better frames into the candidate set — the
sharpest frames in these captures are 2 to 12 times sharper than what was
tested here, and none of them is in the sampled twelve (0160: the sampler,
not the budget, is what stands between the pipeline and them). If those
reconstruct better, this decision is about rank-2 views rather than about
sharpness, and it should be re-taken.

An instrument that separates good reconstructions from bad ones. Everything
above is measured on two that do not.
