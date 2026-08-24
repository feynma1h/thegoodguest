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
four is a **MISS**, and the arithmetic alone would have green-lit it. It is
refused on other grounds, and the reasoning generalises past this item:

> **Any change to what SAM 3D is shown produces a different object, not a
> better or worse one.** 0197 measured the effect as large and
> BIDIRECTIONAL — the same swap gained one table a full set of legs and cost
> another the ones it had, with every input-side measure pointing the same
> way on both. So a fallback that alters the input on failure does not
> degrade gracefully; it substitutes **a different object under the same
> identity**, and nothing downstream can detect the substitution. A missing
> object is visible, countable, and honest. A silently swapped one is none
> of those. **Where a fallback must choose between altering the input and
> not running, it must not run** — unless an instrument exists that can
> accept or reject the result on its own merits.

That test is what makes a deferred retry admissible and a downscaled one
not: the deferred retry makes the SAME request with the SAME input, so
there is no substitution to detect. It is also why this reasoning does not
generalise into a ban on retries — only onto retries that change the input.

The instrument that would lift the refusal is 0204's chooser, and it
declines to rank: it refuses on axis disagreement rather than ordering
candidates. So there is no scorer that could adjudicate a downscaled
reconstruction against its full-resolution sibling today.

**3. A pre-allocation gate can predict and has nothing to do.** Free memory
at call time is the causal variable and a gate on it separates perfectly.
But a gate that refuses turns an OOM into a skip — the same outcome. The
only actions it could take are already taken (`empty_cache`) or out of
scope (reordering, which the frozen plan forbids).

**4. The intervention the data supports is a deferred retry at the frame
boundary.** **REFUTED THE SAME DAY — see the amendment below before
acting on any part of this paragraph. It is preserved because a future
session that reads only the recommendation would rebuild it.** Not a smaller request and not a gate: the *same* request, made
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

## Amendment, same day — the deferred retry is inert, and finding 4 is wrong

Finding 4 above proposed re-attempting the same request at frame-boundary
baseline occupancy, and predicted all 22 recovered. It was green-lit. It was
checked before implementation and it does not survive the check.

**The structural half, which needs no numbers.**
`_reconstruct_with_retry` already calls `gc.collect()` + `empty_cache()`
between attempt 1 and attempt 2, and pass 2 calls `_free_gpu_memory()` after
every object, so **no other object is ever in flight when a reconstruction
runs**. `_reconstruct_one_object` additionally drops the 15-key GPU result
dict eagerly, before upload. A deferred retry at any boundary therefore runs
under conditions IDENTICAL to attempt 2. There is no state a deferral clears
that the existing retry does not already clear, and no memory a frame
boundary returns that an object boundary does not.

**The arithmetic half, which says why the shortfall persists, and which the
log query below turns from an estimate into an identity.**

An OOM means `request > free`, which is `inuse + request > capacity`. If the
object began its forward pass at baseline, then its `inuse` at the moment of
failure is baseline plus its OWN accrual — so re-running it from baseline
reproduces the same accrual and the same inequality. **Restarting a failed
object changes nothing that appears in the inequality.** That is not an
estimate; it is what the failure condition says once the starting point is
known.

**The starting point is now measured, not assumed.** `_log_vram` lines from
Cloud Logging, 125 of them across **16 revisions** from `00032-km5` to
`00072-pox`, at frame boundaries and at `after_census_pass2`:

| | |
|---|---|
| `allocated_mib` values observed | **16431 and 16439 — nothing else** |
| spread, across 16 revisions and a month | **8 MiB** |
| peak_mib observed | up to 22177 = **21.66 GiB** |
| headroom at that peak on a 22.03 GiB card | **0.37 GiB** |

So memory returns to an invariant baseline before every object, the baseline
has not drifted at all, and the pipeline's successful peaks run **exactly at
the ceiling**. With the measured 0.375 GiB of non-PyTorch context the
transient budget is 22.03 − 16.05 − 0.375 = **5.61 GiB**, and the observed
successful peak transient is 21.66 − 16.05 = **5.61 GiB**. The pipeline
routinely runs the card to its last hundred megabytes; the OOMs are the
objects that need a hair more than that.

**Correction while citing it:** 0061 records this baseline as "16.4 GiB"
from the same three readings (16431 / 16439 / 16439 MiB). Those are MiB, and
16439 / 1024 = **16.05 GiB** — the note divided by 1000. The slip is small
and changes no conclusion in 0061, but every budget computed from it is
0.35 GiB optimistic, which is more than the median shortfall this note is
about.

The objects therefore do not fail because they were asked for at a crowded
moment. They fail because their forward pass needs more transient memory
than the card has left once both models are resident.

**What that costs the note's own framing.** "Headroom, not size" is right
that the shortfall is small — 16 to 230 MiB — and right that mask area
cannot predict it. It is **wrong about where the headroom can come from**.
It cannot come from timing, because timing is already optimal. It can only
come from the **baseline**, and the baseline is the two models.

**So the lever is the 16.4 GiB baseline, and there is one obvious candidate.**
Pass 1 completes all segmentation before pass 2 begins, and pass 2 touches
SAM 3 only through `_mask_refiner_for`. With `PERCEPTION_MASK_REFINE` off —
which is the shipped default — **SAM 3 is provably idle for the whole of
pass 2 while holding multiple GiB of VRAM**. 0191 measures the two HF
snapshots at 17.207 GiB on disk with SAM 3D's share at 11.199, putting SAM
3's at roughly 6 GiB; VRAM residency is not disk size, but the order is
right, and freeing even 1.2 GiB covers 21 of the 22 failures while freeing
3 GiB covers all of them including the 6.43 GiB outlier.

That is not built here. It changes model lifetime from process-scoped to
pass-scoped, it costs a reload (~100 s against a 900 s budget) on the next
request that segments, and it is **mutually exclusive with mask refinement**,
which 0212 is about to turn on and which calls SAM 3 inside pass 2. Those are
real trades and they belong to whoever owns throughput.

**The cheapest next step is a log query, not a GPU run.** The arithmetic
above rests on 0061's 16.4 GiB baseline, measured on revision
`00026-449` in July, while these captures span later revisions. `_log_vram`
already writes `allocated_mib` at every frame boundary and at
`after_census_pass2`. Reading those lines from Cloud Logging on a recent
scene settles whether the baseline has drifted and costs nothing — and it is
0061's own re-open trigger, unexercised since it was written.

## What would change this decision

The deferred retry was predicted to recover all 22 and was refuted before
implementation by the amendment above — **MISS**, and the miss is the
useful part: the prediction assumed a frame boundary is quieter than an
object boundary, and in this pipeline it is not.

What would reopen containment is a smaller baseline. If SAM 3 is ever
evicted for the duration of pass 2, or the two models are ever split across
requests, re-measure this table first: every number in it is a function of
the 5.26 GiB the models leave behind.

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
