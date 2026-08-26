# 0261 — the overlap sort rewards a mask that stops early

**Date:** 2026-08-27
**Status:** Decided (mechanism measured). The three checks below are answered in 0262 and 0263; **0263 inverts this note's reading of the desk pair** and the correction is marked inline.

## Context

0259 closed the frame-selection question with three disqualifications and got
the table's order to match the operator's exactly. But one class of truncation
survived it: an object photographed perfectly, fully in frame, sharp, unoccluded,
still rendering short.

Frames 50 and 51 are the operator's own picks for the desk. The photograph is
not the problem in either.

## What we tried

The `/segment` probe (0260) showed SAM 3 returning **two `desk` instances in the
same frame**, in all three frames that see the desk. They are the same desk at
two extents — same top, same bottom, same left edge, the larger continuing
400-530 px further right:

| frame | short | long | containment |
|---|---|---|---|
| 50 | 284,842 px | 342,215 px | 99.5% of short inside long |
| 51 | 251,645 px | 299,585 px | 99.8% |
| 109 | 117,594 px | 142,654 px | 99.7% |

**The operator confirms it is a single desk with no adjoining surface**, so the
longer mask reads here as the correct extent and the shorter one as partial.

**Measured afterwards, this reading is wrong for the desk (0263).** What the
longer mask adds is a thin arm cantilevered off the desktop, and 54-70% of it
lies OUTSIDE the measured table box. The operator's confirmation stands and does
not settle it: the arm is not an adjoining *surface*. On this pair the shortlist
is choosing correctly. The mechanism below is real and it does cost a real
object — the CHAIR, in frame 50, where the shorter mask drops both armrests and
the base and 95% of that loss is inside the chair's own box.

The per-box shortlist sorts by `(-overlap, frame_index, mask_index)`, and
`overlap` is `box_placement.mask_overlap_with_hull`:

> *"Fraction of a mask's true pixels inside the hull."*

That is **precision with no recall term**. Measured on the pair:

| frame | short mask overlap | long mask overlap | reconstructed |
|---|---|---|---|
| 50 | **0.9878** | 0.8970 | short |
| 51 | **0.9889** | 0.9048 | short |
| 109 | **0.9794** | 0.8583 | short — and SHIPPED |

Three frames, three times the shorter mask, by 9-12 points every time.

## What we chose

Nothing yet — this note records the mechanism, because it is not a tuning
question and the fix is not obvious.

## Why

**The metric structurally prefers a truncated mask, by construction rather than
by accident.** A mask that stops short of the object has every pixel inside the
box and scores near 1.0. A mask covering the whole object spills past the box's
edge and is penalised for each pixel that does. When SAM 3 offers a short and a
long reading of one object, the sort cannot do anything but take the short one.

**The RoomPlan box is a BOUND, not a silhouette**, and that is what makes this
bite. Any mask correctly covering an object whose true extent exceeds its
measured box is marked down for being right. The box is trusted elsewhere for
exactly the reasons 0104 and 0148 give — it is measured, not fabricated — but
those uses ask where an object IS, not how far a mask may extend.

**This is a different axis from 0197 and is not covered by it.** 0197 compared
two VIEWS and found the effect bidirectional, which is why no view sort key was
built. This compares two MASKS of the same object in the same view, where one is
simply more complete than the other. Nothing in 0197 speaks to that, and the
"more complete" judgement here needs no prediction about reconstruction — it is
containment, measured.

**And the pipeline intends to reconcile duplicates — just not this early.**
`fusion._dedup_same_frame` absorbs same-frame same-label duplicates on a MUTUAL
singleton test, deliberately refusing to collapse a coarse parent containing
disjoint children (a `doorway` mask over two real doors). The desk pair would
almost certainly satisfy that test at 99.7% mutual containment. But the
shortlist runs BEFORE fusion, builds one of the pair and policy-skips the other,
so fusion is handed one observation and has nothing to reconcile —
`deduped_observations: 0` on the shipped desk confirms it. **The budget
pre-empts the reconciliation the design provides.**

## What would change this decision — the three checks, now answered

All were offline and free. **Answers in 0262 and 0263**; kept here as asked so
the question and its answer sit together.

1. **Does the bias hit the other objects?** The chair, bed and cabinets also
   returned multiple same-label masks in some frames. If the shorter mask wins
   there too, this is systemic rather than a desk story.
   **ANSWERED: yes — 9 of 10 across five captures, spanning `chair`, `desk` and
   `cabinet` in three rooms. But the shorter mask is only WRONG in four of the
   ten, and the box says which (0263).**
2. **What would a recall-aware metric pick** — IoU against the hull, or
   precision gated on "not contained by a sibling of the same label"? The second
   is attractive because it changes nothing when there is no sibling.
   **ANSWERED: the sibling gate as posed here is the wrong fix — it strikes the
   shorter mask every time, which breaks all three desk frames. The discriminator
   is where the added region falls relative to the box (0263).**
3. **How often does SAM 3 return nested same-label pairs at all?** Across the 19
   probed frames. Frequency decides whether this is worth a code change.
   **ANSWERED: 6 of 28 here, and 15 of 93 over the four preserved captures —
   21 nested pairs across five captures. Containment is bimodal on both:
   of 121 same-label pairs, exactly ONE sits between 0.003 and 0.989 (0263).**

If (1) says the desk is alone in this, it is a narrow curiosity. If nested pairs
are common, the shortlist is systematically shipping the smaller half of every
object SAM 3 reads twice, and that is a bigger finding than anything in 0259.

**Neither branch is what happened.** Nested pairs are uncommon and the shorter
mask is usually the better input. The bigger finding was underneath: the overlap
score is **flat** — 31 of 52 candidates tie at exactly 1.0000, so in 4 of 5 boxes
the view is chosen by frame index rather than by any measurement (0262).
