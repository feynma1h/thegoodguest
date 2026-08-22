# 0228 — the OOM is headroom, not size

**Date:** 2026-08-23
**Status:** Decided (investigation; no behaviour change)

## Context

0227 measured that 22 of 163 detections in the four preserved captures are
lost to CUDA OOM — 12 of them box views, and two boxes (rp7 b03, rp6g1 b04)
lose their ONLY family-compatible mask that way. That is the largest
correctable loss in the corpus and nothing on the build list targets it.

This note is the investigation that was asked for before any containment is
built: what drives the allocation, whether a downscale-and-retry recovers
the twelve, whether a pre-allocation gate can predict the failure, and how
conditional tier-2 interacts with all of it.

## What we tried

Every OOM string carries four numbers, not one — the requested allocation,
free memory at the moment, the process's total in use, and PyTorch's
allocated share. All 22 were parsed and joined to their mask's area, label,
frame and box association.

**What drives the allocation: not the object.** The request is essentially
constant — **0.500 GiB twelve times, 0.750 GiB six times**, one outlier at
3.120 GiB — across an **84x** range of mask area.

| | |
|---|---|
| Pearson r(mask area, requested bytes) | −0.159 |
| Spearman r | **−0.009** |
| best accuracy of ANY mask-area threshold | 0.846 |
| base rate (always predict success) | **0.852** |

An area threshold is worse than not having one. An 8,997 px mask and a
755,763 px mask both OOM'd requesting the same 0.500 GiB. This is the
signature of a fixed-shape model activation: SAM 3D takes a fixed-resolution
RGBA image with the mask as alpha, so mask area does not change any tensor
shape. (P3A-1 registered and **hit**.)

**What does vary is occupancy.** At every OOM the card is full: **20.04 to
21.76 GiB in use of 22.03**, 91-99%. Reserved-but-unallocated is 49-133 MiB,
so fragmentation has no headroom to give.

**The shortfalls are tiny.** Median box-view shortfall **133 MiB**; three
cases short by **16 MiB**.

| headroom freed before the call | box views rescued |
|---|---|
| 0.25 GiB | **11 of 12** |
| 2.00 GiB | 12 of 12 |

**It is not a leak.** PyTorch-allocated oscillates within a frame
(21.14 → 19.71 → 21.32 → 21.36 on rp6g2 f0), so memory is being released
between objects. ~21.2 GiB is a steady state, not a climb.

**A retry already exists and these are its failures.**
`_reconstruct_with_retry` retries once after `gc.collect()` +
`empty_cache()`, and the recorded error is attempt TWO's. So any
"empty_cache would have saved it" arithmetic is void — that flush already
ran.

## What we chose

Nothing is implemented. Three findings, and one intervention the data
supports which is not the one proposed.

**1. 0061's mechanism stands; its characterisation of the residual does
not.** 0061 fixed the traceback-pin cascade and verified memory returns to
a **16.4 GiB model baseline** after every frame, with per-frame peaks of
21.6-21.9 GiB fully released. That is all confirmed here. But 0061 called
the residual "single LARGE objects... 2.6-2.9 GiB allocation requests", and
CLAUDE.md carries that forward as a capacity fact. **It is not what is
happening.** Twenty-one of 22 requests are 0.500-0.861 GiB. The residual is
ordinary objects missing by a few hundred megabytes, not large objects
exceeding the card — and its cost was never counted.

**2. Downscale-and-retry is refused.** Arithmetically a halved request fits
in 12 of 12 box views, so the prediction that it would recover fewer than
four is a **MISS**. It is refused on other grounds: 0197 measured that
changing what SAM 3D is shown has LARGE and BIDIRECTIONAL effects on the
reconstruction — the same swap gained one table a full set of legs and cost
another the ones it had. A reduced-resolution retry therefore does not
produce a degraded version of the same object; it produces **a different
object shipped under the same identity**, with no instrument able to say
which one arrived. Buying twelve reconstructions of unknown provenance is
not worth twelve missing ones.

**3. A pre-allocation gate can predict and has nothing to do.** Free memory
at call time is the causal variable and a gate on it separates perfectly.
But a gate that refuses turns an OOM into a skip — the same outcome. The
only actions it could take are already taken (`empty_cache`) or out of
scope (reordering, which the frozen plan forbids).

**4. The intervention the data supports is a deferred retry at the frame
boundary.** Not a smaller request and not a gate: the *same* request, made
when occupancy is at baseline. 0061's own live verification is the evidence
— allocated VRAM returns to 16.4 GiB after every frame (16431 / 16439 /
16439 MiB measured). At that baseline roughly **5.6 GiB is free**, which
accommodates every one of the 22 requests including the 3.120 GiB outlier.
The failures happen at a transient peak; the retry happens *inside* it. One
deferred re-attempt per failed object, after its frame's other objects have
released, is bounded, local, and does not touch the plan.

## Why

The framing this replaces is "some objects are too big for the card." The
measurement says the objects are all the same size to the allocator, and
what differs is when in the frame they are asked for. That reframes
containment from a quality trade (shrink the input) into a scheduling one
(ask again when the room is empty), and only the second is free of 0197.

**The interaction with item 3 is the load-bearing result, and it inverts
the prediction.** Of nine boxes that hit an OOM on a box view, **seven were
rescued by another view** and only two were lost. Worse for the naive
reading: in **six of the nine the rank-1 view is the one that OOM'd**, and a
lower-ranked view rescued the box. Exactly one box had rank-1 succeed.

So the second arm is not only a bake-off partner — **it is the OOM
fallback, and it is carrying six of nine cases.** The prediction that
conditional tier-2 nets neutral because tier-1 and tier-2 fail together is
**refuted**.

Conditional tier-2 remains safe, but only under a specification the charter
did not state:

> Tier-2 may be skipped only when tier-1 **produced a passing arm** — never
> when tier-1 was merely *attempted*.

Under that rule the corpus loses nothing: the one box whose rank-1 succeeded
(rp7 b01) had its rank-2 OOM anyway. Under the looser rule, six boxes lose
the view that is currently saving them. This is the difference between a
GPU saving and six missing objects, and it is invisible without the OOM
data.

## What would change this decision

The deferred-retry estimate rests on 0061's measured frame-boundary
baseline rather than on a run of its own, so it is a prediction: **all 22
recovered, including all 12 box views**. Register it before building, and
if a candidate revision recovers materially fewer, the assumption that a
frame boundary is quiet is wrong and the finding is a scheduling problem
one level up.

Two things would reopen the refusal of downscale-retry: an instrument that
can score a reconstruction against its measured box well enough to accept
or reject the reduced-resolution result (which is 0204's chooser, and it
refuses on disagreement rather than ranking), or a model whose input
resolution is a documented quality-neutral knob. Neither exists.

Evicting SAM 3 during pass 2 is the other headroom source and is NOT
recommended here: `_mask_refiner_for` calls it inside pass 2, and mask
refinement is the pass 0212 is about to turn on. The two are mutually
exclusive unless refinement batches its segmentation calls, which is a
larger change than this note's scope.
