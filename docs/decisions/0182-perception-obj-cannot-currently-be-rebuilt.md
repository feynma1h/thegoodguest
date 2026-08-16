# 0182 — perception-obj cannot currently be rebuilt

**Date:** 2026-08-16
**Status:** Measured; the blocking cause is fixed by one line nobody has changed yet

## Context

The bench proof for decisions 0180/0181 needs a candidate image, so this
session ran `./infra/deploy_perception.sh obj --candidate` — the repo's own
deploy path, unmodified, on a branch whose only perception change is an
env-gated keyword argument.

The build did not finish. It was cancelled after **30 m 30 s**, still on step
**8 of 49** — `pip install -e '.[dev]'` — with two multi-gigabyte download
steps and forty more steps ahead of it. Nothing was deployed and traffic never
moved.

## What we tried

**The layer cache missed broadly, not just late.** Decision 0120 added
`--cache-from :buildcache` and 0163 measured a source-only build at 10 m 23 s
against a 58 m 39 s uncached baseline. Here the cache manifest imported and the
build then executed `apt-get install`, `git clone` and `mamba env create` for
real — the second build, with the fix, did the same and its step timings are
explicit (`#6 DONE 22.9s` on apt, `mamba env create` running). These are cold
rebuilds.

**Why it missed was not determined**, and it is worth one look. The first place
is the inline cache: `infra/cloudbuild/perception-obj.yaml` already notes that
`BUILDKIT_INLINE_CACHE=1` exports only final-stage layers, and inline cache does
not re-export entries a build itself imported — so a layer that was a cache hit
on 2026-08-13 can be absent from the cache that build published, and the effect
compounds backwards over successive cache-riding builds.

**A trap for whoever picks this up:** in BuildKit's plain progress output the
number after a step id is **seconds since the build started**, not seconds into
that step. Reading `#13 1538.0` as "step 13 has run for 1538 s" produces a
confident and wrong conclusion about which layers cached — it did here, and the
timestamps caught it.

**The obvious suspect is refuted, and is recorded so nobody re-runs it.** The
base image `condaforge/mambaforge:24.7.1-0` is a mutable tag, so a re-push
would invalidate every layer. It has not moved: the base image's
`rootfs.diff_ids[0]` is `sha256:3ec3ded77c0ce89e…`, byte-identical to the
serving image's. A first comparison appeared to show a difference and was
wrong — it compared *compressed* layer digests across two registries, and
Artifact Registry re-compresses on push. Compare `diff_ids`, which are
uncompressed and registry-independent.

**What the cold rebuild then hit is the real finding.** The Dockerfile carries
Meta's setup line verbatim:

```
ENV PIP_EXTRA_INDEX_URL="https://pypi.ngc.nvidia.com https://download.pytorch.org/whl/cu121"
```

**`pypi.ngc.nvidia.com` no longer resolves.** Direct check: `NXDOMAIN`.
NVIDIA's live index is `pypi.nvidia.com`, which resolves;
`download.pytorch.org` also resolves. Because an extra index is tried for
**every** package, pip pays five DNS retries with backoff on every single
dependency: the build log carries **764 retry warnings** and step 8 was at
1538 s and still resolving dependencies when the build was cancelled.

Whether that build would have exceeded its 90-minute timeout was **not
measured** — it was cancelled at 30 minutes, once the cause was established
from DNS and the log, because the remaining time would have produced no
artefact either way. What is measured is the retry toll itself, and that a
cold build already costs 58 minutes without it.

## What we chose

Drop the dead host from `PIP_EXTRA_INDEX_URL`, keeping
`download.pytorch.org/whl/cu121`.

Dropped rather than repointed at `pypi.nvidia.com`, deliberately. The host has
been dead for some time, so recent builds already resolved everything from PyPI
proper — the log shows each retry storm ending in a successful `Downloading …`
from PyPI, including the `nvidia-cuda-nvcc-cu12` and `nvidia-pyindex` pins that
would most plausibly have come from NVIDIA. Removing a dead index leaves the
resolver's effective source set unchanged. Adding a live index that has not
been contributing could quietly change which wheels are selected, which is a
larger change wearing the costume of a smaller one.

## Why it matters more than the probe that found it

**The serving image is fine; the ability to produce a new one is not.** Every
perception deploy since 0120 has been riding the layer cache, and the cache is
what has been hiding this. The moment a build misses — a changed early layer,
an evicted cache tag, a new machine — perception-obj becomes unbuildable inside
its timeout. That blocks any perception change, and it equally blocks a
*rollback* that needs a rebuild.

It is also the third unpinned upstream reference in one Dockerfile, and the
second one already broken. 0180 recorded the first: `git clone --depth 1` of
SAM 3D with no pin, so the model code in an image is dated by neither its tag
nor its deploy. The base image tag is the third; it has not moved yet, but
nothing stops it. A build that reaches outside itself in three places, with a
cache as the only thing keeping it reproducible, is one eviction away from
being a different build.

## What would change this decision

The fix is landed and the same build was re-run to confirm it; the outcome is
in the Outcome section below. If a future build slows down the same way, check
`PIP_EXTRA_INDEX_URL` first — a dead entry there is silent, costs a fixed toll
per package, and shows up only as an inexplicably long resolve.

The step-8 cache miss is still unexplained and worth one look, because a
10-minute build and a 58-minute build are different working conditions.

## Outcome

**The same build, with the dead index removed, succeeded in 62 m 48 s and
zero retries** (against 764 in the run before it, and a step 8 that never
finished). It deployed a candidate at 0% traffic, which then ran the bench in
0181. The 90-minute timeout was never in danger.

Two things measured on that build, both worth carrying:

- **`git clone --depth 1` re-ran** — its layer is stamped with this build's own
  time, not a cached one — and landed on **the same commit
  `f91db411c50efee93d8db7aeb323885650f6f722`** as the serving image. Upstream
  main has not moved since 2026-06-02, so the unpinned clone happened to be
  harmless this time. That is luck, not a property, and it is exactly the pin
  0180 asks for.
- **The cache still missed** with the index fixed (`#6 DONE 22.9s` on apt,
  `mamba env create` running), so 58–63 minutes is the real cost of a
  perception build today. The 10-minute number in 0163 is not what to plan
  around until the cache is understood.
