# Throughput — the charter that owns the OOM loss

**Opened:** 2026-08-23, out of decisions 0227 and 0228.
**Status:** Not started. Nothing here is built.

This exists because the largest measured loss in the four-capture corpus has
no owner. It was found by a selection-and-supply session, is not a selection
problem, and was deliberately not built there.

## The outcome

Recover the reconstructions the GPU currently drops, without changing what
SAM 3D is shown.

The second clause is the hard one and it is not negotiable — see "What is
already refused".

## What it owns

**22 of 163 detections in segmented frames fail to reconstruct with CUDA
OOM — 13%.** Twelve of the 22 are box views, meaning masks that would have
associated with a measured RoomPlan box. Two boxes (**rp7 b03**, **rp6g1
b04**) lose their ONLY family-compatible mask that way and ship as empty
inventory (0227).

The loss is not evenly spread and it is not the objects you would guess.

| | |
|---|---|
| requested allocation | **0.500 GiB x12, 0.750 x6**, one 3.120 outlier |
| mask area range across those | **84x** |
| Spearman r(mask area, requested bytes) | **−0.009** |
| best accuracy of any mask-area threshold | 0.846, against a **0.852** base rate |
| median box-view shortfall | **133 MiB** |
| smallest shortfall | **16 MiB**, three times |
| card occupancy at every OOM | **91-99%** |
| model baseline, invariant across 16 revisions | **16.05 GiB** (16431-16439 MiB) |
| successful peak transient | **5.61 GiB**, against a 5.61 GiB budget |

**The pipeline routinely runs the card to its last hundred megabytes.** The
failures are the objects needing a hair more than that, and mask area cannot
tell you which they will be — an 8,997 px mask and a 755,763 px mask both
failed asking for the same 0.500 GiB, because the request is a fixed-shape
model activation.

## Why it stayed invisible

Three reasons, all worth knowing before trusting any other summary here.

1. **0061's residual was mischaracterised.** That note fixed the traceback-pin
   cascade correctly and its mechanism analysis stands entirely. But it
   described what remained as "single LARGE objects... 2.6-2.9 GiB allocation
   requests", and CLAUDE.md carried that forward for a year as a standing
   capacity fact. **Twenty-one of the 22 requests are 0.500-0.861 GiB.** A
   defect described as "large objects, unavoidable" does not get counted; a
   defect described as "ordinary objects missing by 16 MiB" does.
2. **Nothing aggregates the failures.** Every one is recorded faithfully in
   its frame's `objects.json`, with the full CUDA error string. The manifest
   counts what shipped, association reads what has a splat, and no code or
   report ever reads the failures together.
3. **An OOM-failed view is never retried by any warm re-drive** (0160). The
   frame's `objects.json` caches the failure, so the object is dropped once
   and forever. There is no second chance anywhere in the system today.

## What is already refused — do not re-propose

**Downscale-and-retry.** Arithmetically a halved request fits in 12 of 12 box
views, so the arithmetic alone green-lights it. It is refused because 0197
measured that changing what SAM 3D is shown has **large and BIDIRECTIONAL**
effects — the same swap gained one table a full set of legs and cost another
the ones it had. A reduced-resolution fallback therefore does not degrade
gracefully; it substitutes **a different object under the same identity**,
and nothing downstream can detect the substitution. A missing object is
visible, countable and honest; a silently swapped one is none of those.
Generalised in 0228: **where a fallback must choose between altering the
input and not running, it must not run**, unless an instrument exists that
can accept or reject the result on its own merits. 0204's chooser is the
only candidate and it declines to rank.

**A deferred retry at a frame or object boundary.** Refuted in 0228 before
implementation, and the refutation needs no measurement: `_reconstruct_with_retry`
already retries after `gc.collect()` + `empty_cache()`, `_free_gpu_memory()`
runs after every object, and the vram logs show allocated memory returning to
an invariant baseline at every boundary across 16 revisions. An OOM means
`inuse + request > capacity`; if the object started at baseline, restarting it
reproduces the same accrual and the same inequality. **The queue it would
defer into is already empty.**

**A pre-allocation gate.** Free memory is the causal variable and separates
perfectly, but a gate that refuses turns an OOM into a skip — the same
outcome. Its only useful actions are already taken or forbidden by the frozen
plan.

## The named option — reduce the baseline by evicting SAM 3 for pass 2

The transient budget is `capacity − baseline`, and every refused idea above
tried to shrink the numerator's demand. **The only untried lever is the
baseline**, which is the two models, and one of them is idle.

Pass 1 completes all segmentation before pass 2 begins. Pass 2 touches SAM 3
only through `_mask_refiner_for`. With `PERCEPTION_MASK_REFINE` off — the
shipped default — **SAM 3 is provably idle for the whole of pass 2 while
holding multiple GiB of VRAM.** 0191 puts the two HF snapshots at 17.207 GiB
on disk with SAM 3D's share at 11.199, so SAM 3's is roughly 6 GiB; VRAM
residency is not disk size, but the order is right. Freeing **1.2 GiB covers
21 of the 22**, and 3 GiB covers all of them including the 6.43 GiB outlier.

**Its three costs, stated so the trade is visible:**

1. **Model lifetime becomes pass-scoped rather than process-scoped.** The
   registry in `server.py` currently holds both models as permanent
   singletons with double-checked locking (0007). Eviction and reload is a
   change to that contract, not a knob.
2. **~100 s of reload against a 900 s request budget** — 11% — on the next
   request that segments. `get_sam3()` is already lazy, so the mechanism
   exists; the cost is wall-clock on a service that budget-stops rooms
   today (`b667f891` stops every round).
3. **It is mutually exclusive with mask refinement.** 0212 is about to turn
   refinement on, refinement calls SAM 3 inside pass 2, and refinement is the
   largest measured win in this corpus — rp7's desk from 0.321 to 1.122 of
   its box's narrowest axis. **Trading refinement for OOM headroom is a
   product decision, not an implementation one**, and it should not be made
   by whoever happens to be holding the file.

The exclusivity is not absolute: a restructure that batches pass 2's
refinement calls into their own sub-pass would let SAM 3 be evicted after it,
recovering both. That is the shape worth costing first, and it is a
restructure of `_run_census_two_pass`, which is the same loop the frozen-plan
retry work would need. **These two are one project, not two.**

## Where to start

The log query is done and the baseline is measured, so the first unknown is
the only one left: **how much VRAM does SAM 3 actually hold?** One line of
instrumentation at the top of pass 2 — `torch.cuda.memory_allocated()` before
and after a deliberate SAM 3 eviction on a 0%-traffic candidate — answers
whether 1.2 GiB is even available before anything is designed around it.

Do that before costing the restructure. If SAM 3's residency is under
1.2 GiB the whole option collapses and this charter is about the L4's
capacity rather than about the pipeline's hygiene, which is a different
conversation with a different budget.
