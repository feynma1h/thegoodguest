# 0137 — `roomplan_box.dims` is (width, height, depth), and 0096's premise does not hold

**Date:** 2026-08-09
**Status:** Decided — measured. The solver uses it; the guest's size rule is NOT changed
— that is 0096's call and board item 10(a)'s work.

## Context

Decision 0096 lets the guest speak only a piece's LONGEST dimension, and the
reason it gives is not caution but impossibility. From `scene_facts.py`'s
SIZES section:

> The shipped `dims` triple carries no recoverable axis semantics: it is
> descending-sorted in all six real boxes examined, so the bed's 2.16 is a
> length while the wardrobe's 1.91 is a height, and nothing in the manifest
> distinguishes them. "About 2.2 m at its longest" is true under either
> reading; "2.2 m wide" is a coin flip.

Board item 10(a) names the fix — perception shipping an explicit up-axis
extent, which `box_placement.py` already knows as `i_up` — and calls it "the
best value-to-cost item on this board".

The stage-2 solver needed the footprint (`dims[0]`, `dims[2]`) and the height
(`dims[1]`), so it had to settle what the triple means.

## What we measured

Across the four preserved walk rooms — **31 boxes**, `roomplan_box.dims` as
shipped in the live manifests:

**It is not sorted, in any order.** The largest dimension sits at index 1 in
16 boxes, index 0 in 12, index 2 in 3. A descending-sorted triple would put it
at index 0 every time.

**Component order survives the pipeline intact.** On all 9 boxes that ship a
clip volume, `splat_clip.half_extents_m == dims/2 + margin` component by
component, to 2e-4. The clip is derived from `dims` without reordering.

**`dims[1]` is the height, every time.** Every box with `dims[1] > 1.5 m` is a
wardrobe (4) or a refrigerator (1); no box reads as a 2 m wide, 0.5 m tall
anything. Spot checks: chair `[0.58, 1.13, 0.67]`, sofa `[1.77, 0.91, 0.95]`,
bed `[1.37, 0.55, 2.02]`, wardrobe `[0.99, 2.08, 0.55]`. All four read
correctly as (width, height, depth) and incorrectly under any other reading.

This is RoomPlan's own convention — `CapturedRoom.Object.dimensions` is
(width, height, length) in the object's local frame — and 0076 already
recorded that RoomPlan boxes are pure-yaw, which is what makes `dims[1]`
world-up rather than merely local-y.

## What this means for 0096

**0096's conclusion may still be right; its stated reason is not.** The
premise — "descending-sorted… nothing in the manifest distinguishes them" —
is false on the data. The bed's 2.16 is at index 2 and the wardrobe's 1.91 is
at index 1, and that is exactly the distinction 0096 says does not exist.

Six boxes were examined then; 31 are available now, across four rooms.

**Nothing here changes what the guest may say.** That is deliberate:

- It is a charter change (rule 3b), and charter changes bump
  `PROMPT_VERSION` and require live voice evals. 0096 learned this the
  expensive way, when two new exemplars quietly dropped the invitation
  pattern all five originals carried.
- 0096's SECOND reason for the restriction is untouched by this: splat-derived
  extents are still not size truth (the textile scale collapse, class-6
  truncation), and a confident wrong size is still worse than no size.
- Board item 10(a) is where this lands, and it wants the perception-side field
  (`i_up`) shipped explicitly rather than the client inferring axis semantics
  from a convention it observed. Inferring is what got us here.

So this note is the evidence 10(a) was waiting for, filed where the next
session will find it, and pinned by
`test_room_geometry.py::TestBoxAxisSemantics` so a change in the shipping
convention fails loudly rather than silently making the guest wrong.

## Why the solver uses it anyway

Geometry is the solver's job (0132), and the split it rests on is that the
guest owns language while the server owns coordinates. A footprint is a
coordinate. The solver needs `dims[0]`/`dims[2]` to know where a piece's
corners land and `dims[1]` to keep it on the surface it was measured on, and
it has 31 boxes of evidence for what those are.

The guest still cannot say "0.9 m wide", and this note does not let it.

## What would change this decision

- **Perception ships `i_up` explicitly** (board 10(a)). Then nobody infers
  anything, the pin here becomes redundant, and 0096's restriction can be
  revisited on its own terms with voice evals.
- **A room shows a box whose `dims[1]` is not its height.** The test pins the
  four walk rooms; a fifth room disagreeing is the loud failure this exists
  to produce.
