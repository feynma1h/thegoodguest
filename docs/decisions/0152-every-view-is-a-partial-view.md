# 0152 — every view is a partial view, and that is the regime

**Date:** 2026-08-13
**Status:** Decided — no selection change, one experiment named

## Context

The operator's verdict on the 2026-08-13 walk was a redirect, not a bug
list: "there's no point in spot fixing these problems one at a time in a
capture/frame selection procedure that's not good enough." Their eight
named defects are mostly one thing in several costumes — no legs for the
big table, very short legs, half rendered — plus two 180° facings, which
are the degree of freedom three instrument families are measured dead on.

0146 had already refuted view selection across seven features. That
refutation was scoped to features about the BOX's projection. It did not
test the two ways a view can show only part of an object that actually
apply here: the object being OCCLUDED by other furniture, and its own SAM
mask being CLIPPED by the frame edge. So the redirect deserved a real
test, not a restatement.

## What we tried

**Occlusion, measured geometrically** — project every box into a frame and
count how much of the target's footprint a NEARER box covers. Nothing in
the pipeline computes this, at any layer.

It varies enormously across the shipped views: 0.00 to **0.90**. And on
four of fifteen box objects a far cleaner view exists in the capture and
was never looked at — spike box_05 shipped at 0.90 occluded with a 0.22
view available, rp7 box_05 at 0.50 with a 0.00 available, rp7 box_01 at
0.30 with 0.03, spike box_00 at 0.11 with 0.00.

**But the two "legless table" complaints are not selection failures.**
rp7's table ships at 0.37 occluded and 0.37 is the best the whole capture
offers across 27 qualifying frames; rp6g1's ships at 0.50 and 0.50 is the
best across 49. Every frame that sees those desks well sees them equally
obstructed — which is what a desk with a chair pushed under it looks like
from anywhere a person stands.

**Neither occlusion nor mask clipping predicts quality on the paired set**
(occlusion: better shape 3/5, better cross-view silhouette 0/5; clipping
2/6 and 4/6) — but that set cannot answer the question, because the clean
views were never reconstructed. Every available pair is "occluded" versus
"differently occluded".

**The measurement that does say something is absolute, not comparative.**
How much of a box's projected footprint its own SAM mask actually covers —
the inverse of the `overlap` the ranking uses, and computed nowhere:

    median 0.40, and 13 of 15 shipped views below 0.60
    r(coverage, shape error) = +0.262 — the wrong sign
    the two best-covered views (0.71, 0.78) are the cupboard facing
    backwards and the short-legged table

## What we chose

No selection change, and no capture-technique change. Both are recorded as
untaken with the experiment that would settle them.

The finding that replaces them: **the pipeline's input regime is that every
reconstruction is made from a view showing a median 40% of its object.**
That is not a ranking problem. A single view cannot show a whole piece of
furniture in a furnished room — the far side is never visible and the legs
are occluded from any standing viewpoint — so no selection policy over
single views has a good option to pick.

## Why

The operator is right that the procedure is the problem and the
measurements locate it one level up from where the brief put it: not
*which* frame the pipeline picks, but that it picks **one**. Ten candidate
view-quality measures have now failed to predict reconstruction quality
(0146's seven, plus occlusion, mask clipping and mask coverage here), and
the eleventh reading — the absolute coverage — explains why: they are all
ranking options that are uniformly bad.

That makes multi-view consumption (0151) the whole game rather than one
option among several, and it is why the sampler's 75–83% object-blind
frame budget is worth nothing until something can use more than one view.

## What would change this decision

**The one experiment, and it needs the GPU.** Four objects have a
geometrically much cleaner view available — spike box_05 is the extreme,
0.90 occluded shipped against 0.22 available. Add an occlusion term to the
census cover gain and the association ranking behind an env flag,
re-drive, and compare those four against their shipped reconstructions. If
a genuinely unoccluded view reconstructs materially better, selection is
worth having after all and this decision is superseded for the objects
where a clean view exists. It still would not touch the two legless
tables, where no clean view exists at any layer.

**Capture guidance narrows to one honest form.** 0150 ruled out per-object
sufficiency feedback because coverage is not the scarce resource, and that
stands. What these numbers would support instead is far more specific:
telling a user to get LOW, or to move the chair out from under the desk —
guidance about obstruction, not about angles. Worth building only if the
experiment above says an unobstructed view actually reconstructs better.
