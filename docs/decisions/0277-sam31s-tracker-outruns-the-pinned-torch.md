# 0277 — SAM 3.1's tracker needs a newer torch than SAM 3D lets us have

**Date:** 2026-08-30
**Status:** Decided (measured on a candidate; worked around, not resolved)

## Context

`/track` runs SAM 3.1's multiplex video tracker in `perception-obj`, the same
container as SAM 3 and SAM 3D Objects. The three now share one Python
environment, and that environment's torch is not a free variable.

## What we tried

On `perception-obj-00091-wer` the tracker loaded in 123.1 s, all 189 frames of
the preserved capture fetched in 11.3 s and decoded in 11.1 s, and the first
`add_prompt` raised:

```
RuntimeError: Sort currently does not support bool dtype on CUDA.
  sam3/model/sam3_multiplex_base.py:545, in _det_track_one_frame_impl
    pos_pred_mask_idx = pos_pred_mask.argsort(descending=True)
```

`pos_pred_mask` is a bool tensor; the line moves the detections the tracker is
keeping to the front of the batch. Newer torch has a bool sort kernel for CUDA.
**Ours does not, and ours cannot move.** The Dockerfile's own comment states the
constraint: *"SAM 3D Objects pins torch==2.5.1+cu121"*. pytorch3d is a wheel we
build ourselves against exactly that pair, kaolin is installed from a
`torch-2.5.1_cu121` find-links index, and gsplat is compiled the same way.
Upstream `sam3` declares **no torch version at all** in its `pyproject.toml`, so
nothing in the dependency metadata would have predicted this.

**It is exactly one call.** Every `sort`, `argsort` and `topk` across the six
multiplex modules was checked; the only other one is `np.argsort`, which is
unaffected. A sweep for other version-sensitive APIs — `flex_attention`,
`enable_gqa`, `torch.compiler`, float8, `_scaled_mm` — found none.

## What we chose

**A dtype shim in our own code, verified on the device at construction.**
`models/sam3_video.py` wraps `torch.Tensor.argsort` so a bool CUDA tensor is
cast to uint8 first, then immediately proves it by argsorting a known bool
tensor on the GPU and checking the answer.

## Why

**The shim cannot change any call that works today.** Its branch fires only for
a bool CUDA tensor — precisely the case that currently raises — so every
working call takes the original path. uint8 preserves the ordering exactly
(`False → 0`, `True → 1`), and `argsort` is unstable in both dtypes, so the
arbitrary order within each group is arbitrary the same way. That property is
what makes a monkey-patch defensible here and would not hold for a broader one.

**It belongs in our code, not in the image's copy of Meta's source.** A `sed`
against `/opt/sam3-repo` was the obvious alternative and the repo has precedent
for build-time patching (`/opt/sam3d/patching/hydra`). It was refused because
the patched file would then disagree with the vendored copy that documents what
we run — 0264's "plausible lie" — and because a Dockerfile `sed` is neither
reviewable in a diff nor testable.

**It verifies itself rather than trusting itself.** A shim that silently failed
to install would resurface as the identical RuntimeError two minutes later, on a
GPU request already paid for. The probe costs microseconds and moves that
failure to construction.

**The real finding is the coupling, and it is bigger than the shim.** SAM 3D
Objects' pin now constrains what *other* models this service can host, and
nothing declares that. The next model that wants a newer torch will not be
fixable in one line, and at that point the answer is a separate service rather
than a second shim — the tracker needs no SAM 3D, no pytorch3d, no kaolin and no
gsplat, so it would split cleanly.

## What would change this decision

**A second incompatibility.** One line is a shim; two is a signal that the
environment is wrong, and the split above becomes the cheaper answer. This note
is the thing to re-read at that point rather than adding a second patch.

**SAM 3D Objects moving off torch 2.5.1**, which would let the image follow
upstream and make the shim removable. The removal test is easy and should be
run then: delete it and confirm `argsort` on a bool CUDA tensor returns rather
than raises.

**Vendoring `sam3_multiplex_base.py`** into `upstream/` would make this line
readable in the repo, which it currently is not — the file is only inside the
image. That is a small addition to what 0264 already vendors and it is where
someone will look first when the shim next fails.
