# 0300 — covering counts eight times filling, and the floor shadow says nothing

**Date:** 2026-10-05
**Status:** Decided — Debug builds only; green on synthetic glass, not yet judged on the phone

Amends 0299 in one figure and refutes one of its proposed next steps. Everything
else 0299 decided stands, and its measurements are still the record.

## Context

0299 boxed a see-through object from the detector's outlines and ARKit's floor,
and weighted covering the outline four times filling the silhouette, because
scoring them as plain overlap made a pedestal table 94 cm wide for 120. It was
judged on a walk of 60° to 120° round the object — broadside, where the table's
long axis lies ACROSS the view.

The operator then reported the fault that walk could not see: standing at one
end of the green glass coffee table, the near end is boxed well and the box runs
well past the far end; standing at the far end fixes that and breaks the first.
Measured end-on, one view returned **211 × 10 × 81 cm** for a true
118 × 46 × 56 — a flat slab lying on the floor, 93 cm too long, scoring 0.9749
while the truth scored 0.9510.

The cause is that image-space agreement is nearly blind along the camera's line
of sight: stretching the box a metre away from the camera costs 0.007 of score,
where the same metre sideways costs 0.195. A thirty-fold asymmetry, and it is
pure perspective. **A high score therefore does not mean a settled box**, and
the direction nobody is measuring is whichever one you are facing.

## What we tried

Four things were built and work (they are in the lane's commits, not here):
sparing the mask's bleeding rim, a ladder of seed heights, re-deriving an
unpinned box from all its outlines, and capping that re-derivation. Two things
in 0299's own plan did not survive measurement, and they are why this note
exists.

**Scoring the box's footprint against the outlines' ray-to-floor intersection,
in centimetres instead of pixels.** This was the planned cure for the blindness,
on the reasoning that on the floor plane a centimetre is a centimetre whichever
way it points. It cannot work for an object at table height, and the reason is
geometric rather than a matter of tuning: **the floor shadow does not overlap
the footprint at all.** The dining table's top is 0.735 m and the camera 1.45 m,
so the ray through the NEAR edge of the glass (x = +0.60) lands at x = −0.63,
already past the far end. The shadow is cast entirely beyond the object.
Measured three ways:

- the intersection does not tighten with views. Eight all the way round still
  span x −2.61..3.15 m and z −2.70..2.66 against a truth of x ±0.60, z ±0.40,
  because `OutlineView.admits` returns true wherever a point leaves a view's
  frame or falls behind it — "the view cannot say" — and each camera's far
  shadow runs past the camera opposite;
- a floor term built on it is blind: **0.164 covered at every width from 104 to
  130 cm**, the whole term varying 0.1831–0.1873;
- counting the views that positively SUPPORT each floor cell, rather than those
  failing to contradict it, recovers no threshold either: support ≥ 3 of 8 gives
  x ±0.84..0.92, ≥ 4 gives ±0.44..0.48, ≥ 6 gives ±0.24..0.28.

It would carry information for a LOW object — the coffee table at 46 cm is why
`floorHull` seeds usefully at all — but not for anything at table height.

**The expectation that the pedestal table and the glass table trade against each
other.** 0299's inward pull and the slab's outward one were taken to be two ends
of one dial, so that easing either must worsen the other. Measured, they do not.

## What we chose

`OutlineFit.coveringWeight` is **8**, not 4. The footprint-on-the-floor term is
**not built and should not be proposed again** for an object at table height.

## Why

The pedestal dining table's error was not its ends going unpaid for. At the
truth's own centre each axis is nearly unbiased — width's optimum 118 cm against
a true 120, depth's 80–82 against 80, height's 76 against 75. The 113 × 78 × 78
answer is a **coupling**: a taller, narrower box draws nearly the same silhouette
from a camera only 0.7 m above the table top, and it scores 0.9477 against the
truth's 0.9419.

What that box and the long flat slab both exploit is how well they FILL their own
silhouette. So weighting covering more takes away the advantage in both cases at
once, which is why the dial has one direction and not two:

    weight                 4      5      6      8     10
    coffee end-on       40.9   14.9   14.9    8.9    8.9   worst extent error, cm
    coffee end-to-end    1.3    1.3    1.3    2.9    2.9
    coffee round         2.2    2.0    2.0    2.2    2.2
    coffee one side      1.6    2.6    2.6    2.6    3.6
    pedestal dining      7.1    3.9    3.4    3.3    2.3

8 is where every case seen from more than one side sits within 3.3 cm and the
single end-on view is at its best.

**The 4 was not wrong when it was chosen.** It was propping up a mask whose
bleeding edge was still being scored — the detector's mask is filled and grown,
so it reaches a pixel or two past the object, and scoring that slack paid a box
to be too big in every direction. That accidental outward pull was doing part of
the job the weight is for. Spare the rim and the weight has to carry the inward
pull alone, and 4 is then too low. **This is the shape of the lesson: the weight
and the rim are one mechanism, and neither figure means anything without the
other.**

## What would change this decision

- **If the rim stops being spared**, the 8 is wrong again — in the other
  direction. Any change to `OutlineView.edgeRim` or `minimumInsideShare` must
  re-measure the weight, and must measure BOTH the end-on glass table and the
  pedestal table among chairs. One of those alone proves nothing.
- **If a cheap source of true depth-direction evidence appears** — a second
  camera, a depth model trusted at range, structure from the walk itself — then
  the blindness this note works around goes away and the weight can come back
  down toward plain overlap.
- **For a LOW see-through object the floor shadow is not useless**, and if the
  review ever needs centimetre agreement for one, the refutation above does not
  apply. Re-measure the overlap of shadow and footprint for that height before
  building anything.
- **If the walks show the pedestal table reading too narrow on the phone** where
  the synthetic one does not, the coupling is being driven by something the
  fixture does not have, and the weight is the wrong lever for it.
