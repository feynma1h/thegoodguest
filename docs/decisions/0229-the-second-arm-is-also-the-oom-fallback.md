# 0229 — the second arm is also the OOM fallback

**Date:** 2026-08-23
**Status:** Decided (built, flagged off)

## Context

`_build_reconstruction_plan` emits `box_best_view` and `box_second_view` for
every eligible box, and pass 2 reconstructs both unconditionally. That is a
bake-off: two budget slots at 35-75 s each, on a card that OOMs 13% of the
time (0228), to answer a question 0204's chooser answers by looking at the
first arm alone in most cases.

Making tier-2 conditional on tier-1 already fitting is the obvious saving.
The charter's wording for it was "after the tier-1 arm reconstructs,
evaluate its arm_fit immediately; skip its tier-2 entry if it passes."

That wording is unsafe, and the measurement that says so is the reason this
note exists.

## What we tried

**First, what the second arm is actually doing today.** 0228 traced every
CUDA OOM in the four preserved captures to the box it cost. Nine boxes hit
an OOM on a box view:

| | |
|---|---|
| rescued by another view | **7 of 9** |
| lost entirely | 2 of 9 |
| **cases where the RANK-1 view is the one that OOMed** | **6 of 9** |
| cases where rank-1 succeeded | 1 of 9 |

**In six of nine, tier-1 is the view that failed and a lower-ranked view
saved the box.** Under the charter's wording — skip tier-2 when tier-1 was
attempted and its fit evaluated — those six boxes lose the view currently
rescuing them, because an OOMed tier-1 produces no arm to evaluate and the
loose reading treats "no arm" as nothing to keep the second view for.

**Second, the pass threshold.** Taken from the same 8-box sweep
`_ARM_FILL_MARGIN` was fitted from. Both rank-0 distributions are bimodal:

| axis | healthy cluster | gap | needs-a-second-arm |
|---|---|---|---|
| `fill_dist` | 0.029 - 0.169 | **3.5x** | 0.585, 0.594 |
| `residual_m` | 0.065 - 0.190 | **2.5x** | 0.483 - 0.894 |

Both gates sit at the geometric centre of their gap — 0.3146 and 0.3032,
rounded to **0.31** and **0.30** — so neither is fitted to an end, 1.86x and
1.59x clear on both sides. The two boxes above the fill gap are 0197's pair:
the floating slab and the legless desk, which are exactly the boxes whose
second arm is worth reconstructing.

**Third, whether one gate would do.** It would not, and the case that says
so was already on the record. `fill` reads one axis and the residual reads
three (0205), so a hollow shell of the right height passes the first and
fails the second. spike's bed is that shape exactly — `fill_dist` **0.029**,
the best in the corpus, against residual **0.894**, the worst. A fill-only
gate drops the second arm of the one box 0205 says nobody can adjudicate.

## What we chose

Built behind `PERCEPTION_CONDITIONAL_SECOND_ARM`, default off, with the rule
respecified:

> **Tier-2 may be skipped only when tier-1 PRODUCED A PASSING ARM — never
> when tier-1 was merely attempted.**

`arm_passes` is conservative in one direction only: `None` is not a pass, and
every non-pass path returns False by construction — a missing entry, a
soft-failed one, an unreadable splat, an unplaceable arm, and a raising
measurement all keep the second view. Both checks must hold.

Measured effect on the four preserved captures:

| | |
|---|---|
| boxes whose tier-1 passes | **4 of 8** multi-arm boxes |
| reconstructions saved | **4** — rp6g1 b02, b03; spike b05, b06 |
| of those, second arms `choose_arm` ever uses | **0** |
| walked boxes affected | **0** |

Every skipped second arm is one `choose_arm` returns `chosen_rank=0` on with
`fill_gain` exactly **+0.0000** — reconstructed, uploaded, and provably never
consulted. Every kept one includes both 0197 boxes and the corpus's only
walked `switch`.

The skip is recorded as `skipped_reason: "first_arm_already_fits"`, kept
distinct from `box_covered_by_other_view`: that reason means another view of
this box is planned, this one means this box's own first view rendered well
enough. Folding them would lose the difference between a budget decision and
a quality one, which is the distinction 0227 needed and could not get.

## Why

**The saving is real but narrow, and the narrowness is the finding.**

4 reconstructions across four captures is roughly 140-300 GPU-seconds. Against
the cold plan 0211 measured — 37 planned box views across the same four rooms
— it is about 11%. It is 50% of second views, which sounds larger and is the
same four objects.

Two limits worth stating plainly:

* **rp6g2 gains nothing.** It is the only room that budget-stops every round,
  so it is the room a saving would matter most in, and it has **no multi-arm
  box at all** — 8 best views, 1 second view, 51 long tail. Its problem is a
  53-item tail, and no rule about second arms touches a tail.
* **A warm room gains nothing either.** Three of the four captures' manifests
  carry `box_best_views: 0, box_second_views: 0` — every frame was a
  whole-frame cache hit, so the plan had nothing in it. This is 0160's
  mechanism, and it means the saving only ever materialises on a cold drive.

**And the trade is narrower than the charter assumed.** The charter framed
tier-2 as a bake-off partner, so skipping it looked like removing a
redundancy. It is also the OOM fallback, in six of nine affected boxes, and
that role is **not** something this rule can preserve by being careful — it
is preserved only because an OOMed tier-1 leaves no arm to pass. The two
populations happen to be disjoint on this corpus (a box whose tier-1 OOMed
has one successful arm, so it is not multi-arm, so it is not in the sweep at
all), and a test pins that disjointness rather than trusting it.

**This holds until the throughput charter lands.** If per-object OOM is ever
contained, the fallback role shrinks, the disjointness may stop holding, and
these numbers should be re-measured before the flag is turned on wider. That
ordering is deliberate: the conditional-second-arm saving is worth about
11% of box views, and the OOM it is adjacent to is worth 13% of all
detections.

So conditional tier-2 is what it measures as and no more: **it saves
reconstructions on healthy boxes, and it must not touch the unhealthy ones.**

## What would change this decision

The thresholds are pinned stable across their whole gaps (fill 0.20-0.50,
residual 0.20-0.48 give identical answers on all eight boxes), so a value
change alone should not move anything. If it does, the population has changed
and the sweep needs re-measuring.

**0226 changed the association population from 20/31 boxes to 22/31 and did
NOT change the multi-arm population** — both new boxes carry one arm each —
so the sweep is still the sweep. A later change that gives an existing box
its second arm would need the fixture rebuilt.

The safety property is pinned by a test that was verified to FAIL under the
charter's original loose reading, which is the only way to know a
safety test has teeth.
