# 0165 — what the missing surface is missing to

**Date:** 2026-08-19
**Status:** Decided — closes the de-occlusion lane's gate as a negative

## Context

0155 measured that a reconstruction is fed a median **0.18** of the surface a
capture holds of its object, against a reference of voxels seen by at least
three frames. 0152 measured that shipped views are 0.00–0.90 occluded, by
projecting boxes onto boxes. Nobody had composed the two, so the share of the
starvation that occlusion accounts for was unknown — and an entire proposed
lane, generatively painting an occluded object back in before reconstruction
(`outputs/handoffs/de-occlusion.md`), was gated on exactly that share.

The threshold was registered in writing before anything was measured
(`outputs/lane-d/PREREGISTRATION.md`, sha256 `611ca9f6…`), on 0181's precedent:
a bar chosen after seeing the number is a rationalisation, not a decision.

## What we tried

Every reference voxel a frame fails to capture, classified by projecting it
into that frame and reading the frame's **own measured LiDAR depth** at that
pixel — not a box proxy, because a chair's box covers substantially more than
the chair:

| class | meaning |
|---|---|
| `self` | a nearer surface inside the object's own box is in the way — the 0.50 single-viewpoint ceiling made concrete |
| `foreign` | a nearer surface that is not the object. The only class a de-occluder can attack |
| `clipped` | projects outside the image |
| `no_return` | the depth raster holds no measurement there |
| `grazed` | the frame's return lands within one voxel's depth of this voxel and on the object — quantisation slack, not missing surface |
| `through` | the ray reached past the voxel and nothing was there: porosity, grazing incidence, range |

Three choices bias `foreign` **downward**, two of them registered in advance:
depth rather than box geometry; self wins ties, so a point counts as foreign
only if it lies in a *different* box (which still catches a chair tucked inside
a desk's box, the case that matters); and a 6 cm blocking tolerance, two voxels.

**The trust gate is that the reference reproduces 0155 exactly** — coverage
median 0.18 for the shipped frame and 0.65 for the best three, on the same 15
box objects in the same three rooms.

**The result, shipped frame, n = 15:**

    self       median 0.253    pooled 0.298
    foreign    median 0.080    pooled 0.151
    clipped    median 0.073    pooled 0.177
    no_return  median 0.077    pooled 0.095
    grazed     median 0.169    pooled 0.179
    through    median 0.075    pooled 0.100

    if every foreign occluder vanished: coverage 0.178 -> 0.265
    median absolute gain +0.061, mean +0.101

**Two robustness checks, both of which could have overturned it and did not.**
Excluding quantisation slack from the denominator — the one reclassification
that raises the foreign share — moves the median only 0.080 → **0.104**, still
below the clear-negative line. And of the foreign voxels, those the object's
*own* observed surface also stands in front of, which removing an occluder
would not reveal, are a median 0.005 — so the upper bound was already tight.

Adding the fourth room lowers the median foreign share to 0.029. rp6g2 is the
budget-starved capture and several of its objects are degenerate here (one
shipped frame has no depth at all, another is 94% clipped), so the three-room
figure is the headline and the fourth is a robustness note in the same
direction.

## What we chose

**The de-occlusion lane does not clear its gate. Close it as a recorded
negative.**

The registered bar was ≥ 25% of the deficit, with < 15% a clear negative. The
median object is at **0.080**; the pooled figure of 0.151 sits exactly on the
marginal boundary and is carried by four objects out of fifteen — **the top
four carry 69% of all foreign share and six of fifteen are under 0.05** — which
is the registered secondary rule about concentration, firing.

**Prediction 3 was falsified, and it is the most decision-relevant
falsification.** The two named hard cases — rp7's desk and rp6g1's table, the
operator's own repeated "legless table" complaint — come in at **0.08 and
0.16**, both under the bar, and their largest recoverable class is `clipped` at
0.38 and 0.40: they run off the edge of the frame rather than standing behind
something.

**This does not refute 0152's 0.37 and 0.50; it reframes what they imply.**
Those are the fraction of the box's projected FOOTPRINT that a nearer box
covers. This is the share of an object's missing SURFACE that a nearer measured
surface accounts for — a different quantity with a different denominator, and
the two can both be right. The nearest common reading is the fraction of each
object's whole measured surface that is foreign-occluded in the shipped frame,
which is **0.07 and 0.14**. So a chair does obstruct a lot of the rectangle a
desk projects into, and obstructs comparatively little of the desk's own
missing surface, because most of that surface is missing for other reasons.

Prediction 1 was also falsified in magnitude — `self` was predicted at ≥ 40%
and is 0.253 median / 0.298 pooled. It is still the largest single named class,
but the deficit is more evenly spread than "the back half you cannot see".

**The one complaint that IS occlusion is the half-rendered chair** (rp7 box_00,
foreign 0.49, 98% of it the table in front of it). Occlusion is real in this
data; it is just not what the tables are suffering from.

## Why

Rank the three candidate fixes on one instrument, which is what this
measurement finally allows:

| | median coverage fed to the reconstruction | cost |
|---|---|---|
| today | 0.18 | — |
| perfect de-occlusion | 0.26 | a diffusion dependency in a 37 GB image, a second generative stage, generated pixels in a shipped reconstruction |
| better selection | 0.31 | server-side, free, the frame is already in the capture |
| best three unioned | 0.65 | registration (0151) |

De-occlusion is the **smallest** of the three gains and by far the most
expensive — that comparison is exactly why the bar was set at 25% before
measuring, and the measurement comes in under it.

Two things this argument does **not** rest on, stated so nobody strengthens it
wrongly. It does not rest on 0162, which measured that a sharper view seeing
more surface reconstructed *worse*: that tested a different photograph, not a
repaired one, and the de-occlusion charter's real case — that completing a
silhouette speaks to the model in the channel 0181 showed it weights — is
untouched by it. And it does not rest on occlusion being rare, because it is
not: it is concentrated, which is a different and narrower claim.

## What would change this decision

**A single object clearing the bar is not enough** — rp7's chair does, at 0.49,
and the registered secondary rule is what stops that from carrying the lane.
What would reopen it is the concentration going away: a wider set of captures
where the median object, not the worst four, sits above 25%. Two rooms of the
four here are lightly furnished; a genuinely cluttered room is the case where
this could look different, and nobody has measured one.

**Or the ranking above changing.** If the union (0151, this lane) is measured
and fails, de-occlusion becomes the second-largest remaining gain rather than
the smallest, and +0.08 against a much shorter list of alternatives is a
different decision from +0.08 against a free one.

**The clipping finding is not a mandate to re-open selection.** 0146, 0152 and
0162 refute selection across eleven view-quality measures and one GPU
experiment. That `clipped` is the largest recoverable class for the two tables
says what their input is missing; it does not say that handing the model a
differently-cropped frame produces a better object, and 0162 is the direct
evidence that it does not.
