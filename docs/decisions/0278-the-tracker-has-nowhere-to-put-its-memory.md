# 0278 — the tracker has nowhere to put its memory, and the detector wants 1.27 GiB

**Date:** 2026-08-30
**Status:** Decided (measured on candidates 00091-wer and 00092-rem)

## Context

`/track` runs SAM 3.1's multiplex tracker over a capture's frames on the L4.
Once the inference-mode and bool-sort problems were fixed (0276, 0277), the
route reached propagation and hit the failure that actually bounds it.

## What we tried

**Every OOM lands in the same allocation**, on every concept, at every video
length:

```
sam3_multiplex_base.run_backbone_and_detection
  -> sam3_multiplex_detector.forward_video_grounding_batched_multigpu
  -> _process_grounding_chunk_batched
  -> sam3_image.forward_grounding -> _run_segmentation_heads
  -> maskformer_segmentation._embed_pixels -> group_norm
torch.OutOfMemoryError: Tried to allocate 1.27 GiB.
  22.03 GiB capacity, 1.0-1.2 GiB free, 20.4 GiB allocated by PyTorch.
```

That is the DETECTOR grounding a batch of frames, not the tracker. The builder
hardcodes `batched_grounding_batch_size=16`, so the batch is a **fixed 1.27 GiB
transient** and the failures all report just under it free.

**What consumes the headroom is per-OBJECT tracker state, accumulating per
frame.** Three measurements separate the terms:

| run | frames | objects found | result |
|---|---|---|---|
| monitor | 189 | — | OOM ~23 s in (about frame 120) |
| monitor | **60** | 2 | **OK**, 5.24 frames/s, 56 detections, 22.4 s |
| monitor, chair, desk | 95 | — | OOM, all three |
| 13 concepts | 63 | ≥1 each | OOM, all 13 |
| **window** | **63** | **0** | **OK**, 21.6 s |

`window` is the decisive row. It ran the **same 63 frames in the same request**
as thirteen concepts that OOM'd, and completed — because it tracked nothing. So
the container was not degraded and the length alone is not the problem: memory
grows with frames **times objects**, and the fixed 1.27 GiB batch is what
finally does not fit.

**And there is nowhere for that state to go.**
`Sam3MultiplexTrackingWithInteractivity.init_state` sets no `storage_device`
key at all and takes no `offload_state_to_cpu` — while
`Sam3BasePredictor.start_session` unconditionally passes exactly that argument.
The session layer OFFERS an offload the model cannot honour. That is the same
defect as 0276's workaround 1, seen from the memory side rather than the
signature side, and it is why `offload_video_to_cpu=True` (which the model does
accept, and which we set) moves the frames off the card but not the tracking.

**One OOM cost the whole call.** A failure on the first of three concepts was
followed by the same failure on the other two, because nothing released the
partial pass — memory was freed only by `close_video` at the end of the request.

## What we chose

**Make the batch a knob, release on failure, and treat frames x objects as the
budget.**

`PERCEPTION_TRACK_GROUNDING_BATCH` sets `batched_grounding_batch_size` after the
builder returns, defaulting to 4; at 1 it disables batched grounding entirely.
Both attributes are read from the model on every frame
(`sam3_multiplex_base.py:516-517`), so setting them post-construction is
supported rather than a trick — upstream's own `add_prompt` toggles the first
the same way, and that single-frame path has never OOM'd.

## Why

**An env var, not a constant, because this is the lever most likely to need
another turn.** A revision costs seconds; a rebuild costs ten minutes and this
route has already spent several. The fallback from 4 to 1 requires no build.

**Batching is the right thing to shrink first** because it is pure throughput:
grounding four frames at a time instead of sixteen changes no output, only the
peak. Everything else on the table — fewer frames, fewer objects — changes the
answer.

**The single-frame prompt is the existence proof.** `add_prompt` sets
`use_batched_grounding = False` for its one frame and has never run out of
memory, at any video length, including the 189-frame attempt. The unbatched
path is known to fit.

## What would change this decision

**If batch 1 still OOMs**, the fixed cost is not the batch and the remaining
lever is frames x objects — stride the frames (0273 prices what that costs:
stride 2 is 12.4 degrees between frames against a 71.3 degree field of view) or
cap objects. Both change the answer, so both belong in the report rather than
in a default.

**The durable fix is upstream's, and it is small**: give the multiplex
`init_state` the `storage_device` its sibling classes have, so
`offload_state_to_cpu` — which the session layer already passes — does
something. Until then this service can track a bounded frames x objects
product and no more, and the bound belongs in the route's docstring rather than
in a reader's head.

**A bigger card removes it entirely**, and that is worth pricing against the
split 0277 already proposes: a tracking service needs no SAM 3D, no pytorch3d,
no kaolin and no gsplat, so it could run somewhere with more memory and less
baggage.
