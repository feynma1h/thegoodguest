# 0225 — coverage for visibility, purity for orientation

**Date:** 2026-08-23
**Status:** Decided

## Context

`truthlayer.py` builds a fused per-object LiDAR cloud — every keyframe's
depth raster back-projected, carried to world, clipped to a RoomPlan box's
padded volume, voxelized at 1 cm. It yields 10,684 to 444,126 voxels per
box against the 2,401 points a single-view masked cloud gave the same
chair. That is a 4-180x increase in measured mass, and the natural reading
of it is that every measurement in this repo taken against one view gets
better by being taken against all of them.

That reading is wrong for a whole class of question, and this note exists
because the failure is silent: the fused cloud makes the orientation
question measurably WORSE while looking like strictly more evidence.

## What we tried

Cloud->splat Chamfer as an axis-assignment resolver, over the six axis
assignments RoomPlan boxes admit, scored through production's own
`exp(-rms / _AXIS_CLOUD_SIGMA)` transform so margins land in the same units
as the shipped `_AXIS_MARGIN` (0.10) and as 0081's measured noise band
(0.0018-0.089). Two checks, both free (probe 21):

**M1 — the margin distribution**, best assignment against second best, over
every box in the four preserved captures.

| | value |
|---|---|
| median margin | **0.0287** |
| maximum margin | 0.2565 |
| boxes clearing the shipped 0.10 gate | **1 of 20** |
| boxes inside 0081's refuted noise band | 16 of 20 |

**M2 — stability**, the same winner under `reject_planes` on and off and
under `min_confidence` 1 and 2. **7 of 20 winners move** when the cloud's
contamination changes. A box whose answer moves with the contamination is
reading the contamination.

## What we chose

State the constraint generally, as a property of what the fused cloud is
for, rather than as a footnote on a dead orientation item:

> **COVERAGE for visibility questions. PURITY for orientation questions.**

A visibility question — did this camera see this object's legs, does this
mask claim what the camera saw — asks whether measured mass EXISTS at a
location. More views can only add mass that is genuinely there, so
accumulating them is monotonically better, and the fused cloud is the right
substrate. This is where every useful round-3 result came from: the
sub-slab leg voxels, the band-decomposed claim rate, probes 19 and 20.

An orientation question asks which of several poses of one reconstruction
best EXPLAINS the measured mass. Every voxel that belongs to something
other than the object is a term in that comparison, and a box's padded
volume is 9.5-81.2 percent floor and wall before you count the bag on the
table, the chair tucked under the desk, and the wall behind. Accumulating
views adds contaminating mass at the same rate it adds real mass. 0081's
masked single-view cloud resolves the same DOF at margins 0.15-0.47 — an
order of magnitude clear of what the fused cloud manages — because a SAM
mask is a purity filter and the box is not.

So the fused cloud is not a better version of the single-view cloud. It is
a different instrument with the opposite bias, and the two are not ordered.

## Why

The claim that held orientation up was the **same-mass rule**: clutter
cancels across rotations of one splat, because the point set is identical
and only the pose differs, so contamination is a constant offset that
subtracts out of a comparison.

**M2 refutes it.** The mass is common; its COST is not. Rotating a table
moves its legs relative to a bag that stays put — the bag is in both
candidates' clouds at the same coordinates, but the distance from the bag
to the nearest splat point is a different number in every pose. A common
term whose value depends on the variable being compared is not an offset.
7 of 20 winners moving under a perturbation that leaves the object's own
geometry untouched is that mechanism, measured.

Probe 19 already closed the escape route: the contamination cannot be
removed topologically at any radius, because the LiDAR fills the space
between a bag and a table, so the bag and the table are one connected
component. There is no third option where the fused cloud is made pure.

The three refusals already in the shipped code are all downstream of the
same fact and all stay correct: 0148 rejects cloud-based seating because
the cloud is the visible surface; 0081 records the 180-degree sign as
cloud-near-degenerate at 0.003-0.006; 0205's fill/residual disagreement
exists because a bounding comparison is all a splat-vs-dims check can be.

**Two things die with the same-mass rule.** First, orientation via c2s:
1 of 20 clearing the gate is a gate that never fires, which is worse than
no gate because it looks live. Second, the speculation that a fused cloud
might separate the **180-degree facing sign** — that rested entirely on
same-mass, over a DOF that is *more* degenerate than the assignment DOF
this probe measured, not less. The sign stays exactly where 0171 put it:
read from the layout, shipped flag-only, six refuted instrument families.

## What would change this decision

The constraint is about purity, so only a purity mechanism reopens it. A
per-object fused cloud accumulated through each frame's own SAM mask rather
than through the box volume would be a genuinely different instrument — it
would carry the single-view cloud's purity with the fused cloud's coverage.
It is not free: it needs masks on every keyframe rather than on the sampled
ones, which is the cost that made the box clip attractive in the first
place. If that ever exists, M1 and M2 should be re-run against it before
anything is built on it, and the numbers above are the bar.

Nothing about MORE VIEWS reopens it. That is the variable this probe swept,
in the direction that was supposed to help.
