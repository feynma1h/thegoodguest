# 0192 — perception-geom is retired, and it was a door, not a line item

**Date:** 2026-08-20
**Status:** Decided — executed

## Context

`perception-geom` (VGGT) was built for the photo-upload path and has been
orphaned since that path was deferred. 0190 listed it as a flagged question —
"whether it should exist at all is a product call" — and deliberately placed it
outside every prefix in the registry cleanup policy so nothing could touch it.
The operator asked the question directly.

## What we tried

Checking whether it was used answered a smaller question than the check turned
up. Measured against the live project:

- **Zero requests in 30 days.** The only entry in its log is a health probe
  this session's own verification made.
- **No production code path reaches it.** The only references are three
  operator tools — `call_perception.py` (whose own docstring records that most
  of it already 404s), `fetch_pointmap.py` (the VGGT-pointmap thread 0181 ruled
  a dead end), and `smoke_test_e2e.py`.

And then the part that changed the decision's weight:

- `allUsers` held `roles/run.invoker` — **invocable by anyone on the internet**.
- It ran as `502805861152-compute@developer.gserviceaccount.com`, which holds
  **`roles/editor` project-wide** (confirmed against the live IAM policy).
- It was backed by an **nvidia-L4 GPU**, 8 CPU, 32 GiB.

So a stranger could start a GPU on the project's bill inside a container whose
credentials can edit the project. That is exactly the pair of exposures decision
0106 closed for `perception-obj` (platform gate — only `tasks-invoker@` holds
run.invoker) and decision 0090 closed (a dedicated least-privilege runtime SA,
remediating 0088 finding 1). `perception-geom` was left behind on both, and
nothing pointed at it afterwards, so nothing re-examined it.

## What we chose

Decommissioned, safest step first: removed the `allUsers` binding, deleted the
Cloud Run service, deleted the 12.5 GiB image. Cloud Run is now exactly
`api-internal`, `api-public`, `perception-obj`.

## Why

The cost was never the argument — 12.5 GiB is about ₹109/month. The argument is
that an unauthenticated GPU endpoint running with project-editor credentials is
a standing liability whether or not anyone is calling it, and *nobody calling
it* is what let it sit unexamined for three months.

Deleting rather than merely gating it is the right depth because the service is
**fully reversible at one command**: `./infra/deploy_perception.sh geom` builds
a *fresh* timestamped image on every run, so the stored image carried no restore
value, and the source under `services/perception-geom/` is intact and committed.
Its Dockerfile is also clear of the dead-index hazard 0182 found in
`perception-obj` (different base image, no `PIP_EXTRA_INDEX_URL`), so a rebuild
is not carrying a known landmine.

Gating alone would have left a service nobody watches, still running as editor,
still on a GPU, protected only by an IAM binding that a future
`--allow-unauthenticated` deploy would silently restore.

## What would change this decision

- **If the photo-upload path is revived**, redeploy with the 0090/0106
  treatment applied from the first deploy — a dedicated runtime SA, and
  `--no-allow-unauthenticated` — rather than inheriting the defaults that
  produced this. `deploy_perception.sh`'s `geom` branch still deploys with the
  default SA and does not platform-gate; fix that before, not after.
- **The cleanup policy still excludes `perception-geom`** (0190 §What we chose).
  That is harmless while no such images exist, but a revival would accumulate
  them unbounded again — the exact defect 0190 fixed. Add a
  `mostRecentVersions` KEEP for it in `infra/artifact-cleanup-policy.json` at
  revival time, and give it the `serving` tag treatment 0190 gave
  `perception-obj`.
