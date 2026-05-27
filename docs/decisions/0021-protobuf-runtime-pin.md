# 0021 — Pin protobuf runtime to match gencode in api-internal/api-public images

**Date:** 2026-05-27
**Status:** Proposed (pending implementation — promote to Accepted when the fix commits)

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

(To be filled when the fix lands — document the actual investigation, including
which dep was pulling in protobuf 6.33.6, whether any other dep upper-bounded
protobuf below 7.x, and what was observed when the fix was applied. Do not
transcribe the candidate paths sketched before investigation; record what
was actually done.)

## What we chose

(To be filled when the fix lands — state the chosen direction with evidence:
pin-up, regen-down, or something else, and why the transitive dep tree allowed
or required it.)

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
