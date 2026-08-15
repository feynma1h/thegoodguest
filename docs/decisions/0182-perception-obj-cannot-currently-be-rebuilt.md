# 0182 — perception-obj cannot currently be rebuilt

**Date:** 2026-08-16
**Status:** Measured; the blocking cause is fixed by one line nobody has changed yet

## Context

The bench proof for decisions 0180/0181 needs a candidate image, so this
session ran `./infra/deploy_perception.sh obj --candidate` — the repo's own
deploy path, unmodified, on a branch whose only perception change is an
env-gated keyword argument.

The build did not finish. It was cancelled at ~72 minutes of its 90-minute
timeout, still on step **8 of 49**, with two multi-gigabyte download steps and
roughly forty steps ahead of it. Nothing was deployed and traffic never moved.

## What we tried

**The layer cache missed.** Decision 0120 added `--cache-from :buildcache` and
0163 measured a source-only build at 10 m 23 s against a 58 m 39 s uncached
baseline. Here the cache manifest imported (`#4 importing cache manifest from
…:buildcache`) and the build then executed `[ 4/49] RUN git clone`,
`[ 5/49] RUN mamba env create` and `[ 8/49] RUN pip install -e '.[dev]'` for
real — an essentially cold rebuild. **Why it missed was not determined.**

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

## What we chose

Cancel rather than let it time out — the diagnosis was already complete from
DNS and the log, and the remaining twenty minutes would have produced no
artefact — and record this rather than fix it in passing.

Not fixed here for two reasons. The change alters the build environment for
production, which is exactly what this session's charter reserves. And the fix
deserves a deliberate choice between dropping the dead host and pointing at
`pypi.nvidia.com`, which is a decision about whether any package is expected to
come from NVIDIA's index at all — pip already resolved every dependency it
reached from PyPI proper.

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

The measured cost is concrete: **58 m 39 s uncached before, and now longer than
the 90-minute timeout allows.**

## What would change this decision

Replace or drop the dead index and the build should return to roughly its
58-minute uncached shape, which fits. That is worth doing whether or not the
pointmap bench is ever run.

The cache miss itself is still unexplained and worth one look, because a
10-minute build and a 58-minute build are different working conditions. The
inline-cache mode is the first place to look: `infra/cloudbuild/perception-obj.yaml`
already notes that `BUILDKIT_INLINE_CACHE=1` exports only final-stage layers
and that `buildx --cache-to type=registry,mode=max` is the alternative.
