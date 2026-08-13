# 0120 — perception-obj builds cache layers via BuildKit inline cache on a stable tag

**Date:** 2026-08-10
**Status:** Decided; speedup measured 2026-08-13 (see Outcome)

## Context

Every perception-obj Cloud Build was a full ~40-minute rebuild, even for a
last-layer change: the 0109 session paid two full rebuilds to fix a Dockerfile
line that sits below the model bakes, and board item 8(d) named the fix.
`infra/cloudbuild/perception-obj.yaml` builds with `docker build` and pushed a
timestamped tag only, so no build could ever reference a previous build's
layers — Cloud Build workers are fresh VMs with an empty local Docker cache.

## What we tried

Three mechanisms considered, one built:

1. **The classic Cloud Build recipe** (docs-era: `docker pull previous-image
   || true`, then `--cache-from previous-image`). Rejected on a fact of this
   build: the yaml already forces `DOCKER_BUILDKIT=1` because the HF-token
   secret mount requires it, and **BuildKit does not read pulled local images
   as `--cache-from` sources** — it resolves the ref against the registry
   itself. The pull step would fetch a multi-GB image every build for zero
   cache effect.
2. **buildx with `--cache-to type=registry,mode=max`**. Exports cache for
   every stage, but needs a builder-instance setup step and a second registry
   artifact. Unnecessary here: the perception Dockerfile is **single-stage**,
   and inline cache (min mode) exports exactly the final image's layers —
   which for a single-stage build is all of them.
3. **BuildKit inline cache** — built. `--build-arg BUILDKIT_INLINE_CACHE=1`
   embeds the cache manifest into the image itself; `--cache-from` points at
   a stable `:buildcache` tag; every successful build re-tags and re-pushes
   it.

## What we chose

`infra/cloudbuild/perception-obj.yaml` builds with
`--cache-from ${_CACHE_URI} --build-arg BUILDKIT_INLINE_CACHE=1`, tags the
image as both `${_IMAGE_URI}` (timestamped, what deploys pin) and
`${_CACHE_URI}` (`…/perception-obj:buildcache`), and pushes both. `_CACHE_URI`
is a literal substitution default so a bare `gcloud builds submit --config`
still caches; the deploy script passes nothing new.

## Why

- **The stable tag is the whole trick.** Deploy tags are timestamps, so the
  next build has nothing fixed to reference; `:buildcache` always names the
  newest successful build. It shares every layer with that build's
  timestamped tag, so the registry cost is one tag record, not a second image.
- **Cache moves only on full success.** The push step runs after `docker
  build` completes, and the perception Dockerfile carries its own build-time
  smokes (import smoke, SPZ encoder armed, privacy armed) — a build that
  fails any of them never moves the tag, so the cache can never point at an
  image whose smokes failed.
- **A missing or metadata-less cache ref is non-fatal.** Observed on the
  validation build itself: BuildKit logs
  `#4 ERROR: …/perception-obj:buildcache: not found` on the cache-import
  step and the build proceeds uncached, re-seeding the tag. That ERROR line
  is the expected first-build/wiped-repo shape, not a failure — the wording
  matters because someone reading the log for a real failure will find it.
- **The first build gets zero hits BY DESIGN.** Pre-existing images carry no
  inline-cache manifest, so there was nothing to validate the speedup against
  in this session. The validation build run for this note — ID
  `5ab7cb34-7a69-494d-b686-2bbcaa7f95c3`, SUCCESS, 2026-08-09 21:05:37Z →
  22:04:16Z (**58 min 39 s**, the uncached baseline) — proved the config end
  to end: the absent-tag import ERROR was non-fatal, the Dockerfile's own
  smokes ran, and both tags pushed with ONE digest
  (`sha256:ebeab44a…` as `20260810-023434` and `:buildcache`). **The
  measured speedup comes from the NEXT real build; record it here.** The
  model bakes (SAM 3/SAM 3D snapshots, DINOv2, the conda env) sit above the
  server-code COPYs, so a code-only change should reuse every heavy layer
  and pay only COPY + smoke time.

## Outcome

The next real build was the room-quality ship (2026-08-13, build
`ca372cd8-de1e-4077-af4f-d90a947c31ea`, image `20260813-222442`): a source-only
change to `fusion.py` and `box_placement.py`, nothing above them touched.

**BUILD step 10 min 23 s, 11 min 29 s wall clock, against the 58 min 39 s
uncached baseline — 5.1×.** The prediction in the bullet above holds: every
heavy layer was reused and the build paid COPY plus smoke time.

That is the realistic case rather than a best case, because most perception
deploys change only Python; a build that touches the conda env or a model bake
still pays for the layers below it, and the two Dockerfile-level failures this
repo has had (0109's node, 0090's missing COPY) were exactly those.

## What would change this decision

- The Dockerfile grows a second stage → inline cache stops covering the
  early stages; switch to buildx `--cache-to type=registry,mode=max`.
- The registry or region moves → `_CACHE_URI`'s literal default moves with
  `_IMAGE_URI`'s construction in `deploy_perception.sh` (both are named in
  the yaml comment).
- A poisoned or stale cache suspicion (apt/model drift hidden by a cached
  layer): delete the `:buildcache` tag — the next build is a clean full
  rebuild that re-seeds. BuildKit keys layers on Dockerfile content and
  context checksums, so ADD/COPY changes bust naturally; only
  network-fetching RUN steps (apt, git clone, HF snapshot) can go stale
  behind an unchanged instruction, which is the standing property of every
  Docker layer cache rather than something this change introduces.
- The next real build shows no reuse where reuse was expected → suspect the
  inline manifest (min mode) or a context-checksum difference between
  workers; that investigation starts from the build log's `importing cache
  manifest` lines.
