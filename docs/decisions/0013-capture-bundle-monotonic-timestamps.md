# 0013 — Capture-bundle timestamps: device-monotonic, with wall-clock alongside

**Date:** 2026-05-26
**Status:** Decided

## Context

`CaptureBundle.started_at_us` and `ended_at_us` are currently documented as
"epoch microseconds" — wall-clock time from the device's real-time clock.
`Frame.timestamp_us` is documented as being in the same clock domain.

No iOS app exists yet. The only bundle writer is `tools/build_test_bundle.py`,
which fills these fields from `time.time_ns()`. The contract has never been
exercised by a real ARKit capture.

On the iOS side, frame timestamps will come from `ARFrame.timestamp`, which
is a `TimeInterval` sourced from `CACurrentMediaTime()` / `mach_absolute_time()`
— **device-monotonic seconds since boot**, not wall-clock. To honor the
current schema, iOS would have to snapshot a `(wall_now, mono_now)` offset
once at capture start, convert every `ARFrame.timestamp` to wall-clock by
adding it, and trust that the offset doesn't shift mid-capture (NTP sync,
manual clock change, DST). That conversion loses the property we actually
want from frame timestamps: durations and inter-frame deltas should be
reliable regardless of what the wall clock does.

Captures are short (seconds to minutes), so a clock jump during capture is
unlikely — but "unlikely" plus "silently produces garbage durations" is the
wrong place to land for a contract that's about to be frozen as v1. This is
the cheapest moment to fix it: zero production bundles, no Swift code, 9
call sites in 5 Python files.

## What we tried

**A. Leave it wall-clock; iOS converts.**
Rejected. Pushes the clock-domain conversion (and its failure mode) into
every iOS bundle writer, and forces the backend to trust that conversion.
The bug, if it ever fires, surfaces as nonsensical durations in downstream
perception with no way to recover.

**B. Keep field names, change semantics to monotonic.**
Rejected. `started_at_us` continuing to exist with a quietly-changed
meaning is a trap: any caller doing `time.time() - bundle.started_at_us/1e6`
silently breaks with no compile-time or import-time signal. Renames force
callers to update; silent semantic shifts do not.

**C. Add monotonic fields alongside the existing wall-clock fields.**
Rejected. There are zero existing bundles to maintain compatibility with.
Carrying both creates a "which one is canonical?" question for every reader,
and the answer would always be "the monotonic one" — so just have that one.

**D. Rename to device-monotonic + add a separate wall-clock field.** Chosen.

## What we chose

In `CaptureBundle`:

- Field 6: rename `started_at_us` → `started_at_device_us`. Semantics
  change from wall-clock epoch µs to device-monotonic µs in the same domain
  as `ARFrame.timestamp` (CACurrentMediaTime / mach time).
- Field 7: rename `ended_at_us` → `ended_at_device_us`. Same domain change.
- Field 11 (new): `int64 started_at_wall_us`. Wall-clock microseconds at
  the instant the user pressed start. Client-set, single field (no
  `ended_at_wall_us` — reconstructable from the monotonic pair, and storing
  both invites ambiguity if they disagree across a clock jump).

In `Frame`:

- `Frame.timestamp_us` (field 2) — no field change, but the docstring is
  updated to reflect the now-consistent contract: device-monotonic µs, same
  domain as `CaptureBundle.started_at_device_us` / `ended_at_device_us`,
  sourced from `ARFrame.timestamp`.

Field numbers 6 and 7 are reused with new names. Safe at the wire level
(proto3 keys on numbers, not names) and correct here because the *semantics*
are changing — keeping the old name on a renumbered field, or the old
number on a kept name, would both be more confusing than a clean rename.
No production bundles exist whose wire bytes need to round-trip.

The `schema_version` field is not bumped. Pre-v1, the field has no consumer
and the contract has never been frozen. Once v1 ships, future breaking
changes will bump it per the proto file header's convention.

The "device" naming over "monotonic" is deliberate: "monotonic" is a
clock-source label, and if Apple ever changes the underlying clock source
the label would be wrong but the contract unchanged. "Device" stays true.

The wall-clock field is `started_at_wall_us` rather than `created_at_wall_us`
to mirror the device-pair naming and avoid the question "created when —
pressed start, finalized bundle, uploaded?"

## Why

The capture timeline (what duration was this, when did each frame fire
relative to start) needs to be in a clock that can't jump. ARKit gives us
exactly that clock for free in `ARFrame.timestamp`. Storing capture-start
and capture-end in the same clock makes frame-to-bundle math trivial and
correct by construction, and removes a conversion step (with its failure
mode) from every iOS writer.

Wall-clock is a separate concern — humans want to see "captured on May 25
at 4:32 PM," and the backend wants to sort captures across devices. Those
needs are met by a single low-precision wall-clock field set once at
capture start. They do not need microsecond precision or end-of-capture
mirroring.

## What would change this decision

- **ARFrame.timestamp behaves unexpectedly in practice.** If it resets on
  AR session restart, jumps during device sleep on some iOS version, or
  otherwise violates the monotonic-since-boot assumption, revisit. The fix
  would likely be capturing the offset at session start and storing it in
  the bundle, not reverting to wall-clock.
- **Cross-device frame-level sync becomes a requirement.** Multi-device
  captures synchronizing to sub-millisecond would need a different approach
  (probably a shared reference timestamp negotiated out of band). Not on
  the roadmap.
- **iOS starts producing bundles before this lands.** Then the cost
  calculation changes — coordinated client+backend deploy instead of a
  Python-only refactor. This decision exists to land before that happens.
