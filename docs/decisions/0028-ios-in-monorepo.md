# 0028 — iOS app lives in the monorepo (`ios/` directory), not a separate repo

**Date:** 2026-05-29
**Status:** Decided

## Context

The iOS capture app is the next major build workstream. Before starting, we
needed to decide where the Xcode project lives: a separate git repository
(clean toolchain isolation) or an `ios/` directory in this Python/backend
monorepo (shared proto contract). No code was written for either; the
decision was architectural. The two options were evaluated on their
coordination cost around `capture_bundle.proto`, which is the contract both
sides must stay in sync with.

## What we chose

`ios/` directory in this monorepo. The Xcode project lives at
`ios/RoomStudioCapture/`. The generated Swift proto output,
`ios/RoomStudioCapture/RoomStudioCapture/Generated/CaptureBundle.pb.swift`, is committed as
version-controlled source, the same way `packages/schemas/roomstudio_schemas/
capture_bundle_pb2.py` is committed today. `tools/gen_proto.sh` already
hardcodes this output path; it becomes functional once `protoc-gen-swift` is
installed (`brew install swift-protobuf`).

Swift Package Manager is the only dependency manager for the iOS project (no
CocoaPods, no Carthage). Xcode build artifacts are gitignored:
`xcuserdata/`, `*.xcuserstate`, `DerivedData/`, `.DS_Store`.

Two iOS implementation rules settled during scoping, recorded here for the
iOS build chat:

1. **Gravity / tracking state:** skip keyframes captured under
   `ARCamera.TrackingState.limited` rather than emitting a zero or
   non-unit-norm gravity vector. A zero gravity vector is structurally
   invalid (not a unit vector); the proto contract requires it to be set on
   every ARKit frame, so the right handling is to not emit the frame at all
   until tracking is nominal.

2. **`Device.hardware_id`:** derive via `sysctlbyname("hw.machine", ...)`,
   not `utsname().machine`. `utsname().machine` returns the architecture
   string (`"arm64"`, `"x86_64"`) on the simulator, not the model identifier.
   `sysctlbyname("hw.machine")` returns `"iPhone15,3"` on device and a
   simulator-specific string on simulator — both are acceptable; the model
   string is used for telemetry only, not as a device key.

## Why

**Proto sync is the deciding factor.** `capture_bundle.proto` is the
central contract between iOS and backend. When a field is added or changed,
the impact must be visible in a single commit: proto change + regenerated
Python stubs + regenerated Swift stubs, reviewed together. In a separate
iOS repo, this requires coordinating two PRs across two repos — the
pattern that causes contract drift.

This project's own history demonstrates the risk: decisions 0014, 0017, and
0019 all evolved the proto and backend in tight lockstep, with a single
commit serving as the authoritative record of what changed and why. A
separate iOS repo would have broken that chain for every proto iteration.

The CI separation objection is real but inexpensive to address: Cloud Build
yamls do not touch `ios/`; Xcode Cloud (or a GitHub Actions mac runner)
triggers only on `ios/**` changes. The toolchains don't interfere on the
build system side. A backend developer without Xcode is unaffected; an iOS
developer without a Python virtualenv is unaffected.

## What would change this decision

- If the iOS app grew a team with a strong preference for independent repo
  history, issue tracking, and access controls, and the proto-sync overhead
  could be absorbed via a submodule or published Swift package. Currently the
  team is one operator; the overhead is zero.
- If Xcode project file churn (`.xcodeproj/project.pbxproj` changes on
  structural edits) became a meaningful noise problem in PRs for backend
  contributors. SPM-only dependencies reduce this significantly since
  package state lives in `Package.resolved`, not inside `.xcodeproj`.
- If the proto stabilizes and `CaptureBundle.pb.swift` stops changing — at
  that point a published Swift package for the generated proto would be
  viable, and the cross-repo coordination cost drops to near zero.
