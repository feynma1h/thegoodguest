# 0109 — Node comes from conda-forge, not apt

**Date:** 2026-08-09
**Status:** Decided

## Context

The `/compress` stage (decisions 0125/0126) needs a Node runtime inside the
perception-obj CUDA image, because the compressed splat tier must be written
by Spark's own `SpzWriter` — the same build the browser decodes with. The
Dockerfile added it the obvious way:

```dockerfile
RUN apt-get install -y --no-install-recommends nodejs npm
```

That had never been built. The four-surface deploy was the first Cloud Build
to run it, and the build **failed** — which is the in-image smoke working
exactly as designed, catching the problem at build time rather than shipping
a service whose only symptom would have been "no compressed tier, ever".

## What we tried

`apt install nodejs`, and it *succeeded*. So did the npm install:

```
Get:25 .../focal-updates/universe amd64 nodejs amd64 10.19.0~dfsg-3ubuntu1.6
+ @sparkjsdev/spark@2.1.0
added 3 packages from 2 contributors in 2.193s
```

The base image is `condaforge/mambaforge:24.7.1-0`, which is Ubuntu 20.04, and
focal's `nodejs` is **10.19.0** — a 2018 runtime. `tools/spz_encode.mjs`
cannot run on it, for at least three independent reasons:

- `import { readFileSync } from "node:fs"` — the `node:` specifier prefix
  needs Node >= 14.18.
- `e?.message ?? e` — optional chaining and nullish coalescing need Node >= 14.
- Spark 2.1.0 is `"type": "module"` ESM, loaded via `await import()`.

**Nothing warned on the way in**, and that is the part worth remembering.
Spark declares no `engines` field, so npm had no constraint to check and
installed a package the runtime could not execute. `--omit=dev` is an npm 7+
flag and focal's npm is 6, so that was silently ignored too. Every layer
reported success right up until node was actually asked to run.

## What we chose

Install Node from conda-forge, into its own prefix, pinned exactly:

```dockerfile
RUN mamba create -y -p /opt/nodejs -c conda-forge "nodejs=22.23.1" \
    && mamba clean -afy
ENV PATH=/opt/nodejs/bin:$PATH
```

Also, in the same layer: the smoke no longer swallows node's stderr. It used
`capture_output=True, check=True`, so the failure surfaced as a bare
`CalledProcessError` with no reason attached — the actual cause had to be
inferred from the apt version several hundred log lines earlier. It now
asserts on the return code and prints node's stderr tail.

## Why

**conda rather than apt or a tarball.** This image already *is* a conda image
— it builds the whole SAM 3D environment with `mamba env create`. Using the
package manager that is already there gets a pinned, checksummed artifact with
no `curl | bash` and no hand-managed sha256 (the alternative that would have
matched 0069's LaMa-weights precedent, but with more moving parts than this
base image needs). Adding a NodeSource apt repo was the third option and is
strictly worse: it is a third-party repo added to a service that parses
untrusted user bundles.

**22.23.1 exactly, not `22.*`.** It is the version `web/` builds with and the
version the encoder was measured on in 0126 (a real 34 MB splat at 5.86× in
1.2 s). 0126's rule is that ONE encoder writes what the browser reads; pinning
the runtime as well as the package is the same argument applied one level
down. A floating minor would let the two sides drift on a dot release, which
is the failure 0126 exists to prevent.

**Its own prefix, not `base` and not `sam3d-objects`.** `/opt/nodejs/bin`
contains only node/npm/npx, so prepending it to PATH cannot shadow `python`
or anything the SAM3D env provides, and a conda resolve cannot perturb either
existing env. Installing into `base` would have worked and would have put node
on PATH via `/opt/conda/bin`, but it lets the solver touch the environment
conda itself runs from, for no benefit.

## What would change this decision

- Spark raising its own Node floor past 22, or `web/package.json` moving to a
  different Node major — the pin should move with it, deliberately, in the
  same commit as the web-side change.
- If the CUDA base image is ever rebased onto something newer than Ubuntu
  20.04, `apt install nodejs` becomes viable again — but conda still gives an
  exact pin that apt does not, so this would stay.
- Worth noting separately, found while diagnosing: `infra/cloudbuild/
  perception-obj.yaml` passes no `--cache-from`, and Cloud Build workers start
  cold, so **every** perception build is a full ~40 minute rebuild from
  scratch even when only the last layer changed. That is its own fix and its
  own decision; it is recorded here because it is the reason a one-line
  Dockerfile change costs 40 minutes to validate.
