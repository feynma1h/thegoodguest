# 0006 — sys.path hack removal in process_receiver.py

**Date:** 2026-05-23
**Status:** Decided

## Context

`process_receiver.py` imports `CaptureBundle` from `thegoodguest_schemas`, but
when the file was written `thegoodguest-schemas` was not installed as a pip
package in the perception-obj container — it was only available as source in
the repo. To work around this the file inserted `packages/schemas/` into
`sys.path` at import time:

```python
_schemas_path = Path(__file__).resolve().parents[2] / "packages/schemas"
if str(_schemas_path) not in sys.path:
    sys.path.insert(0, str(_schemas_path))
```

## What we tried

**Keeping the sys.path hack in the container.**  
Locally, `process_receiver.py` lives at
`services/perception-obj/process_receiver.py`, so:

- `parents[0]` → `services/perception-obj/`
- `parents[1]` → `services/`
- `parents[2]` → repo root

The path resolves to `<repo_root>/packages/schemas/`, which exists. Tests
pass. The import works.

In the container, the file is COPYed to `/app/process_receiver.py`, so:

- `parents[0]` → `/app/`
- `parents[1]` → `/`
- `parents[2]` → `IndexError` — pathlib `_PathParents` is bounded by the
  number of path components, and `/` has none above it

The `IndexError` is raised at module load time (not at the first `/process`
request). Because `process_receiver` is imported at the bottom of `server.py`
to register the `ProcessRequest` type annotation, this means the service
fails to start entirely — uvicorn exits before binding to the port, the Cloud
Run startup probe never gets a TCP connection, and the deploy rolls back.

## What we chose

Install `thegoodguest-schemas` as a proper pip package in the container image,
using the same two-stage 0005 protobuf workaround already applied in
`services/api/Dockerfile` (that service was later split into api-internal and
api-public, which both still build this way). Remove the `sys.path` manipulation and the now-
unused `sys` and `Path` imports. The import becomes a straightforward
top-level `from thegoodguest_schemas import CaptureBundle`.

This required switching the perception-obj Cloud Build context from the
service directory (`services/perception-obj/`) to the repo root, so that
`packages/schemas/` is reachable during `docker build`. That change was
already necessary to fix the separate problem of the four receiver modules
not being COPYed into the image.

## Why

The `sys.path` hack gave a false sense of correctness: it worked in every
local environment because the file was always two directories below the repo
root. The container broke the invariant. A pip install is the right
abstraction — it works regardless of where the source file ends up, and it
makes the dependency visible to tooling.

The cost of the pip install approach is that the Dockerfile must now be
built from the repo root (to reach `packages/schemas/`). This is already
the pattern used by `services/api/Dockerfile` (that service was later split into api-internal and
api-public, which both still build this way) and adds negligible complexity.

## What would change this decision

If `thegoodguest-schemas` were published to PyPI, the `COPY packages/schemas/`
+ local `pip install` could be replaced with a simple versioned
`pip install thegoodguest-schemas==X.Y.Z`. The repo-root build context would
remain the right choice (it also covers `COPY services/perception-obj/…`
paths), but the schemas COPY layer could be dropped.
