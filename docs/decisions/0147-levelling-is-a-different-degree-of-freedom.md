# 0147 — levelling is a different degree of freedom from the dead one

**Date:** 2026-08-13
**Status:** Decided

## Context

The 2026-08-12 walk ranked contact tilt as its top new class: four objects
at the right height, "touching at one point" — the spike room's speaker,
rp7's table lamp, and rp6g1's lamp and monitor. The 0104 support snap is
height-only, so an object landed exactly on a measured surface still meets
it at whatever tilt its rotation carried.

The obvious objection is that rotation is settled ground: three instrument
families are measured dead on it (0081 refuted every appearance-scorer
variant; 0104 refuted four more attacks including per-view aggregation and
a truncation-direction prior), and the standing instruction is not to
re-attempt without a genuinely new evidence source.

## What we tried

Measured the tilt first, on every placed free object in the four preserved
rooms. Median 5.1°, p90 21.3°, and the walk's four are 5.5°, 7.4°, 5.0°
and — the spike speaker — **39.9°**. That speaker's own capture photo
(frame 142, mask 4) shows a soundbar standing vertically against a
cabinet. The 40° is not a subtle contact-quality issue; the object is
lying over.

Then tested whether an object's own mass can say which way is up: the
world-frame principal axes of what is RENDERED, taking the axis nearest
vertical. It agrees with the shipped rotation's nearest axis to within
0.5° on every well-formed object (speaker 39.91 against 40.34, rug 10.93
against 10.94, the lamps to 0.03), so the two readings corroborate.

Then whether correcting it helps, using the underside as evidence — the
height range of the lowest decile of the mass, which is "touches at one
point" as a number. All six upright-resting objects improve, the speaker
by 8× (0.0296 → 0.0035 m). Wall and hanging classes get WORSE: curtains,
mirrors, clocks and artworks all regress, which is the expected answer for
objects whose rotation is owed to a measured wall rather than to gravity.

## What we chose

A levelling pass in fusion, ahead of surface construction and the support
snap, behind two independent gates:

* **class** — only classes that rest on something level, the union of the
  two vocabularies that already describe that population (things that rest
  ON surfaces, things that stand ON the floor). Wall and hanging classes
  are excluded by their absence.
* **evidence** — the underside must measurably flatten, or the correction
  is discarded and logged.

The correction is the minimal rotation taking the nearest principal axis
onto world up, applied about the object's own mass, so an object moves by
exactly its measured tilt and never further, and never sideways.

## Why

**Tilt is not the dead degree of freedom.** The dead one is the splat
canonical frame's axis ASSIGNMENT and its 180° yaw sign, where the only
available evidence is appearance or a thin single-view cloud — 0104's own
mechanism finding is that the cloud instrument works *because* that cloud
is a thin surface correlated with the splat's truncation, so more evidence
of the wrong kind destroys the signal. Tilt is rotation about a HORIZONTAL
axis, and it has a prior none of those had: gravity, for a class of object
whose entire relationship with the room is that it rests on something
level. The minimal-rotation construction is what keeps the two separate —
a levelled object keeps whatever yaw it had, and that is test-pinned.

Both gates are load-bearing and each was verified to refuse on its own.
Admitting the wall and hanging classes to the vocabulary as an experiment,
the evidence gate alone refuses ten of them on real data. Conversely a
round-bottomed object — a vase, a potted plant, both in the vocabulary —
has no flat underside to flatten, so the gate declines and its shipped
rotation stands. That is the conservative direction and it is the point:
where the object cannot show a contact, nothing is invented.

## What would change this decision

A source of orientation that is trustworthy in the horizontal plane too —
then levelling stops being a special case and becomes part of a general
rotation fix rather than a pass of its own.

An object class that genuinely rests tilted (a leaning mirror on a floor,
a reclined chair) appearing in the levelling vocabulary. The evidence gate
should already refuse it; if it does not, the class leaves the vocabulary
rather than the gate being loosened.
