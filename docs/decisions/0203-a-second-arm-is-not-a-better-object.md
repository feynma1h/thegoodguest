# 0203 — a second arm is not a better object

**Date:** 2026-08-21
**Status:** Decided

## Context

0197 fixed three of the operator's named objects by changing what SAM 3D
was shown, and 0198 fixed a fourth by repairing a mask. Every one of those
wins was chosen the same way: by eyes, then confirmed against the object's
measured RoomPlan box. The natural production reading is "give each object
more views and the good one will be among them", which is what 0202 builds.

Before shipping that, it is worth asking what production does when an
object HAS two views.

## What we tried

Read it. `box_placement.build_box_object`:

```python
best_view = None
for assoc in associations:  # already sorted best-first
    candidate_splat = ctx.get_splat(assoc.obs["splat_gcs_uri"])
    if candidate_splat is not None:
        best_view, splat = assoc, candidate_splat
        break
```

The first association with a splat wins. `associate_observations` sorts by
mask-hull overlap — how much of the mask falls inside the box's projected
footprint. That is an **input-side** measure, computed before any
reconstruction exists, and it is a close relative of the family 0197
retired: it describes the box's projected footprint, not how well the
object was photographed.

So the arm that ships is chosen by a number that is measured not to predict
reconstruction quality, and the second arm is reconstructed, uploaded, and
then never looked at.

That is exactly what 0197 measured from the other side without naming it
here. Its whole probe was "push the alternative through production's own
`build_box_object` with the association list **reordered**" — the reordering
was necessary because reordering is the only way to make production choose
differently. rp6g1's table went 0.406 to 1.004 of its measured box height
on a view that was already reconstructed and already in the bucket.

## What we chose

Nothing, here. This lane's boundary is what `/process` shows the model, and
arm selection lives in fusion's placement. The finding is recorded rather
than built, and 0202 ships off by default because of it.

What is recorded is that the instrument already exists and is already
measured. 0197 swept two output-side checks against the RoomPlan box —
vertical fill (the placed splat's span over the box's measured height) and
`box_fit_residual`, which every box entry already carries — over the 8 boxes
in the four preserved rooms that have a second cached view. They agree with
the eyes on both walked objects including keeping rp7's shipped view
unprompted, agree with each other on 7 of 8, are inert on 6 of 8, and
produce bimodal gains: 0.000 six times, then 0.017, then 0.590. A 34.7x
gap.

## Why

The three pieces of this only work as a chain, and the chain has a hole in
the middle:

1. **supply** — sample views with objects in mind (0202);
2. **selection** — choose among an object's arms on the output side (this
   note, unbuilt);
3. **repair** — fix a mask that cut its object short (0198, 0201).

Supply without selection is not a quality change. It is 48 to 60 usable
views feeding a chooser that ranks by mask-hull overlap, and 0197's rp7 desk
is the case that shows it can go the wrong way: the alternative view there
made the object worse, and no input measure said so. More arms means more
chances for the chooser to be wrong as well as right — which is precisely
0197's bidirectionality, arriving one stage later than anyone expected it.

Repair does not have this problem, which is why it lands on its own: it
does not add an arm, it changes the one arm that was going to ship anyway.

The reason to write this down rather than build it is that 0197 already
named its own gate — "an operator sitting on two objects is the gate before
any of it ships" — and that sitting was superseded rather than answered:
the operator blessed the spike f142 table live, walked the rp7 desk, and no
formal A-or-B verdicts were recorded. So the instrument is measured, the
gate is unresolved, and the honest state is a named dependency rather than
a silent one.

## What would change this decision

- **The operator answers 0197's gate**, on rp6g1's table and one more
  object. Then `build_box_object` should choose its arm by fill and
  `box_fit_residual` with a margin inside the 34.7x gap, and 0202's flag
  has a reason to default on.
- **Axis assignment becomes resolved on most boxes.** Both instruments read
  extents under the chosen mapping, and 0198's amendment measured a case
  where both PREFER the wrong mapping on a strongly anisotropic object.
  Selection built on top of an unresolved mapping inherits that.
- **Someone tries to make selection a pre-reconstruction decision.** It is
  not one, and the eleven refuted measures plus 0197 are why. The whole
  point of scoring the arm is that the arm exists.
