# 0270 — reserve a whole view per box, rather than reject the cut ones

**Date:** 2026-08-27
**Status:** Decided and built, behind `PERCEPTION_BOX_WHOLE_VIEWS` (default off)

## Context

[0259](0259-disqualify-a-frame-do-not-rank-it.md) proposed disqualifying frames
that cut an object at the image border. Its measurements held; its proposal did
not. Amended on the same day, it records why: making border contact a coverage
gate moved 20 of 24 frames and orphaned a box outright, and as a scoring
preference it never reached the frames that mattered — which is
[0236](0236-a-veto-is-a-re-roll-not-a-filter.md)'s finding arriving a second
time. Removing a candidate re-rolls a greedy selection, and the cost lands in
alternatives only the chooser can see.

The defect underneath is real and was measured on a room: the cover pass took 3
frames and the remaining 9 were pose-diverse residue, which never asks where
anything is, so **five of six boxes shipped a view ranked #25 or worse of their
own candidates**.

## What we chose

`select_box_whole_views` in `census_sampling.py`. For each measured box, reserve
the single best frame in which that box's projected footprint does not reach the
image boundary — highest visibility first, preferring the sharper half of the
capture. The reservation happens BEFORE the cover pass and the residue, inside
the same `max_frames` budget.

Nothing is removed from any candidate pool. The cover pass and the residue are
unchanged in kind, and the selection they make afterwards is the selection they
would have made anyway.

Three details that are load-bearing rather than incidental:

- **Wholeness is contact, not clearance.** `WHOLE_VIEW_EDGE_MARGIN_PX` defaults
  to 2. A larger margin rejects exactly the tight, complete views this pass
  exists to find.
- **Sharpness is a percentile of the capture's own distribution**, never an
  absolute bar: variance of the Laplacian tracks scene texture as much as focus,
  so a threshold that suits one room rejects everything in a plainer one. At the
  default 50th percentile on a real capture, the operator's two chosen frames sit
  at the 88th and 93rd and the two they called blurry at the 32nd and 38th.
- **Completeness is the gate; sharpness is applied inside it.** A sharp cut view
  must never beat a soft whole one.

The degrade order is fixed and terminates: whole-and-sharp, then whole, then best
available. A box with any view at all gets one.

## Why

The difference between this and 0259's proposal is the whole argument. A veto
changes what the chooser is choosing between; a reservation changes only what has
already been chosen before the chooser runs. 0236 refused the first for reasons
that are measured and still hold. Neither of them applies to the second, and the
distinction is what lets this pass address the defect 0259 correctly identified
without paying 0236's cost.

**A pass that can starve a box is a veto wearing a different name**, which is why
the degrade order has no terminal branch that returns nothing, and why the
anti-starvation case is a named test rather than an implied one.

`whole_and_sharp` is reported only when sharpness was actually measured. Claiming
the tier after skipping the check reports an inspection that never happened, and
the manifest is read by people deciding whether a room is worth re-driving.

## What would change this decision

The flag going on by default, which needs the usual byte-identical-off proof plus
a GPU round showing the reserved views reconstruct better than the ones they
displace — the output-side check, since no input-side measure has ever separated
good from bad here (0197).

Note also what this pass does NOT reach: it takes a box as its argument, so the
nine object kinds with no RoomPlan box
([0271](0271-nine-of-fourteen-objects-have-no-box.md)) get nothing from it.
