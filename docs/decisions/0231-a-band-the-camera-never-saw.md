# 0231 — a band the camera never saw

**Date:** 2026-08-23
**Status:** Decided (built, inert — no threshold, no gate)

## Context

`mask_refine.unclaimed_in_box` returns one number for a box view: the share
of the frame's own measured, in-box, off-plane points that no mask claims.
`fraction >= 0.30` flags the view for refinement.

That number pools two different defects, and the only response available to
either is the same one.

* **rp7 f114** — the camera SAW the desk's lower band and the mask claimed
  almost none of it. A mask defect, and exactly what 0198's repair fixed.
* **rp7 f7** — the camera saw NOTHING there; the legs run off the frame.
  A view defect. No prompt and no repair reaches it.

They read **0.403** and **0.163**. On f7 the action the number suggests is
the wrong one, and no threshold on a pooled value can say so, because a band
the camera never saw contributes no considered points at all — its absence
is invisible in a mean taken over the points that exist.

## What we tried

Decomposed the detector's already-considered points by height, using the
crude structural cut the instrument already uses: `lower` [0.10, 0.70),
`upper` >= 0.70. A band with zero considered points reports **`None`, never
0.0**.

Replayed production's own `unclaimed_in_box` over every planned box view in
the four preserved captures — **26 views**. The pooled numbers reproduce
0198's pair exactly (0.403 / 0.163), which is the check that this is
production's detector rather than a relative of it.

Predictions registered first, all three **hit**:

| | |
|---|---|
| the charter's pair separates on the lower band | f114 **864 px at 0.576 unclaimed**; f7 **0 px, `None`** |
| views whose lower band is not visible at all (predicted 3-15) | **8 of 26** |
| category disagreements between pooled flag and lower band (predicted >= 1) | **5** |

The disagreements are the payload, and four of the five run the dangerous
way — **flagged for refinement while the lower band is not visible at all**:

| view | pooled | flagged | lower band |
|---|---|---|---|
| rp6g1 b02 f178 bed | 0.3119 | yes | **not visible** |
| rp6g1 b03 f216 desk | 0.3217 | yes | **not visible** |
| spike b05 f171 desk (x2 masks) | 0.6729 | yes | **not visible** |
| spike b00 f398 cabinet | 0.1999 | **no** | **0.9118** unclaimed over 102 px |

The last one runs the other way: the camera saw that cabinet's lower band and
the mask claims almost none of it, and the view is not flagged, because 2,253
upper-band pixels at 0.167 outvote 102 lower-band pixels at 0.912.

One measurement fell out that belongs to the next item. Of 152,427 considered
points across all 26 views, **269 — 0.2% — lie below 0.10 of box height**,
and **24 of the 26 views have exactly zero there**. That is the room-plane
rejection emptying the bottom tenth of every floor-standing box, measured on
production's geometry rather than on the instrument.

## What we chose

Record both readings beside the pooled one. **No new threshold, and nothing
is gated on them.** `flagged` is byte-identical to what it was, and a test
pins that.

The record carries an explicit null rather than omitting the key, because a
reader has to be able to tell "the mask claimed none of what was seen" from
"nothing was seen" without knowing which keys to expect.

## Why

Splitting without gating looks like half a change. It is the whole of what is
justified, for a reason this repo has paid for before: **a threshold fitted
to 26 views on four rooms is the sort-key mistake 0197 refused**, and the
disagreement table above is a description of a population, not evidence about
what to do with any member of it.

What the split changes today is that the two defects are *distinguishable in
the record*. Four of 26 planned box views spend a refinement on a band the
camera never saw, and nobody could have known that from the manifest. Whether
that refinement is wasted is a separate question — an unclaimed tabletop is a
real mask defect and the repair may well be right there — but it is not the
LEG story, and the leg story is what 0198's headline is about.

The one alignment hazard is pinned rather than argued. `bands` indexes the
height fractions of the kept points while `free` indexes the same points in
raster order; if those diverge the numbers stay plausible and become
meaningless. Three synthetic tests fix it by construction, including a mirror
case that a transposed or reversed index cannot pass, and they derive the
band boundary from `BAND_UPPER_MIN` rather than hard-coding it.

## What would change this decision

The obvious next step is to gate on the split — refine only where the lower
band is visible and unclaimed. **Do not take it on these numbers.** Four
views is a population that cannot support a rule, and 0201's flag rate is
measured on the cold plan (10 of 37) rather than the warm one this replay
uses (26 views), so the two are not the same denominator.

What would support it is the output side, which is where every instrument in
this repo that has ever worked has lived: reconstruct the flagged views with
and without refinement and score the results against their measured boxes.
That is a GPU bench, it is the shape 0198 and 0211 already used, and it would
answer whether a refinement aimed at an invisible band helps, harms, or does
nothing.

If the band cut is ever retuned, `BAND_LOWER_MIN` and `BAND_UPPER_MIN` are
the one place, and the instrument's copies in `outputs/room-quality/partwise.py`
carry the same values for the same reason — they were chosen so a tabletop
lands in `upper` on every box in the four captures, and nothing has been
fitted to them since.
