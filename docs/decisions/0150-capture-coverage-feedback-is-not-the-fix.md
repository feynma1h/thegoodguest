# 0150 — capture-coverage feedback is not the fix for truncation

**Date:** 2026-08-13
**Status:** Decided — do not build yet, with a named test

## Context

The second of the two capture-side defects the room-quality brief opened
on: nothing tells the user an object has been sufficiently OBSERVED. RP-7's
floor plan proves an object was DETECTED — walls stroking in, labelled
rects, a camera cone, coverage ticks — and none of it proves the object was
seen from enough angles to reconstruct. The proposal is per-object capture
sufficiency: furniture that reads as "captured" only once observed from
enough angles, and visibly still wanting otherwise.

It carries a design cost that has to be argued rather than skipped: RP-7
deliberately REPLACED the camera preview with the floor plan, so a camera
view with boxes over furniture re-opens a considered decision. The floor
plan is an equally valid host for the same signal.

## What we tried

Before designing the surface, asked whether the signal would help — using
the four preserved captures as a natural experiment, because they already
span a 40× range of per-object coverage.

**Supply.** Projecting every RoomPlan box into every keyframe of its own
capture (pure geometry, production's own `project_box_footprint`), each
box has between 4 and 156 frames that see it at the census cover bar, and
a view with in-frame fraction 1.000 exists for 20 of 25 boxes in the three
non-starved rooms.

**What the pipeline takes.** Of the good (frame, box) pairs a capture
contains, the twelve sampled frames hold **3.5% on rp7, 3.9% on rp6g1 and
1.6% on the spike room**. The census cover pass reaches every box in 2 to 3
picks; the remaining 9 or 10 slots go to pose-diverse residue, which is
object-blind by construction.

**Whether supply buys quality.** Correlated each box's supply against its
shipped reconstruction's shape agreement with its measured box — sorted
extents against sorted dims under the best uniform scale, so no dependence
on the axis mapping. Over 20 boxes spanning 4 to 156 qualifying frames:

    Pearson r = +0.018
    below-median supply: mean shape error 0.199
    above-median supply: mean shape error 0.177

Nothing. And 0146 has already refuted picking a better view among the ones
you hold, on seven view features and two instruments.

## What we chose

Do not build per-object capture-sufficiency feedback, and do not re-open
the camera-preview decision to host it. The floor plan stays as it is.

## Why

The feature would ask users to work harder at something the pipeline
already discards 96 to 98 percent of. Coverage is not the scarce
resource: every piece of furniture in these rooms was walked past from
dozens of angles, and each was reconstructed from one view.

The mechanism is also visible rather than inferred. SAM 3D reconstructs
from a single image and mask; the pipeline picks one splat per object and
throws the rest away. So the only channel through which more coverage
could reach the output is better SELECTION, and selection is measured
dead. The clearest single data point is spike box_05, whose two candidate
reconstructions come from **the same frame** — same camera, same instant,
different mask — and differ 3× in shape error and 2.6× in point count.
Nothing a user does with a phone addresses that.

Shipping the feature would also be a promise the pipeline cannot keep: an
object marked "captured" would still be reconstructed from one view and
could still render truncated, and the user would have been told they had
done the thing that prevents it.

## What would change this decision

**The named test, which the operator can run in one scan.** Re-capture the
reference bedroom deliberately — several genuine angles on every piece,
recorded — and compare per-object shape agreement against the same room's
existing capture. This decision predicts little or no improvement. If
truncation drops materially, the prediction is wrong, this note is
superseded, and the feature is worth building with real numbers behind it.

**A reconstruction path that consumes more than one view of an object.**
That inverts the argument completely: coverage would then be the scarce
resource, sufficiency would be a real thing to signal, and the 96–98%
being discarded becomes the headline rather than a curiosity.

**A sampler that spends its budget on objects rather than pose spread.**
Not a reason to build the UI, but it is where the same finding points:
the budget already exists and 75–83% of it is spent object-blind.
