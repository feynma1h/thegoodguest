# 0005 — protobuf version workaround in container

**Date:** 2026-05-23
**Status:** Decided

## Context

The ingester container (`services/api/`) needs two things that have mutually
exclusive pip dependency constraints:

- `thegoodguest-schemas` requires `protobuf>=7.35.0` — enforced by
  `ValidateProtobufRuntimeVersion` in the generated `capture_bundle_pb2.py`,
  which calls `ValidateProtobufRuntimeVersion(PUBLIC, 7, 35, 0, ...)` at import
  time and raises `VersionError` if the runtime version is lower.
- `google-cloud-tasks` and `google-cloud-firestore` (via `proto-plus 1.x`)
  declare `protobuf<7.0.0dev` — pip resolves this to protobuf 6.x.

## What we tried

**Schemas first, google-cloud second (original Dockerfile layer order):**
pip installed thegoodguest-schemas fine (protobuf 7.35.0). Then the google-cloud
install ran, resolved the proto-plus constraint, and *downgraded* protobuf from
7.35.0 to 6.33.6. Symptom at container startup: `VersionError: Detected
incompatible Protobuf Gencode/Runtime versions when loading
capture_bundle.proto: gencode 7.35.0 runtime 6.33.6. Runtime version cannot be
older than the linked gencode version.`

**Single pip install with explicit `protobuf>=7.35.0`:**
Including `protobuf>=7.35.0` in the same `pip install` call as google-cloud-*
forces the resolver to satisfy both constraints simultaneously. Symptom: pip
24.0 raises `ResolutionImpossible` — no version of protobuf satisfies both
`>=7.35.0` and `<7.0.0dev`. Build fails before producing an image.

## What we chose

Install google-cloud-* first (pip resolves to protobuf 6.x), then
force-reinstall protobuf to >=7.35.0 before installing thegoodguest-schemas:

```dockerfile
RUN pip install --no-cache-dir \
        fastapi "uvicorn[standard]" \
        google-cloud-storage google-cloud-firestore google-cloud-tasks

COPY packages/schemas/ packages/schemas/
RUN pip install --no-cache-dir --no-deps --force-reinstall "protobuf>=7.35.0" \
    && pip install --no-cache-dir packages/schemas/
```

`--no-deps` prevents pip from re-resolving proto-plus's constraint when
upgrading protobuf. `--force-reinstall` bypasses the installed-version check.
After this, protobuf is at 7.35.0; thegoodguest-schemas imports successfully;
google-cloud-* packages operate normally at runtime.

## Why

proto-plus 1.x declares `protobuf<7.0.0dev` defensively, but its actual usage
of the protobuf Python API is limited to stable surface (`Message`,
`DescriptorPool`, `FieldDescriptor`, descriptor serialization). None of these
interfaces changed incompatibly between protobuf 6.x and 7.x. The constraint is
overly conservative — the libraries work at runtime with protobuf 7.35.0 even
though they claim they don't.

The alternative — downgrading the `protobuf>=7.35.0` requirement in
`packages/schemas/pyproject.toml` — would require regenerating
`capture_bundle_pb2.py` with an older protoc so the `ValidateProtobufRuntimeVersion`
call embeds a compatible version number. That conflates a toolchain constraint
with a runtime constraint and would require coordinating the protoc version with
whatever version the google-cloud ecosystem can accept. Not worth it while the
hack works.

## What would change this decision

When `pip install google-cloud-tasks` in a clean env resolves to protobuf >=7
without the force-reinstall, the hack can go. Concretely: if you run
`pip install google-cloud-tasks && pip show protobuf` and the installed version
is >=7.0.0, the force-reinstall step in the Dockerfile is no longer needed.
Remove it, consolidate the two RUN steps back into one, and delete this note.
