# 0061 — OOM cascade root cause: the in-except retry pinned the failed attempt's GPU tensors

**Date:** 2026-07-21
**Status:** Decided

## Context

During scene `25a14caf` (126 real keyframes), GPU memory was observed
"climbing monotonically, 22.03 GiB saturated by frame 10, then intermittent
per-object OOM". The envelope-fix brief suspected per-object results with
on-GPU tensors retained in the receiver's accumulator, with instructions to
verify before fixing.

## What we tried

Verification from the production OOM messages' allocator stats (17 soft-fail
lines, frames 6–20). Every OOM reported the same signature, e.g.:

> Tried to allocate 20.00 MiB. GPU 0 has a total capacity of 22.03 GiB …
> 21.67 GiB is **allocated by PyTorch**, and 53.45 MiB is **reserved by
> PyTorch but unallocated**.

- Reserved-but-unallocated consistently <90 MiB → **not fragmentation**
  (`PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` was already set in the
  deploy env; allocator tuning was never the missing piece).
- The accumulator theory is falsified by the code: `objects_out` /
  `frame_results` hold only JSON-serializable data, and the object loop
  already did `del result` + `empty_cache()` per object in a `finally`.
- The pattern that fits all observations: clean frames (11, 18, 21)
  succeeded BETWEEN OOM frames — live memory returned between objects, so
  nothing was accumulating across objects at all.

The actual mechanism: the OOM retry ran **inside the except block**. While
an exception is being handled, its traceback pins every frame of the failed
attempt — including the SAM 3D pipeline's intermediate GPU tensors at the
deepest point of the failure. The retry therefore double-booked the card
against the pinned first attempt: that is how a 20 MiB allocation fails on
a 22 GiB GPU with ~21.7 GiB "allocated". Each logged OOM is really "attempt
1 failed big, attempt 2 suffocated under attempt 1's corpse". Frames↔
tracebacks form reference cycles, so even refcounting doesn't free them —
only gc.collect() does.

## What we chose

In `services/perception-obj/`:

1. `_reconstruct_with_retry`: the retry moved OUTSIDE the except handler;
   `_free_gpu_memory()` (gc.collect **then** empty_cache — order matters for
   the cycle sweep) runs between attempts.
2. Eager result drop in `_process_frame`: layout (numpy) and PLY bytes are
   extracted immediately after reconstruction, then the 15-key result dict
   of GPU tensors is dropped BEFORE the GCS upload and placement tail work.
3. `torch.no_grad()` around `SAM3DModel.reconstruct` — Meta's pipeline
   guards most stages internally but `run()` has gaps (the pose decoder runs
   bare); an output with a live `grad_fn` pins its activation graph.
   Deliberately no_grad and NOT `inference_mode`: the pipeline uses
   `inference_mode(mode=False)` sections internally, and in-place updates to
   inference tensors outside their creating context are runtime errors we
   cannot risk on a GPU we can't test locally.
4. Per-frame `vram` log lines (allocated/reserved/peak, peak reset each
   frame) so the flat-memory invariant is verifiable in production, plus
   `empty_cache` between frames.

## Why

The fix follows the evidence: the only reference holder large enough and
transient enough to explain both the OOMs and the interleaved successes is
the exception traceback, and the two receiver-side lifetimes (result held
through upload/placement; graphs from unguarded stages) are the remaining
real holders worth closing. No speculative allocator knobs were added — the
one usually recommended (expandable_segments) was already on, and the
observed reserved-but-unallocated numbers say fragmentation wasn't the
problem.

## Live verification (2026-07-21)

Revision `perception-obj-00026-449`, scene `25a14caf` re-drive: allocated
VRAM returned to the 16.4 GiB model baseline after every frame
(16431 / 16439 / 16439 MiB; per-frame peaks of 21.6–21.9 GiB fully
released). The invariant holds. Residual truth: single LARGE objects can
still exceed the card transiently (2.6–2.9 GiB allocation requests on top
of the baseline mid-pipeline) — the per-object soft-fail contains those,
and frames complete around them. That is a capacity fact about L4 + these
models, not a lifecycle bug.

## What would change this decision

If the post-fix production `vram` lines show allocated memory still
climbing across frames (not returning to a flat baseline after
`_free_gpu_memory`), there is a second holder inside the SAM 3D pipeline
itself (model-attribute caching) — that would need an upstream-code dive,
not more receiver hygiene.
