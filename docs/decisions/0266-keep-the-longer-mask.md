# 0266 — keep the longer mask, and do not merge objects to hide a bad one

**Date:** 2026-08-28
**Status:** Decided (measured; nothing built)

## Context

0261 found the shortlist taking the shorter of two nested masks. 0263 built a
grown-box gate for the choice and 0265 built four more instruments after that
gate was refused. Every one of them was scored against ten labels, of which two
were the author's own judgement.

**The operator ruled on both, 2026-08-28, and both were wrong.** spike frame 398
`cabinet` is better in the LONGER read. rp6g2 frame 0 `chair` is accurate in
NEITHER — the shorter has no legs, and the longer takes another chair's legs and
the table's.

That second ruling is not a label. It is a different failure.

## What we tried

Rescored over the nine pairs that have a verdict:

| instrument | correct | measurable |
|---|---|---|
| today's `mask_overlap_with_hull` sort | 1 / 9 | 9 |
| added-region containment in the box (0263) | 5 / 9 | 9 |
| SAM 3's score — the existing dedup (0265) | 5 / 5 | 5 |
| neighbour-absorption veto (0265) | 7 / 9 | 9 |
| grown-box precision gate (0263) | 8 / 9 | 9 |
| **keep the longer mask** | **9 / 9** | 9 |

**All nine want the longer mask.** Every discriminator built over three days is a
list of ways to lose points by refusing a correct merge, and the metric that
ships is the one that refuses nearly all of them.

## What we chose

**When SAM 3 returns one object at two nested extents, keep the longer. No
gate, no score, no box.**

Detection is unambiguous: across 121 same-label pairs in five captures,
containment is bimodal — 21 at >= 0.989, 99 at <= 0.003, exactly one in
between. Nothing needs tuning.

**And refuse the second idea this note exists to test.** The operator asked
whether a dining table and its chairs should be segmented and reconstructed as
one ensemble, since they are never separated in the product. Measured, no — not
as a general rule:

- **Adjacency cannot identify an ensemble.** 18 of 131 box pairs across five
  captures sit within 0.20 m on the floor, and the close ones include
  bed + nightstand in **four different rooms**, `table` + `refrigerator` at
  0.001 m, storage + storage at 0.000 m and sofa + sofa at 0.014 m. The sharpest
  case is the operator's own room: `90eebfc4`'s table and chair are **0.001 m
  apart** — a desk and an office chair, the chair most likely of all to be moved
  alone.
- **The semantic narrowing is not available.** Firing only on `dining table` +
  `dining chair` would dodge the desk case. Both terms are in
  `DEFAULT_OBJECT_PROMPT` and **neither has ever been emitted** — 0 occurrences
  in 323 detections across five captures, where SAM 3 returned `chair` 48 times
  and `desk` 28. It cannot tell a dining set from a desk.
- **An ensemble mask does not fail cleanly; it binds to the wrong box.** The
  union of rp6g2 frame 0's seven `chair` masks scores **0.7456 against the TABLE
  box** and is admitted, against 0.4596 and 0.1936 for the two chair boxes.
  It would take the table's centre and yaw, be clipped by `splat_clip` to the
  table box plus 0.10 m — deleting the chairs — and be measured by `arm_fit`
  against table dimensions. Each observation binds to at most one box, so both
  chair boxes would be left unmatched and read as detection failures.
- **The union of the member boxes is not an oriented box.** rp6g2 carries five
  distinct yaws, so no composite box can stand in, and placement, clipping, arm
  fitting, the manifest and the viewer all take one.
- **It discards the only ground truth in the system.** The measured box is the
  one quantity here that is not a model's output, and it is what read rp6g1's
  table at 0.406 -> 1.004 of its box height. An ensemble has no box, so nothing
  could grade it.
- **Privacy cuts against it.** Suppression is per-DETECTION (0089):
  `partition_detections` drops a whole suppressed detection. A person seated at
  a dining table is excluded from a chair mask because they are their own
  detection; a mask drawn around the whole set contains them and there is no
  sub-region removal.

Two costs are predictions rather than measurements and are named as such: an
ensemble occludes itself far more than a single chair does, so single-view
truncation should get worse per unit volume; and merging forecloses per-object
arrangement, which is the product surface the redesign thesis rests on.

## Why

**The choice between two masks was never the hard part.** Nine of nine want the
larger one, and the pipeline already believes this — `fusion._dedup_same_frame`
collapses nested pairs and keeps the higher-scoring member. It simply runs after
the shortlist has spent a reconstruction. The defect is ordering, not judgement.

**rp6g2's chair is a different failure wearing the same costume, and merging is
the wrong response to it.** No mask on offer is a chair, so no rule for choosing
between masks can help. The ensemble idea is attractive precisely because it
makes that failure invisible — a plausible object appears where an
unreconstructable one was. That is the thing this repo does not do: a guessed
transform is never emitted, a failure yields explicit `placed: false` with a
reason. Merging two objects to avoid admitting one cannot be segmented is the
same move in a new place.

**The ensemble's appeal is real and it should be recorded, not dismissed.** It
does address the right failure — chair and table legs interleave, so no
single-chair silhouette exists from that view, and an ensemble has a clean outer
boundary. What it lacks is a way to know when to fire that does not merge a bed
with its nightstand.

## Measured alongside, and separate: the two views land on one viewpoint

Applying all of this to the study table leaves three survivors — frames 50, 51
and 109, the operator's own picks in their order — and the per-box budget is 2,
so SAM 3D would be handed frames 50 and 51.

**Those two are 2.0 degrees apart.** Measured from the poses: 50 and 51 sit
1.70 m and 1.75 m from the box with viewing directions two degrees apart, while
109 is the only distinct angle in the set at 16-18 degrees. So ordering the
survivors by box coverage spends both budget slots on one viewpoint and drops
the one different view.

This is not a mask problem and no rule in this note touches it. The census
sampler already spreads FRAME selection by pose (farthest-point residue); the
per-box shortlist that picks a box's second view has no such term, and 0259's
disqualifications do not add one — they only remove frames. Worth noting before
anyone reads "the operator's picks, in their order" as a finished result: the
ORDER is right and the BUDGET spends it badly.

The obvious response — require a box's second view to differ from its first by
some angle — is a fact about geometry rather than a prediction about a
reconstruction, so it is in the class 0259 established as safe. It is untested,
and 0236 is the standing warning against evaluating a supply change apart from
the chooser that consumes it.

## What would change this decision

**A criterion that is measured rather than semantic.** The one candidate left is
the mask evidence itself: if across every frame no mask of box A can be drawn
without covering box B's volume, then A and B are inseparable **in this
capture** — a fact about what was photographed, not a guess about what the
objects are. It is offline, computable from the preserved captures, and it would
fire on rp6g2's dining set while leaving a bed and nightstand alone, because a
nightstand is separable from a bed in almost any frame. Untested.

If that measure works, the ensemble becomes worth costing properly — and the
cost is a new object kind through six subsystems, which is why it needs the
criterion first.

**`dining chair` and `dining table` being dead prompt terms is its own finding**
and is separately actionable: 0226 made the prompt and the family map one
contract, and three more terms in that prompt (`table`, `side table`,
`armchair`) have also never been emitted.
