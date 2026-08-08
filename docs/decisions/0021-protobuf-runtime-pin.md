# 0021 — Pin protobuf runtime to match gencode in api-internal/api-public images

**Date:** 2026-05-27
**Status:** Accepted

## Context

First execution of `infra/RUNBOOK.md` halted at Phase 2 deploy of api-internal.
The Cloud Build succeeded; the Cloud Run deploy failed because the container's
first revision (`api-internal-00001-5zx`) exited at import time:

```
google.protobuf.runtime_version.VersionError: Detected incompatible Protobuf
Gencode/Runtime versions when loading capture_bundle.proto: gencode 7.35.0
runtime 6.33.6. Runtime version cannot be older than the linked gencode version.
```

`packages/schemas/roomstudio_schemas/capture_bundle_pb2.py` is generated with
gencode 7.35.0 (from whatever `protoc` is installed locally where
`tools/gen_proto.sh` was last run). The api-internal image installs an older
`protobuf` (6.33.6, presumably as a transitive of `google-cloud-firestore` or
similar). Protobuf's cross-version guarantee requires runtime ≥ gencode, so the
import raises immediately.

The 233-test suite did not catch this because tests run against the local Python
environment, where `protobuf` happens to match the gencode used by `gen_proto.sh`.
The container never gets exercised by the test suite.

The same `capture_bundle_pb2.py` is imported by api-public; the same risk
applies there.

## What we tried

**Checked whether the fix from 0005 was already present:** Yes — both new
Dockerfiles already had the `--no-deps --force-reinstall "protobuf>=7.35.0"`
step from the moment of the two-service split (commit `b0c8629`). The workaround
was not missing; it was in the wrong position.

**Traced which layer undid the pin:** `packages/schemas/pyproject.toml` declares
`protobuf>=7.35.0`. `packages/api-core/pyproject.toml` declares
`google-cloud-firestore>=2.14,<3.0`; Firestore pulls `proto-plus 1.x` which
declares `protobuf<7.0.0dev`. In both Dockerfiles, Layer 2 ran the
force-reinstall (protobuf → 7.35.0), then Layer 3 ran `pip install
packages/api-core/`. Even though Firestore was already installed, pip's resolver
re-checked the dep tree when satisfying api-core's `google-cloud-firestore` dep,
saw proto-plus's `<7.0.0dev` constraint violated by protobuf 7.35.0, and
downgraded protobuf back to 6.33.6. The symptom (runtime 6.33.6) is exactly what
a resolver-triggered downgrade produces.

**Confirmed no other dep caps protobuf below 7.x:** Neither service's
`pyproject.toml` nor either local package's `pyproject.toml` specifies an upper
bound on protobuf. The only upper bound in the transitive tree is proto-plus's
`<7.0.0dev`. No second constraint blocked a simple layer-reorder fix.

**Considered regenerating gencode at a lower version:** Rejected. It would
require pinning `protoc` in `tools/gen_proto.sh` and accepting static typing
against an older API surface. The 0005 force-reinstall approach already works
at the services/api/ level; the issue was purely layer ordering, not the approach
itself.

## What we chose

Swap Layer 2 and Layer 3 in both Dockerfiles so that `packages/api-core/` is
installed *before* the protobuf force-reinstall:

```
Layer 1: pip install service deps (google-cloud-*, firebase-admin) → protobuf 6.x
Layer 2: pip install packages/api-core/  ← moved earlier; protobuf still 6.x, no conflict
Layer 3: pip install --no-deps --force-reinstall "protobuf>=7.35.0"
         pip install packages/schemas/   ← nothing after this re-resolves the tree
Layer 4: COPY service source
```

After the reorder, nothing installed after the force-reinstall touches the dep
tree, so proto-plus cannot trigger a downgrade. The `packages/schemas/` install
that follows finds `protobuf>=7.35.0` already satisfied and does not invoke the
resolver for protobuf.

Added a container-import smoke step to both `infra/cloudbuild/api-internal.yaml`
and `infra/cloudbuild/api-public.yaml` between build and push:

```
docker run --rm <image> python -c "
  from roomstudio_schemas import CaptureBundle, CaptureTier
  from roomstudio_api_core.scene import Scene
  print('import smoke: OK')
"
```

If this step fails, the push is blocked. The smoke catches any future
layer-ordering regression before the image reaches Cloud Run.

## Why

The bug is structural, not incidental. `gen_proto.sh` runs on whatever machine
the developer happens to be on; the container is built in Cloud Build from
`pyproject.toml`/`requirements.txt`. Nothing currently couples the two. Every
regen is a chance for the gencode to outpace the pinned runtime silently — the
dev's local Python environment matches the new gencode (because it generated it),
the test suite stays green, the bug only surfaces at container-start time on
Cloud Run.

A CI smoke that imports inside the built image addresses the structural risk
(board item 3). The version pin (whichever direction) addresses the immediate
failure. Both should land together.

## What would change this decision

- The protobuf project changes its cross-version guarantee policy.
- `roomstudio_schemas` stops shipping generated code and switches to a
  pure-runtime proto parser (unlikely; would lose static typing).
- A different runtime dependency mandates an older `protobuf` upper bound,
  making the pin direction non-trivial; in that case `tools/gen_proto.sh` would
  need to pin its generator version downward instead.
