# 0274 — SAM 3.1 is a tracker release, and the image path has nowhere to move to

**Date:** 2026-08-30
**Status:** Decided (read from source and from the HuggingFace API)

## Context

0271 proposes moving to SAM 3.1 to get "per-frame masks plus stable instance
IDs" for the nine object kinds RoomPlan never boxed. Read as a version bump —
same call sites, newer weights — that is not what SAM 3.1 is, and the
difference decides the whole shape of the work.

## What we tried

Read, not inferred. `facebookresearch/sam3` at `8f0b7f4d`, which is the commit
the serving image was built from and which is byte-identical to today's `main`
for every file below.

**SAM 3 is two components sharing one backbone.** The paper's own framing: "an
image-level detector and a memory-based video tracker". The detector answers
Promptable Concept Segmentation — text in, every matching instance out — and is
what `Sam3Processor.set_text_prompt` wraps. That is the only half
`models/sam3.py` has ever called.

**The detector's output carries no instance identity at all.**
`sam3_image_processor._forward_grounding` sets exactly four keys —
`masks_logits`, `masks`, `boxes`, `scores` — and `set_image` builds a fresh
state per call. Instances are rows of a tensor; nothing relates row 3 of frame
41 to row 3 of frame 42. **No amount of calling `/segment` produces a map**, and
that is a property of the contract rather than a limitation of our wrapper.

**SAM 3.1's only checkpoint is the tracker's.** `facebook/sam3.1` holds one
weight file, `sam3.1_multiplex.pt` (HuggingFace API, 2026-08-30), against
`facebook/sam3`'s `sam3.pt` plus `model.safetensors`. In `model_builder.py`,
`download_ckpt_from_hf(version="sam3.1")` is called from exactly one place —
`build_sam3_multiplex_video_model` — while **`build_sam3_image_model` hardcodes
`download_ckpt_from_hf(version="sam3")`** and takes no version parameter at all.

The release note agrees: SAM 3.1 is Object Multiplex, "a shared-memory approach
for joint multi-object tracking", ~7x faster at 128 objects.

## What we chose

**Adopt the video tracker as a new model beside the detector, and leave the
image path exactly where it is.**

`/process` and `/segment` keep loading `facebook/sam3`. `/track` loads
`sam3.1_multiplex.pt` through `build_sam3_multiplex_video_predictor`, which
builds a tracker AND a detector from that one merged checkpoint.

## Why

**"Upgrade SAM 3 to SAM 3.1" is not an available action for the path we use.**
There are no 3.1 image-detector weights published to move to, and no parameter
that would load them if there were. A session that set out to bump a version
would have found this only at model-load time, on a GPU, which is the most
expensive place to learn it — and the belief is entirely plausible from the
version numbers alone.

**Read the other way round, the news is better than 0271 assumed.** The map
needs a tracker; SAM 3.1 is precisely the release that made multi-object
tracking cheap. The migration's justification is therefore not "3.1 has better
masks" — it does not, for our path — but "the thing that produces object
identity is now affordable to run over a whole capture."

**Two models coexisting is a cost, not a free upgrade.** The image detector and
the multiplex tracker are separate checkpoints, ~3.45 GB and ~3.50 GB, and both
are baked into the image because this service scales to zero. 0228 measured
5.26 GiB of headroom on the L4 with SAM 3 and SAM 3D resident, so **/track must
never share a request with reconstruction** — it loads its own model and
nothing else, the way `/segment` deliberately never loads SAM 3D.

**And the 3.1 checkpoint does contain a detector**, loaded as
`Sam3MultiplexDetector` during tracking. So tracked masks come from 3.1-era
detector weights while `/process` keeps 3.0's. That is a real difference
between what `/track` sees and what the pipeline sees, and any comparison of
their masks has to account for it rather than assume one vocabulary.

## What would change this decision

**Meta publishing 3.1 image weights**, or giving `build_sam3_image_model` a
`version` parameter. Then the image path has somewhere to move and the question
becomes an ordinary bump, to be measured against the mask work in 0198/0266
rather than assumed to be an improvement.

**`facebook/sam3.1` is separately gated.** Access to `facebook/sam3` does not
imply it; both were confirmed reachable with our token before any build. A
token that loses the second fails the image build at the download step, not at
run time, which is the cheap place.
