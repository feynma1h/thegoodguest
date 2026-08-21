# 0211 — the flag was never in the image

**Date:** 2026-08-21
**Status:** Decided

## Context

Three perception flags shipped built-and-off and none had run on a GPU:
mask refinement (0201), arm selection (0204), the object-aware residue
(0202). CLAUDE.md describes them as "BUILT and OFF, each behind one env
var", and the natural reading of that sentence — the one this lane took —
is that setting the env var on a revision turns the pass on.

It does not, and it failed twice, for two different reasons, and the second
one is the durable defect.

## What we tried

**First: a 0%-traffic candidate off the serving image's own digest**
(`sha256:faa005c8…`), env-only, `PERCEPTION_MASK_REFINE=1`. rp7 was made
refine-cold per 0210 and driven twice, reaching the flagged view — rp7 f114's
desk, 0.403 unclaimed against a 0.30 gate, the sharpest registered prediction
this project has — on the second drive.

**Nothing happened.** The desk came back `0.983 × 0.212 × 0.718`, the same
21 cm slab at the same 695,328 Gaussians, no `.mask.npz` sidecar, and **no
`mask_refine` log line**. Every innocent explanation was measured and
eliminated: the live segmentation was `array_equal` to the cached one and the
detector re-run on it read **0.4030, flagged=True**; frame 114 carries depth
and no suppressed person; a sweep over `room=None`, `depth_confidence=None`
and all six boxes flags in every case that matters; the env var was set on the
revision the logs confirm served both drives.

The answer was in the build. The source snapshot a build was made from is
readable (`gcloud builds describe` → `gcloud storage cp` → `tar tzf`), and
`services/perception-obj/mask_refine.py` **is not in it**. All three flag
names appear zero times across that image's `process_receiver.py`,
`census_sampling.py` and `box_placement.py`. The image predated all three
merges — arm selection by thirteen hours.

**Second: a real build**, `deploy_perception.sh obj --candidate` from a branch
carrying all three. The source tarball now has `mask_refine.py` and all three
flag names. The candidate 500s on `/process`:

    ModuleNotFoundError: No module named 'mask_refine'

## What we chose

Add the missing line, and a test over the manifest.

`services/perception-obj/Dockerfile` copies modules **one COPY line at a
time** — 25 lines for 25 modules — rather than copying the directory.
`mask_refine.py` was added to the service without its line, so no build of any
commit could ever have contained it. The merge dates explained the first
image; this explains every image.

The severity is worse than a missing feature, and this is the part worth
carrying: `process_receiver` imports `mask_refine` **unconditionally** at the
top of `_reconstruct_one_object`, not inside the flag check. So an image built
from that tree raised on **every object of every scene with the flag off**.
`main` was undeployable and nothing said so.

`tests/test_dockerfile_manifest.py` now checks the manifest in both
directions, plus a by-name pin on `mask_refine.py`.

## Why the failure was invisible for so long

Three separate layers each hid it, and they compose:

1. **Every local signal is green.** The module is in the repo, in the build
   context, and in the build's own source tarball. 948 tests pass. Every
   offline probe imports it directly from the working tree. Nothing local
   reads the Dockerfile.
2. **The flag's silence is by design.** `_mask_refiner_for` logs only *after*
   the model call. Its three early exits — pass disabled, not a box view, no
   depth — and the detector's two are all quiet, because a pass that is off
   should be invisible. So enabled-and-undeployed, enabled-and-correctly-
   declining, and enabled-and-working-on-a-cache-hit produce **the same
   observable: nothing**.
3. **The costs are paid before the failure.** The first image failed silently
   at the end of a full 900 s GPU request. The second failed loudly, but only
   after a cold start and a 131 s model load.

What separated them was neither a log nor a test but the build artifact
itself. **The check costs one command and no GPU, and belongs before the first
GPU-second of any flag that has never run:**

    gcloud builds describe <id> --region=asia-southeast1 \
        --format='value(source.storageSource.bucket,source.storageSource.object)'
    gcloud storage cp gs://<bucket>/<object> . && tar tzf <object> | grep <module>

## Why candidate mode earned its keep

Decision 0142 asks for candidate → smoke → flip on perception-obj because "a
revision that fails at run time burns a full 900 s GPU request before anyone
finds out". This is that case, one deploy short of production: a direct
`deploy_perception.sh obj` would have moved 100% of traffic onto a revision
where every scene 500s, and — per 0190 — moved the `serving` tag with it.

CLAUDE.md's "BUILT and OFF, each behind one env var, each with a
byte-identical degrade proven against all four preserved captures" is true of
the repository and false of production, and the sentence gives no hint which
it describes. That gap is what this note exists to close.

## What would change this decision

- **Copying the directory instead of enumerating it.** The per-file COPY list
  exists for layer-cache granularity — a change to one module invalidates only
  the layers below its line. `COPY services/perception-obj/*.py` would make
  this class of bug impossible and cost one rebuilt layer per source change.
  Given 0199 measured source-change builds at 8-10 minutes either way, that
  trade now looks worth re-taking; the test is the cheaper half and is what
  shipped here.
- **A log line on the enabled-but-declined path.** One `logger.info` where the
  refiner declines would have cut this diagnosis from hours to a minute.
  Deliberately not added by this lane: its scope is evidence, not the code
  under test, and the Dockerfile line was a release blocker where this is an
  ergonomic one.
- **`/ready` reporting which optional passes the image contains.** It already
  reports per-model state. That would turn "is the flag deployed?" into a GET,
  and is the only one of these three that helps an operator rather than a
  developer.
