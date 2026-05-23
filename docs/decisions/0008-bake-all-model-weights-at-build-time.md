# 0008 — Bake all model weights at build time

**Date:** 2026-05-24
**Status:** Decided

## Context

During investigation for the lazy-load refactor (0007), we found that
SAM 3D Objects' backbone embedder (`sam3d_objects.model.backbone.dit.
embedder.dino.Dino`) calls `torch.hub.load("facebookresearch/dinov2",
"dinov2_vitl14_reg")` at model init. `torch.hub` uses a separate cache
from HuggingFace (`TORCH_HOME`, not `HF_HOME`). `TORCH_HOME` was unset
in the Dockerfile, so it defaulted to `/root/.cache/torch/hub/` — not
populated at build time. Result: ~1.13 GB downloaded from
`dl.fbaipublicfiles.com` on every cold start.

The existing HuggingFace weights (SAM 3, SAM 3D Objects) were already
baked via `snapshot_download()` in Dockerfile RUN steps. DINOv2 was the
gap because it goes through `torch.hub` instead of the HF SDK.

The investigation also revealed the correct DINOv2 variant: the cold-
start logs showed `dinov2_vitl14_reg` (register-token variant), not
plain `dinov2_vitl14`. The `Dino` class accepts `dino_model` as a
config parameter; the actual variant is set by pipeline.yaml, not the
class default. A pre-cache step using the wrong variant string would
download the wrong file and leave the runtime fetch intact.

## What we chose

All model weights must be in the image at build time. No weight
downloads at runtime, ever. The implementation pattern:

1. Set cache env vars (`TORCH_HOME`, `HF_HOME`) to explicit paths
   visible in the image layer listing, not buried under `/root/.cache`.
2. Pre-download in a `RUN` step using the **exact same function call and
   arguments** the inference code uses. Cache keys are derived from the
   call arguments — mismatched arguments (e.g. `dinov2_vitl14` vs
   `dinov2_vitl14_reg`) produce different cache entries, and a runtime
   load with different arguments will silently re-download rather than
   hit the bake. When in doubt, copy the call verbatim from the
   inference code.
3. Follow with a `RUN` step that asserts the expected checkpoint file
   exists at the cache path. Fails the build loudly if the bake didn't
   work. Prevents deploying an image that will silently fall back to a
   runtime download on first cold start.

For the DINOv2 case:

```dockerfile
ENV TORCH_HOME=/opt/torch_hub
RUN python -c "\
import torch; \
torch.hub.load('facebookresearch/dinov2', 'dinov2_vitl14_reg', \
    pretrained=True, trust_repo=True)"

RUN python -c "\
from pathlib import Path; \
cache = Path('/opt/torch_hub/hub/checkpoints'); \
assert any(p.name.endswith('reg4_pretrain.pth') for p in cache.iterdir()), \
    f'DINOv2 weights not cached at {cache}'; \
print(f'DINOv2 cached: {[p.name for p in cache.iterdir()]}')"
```

## Why

Runtime weight downloads fail in three ways: (1) network unavailability
in the production Cloud Run environment, (2) upstream URL changes —
`torch.hub` floats on `main` by default, not a pinned commit, (3)
additional cold-start latency on top of the ~195s model init. None are
acceptable. Container images should be self-contained.

The "verify with an assert" discipline is worth calling out explicitly:
`torch.hub.load()` with a pre-populated cache succeeds silently, but so
does a cache miss (it just re-downloads). Without the assertion, a
broken bake step (wrong path, wrong variant name, transient network
failure during build) produces a passing build and a broken deploy.

## Convention going forward

When adding any model that fetches weights at init time (`torch.hub`,
`from_pretrained`, `hf_hub_download`, custom URLs), the Dockerfile must:

1. Set the relevant cache env var to an explicit path.
2. Pre-download in a `RUN` step using the **exact same function call and
   arguments** the inference code uses. Cache keys are derived from the
   call arguments — mismatched arguments produce different cache entries,
   and a runtime load with different arguments will silently re-download
   rather than hit the bake. When in doubt, copy the call verbatim from
   the inference code.
3. Follow with a `RUN` that asserts the file exists and prints its name.
   Build must fail if the file is missing.

## What would change this decision

Revisit if: (a) the image exceeds Cloud Run's 32 GB image size limit,
(b) Cloud Build time per deploy exceeds 30 minutes consistently, or
(c) we add a service that needs to share weights with perception-obj
and duplicating the bake across images becomes wasteful.

If any of these trigger, a Cloud Storage-mounted model cache could
replace baked weights. This convention would still apply to the
cache-population step in that world.
