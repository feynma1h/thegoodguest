---
name: sam3-upstream
description: Look up how SAM 3 / SAM 3.1 actually behaves — API shapes, tensor conventions, thresholds, prompt handling, instance IDs, version differences — from the vendored source and official sources rather than inferring it. Use whenever a question about SAM 3, SAM 3.1, or SAM 3D's behaviour arises, before writing code against it, and before explaining why it did something. Covers version migrations, where the vendored source describes the version being replaced and only official sources describe the new one.
---

# SAM 3 / SAM 3.1 — read it, do not infer it

This project has been wrong about SAM 3's own behaviour more than once, and
each time the answer was already written down somewhere it could have been
read. Decision 0264 is called *"read the model, not the wrapper"* for that
reason: a docstring in our own wrapper described a 256-wide mask prompt that
had been 288 upstream, and reading the wrapper instead of the model produced a
confident, wrong explanation. Another cost a lane a day on the belief that
SAM 3's visual path was unavailable, when it simply is not constructed unless
you ask for it.

**So the rule is: for any claim about what the model does, cite where you read
it.** Not what the wrapper says it does, not what seems reasonable given the
output.

## Read in this order

**1. The vendored source, which is IN THIS REPO.**

```
services/perception-obj/upstream/sam3/     model_builder.py, sam3_image.py,
                                           prompt_encoder.py,
                                           sam3_image_processor.py,
                                           sam1_task_predictor.py
services/perception-obj/upstream/sam3d/    inference.py
services/perception-obj/upstream/README.md what is pinned and why
```

`services/perception-obj/tests/test_upstream_pins.py` asserts facts about that
source. If a pin fails after a version bump, the pin is the record of what
changed — read it before changing it.

This is the highest-authority source available offline, and it is the code that
actually runs. Start here.

**2. Our own wrapper**, `services/perception-obj/models/sam3.py` and
`models/sam3d.py` — but only to learn what WE do to the model's inputs and
outputs. Never as evidence of what the model does.

**3. Official upstream, on the web.** Use `WebFetch` / `WebSearch`:

- the Meta / facebookresearch SAM 3 repository — README, model card, config
  files, and the release notes or diff between SAM 3 and SAM 3.1
- the paper or model card for the version in question
- Hugging Face model cards for the checkpoints we pin

**Prefer the primary repository over blog posts, tutorials and third-party
summaries**, which routinely describe an older release or a different variant.
When sources disagree, the vendored source in this repo wins for "what runs
here", and the official repo wins for "what the model is capable of".

## During a version migration, that order INVERTS

**The vendored source is the version you are moving FROM.** While the repo
carries 3.0 and the work is 3.1, `upstream/sam3/` cannot answer a single
question about 3.1 — and it will answer confidently and wrongly, because the
class and function names are the same. Reading it and reasoning about the new
version from it is the precise mistake this skill exists to prevent, wearing a
disguise.

So, mid-migration:

- **What 3.1 does** → the official repo, release notes, model card, and the
  3.0→3.1 diff. There is no offline substitute and you must not invent one.
- **What we run today** → the vendored source, which is still the old version
  until the bump lands.
- **What changes for us** → the difference between those two, stated
  explicitly, per call site we depend on.

**Say which version every claim is about.** A sentence about "SAM 3" that is
silently about 3.0 while the reader is building 3.1 is worse than no sentence.
Once 3.1 is vendored, this section stops applying and the ordinary order above
resumes.

## Questions this exists to answer without guessing

- What exactly does `segment()` return, and in what tensor layout and dtype?
- Is a value a probability map, a logit, or a boolean? (0262/0263 turned on
  exactly this; the probability map was being discarded.)
- What resolution does the model run at internally, and what does it do to an
  input that is not that size?
- How are text prompts tokenised, and does a multi-word term behave as one
  concept or several?
- Which prompt modes exist — text, points, boxes, masks — and which are built
  by default versus only when requested?
- **For 3.1 specifically:** what is new relative to 3.0, what changed in the
  output contract, and are instance IDs stable across frames — and if so, under
  what conditions and with what failure modes?

## Before writing code against it

State, in one line each: what you read, where, and what it says. If a question
cannot be answered from the vendored source or an official source, **say it is
unanswered** and propose the smallest experiment that would settle it. An
inferred explanation that sounds right is the specific failure this skill
exists to prevent.

## Before a deploy that changes the model

A version bump changes what every downstream stage receives. Check, and record
the answer where the code lives:

- the output contract — keys, shapes, dtypes, and their meaning
- whether thresholds and their defaults moved
- whether the checkpoint files, their names, or their loading path changed
- whether anything the Dockerfile copies or pins needs to move with it
- what `test_upstream_pins.py` will now assert, and whether a failing pin is a
  real regression or a stale expectation

`infra/RUNBOOK.md` carries the candidate → smoke → flip phases. A perception
build is 8-10 minutes off cache; route registration cannot be checked locally
at all, which is why the candidate exists.
