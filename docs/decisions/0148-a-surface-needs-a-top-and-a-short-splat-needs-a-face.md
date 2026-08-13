# 0148 — a surface needs a top, and a short splat needs a face to sit on

**Date:** 2026-08-13
**Status:** Decided

## Context

The 2026-08-12 walk on rp7: "the released monitor … still floats above the
desk." Its manifest says it was snapped — `support_snap_m: 0.1006`,
`support_box: box_00` — so the pass believed it had already rested it.

## What we tried

Read which box it rested on. `box_00` in rp7 is the **chair** tucked under
the desk, top at y = −0.39; the desk is `box_02`, top at −0.67. The chair
overlaps the desk's footprint, its top was the nearer of the two by |dy|,
and the snap takes the nearest reachable surface. So the monitor was
resting, 0.28 m above the desk, on a chair back.

The splat half of the surface set has always had a class rule — "the
supporter must itself be a furniture class that HAS a top surface — a lamp
never supports a TV" (0104). The measured half, built from RoomPlan boxes,
had none: every box was a surface, so a chair, a bed and a sofa were all
tables.

Applying the rule moved the monitor to the desk and exposed the second
half. It now lands on the desk's MEASURED top and still sits 0.206 m above
the desk anyone can SEE, because the desk's own splat fills 0.42 of its
measured height — a tabletop with the legs cut off — and was centred in
its box, which puts half the deficit below it and half above.

Four of 21 box objects across the four rooms under-fill badly (0.31 to
0.42 of box height); in every one, the gap at the floor and the gap at the
top are equal to within a centimetre, which is centring doing exactly what
it does.

The obvious anchor for a short splat is the observation's own LiDAR cloud,
and it was measured **unusable**: the cloud is the VISIBLE surface, so it
is top-biased on everything (a chair's cloud spans 0.47 m of a 1.08 m box)
and matching to it would push well-fitting objects upward too — the
offsets it proposes are +0.26 to +0.36 m on objects that fill their boxes
correctly.

## What we chose

One vocabulary answering both questions: which RoomPlan categories have a
top that things rest on. `table` and `storage` — the same list the splat
rule already carries, translated into RoomPlan's own words, with one home
in `box_placement` that fusion reads.

* a box is a support surface only if its category is in it;
* a splat that under-fills its box is seated against the box's measured
  TOP if its category is in it, and against the box's FLOOR otherwise.

The resting object's underside is also now percentile-clipped, like every
other extent in the pipeline. Taken from the raw minimum, the 12 mm of
stray gaussians measured below the reviewed monitors became 12 mm of hover.

## Why

The two questions are the same question. A category whose top is a surface
must have its top in the right place, because other objects are placed
against it; a category whose top supports nothing has exactly one contact
worth being right, the floor. Splitting that into two vocabularies would
guarantee the drift that produced this defect in the first place — the
splat rule and the box rule disagreeing.

Seating is not a claim about the object's true extent and does not touch
it. Position stays measured horizontally, scale and rotation are
untouched, and `splat_clip` follows the object so the declared clip is
still measured where the object actually is. What moves is which face of
a measured box an incomplete reconstruction is aligned to, and both faces
are measurement.

`table,storage` is deliberately short. A bed is a thing people put laptops
on; no capture has produced that, and the house rule is that a category
joins on evidence rather than on the argument that something could be put
on it.

## What would change this decision

The seating direction is a taste call the operator has not made yet, and
it is a real trade: rp7's desk now has its top at the measured height with
its legs stopping 0.47 m above the floor, where before the whole desk
floated 0.22 m up with the monitor floating 0.21 m above THAT. The A/B is
in the walk pack. If the operator prefers the floor anchor for surface
categories too, it is one vocabulary entry.

A third option was not built and is theirs to rule on: stretching the
vertical axis alone to fill the measured height, which would put a
truncated desk's top AND legs where they belong at the cost of its
proportions. 0080 ruled per-axis stretch out on the grounds that it
amplified truncation, and that ruling stands until they revisit it —
this note records that the narrow form (one axis, whose direction the
layout prior confirms, toward a measured height, only for objects under
0.85 fill) was not the thing they judged.
