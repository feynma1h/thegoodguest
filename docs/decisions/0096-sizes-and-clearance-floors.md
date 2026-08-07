# 0096 — Sizes and clearance floors: what the extents actually support

**Date:** 2026-08-08
**Status:** Decided

## Context

Conversation stage 1 shipped with a recorded gap (0058): manifest v2 carried
no per-object extents, so sizes, gaps and clearances were unspeakable and the
charter forbade restating centre distances as any of them. The manifest now
carries `extent_m_sorted` (0067) and `roomplan_box.dims` (RP-4), so the
standing fast-follow was to consume them with a `facts_version` bump.

The question was never "can we read the field" — it was "which of these
numbers is true enough to say out loud."

## What we tried

Read the real manifests instead of the schema. Three things fell out of the
reference room (`a7e073ae`, 25 objects, 6 RoomPlan boxes):

1. **A real meter-scale rug ships `extent_m_sorted` of 0.456 × 0.292 × 0.005.**
   That is the textile scale collapse from 0075, still open. Splat extents are
   also exposed to class-6 visible-region truncation, open from the RP-8 walk.
2. **Unplaced objects can still carry a RoomPlan box with real dims.** Three of
   them do. Placement and measurement are independent.
3. **`roomplan_box.dims` is descending-sorted in all six real boxes.** The bed
   is `[2.16, 1.85, 0.61]` (largest is a length); the wardrobe is
   `[1.91, 0.68, 0.38]` (largest is a height). `box_placement.py` reads
   `dims[1]` as the up extent, which is inconsistent with both readings — so
   the axis semantics are not recoverable from what ships.

Computing a true gap from centre distance minus half-extents along the
connecting axis was considered and rejected: it needs each box's rotation
applied to its extents, and gets the sign of its own error wrong when the
extent is a truncated splat.

## What we chose

`FACTS_VERSION` 2, `PROMPT_VERSION` 2.

**Sizes** come only from `roomplan_box.dims`, only at box confidence
high/medium, and speak only the LONGEST dimension: "about 2.2 m at its
longest". Splat extents are size-silent. A size exists independently of
placement.

**Clearances** are a new fact class, and they are rigorous LOWER BOUNDS:
`d − (r_a + r_b)` where `r` is the box circumradius `|dims|/2`. No point of
either box is closer than that to the other under any rotation. Emitted only
when positive, rounded DOWN, phrased "at least", and only between two
measured boxes.

Charter rules 3a/3b carry the epistemics; two exemplars show the refusals.

## Why

**A confident wrong size is worse than no size.** The rug is the proof: a
meter-scale object shipping as 0.46 m would have the guest state a number
wrong by ~3× in the same voice it uses for true ones. Everything downstream of
"numbers are verbatim-only" depends on the numbers reaching the prompt being
true, so the filter belongs at the facts layer, not in the model's judgement.

**Low box confidence is where the labels are wrong too.** The spike room's
wardrobe arrives as a low-confidence "refrigerator". RP-7 already withholds
the *name* at that tier; attaching an authoritative-sounding size to a wrong
name is the same error with more credibility behind it.

**Longest-dimension-only is not a hedge, it is the whole of what the data
supports.** "About 2.2 m at its longest" is true under either reading of the
dims triple; "2.2 m tall" is a coin flip on a room-by-room basis. This is the
same failure family as 0065's identity twin — a metric that certifies less
than it appears to — and the response is the same: say exactly what was
measured.

**Clearances via circumradius are sound where the tempting version is not.**
The bound holds under any yaw, needs no rotation convention, and cannot be
falsified by an object being *bigger* than its box. Requiring both objects to
be boxes matters for one specific reason: a truncated splat understates the
object, which would make the bound OVERSTATE the gap. That is the one
direction the error must never go, since a floor is what a person leans on
when deciding whether something fits. Rounding down rather than to nearest is
the same argument at one decimal place.

**The voice evals earned their place on this change.** The first live run went
red on a *pre-existing* eval: both new exemplars ended without an invitation,
diluting a pattern all five originals carry, and the grounded-answer reply
stopped inviting. That is a real voice regression that no offline test could
see, caught before it shipped. Four new live evals now cover the two failure
modes specific to this change — upgrading a floor into a measurement, and a
longest-dimension into a height.

## Also changed

Charter rule 5 stopped claiming the walls and floor "haven't arrived". The
shell ships (0066/0069/0077) and the person may be looking at it; the guest
still cannot see it, which is a different sentence. A test pins that the old
phrasing does not come back.

## What would change this decision

- **Perception ships the up-axis extent explicitly.** `box_placement` already
  knows it as `i_up`. One additive manifest field unlocks height, width,
  footprint and area talk, and the longest-dimension restriction retires.
- **The textile scale collapse and class-6 truncation close.** Then splat
  extents become size-eligible, subject to their own confidence tier, and
  clearances extend to splat-only objects — but only once the error's SIGN is
  known to be conservative.
- **A real user asks for exact gaps often enough to matter.** The honest
  upgrade is not a tighter formula on this data; it is per-object oriented
  bounding boxes from perception.
