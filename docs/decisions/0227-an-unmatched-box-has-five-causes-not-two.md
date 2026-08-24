# 0227 — an unmatched box has five causes, not two

**Date:** 2026-08-23
**Status:** Decided

## Context

After 0226 raised association from 20/31 boxes to 22/31, nine RoomPlan
boxes across the four preserved captures still carry no observation. Six
were characterised as having "no overlapping mask at all, in any sampled
frame" and were to be split two ways — detected-but-not-sampled (which
selection can reach) against never-detected (which it cannot). Three more
were declined label matches, each on a stated reason.

The split was the gate on items 3-8: if those six were never detected, the
defect is upstream of every item on the list.

## What we tried

For each of the nine boxes, every mask in every segmented frame was scored
against the box's projected footprint, and each mask clearing
`_BOX_MATCH_MIN` was traced to its actual fate in the shipped
`objects.json` — reconstructed, policy-skipped, or failed — and checked for
a rival box that greedy association would hand it to first. Box visibility
was measured twice, over the segmented frames and over every keyframe in
the capture.

**The stated premise is false for four of the six.** Masks overlapping
those boxes exist, at up to 1.0000, family-compatible, uncontested. They
are absent from association because they carry `ok=False`, which no
association-side view can see: an entry with `ok=False` has no splat, so it
is not an observation.

| box | | verdict |
|---|---|---|
| rp7 b03 | storage | **PLAN_SKIP** — three uncontested `cabinet` at 1.0000 / 0.9859 / 0.9856; two OOM, one policy-skipped |
| rp6g1 b04 | storage, *declined* | **OOM** — two uncontested `cabinet` at 1.0000, both CUDA OOM |
| rp6g2 b09 | storage, *declined* | **PLAN_SKIP** — uncontested `cabinet` at 0.5561, policy-skipped |
| spike b01 | storage | **COMPETITION** — its one compatible mask (0.6836) lost to b00 at 0.8442; zero plan-side associations |
| rp6g2 b04 | sofa | **DETECTION** — 0.909 in-frame in a segmented frame, no mask ≥ MIN |
| spike b02 | table | **DETECTION** — 0.981 in-frame, no compatible mask |
| rp6g2 b02 | storage | **SAMPLING** — 0.943 in-frame over the full capture, 0.000 over the six segmented frames |
| rp6g2 b01 | sofa | **NEVER_FRAMED** — tops out at **0.657** in-frame across all 124 keyframes |
| rp6g2 b07 | table, *declined* | **LABEL** — ten masks ≥ MIN, all `chair`, none compatible |

Predictions registered before measuring: ≥4 of the six are sampling misses
(**MISS** — one is); all six well framed somewhere in the full keyframe set
(**MISS** — rp6g2 b01 never is); the three declines are label conflicts
(**MISS** — one of three is).

Aggregate over 163 detections in segmented frames: **127 reconstructed
(78%), 22 lost to CUDA OOM (13%), 14 policy-skipped.** Twelve of the 22
OOM losses are box views — masks that would have associated.

## What we chose

Record the five-way taxonomy, and record that the two causes the split
asked about are the two smallest: one SAMPLING and one NEVER_FRAMED out of
nine.

**Two of the three declines were argued on incomplete information, and
neither needs the map change it was declined over.** rp6g1 b04 was declined
because "a wardrobe wearing a door's appearance is worse than one with
none" — but a `cabinet` mask covers that box at 1.0000, uncontested, in two
separate frames, and both died on the GPU. rp6g2 b09 was declined over an
`artwork` at 1.0000 while an uncontested `cabinet` at 0.5561 sat beside it,
policy-skipped. In both cases the correct label was already segmented and
already associated by the plan's own reckoning. **The declines stand as
declines — nothing about the map should change — but the boxes are not
label problems and will not be fixed by treating them as such.**

rp6g2 b07 is confirmed LABEL exactly as stated: ten `chair` masks at up to
1.0000 over a `table` box, which is 0148's tucked-chair geometry working as
designed. The decline stands on its own reasoning.

## Why

The taxonomy matters because each cause has a different owner and only two
of the five are reachable by anything on the current build list.

* **OOM and PLAN_SKIP (4 of 9)** are reconstruction-side. Selection cannot
  see them: the frame was chosen, the object was segmented, the mask was
  correct, and the GPU or the per-box view budget dropped it. These are the
  largest bucket and they are the one item 3 touches, by not spending a
  slot on a tier-2 arm whose tier-1 already passed.
* **COMPETITION (1)** is association-side and is a genuine hazard of
  greedy single-assignment. It is the same mechanism that made rp6g2 b07's
  match a bad idea, seen from the other end: there, taking the chair would
  have starved a chair box; here, b00 legitimately outbids b01 and b01 gets
  nothing at all. Nothing on this list addresses it and nothing should
  without a second look — a rule that lets a loser re-bid on a taken mask
  is a rule that can hand one object to two boxes.
* **DETECTION (2)** is prompt-side or model-side. A `sofa` box 0.909
  in-frame with no mask over it is SAM declining to segment furniture it
  was prompted for.
* **SAMPLING (1)** is the only one item 7's selector reaches directly.
* **NEVER_FRAMED (1)** is capture-side and is the honest floor. rp6g2 b01
  is a 1.77 m sofa that no keyframe in a 124-frame capture ever frames past
  0.657. No selector, prompt, or budget reaches it, because the photograph
  does not exist.

The `ok=False` invisibility is worth naming on its own. `objects.json`
records exactly why each detection failed — `skipped_reason` or a CUDA
error string — and every one of those records is intact and readable. What
was missing is that nothing ever *reads them together*: the manifest counts
what shipped, association reads what has a splat, and the failures sit in
per-frame files nobody aggregates. Four of nine boxes had their answer
written down and unread.

## What would change this decision

The OOM share is measured on four captures that were driven repeatedly, and
per-entry reasons are durable while the plan state at the time is not
reconstructable offline — a warm re-drive changes `done_ok` and therefore
which views are policy-skipped. So treat the 12 box-view OOM losses as the
solid number and the PLAN_SKIP attributions as correct-per-entry rather
than as a stable rate.

If per-object OOM containment improves — a smaller reconstruction working
set, or admission that refuses a mask whose pixel count predicts the
allocation — this table should be re-measured before anything is built on
its shape. The 13% OOM rate is the single largest correctable loss in it,
and it is not a selection problem.
