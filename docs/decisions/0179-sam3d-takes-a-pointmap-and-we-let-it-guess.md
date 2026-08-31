# 0179 — SAM 3D takes a LiDAR pointmap, and we let it guess one instead

**Date:** 2026-08-14
**Status:** Superseded by 0180 and 0181 — read those first. Kept as where the parameter was found.

This note recorded the discovery from upstream source and left the decisive
question open. Both halves were then settled inside the serving image: **0180**
measured that the pointmap conditions SHAPE, not layout alone, refuting the
reading this note hedged; **0181** measured that feeding it real LiDAR barely
changes the reconstruction, so it is not the fix for class-6 truncation. Kept
because it is where the parameter was found and because 0180 cites it.

## Context

Two questions had a settled answer in this project: SAM 3D reconstructs from a
single RGB image, and neither model receives any ARKit or RoomPlan data.
`models/sam3d.py` passes `(rgba, mask, seed)` and its docstring records why —
"positional args to match Meta's demo/README, which is the only documented call
signature."

That reasoning was sound and the conclusion drawn from it was wrong.

## What we tried

Read the upstream source rather than the documentation.

`notebook/inference.py` on `facebookresearch/sam-3d-objects@main`:

```python
def __call__(self, image, mask, seed=None, pointmap=None) -> dict:
```

There is a **fourth parameter**. It appears in neither the README, the demo,
nor the published API reference — which is exactly why matching the documented
call missed it. It is forwarded unmodified into `InferencePipelinePointMap.run()`,
a pipeline class named for it.

Meta's own description: SAM 3D "can also accept an optional scene point map
obtained via hardware sensors **such as LiDAR** or monocular depth estimation,
which helps in estimating **layout** more accurately."

Traced through `sam3d_objects/pipeline/inference_pipeline_pointmap.py`:

- **Format** — `(H, W, 3)` per-pixel XYZ, float32, **metres**, camera frame
  (converted internally to the pytorch3d convention), clipped to the object by
  the alpha mask.
- **Intrinsics** — `infer_intrinsics_from_pointmap` derives them from the
  pointmap rather than taking them as input.
- **What it conditions** — layout pose and scale for certain, through an
  explicit optimisation step. **Whether it ALSO conditions shape is UNRESOLVED**
  and an earlier draft of this note wrongly called it settled. The pipeline puts
  the normalised pointmap tensors into `ss_input_dict`, and
  `sample_sparse_structure` maps only `["image"]` explicitly — but
  `get_condition_input` builds `condition_kwargs` as *every key not in the
  mapping* and passes it into the condition embedder, so the pointmap reaches
  the embedder as kwargs. Whether the embedder consumes them or swallows them
  in `**kwargs` decides the question and was not read.

And the finding that matters most: **when `pointmap` is None the pipeline
computes one itself**, `output = self.depth_model(loaded_image)` — a monocular
depth model run on the single RGB frame.

## What we chose

Nothing yet; this note exists so the next session starts from measurement.

But the framing changes. This is not an unused capability we could adopt. The
pipeline uses a pointmap on **every reconstruction we have ever run**. Ours is
**estimated from one photograph by a monocular depth model, on a capture that
carries measured LiDAR depth for that exact frame.**

## Why it matters, stated at its true scope

Its effect on truncation is **unknown, not excluded** — see above. If the
condition embedder consumes the pointmap kwargs, a metric pointmap would tell
the model how deep an object actually is, which is the axis our cupboard is
3.4x short on. That would make this the most direct attack on class-6 anyone
has proposed. If the embedder ignores them, lane D's premise is unaffected.
**The probe must test both**, and must not assume the layout-only reading.

It attacks **layout** — which is the other half of everything this project has
spent months on:

- 0065 fixed the layout convention by brute force over 576 variants, and its
  first answer was a duality twin that rendered objects face-down.
- 0080 measured a shipped layout rotation ~90° wrong in yaw on the spike bed.
- 0081 measured the layout's up sign wrong 1 in 6, which is why only its axis
  line is trusted.
- 0104 and 0156 refuted three more instrument families on the 180° sign.
- Lane E (0170/0171) found the layout sign does carry the answer, ships it
  flag-only, and gets one of three wrong.

Every one of those measured a layout produced from **guessed** depth. Whether
they were measuring the model's limit or the guess's limit has never been
separated, and that is a cheap thing to find out.

`placement_math` already does depth backprojection, and `placement.observation_world_cloud`
already builds metric per-observation clouds. The input this wants is close to
something we compute today.

## What would change this decision

Three things are unverified and all are checkable inside the image without a
GPU inference run:

1. **Whether our build even has the parameter.** The Dockerfile does
   `git clone --depth 1` with **no pin**, so the image carries whatever
   upstream `main` was on build day and two builds of the same Dockerfile can
   differ. That is a reproducibility hazard in its own right and worth pinning
   regardless of this note.
2. **Whether `checkpoints/hf/pipeline.yaml` instantiates
   `InferencePipelinePointMap`** or a pipeline without the pointmap path.
   `Inference.__init__` selects from that config.
3. **Whether the released checkpoint was trained with pointmap conditioning**,
   or whether the path exists for a variant we do not have.
4. **Whether `ss_condition_embedder` consumes the pointmap kwargs.** This is
   the one that decides whether the pointmap touches shape or only layout, and
   it is answerable by reading the embedder class named in `pipeline.yaml`.

If any of the three is negative this closes cheaply and the answer is recorded.
If all three are positive, the experiment is one re-drive of a preserved LiDAR
capture with a real pointmap, compared against the shipped layout on rooms
whose failures are already adjudicated.
