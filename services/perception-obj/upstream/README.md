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
- **No mask-quality or IoU head.** The returned state is `masks_logits`, `masks`,
  `boxes`, `scores` and size metadata — nothing analogous to SAM 1/2's
  `iou_predictions`. `masks_logits` is the only boundary-confidence signal that
  exists, and we discard it.
- **Geometric prompts carry a `label`, so NEGATIVE boxes are supported**
  (`{"box": [...], "label": True/False}` in `examples/sam3_image_interactive.ipynb`).
  `models/sam3.refine_with_box` only ever sends positive ones.
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
