# 0158 — the turn is a selection between two candidates, not a rotation

**Date:** 2026-08-13
**Status:** Decided and BUILT, not deployed — `spec_solver.turn_around`, with
its pins in `services/api-public/tests/test_facing_correction.py`.

## Context

0157 settles that a person may correct a facing. This note settles what the
room does when they do, and it is a narrower thing than "rotate the object" —
narrow enough to be safe, which is the whole point.

## What we tried

The loose version is a rotation with an angle, or a `face_toward(anchor)` that
aims a piece at something. Both were rejected on the same reading of the
existing code rather than on taste.

**A piece has no measured front.** RoomPlan gives a box a yaw and the operator
walk scored it 9/9 on facing (0076), but nothing anywhere marks which side of
a box is its face. So "make the desk face the window" cannot be grounded, ever,
with what this pipeline holds. The tool therefore takes no direction, and the
guest's honest answer is that it can offer the other of the two ways the piece
might be sitting and the person can say whether that is the one.

**An arbitrary angle breaks the clip.** The browser expresses each `splat_clip`
volume (0104) in the mesh's own frame and parents it, so the volume travels
with the object. That is exactly right for a move and exactly wrong for a
rotation — turn the mesh by an arbitrary angle and the measured box turns with
it, and the volume that was cutting the RoomPlan box is now cutting something
nothing measured.

## What we chose

**The half turn about the box's vertical axis, and nothing else.**

Perception enumerates the extent-consistent, right-handed mappings of a
splat's axes onto its box and ships one. `box_placement._partner_index`
defines the partner of that pick as the same assignment and the same `s_up`
with the opposite `s_h1`. Measured through perception's own enumerator over
1924 partner pairs: **the partner's quaternion is `rotY(π) ⊗ q_chosen` to
2.2e-16**, and the piece's own up axis is preserved to better than 1e-4 — a
facing flip, not a somersault. RoomPlan boxes are pure-yaw (0076), so the
box's vertical axis is world up and the flip is a left-multiplication in the
world frame. In components it is a pure permutation with two sign changes,
`(x, y, z, w) → (z, w, −x, −y)`, so a corrected rotation is never a rounded
one.

So the correction is not a new value. **It selects the other member of a set
the pipeline already built and could not choose between.**

Three properties follow, all measured on the four preserved walk rooms, and
together they are why this is the one rotation that can ship:

- **The footprint is exactly invariant** — 0.00e+00 across all 21 box
  placements, because a rectangle maps onto itself under a half turn about its
  centre. Floor containment and every overlap are bit-for-bit what they were,
  so no geometric constraint can newly fail and there is no geometric refusal
  to write. Every refusal in `turn_around` is about eligibility.
- **The clip volume survives it.** The volume's centre coincides with the
  object's position — the rotation pivot — to 4.8e-5 m, and a box is symmetric
  about its centre under a half turn, so the parented SDF still cuts the
  measured box afterwards, in either build order.
- **It is its own inverse**, so a second turn is not a second entry. It drops
  the first, and the room is back the way the scan drew it. Storing the double
  flip instead would leave an entry claiming a change equal to no change, and
  the room reporting "1 piece turned" while nothing is turned.

**Eligibility is `rotation_source == "roomplan_box"`.** On real data that
coincides exactly with having a measured box (21 of 21), so the gate admits
precisely the pieces whose sign perception left unresolved. The other 26
placed pieces across those rooms are `sam3d_layout`, whose sign IS pinned by
signed regression tests (0065), or carry no rotation claim at all. Neither is
an unresolved bit, so neither is ours to overrule.

## Why the quarter turn is NOT in scope

A 90° error is an ASSIGNMENT error, and the assignment is a different DOF with
a different evidential status. Three measured reasons, in order of weight:

1. **It is measured, and sometimes decisively.** The cloud instrument resolves
   the assignment on 9 of 21 box placements at margins 0.10–0.47. Overruling
   that is "the measurement is wrong", which is a different product question
   from "the measurement is absent" — the one this whole path is built on.
2. **"The other way" is undefined.** An unresolved piece carries up to eight
   candidates. There is no second thing for a person to name, so a
   direction-free tool cannot express the correction and a direction-taking
   one is the coordinate problem again.
3. **The invariants above all fail.** A quarter turn changes the footprint,
   can break floor containment and overlap, and rotates the clip volume off
   the measured box — so the box's own extents would then amputate the result.

The honest answer when a person says a piece is lying on its side is that the
room cannot fix that, not a half turn that does not address it.

## What would change this decision

- **Splat axis resolution ships**, and with it a manifest that says which
  candidates were live and how close they scored. A correction could then
  offer the runner-up by name rather than a fixed half turn.
- **A piece gains a measured front** — a semantic front face from perception,
  or a catalog asset with a known orientation. Then `face_toward` becomes
  groundable and the refusal in this note stops being permanent.
- **Boxes stop being pure-yaw.** The flip is `rotY(π)` because the box's
  vertical axis is world up. A tilted box would need the flip about the box's
  own axis, which is the same idea and different arithmetic.
