# 0143 — the up extent is declared per box, and the horizontals stay unnamed

**Date:** 2026-08-09
**Status:** Decided

## Context

Decision 0096 let the guest speak only a box's LONGEST dimension, because
nothing in the manifest distinguished which of the three numbers in
`roomplan_box.dims` was a height and which were a footprint. That restriction
is what board item 10(a) wanted lifted: with an up axis named, height, width,
footprint and area all become speakable.

The premise underneath 0096's restriction turned out to be wrong; decision 0137
settles that separately and is the reference for it. What remained was a design
question this note answers: given that `dims` is Apple's local (x, y, z) order
with index 1 the vertical extent, how should perception SAY so?

## What we tried

The obvious route was to recover the up axis — to infer it from the shipped
data, for instance from a splat-extent index. That is what "recover the axis
convention" would mean, and it is the shape the board item was written in.

## What we chose

Not recovery. **Declaration**, warranted per box.

`roomplan_box.extent_axes_m` ships additively on every box object, placed or
not, carrying `up_m`, `horizontal_m` (descending), and `up_tilt_deg`. `dims`
is untouched and stays in RoomPlan's own local order — it is provenance.

The warrant is measured off each box's own transform rather than assumed from
the format. `dimensions[1]` spans local +Y, which is a claim about the WORLD
vertical only while local +Y *is* world +Y — exactly what a pure-yaw transform
gives. So the emitter reads the transform's up column, measures its tilt from
world vertical, and if that exceeds `PLACEMENT_BOX_UP_MAX_TILT_DEG` (5°) the
block is **absent** rather than present-and-wrong.

The two horizontal extents ship descending and **deliberately unnamed**.

## Why

Inferring is precisely what produced the error 0137 had to correct. A field
that declares what was measured cannot be misread the way a convention that
must be reconstructed can be.

**Absent beats flagged.** Absent is already the state every existing consumer
handles — a reader that does not know the new key sees exactly the block it saw
before, and a reader that does falls back to the sorted triple it has today. An
emitted-but-untrustworthy number is the failure 0096 exists to prevent, and a
confidence flag on a height invites someone to use the height anyway.

The tilt is taken off the **normalized** up column, so a 1e-7 column-norm error
does not read as lean that is not there — real data measures exactly 0 across
the spike room's nine boxes. It is also signed rather than axis-line: an
upside-down box has no "up" extent to report, and an axis-line test would
happily report one.

**Horizontals stay unnamed because RoomPlan does not fix which of local X and Z
is the long one, and no facing convention exists that would make one "width"
and the other "depth".** Naming them would be the 0065 error repeated — a label
certifying more than was measured. They are a footprint pair, not two named
dimensions.

This is **emit only**: no `scene_facts` consumption and no `FACTS_VERSION`
bump. The charter rule that restricts size talk is a voice rule, and changing
what the guest says requires live voice evals; shipping the data and changing
the speech are separate acts, and coupling them would have put a voice change
inside a perception deploy.

## What would change this decision

If RoomPlan ever exposes a facing convention that fixes which horizontal is
frontal, the pair can become two named dimensions — and only then.

If a future capture tier produces boxes that are legitimately tilted (a wedge,
a sloped ceiling fixture), the 5° gate will start suppressing blocks that a
consumer would have wanted, and the right answer is a richer representation
than one up extent, not a wider gate.

The consumption half — `scene_facts` reading this field, with a
`FACTS_VERSION` bump and live voice evals — is the follow-on this note
deliberately does not do.
