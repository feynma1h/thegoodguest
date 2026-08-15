# 0180 — The pointmap conditions the shape, not only the layout

**Date:** 2026-08-16
**Status:** Measured inside the serving image

## Context

Decision 0179 found that SAM 3D Objects' `Inference.__call__` takes an
undocumented fourth parameter, `pointmap`, that Meta describes as accepting a
scene point map from LiDAR — and that when it is None the pipeline estimates one
with a monocular depth model. It left four things unverified, and named the
third as the one that decides how much this matters: **whether the pointmap
reaches the model's shape branch or only its layout branch.** An earlier draft
of 0179 said layout-only; that was over-claimed from a single file summary.

All four are now measured, in the image that is serving.

## What we tried

Read the serving image rather than upstream `main`. The image
(`perception-obj:20260813-222442`, digest `sha256:d15ca00d…`, revision
`perception-obj-00043-yiz`) was read directly out of Artifact Registry: layer 4
carries the `/opt/sam3d` clone, layer 7 carries the installed pytorch3d, and
`checkpoints/hf/pipeline.yaml` was streamed out of the 12 GB checkpoint layer
without downloading it whole.

**Check 1 — does our build have the parameter? YES.** The clone in the image is
`facebookresearch/sam-3d-objects` at commit
`f91db411c50efee93d8db7aeb323885650f6f722` (2026-06-02), and
`notebook/inference.py` reads:

```python
def __call__(self, image, mask, seed=None, pointmap=None) -> dict:
    ...
    return self._pipeline.run(image, None, seed, ..., pointmap=pointmap)
```

**Check 2 — does `pipeline.yaml` instantiate the pointmap pipeline? YES.** Its
first line is
`_target_: sam3d_objects.pipeline.inference_pipeline_pointmap.InferencePipelinePointMap`,
and its `ss_preprocessor` carries a full `pointmap_transform`,
`img_mask_pointmap_joint_transform`, `normalize_pointmap: true` and a
`pointmap_normalizer`. The gate in `preprocess_image` —
`if pointmap is not None and preprocessor.pointmap_transform != (None,)` — is
open.

**Check 3 — does `ss_condition_embedder` consume the pointmap? YES, and it feeds
the shape.** Three facts compose:

1. `pipeline.yaml` sets `ss_condition_input_mapping: []`, so
   `get_condition_input` puts **every** key of `ss_input_dict` into
   `condition_kwargs` — image, mask, pointmap, rgb_pointmap and the scale/shift
   pair.
2. The embedder is an `EmbedderFuser`, whose `forward(*args, **kwargs)` ignores
   positional arguments entirely and reads its inputs **by kwarg name** from a
   configured `embedder_list`. `ss_generator.yaml` configures three entries:
   Dino over `image`/`rgb_image`, Dino over `mask`/`rgb_image_mask`, and
   **`PointPatchEmbed` (embed_dim 512, input_size 256, patch_size 8) over
   `pointmap` (cropped) and `rgb_pointmap` (full)**. All tokens are projected
   to a common width, given a learned positional index per modality, and
   concatenated.
3. Those concatenated tokens are the conditioning for a single MM-DiT whose
   `latent_mapping` emits `shape` (8 channels at 16³, decoded to the sparse
   structure) **alongside** `6drotation_normalized`, `translation`, `scale` and
   `translation_scale`. One conditioning stream, one backbone, both outputs.

So the pointmap is not a post-hoc layout correction bolted onto an
image-conditioned shape model. It is a first-class conditioning modality on the
stage-1 generator that decides the object's coarse 3D occupancy.

Two supporting details point the same way. `ss_generator.yaml` trains with
`dropout_prob: 0.1` and `drop_modalities_weight: [[[pointmap, rgb_pointmap],
1.0]]` — a dedicated classifier-free-guidance channel for the pointmap — and
`PointmapCFG.inner_forward` runs a third forward pass with
`force_drop_modalities = ['pointmap', 'rgb_pointmap']` specifically to guide
*away* from the pointmap-free prediction. A modality nothing depends on does not
get its own guidance term.

**Check 4 — was the released checkpoint trained with it? YES.**
`init_ss_condition_embedder` instantiates the fuser (PointPatchEmbed included)
and loads it from `ss_generator.ckpt` through `load_model_from_checkpoint(...,
strict=True)`, which is `model.load_state_dict(state_dict, strict=True)`.
Missing or unexpected keys raise. Every reconstruction this project has run
loaded that model without error, so the released checkpoint carries trained
`PointPatchEmbed` weights. The training-time modality dropout above says the
same thing from the config side.

## What we chose

Record the answer and the input contract; do not change
`services/perception-obj/models/sam3d.py` yet. The one-object bench proof needs
a GPU, and the only GPU here is behind a deploy.

**The stage-2 boundary, which matters for reading the result.** `run()` calls
`preprocess_image(image, self.ss_preprocessor, pointmap=pointmap)` for stage 1
but `preprocess_image(image, self.slat_preprocessor)` — no pointmap — for
stage 2, and `slat_preprocessor` has no pointmap transform at all. So the
pointmap shapes the sparse structure and the pose, and appearance is decided
from the image alone.

**What the shape branch actually sees.** The pointmap is normalised
scale-shift-invariantly before the embedder (`ObjectCentricSSI`, shift = median
of the masked points, scale = the scene scale), so absolute metres are
*removed* on the way in. The metric content is not wasted — the same scale and
shift are handed to the `ScaleShiftInvariant` pose decoder, which is how the
predicted translation and scale become metric. So:

- **layout** consumes the pointmap's absolute scale, and
- **shape** consumes its *relative* geometry — the depth relief across the
  object, which is exactly what a monocular estimate gets wrong when it
  flattens a deep object into a slab.

Truncation is a relative-geometry failure, so it is on the near side of that
boundary, not the far side.

**The input contract, measured rather than inferred:**

- **Shape** `(H, W, 3)` float32, one XYZ per pixel, a torch tensor. A supplied
  pointmap is nearest-resampled to the RGB frame's size by `compute_pointmap`,
  so it may be given at the LiDAR's own resolution.
- **Frame** the pytorch3d camera convention: +X **left**, +Y up, +Z **forward**.
  A supplied pointmap is used verbatim — the `camera_to_pytorch3d_camera`
  rotation is applied only on the monocular branch. That rotation is
  `diag(-1, -1, 1)` acting on row vectors (computed from the pytorch3d installed
  in the image, not from memory), i.e. an OpenCV-style camera map with X and Y
  negated. From our own frame: `p_sam3d = (-X, +Y, -Z)` of an ARKit camera-local
  point — which is decision 0065's `_SAM3D_CAM_TO_ARKIT_CAM = diag(-1, 1, -1)`
  read in the other direction, so two independent derivations agree.
- **Units** metres, and genuinely metric: the scale is read off the pointmap and
  becomes the object's metric size.
- **Extent** the **whole frame**, not the object. 0179 said "clipped to the
  object by the alpha mask"; that is wrong. The pipeline crops around the mask
  itself for the `pointmap` token stream and keeps an uncropped copy for the
  `rgb_pointmap` stream, and the normaliser needs unmasked pixels to compute the
  scene scale.
- **Holes** `NaN`. `PointPatchEmbed` computes `valid_mask = xyz.isfinite()
  .all(dim=-1)` and substitutes a learned `invalid_xyz_token` for every invalid
  point; `pad_to_square_centered` pads the pointmap with NaN for the same
  reason. NaN is the sanctioned "no measurement here" value, which is what
  low-confidence and dropped LiDAR pixels need.
- **Resampling** every resize in the chain is nearest — ours to RGB size, the
  518 preprocessor resize, and `PointPatchEmbed.resize_input` down to 256. So
  supplying at the native 256×192 and letting the pipeline upsample is
  bit-identical to upsampling ourselves, and nothing along the path invents a
  depth between two surfaces.

## Why

Because the difference between the two readings is the difference between a
layout tweak and an attack on the defect this project has ground on longest.

Under the layout-only reading, feeding LiDAR could fix translation and scale and
would leave the reconstruction's geometry alone. Under what the code actually
does, the measured depth is one of three token streams conditioning the
generator that decides the object's coarse occupancy — so the model's answer to
"how deep is this cupboard" is conditioned on a guess where a measurement was
available. 0080's class-6 truncation, the desks with no legs, the spike cupboard
3.4× short: every one of those was produced by a shape branch reading a
monocular estimate of a frame whose LiDAR we captured, uploaded, stored, and
used for everything except this.

That does not prove the measured pointmap fixes them. It establishes that the
question is well posed and cheap, which the layout-only reading would have
denied.

**Consequence for lane D.** Lane D is scoped to union incomplete
reconstructions after the fact. Its premise — that the incompleteness is fixed
by the time we see it — is now known to rest on an input we chose to guess.
Lane D is not refuted; unioning two views may still be the only route to a
complete object. But the cheaper attack is upstream of it and should be measured
first.

**A reproducibility defect found on the way, unrelated to the outcome.** The
Dockerfile does `git clone --depth 1` with no pin, so the image carries whatever
upstream `main` was on build day. The BuildKit layer cache (0120) makes this
sharper, not softer: the clone layer in the image tagged `20260813-222442` was
created **2026-08-09T21:06:40** and is reused verbatim by every build whose
earlier layers are unchanged. So the SAM 3D source in the image is neither
pinned nor dated by the tag, two builds of one Dockerfile can carry different
model code, and a cache eviction would silently change it. Pin the clone to
`f91db411c50efee93d8db7aeb323885650f6f722` — the commit measured above — so the
pin records what has in fact been running.

## What would change this decision

Checks 1–4 are properties of one image. A `git clone` at a different upstream
commit can change all four at once, which is the reason for the pin above. If
the clone is ever re-pinned, re-read `ss_generator.yaml`'s `embedder_list` — it
is the single line that decides shape-vs-layout, and nothing else in the chain
announces a change.

If the one-object bench proof shows a measured pointmap changing layout but not
shape, that does not overturn this note — the path is there and trained either
way — but it would mean the shape branch weights the pointmap tokens weakly, and
lane D's premise would be restored.
