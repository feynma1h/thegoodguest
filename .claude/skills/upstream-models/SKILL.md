---
name: upstream-models
description: How to establish what SAM 3 or SAM 3D Objects actually does, before asserting it. Use whenever work touches segmentation or reconstruction behaviour — mask scores, thresholds, duplicate instances, refinement prompts, reconstruction inputs — or whenever you are about to state what a third-party model returns, means, or guarantees. Also covers pinning and refreshing the vendored upstream copies.
---

# Establishing what the models actually do

This repo has reached wrong conclusions more than once by reasoning about SAM 3
and SAM 3D from our own wrapper plus priors. The failure is always the same
shape: a plausible statement about model behaviour, never checked, propagated
into a decision note.

## The rule

**Do not assert what a third-party model returns, means, guarantees or
thresholds without citing a line of its source.** "Detection scores usually
mean X" is not a citation. If you cannot cite it, say you have not checked —
that sentence is cheap and a wrong premise is not.

## Where the source is

The running source lives inside the container image and is unreadable from a
worktree. A pinned, verbatim copy of the entry points our wrappers call is at:

    services/perception-obj/upstream/README.md      <- read this first
    services/perception-obj/upstream/sam3/          <- image processor, model builder
    services/perception-obj/upstream/sam3d/         <- the Inference class

`upstream/README.md` carries the pins and a section of settled facts — the score
formula, the 0.5 confidence threshold, the absence of NMS and of any IoU head,
the availability of negative geometric prompts. Read that before re-deriving
any of it, and add to it when you settle something new.

## When the answer is not in the vendored files

In order:

1. **The rest of the pinned repository.** Fetch the file at the pinned SHA
   rather than from `main`, or the answer may not describe what we run:
   `https://raw.githubusercontent.com/facebookresearch/sam3/<pinned-sha>/<path>`
2. **`examples/` in the SAM 3 repo — twelve notebooks, and they are the real
   documentation.** The README documents almost none of this: not the score's
   meaning, not the threshold, not what to do with duplicate instances. The
   notebooks are where the authors show intended usage. `sam3_image_interactive.ipynb`
   is the one for refinement prompts; `sam3_image_predictor_example.ipynb` for the
   basic flow.
3. **The paper**, for what a head is conceptually — but the source is what runs.

If you had to go outside the vendored copy to answer something, **vendor the
file you read** or record the answer in `upstream/README.md`. The next session
should not repeat the fetch.

## Reading traps that have already cost time

- **Our own comments have been wrong about where the source is.** `models/sam3.py`
  named `/opt/sam3` until 2026-08-28; the image has never contained that
  directory. Trust the Dockerfile over a comment, and fix the comment.
- **`main` is not what we run.** Both clones are pinned. Upstream moving does not
  move us, and reading `main` to answer a question about production is a
  category error.
- **SAM 3.1 shares `main` with SAM 3 and needs different checkpoints.** Any claim
  about model behaviour has to say which.
- **Absence of documentation is a finding, not a dead end.** If upstream does not
  specify something, that means the behaviour is ours to define and ours to
  measure — say so explicitly rather than inventing an upstream intent.

## Changing a pin

Deliberate, never incidental. `tests/test_upstream_pins.py` enforces that the
Dockerfile, `upstream/README.md` and the vendored files agree; it will fail if
you move one and not the others. The procedure is in `upstream/README.md`.

Cost to know before proposing it: editing the SAM 3D clone line invalidates the
Docker layer cache from near the top of the file — the ~50-60 minute build, not
the 8-10 minute one. Absorb it on a build that is happening anyway.
