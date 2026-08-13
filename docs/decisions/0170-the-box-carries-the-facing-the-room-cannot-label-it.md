# 0170 — the box carries the facing; the room still cannot label a row

**Date:** 2026-08-14
**Status:** Decided (extends 0169's derivation and corrects what it can be used for)

## Context

0169 set out to grow the 180° facing sign's truth table, which had five
hand-adjudicated rows against a one-bit question — too few to separate an
instrument from a coin, and the reason five instrument families had been
called dead on evidence that could not carry the verdict. It derived the
facing of wall-backed furniture from measured RoomPlan walls plus the box's
measured yaw, with a class-dependent facing axis: the long horizontal for
beds, the shallow one for storage and sofas.

It recorded that rule as incomplete, because the spike room's bed appeared
to have its side against a wall rather than its headboard, and asked for a
robust form that tests both horizontal axes for perpendicularity and lets
the functional prior pick only the direction along whichever is wall-normal.

Building that form found something better and something worse.

## What we measured

**The facing axis is not a per-object adjudication. It is a property of the
format.** Over every box in the four preserved walk captures — 31 boxes, 25
of which stand against a measured wall — the face presented to that wall is
the box's own local **−Z** on **23 of 25**. Under a fair coin, landing on
one named face that often is p ≈ 9.7e-06.

By category: storage 9/9, table 6/6, bed 3/3, sofa 3/3, refrigerator 1/1,
chair 1/3. The two exceptions are both chairs, and both have their **+Z**
against a wall at 0.255 m and 0.258 m — which is a desk chair tucked at a
desk that stands against that wall, facing it. Same convention, read
correctly.

So RoomPlan's box local **+Z is the object's front**, and every box carries
a measured facing direction whether or not it touches anything. That is
consistent with 0076, where the operator verified the spike room's boxes
9/9 on position, extent *and facing*, and it makes 0169's class rule
unnecessary rather than incomplete: the bed's headboard question dissolves,
since its −Z face is against wall_12 at 0.000 m along its long axis.

**The obvious null is refuted.** RoomPlan could be orienting +Z toward the
scanner, which would put −Z at the wall for exactly the same objects and
mean nothing about furniture. It is not: 4 of 21 box placements have +Z
pointing *away* from their own source camera, two of them at dot −0.95 and
−0.99. An axis defined by the camera cannot do that.

## What this does NOT deliver, which is the important half

0169 already said the room gives the answer and not the mapping. Working
with it makes the consequence sharper than that sentence reads, and it is
worth stating plainly because the charter that followed from 0169, and an
earlier draft of this note, both got it wrong:

**A row of this table is a direction, not a label.** It says the front
points along +Z_box. Deciding whether a given rotation is correct needs the
splat-local direction of the splat's own front, and the room has no opinion
about that whatsoever. So the table grew from 12 rows to 21 — and from 5
labels to 5 labels.

Worse, the shape of the geometry makes the naive check vacuous. For
wall-backed furniture the observing camera stands on the front side, so
"the front ends up facing +Z" and "the observed side ends up facing the
camera" are the same statement. An instrument that places the observed side
toward its camera therefore satisfies the room automatically, and a probe
built to grade one that way scored 7 agree / 0 contradict on rooms where
the answer was independently wrong. That probe was withdrawn.

## What we chose

Use the convention as what it is: a measured facing direction per box, and
a corroborated fact about the format. Do not use it as a grading oracle for
sign instruments, and do not build a placement rule on it.

The table that can actually grade a sign instrument is still made of eyes:
the operator's five rows, plus rows adjudicated from renders of a splat
against the photograph that made it. That is the constraint 0169 set out to
remove, and it is not removed.

## What would change this decision

A splat whose front is identifiable from the splat itself — from a union of
registered reconstructions giving the far side real observed texture
(0151), or from a catalog asset with a known front. Either turns every one
of these 21 directions into a gradeable row at once, and this note becomes
the oracle 0169 hoped for.

If a capture has no RoomPlan room — an ARKIT_ONLY tier, or a `roomplan`
parse that degraded to `anchor_envelope` — there are no boxes and this
yields nothing. It degrades to silence, never to a wrong direction.
