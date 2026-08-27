# Vendored upstream — the SAM entry points we reason about

**Read this before asserting anything about how SAM 3 or SAM 3D behaves.**

These are verbatim copies of Meta's source at the commits the Dockerfile pins.
They exist because the running source lives inside the container image at
`/opt/sam3-repo` and `/opt/sam3d`, so no session working in this repo could
read it — and several sessions have reasoned about model behaviour from our own
wrapper plus priors, and been wrong.

Nothing here is imported or executed. It is documentation that happens to be
the actual code.

## What is here, and why each file

| file | upstream path | why we need to read it |
|---|---|---|
| `sam3/sam3_image_processor.py` | `sam3/model/sam3_image_processor.py` | everything `models/sam3.py` calls: `set_image`, `set_text_prompt`, `add_geometric_prompt`. The score, the threshold, the returned keys. |
| `sam3/model_builder.py` | `sam3/model_builder.py` | `build_sam3_image_model`, which is how we construct the model. |
| `sam3/sam3_image.py` | `sam3/model/sam3_image.py` | the model object itself, and `predict_inst` — the POINT-prompted path we do not use. |
| `sam3/sam1_task_predictor.py` | `sam3/model/sam1_task_predictor.py` | what `predict_inst` delegates to. |
| `sam3d/inference.py` | `notebook/inference.py` | the `Inference` class `models/sam3d.py` calls. SAM 3D does not expose it in the installable package. |
| `*/LICENSE` | `LICENSE` | Meta's SAM License. §1.b.i requires the Agreement to travel with any copy of the materials, which is why it is here rather than referenced. |

## The pins

| | repository | commit | dated |
|---|---|---|---|
| SAM 3 | `facebookresearch/sam3` | `8f0b7f4d4e7eda2ed606ebde6702c93359ad01da` | 2026-08-14 |
| SAM 3D Objects | `facebookresearch/sam-3d-objects` | `f91db411c50efee93d8db7aeb323885650f6f722` | 2026-06-02 |

**These are the commits the SERVING image was built from**, not upstream's
current HEAD, and that is deliberate: the pin was introduced to make future
builds reproducible, not to move the model. `perception-obj-00074-var` was
built 2026-08-24; `8f0b7f4d` was `sam3`'s HEAD then. Upstream has moved three
commits since, all "Fix B001: Replace bare except with except Exception" — lint
only. `sam-3d-objects` has not moved since June.

**Before the pin, both clones were `--depth 1` with no commit**, so every
rebuild silently took whatever was on `main`. Two builds of identical source
could ship different model code, and nothing recorded which.

`tests/test_upstream_pins.py` asserts these SHAs match the Dockerfile. If you
change one, change both — that test is the only thing keeping this file from
becoming a plausible lie.

## What reading it settled, so nobody re-derives it

Every line below was checked against `sam3/sam3_image_processor.py` here. None
of it is in upstream's README, which documents none of this — the source and
the twelve notebooks in `examples/` are the only authority.

- **`scores` is a detection confidence, not a mask-quality score.** It is
  `out_logits.sigmoid() * presence_logit_dec.sigmoid()` — a per-query match
  probability times a per-image presence probability for the prompted concept.
  Both factors ask "is this a `desk`". Neither asks "is this outline complete".
- **Comparing two instances of ONE concept in ONE image, the presence factor is
  common and cancels**, so the ratio is purely the per-query match logit.
- **`confidence_threshold` defaults to 0.5** and everything below it is dropped
  before we see it (`keep = out_probs > self.confidence_threshold`). That is why
  no observed score is below ~0.504. It is a constructor argument and there is a
  `set_confidence_threshold` setter; we set neither. Upstream's interactive
  notebook exposes it as a live slider, so they treat it as tuneable.
- **No NMS and no deduplication anywhere in this path.** Several instances of one
  object are expected output, and reconciling them is the caller's job. There is
  no "one segment per object" switch.
- **`set_text_prompt` returns no mask-quality score.** Its state is
  `masks_logits`, `masks`, `boxes`, `scores` and size metadata, and `scores` is
  the detection confidence above. **This does NOT generalise to SAM 3** — see
  the next entry, which corrects an earlier reading of this file that did
  generalise it.
- **SAM 3 is two components sharing one backbone, and we use one of them.** The
  paper's own framing: "an image-level detector and a memory-based video tracker
  that share a single backbone". The detector answers Promptable CONCEPT
  Segmentation — text in, every matching instance out — and is what
  `Sam3Processor.set_text_prompt` wraps. The tracker answers Promptable VISUAL
  Segmentation — points, boxes or masks in, ONE instance out — and is SAM 2's
  task, updated.
- **The visual path takes POINTS, and it is on the model we already build.**
  `model.predict_inst(inference_state, point_coords=..., point_labels=...,
  multimask_output=True)` returns `(masks, scores, logits)`, where `scores` IS a
  mask-quality estimate and `multimask_output` returns three ranked candidates.
  It takes the same `inference_state` `set_image` already produces, so nothing
  new has to be loaded. `examples/sam3_for_sam1_task_example.ipynb` is the
  worked example. `models/sam3.py` has never called it.
- **`masks_logits` is misnamed and we throw it away.** It is post-`sigmoid()`,
  so it is a per-pixel PROBABILITY in [0, 1] at full image resolution, not a
  logit — anyone reading the name would assume otherwise. The binary mask is
  literally `masks_logits > 0.5`, and that 0.5 is a bare constant with no
  parameter behind it (unlike `confidence_threshold`, which is settable). It is
  the one dense, per-pixel, DEPTH-FREE signal the model emits.

  **What it is NOT, measured: a place where missing parts hide.** This file
  once said a leg scored 0.45 would be deleted with no record. 0268 read the map
  for the study table's three frames and swept the cut: lowering it to 0.1 grows
  the mask by at most 18%, and 83-96% of what cut 0.40 adds lies within TWO
  PIXELS of the existing boundary. It is a skirt, not a part. The model is not
  uncertain about that leg — it does not see it as desk at any threshold.
- **Geometric prompts carry a `label`, so NEGATIVE boxes are supported**
  (`{"box": [...], "label": True/False}` in `examples/sam3_image_interactive.ipynb`).
  `models/sam3.refine_with_box` only ever sends positive ones.
- **A box prompt rides ON TOP of the text prompt, so "this box, and it is a
  `table`" is one call.** `add_geometric_prompt` appends to the state's
  geometric prompt and re-runs grounding; it only substitutes the dummy text
  `"visual"` when no text prompt was set. So the answer stays "the `table` in
  this picture", not a fresh box-driven instance. This is exactly what
  `refine_with_box` does today — and passing the RoomPlan box's own projected
  bbox as that prompt is MEASURED to fail: 0198 recorded 113,465 px on rp7 f114
  with a chair base and a stool absorbed, which is why
  `mask_refine.prompt_box_cxcywh` deliberately does not use it.
- **SAM 3.1 exists, is on the same `main`, and needs DIFFERENT checkpoints.** We
  download `facebook/sam3` weights. An unpinned clone could therefore pair 3.1
  code with 3.0 weights; the pin is what prevents that.

## Refreshing a pin

Deliberate act, never a drive-by:

1. Move the SHA in `Dockerfile` and in the table above, together.
2. Re-fetch the vendored files at the new SHA (`curl` the raw URLs).
3. Re-read the diff on `sam3_image_processor.py` and update the section above if
   any of it changed.
4. Note the cost: editing the SAM 3D clone line invalidates the layer cache from
   near the top of the Dockerfile — the ~50-60 minute build, not the 8-10 minute
   one. Absorb it on a build that is happening anyway.
