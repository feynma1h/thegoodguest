# 0298 — a reason code belongs to one category, and the bundle's clock starts at capture

**Date:** 2026-09-15
**Status:** Decided

## Context

`PrivacyInfo.xcprivacy` declared `54BD.1` for UserDefaults, `35F9.1` and
`0A2A.1` for SystemBootTime, and `DDA9.1` for FileTimestamp, each beside a
description in Apple's own words; `tools/test_privacy_manifest.py`, the labels
document and PROJECT.md repeated them. Two of those codes are not in the
category they were declared under — `54BD.1` is an Active Keyboards reason, and
`0A2A.1` a File Timestamp one that only third-party SDKs may declare — and
upload refuses a code that is not valid for its category (ITMS-91055).

## What we tried

Apple's list was re-read from the JSON behind the documentation pages. Under
`https://developer.apple.com/tutorials/data/documentation/bundleresources/app-privacy-configuration/nsprivacyaccessedapitypes/`,
`nsprivacyaccessedapitypereasons.json` lists all seventeen codes in one flat
run, and `nsprivacyaccessedapitype.json` groups the same codes by category. The
error had one shape, six times over: each code carried the description of the
entry listed directly below it.

| Code | Description it carried | Whose it is |
|---|---|---|
| `54BD.1` (declared) | only accessible to the app itself | `CA92.1` |
| `CA92.1` (rejected) | members of the same App Group | `1C8F.1` |
| `DDA9.1` (declared) | files inside the app container | `C617.1` |
| `C617.1` (rejected) | files the user granted access to | `3B52.1` |
| `35F9.1` (declared) | absolute timestamps for in-app events | `8FFB.1` |
| `0A2A.1` (declared) | elapsed time between events | `35F9.1` |

Every phrase was genuinely Apple's, which is how a check of the wording against
the page could pass, and why the test that pinned the exact strings held the
error in place rather than guarding against it.

Correcting SystemBootTime raised the question of what actually leaves the
device. The bundle carried `started_at_device_us`, `ended_at_device_us` and
every `Frame.timestamp_us` as raw device-monotonic readings: how long the phone
had been awake since it last restarted. No boot-time reason lets a capture
upload carry those. `35F9.1` lets only elapsed time between events in the app
leave the device; `8FFB.1` lets absolute timestamps of in-app events leave, but
not boot time or anything else derived from it; and `3D61.1` covers only a bug
report the person chooses to submit. What the values are used for settled it:
no service reads them, and the readers that do — `tools/inspect_bundle.py`,
`tools/convert_roomplan_spike.py`, and `tools/track_select.py` into
`track_selection.py` — take differences only. The DEBUG-only live-boxes review,
unmerged, already reduces every reading to an offset from its session start
before a meter or its log sees it.

## What we chose

- **`CA92.1`, `35F9.1` alone, and `C617.1`**, each stated in the manifest and in
  `EXPECTED_REASONS` with why its neighbours do not fit.
- **The bundle's device clock counts from capture start.** `BundleAssembler`
  writes the capture window and every frame timestamp relative to
  `startedAtDeviceUs`, so `started_at_device_us` is 0, and `BundleClockTests`
  pins it through a written bundle.pb. Every difference a reader takes is
  unchanged to the microsecond; field names, numbers and `schema_version` stay.
  This amends 0013: the same clock, a new origin.
- **The test carries Apple's table.** `VALID_REASONS` lists every code under its
  category, so a declared code must be one its own category publishes, and the
  SDK-only `0A2A.1` and `C56D.1` may not appear at all. The table was compared to
  the grouped JSON by script, code by code and in order, not by eye.

## Why

A reason code makes two claims: the category, which upload checks, and the use,
which nothing checks. So the category check is a test that fails naming the
category a misplaced code really belongs to, and the use is made true in code
rather than asserted in a comment — a manifest saying the bundle sends elapsed
time is worth nothing while the bundle sends uptime.

Rebasing on the device is the one fix that changes no reader. Converting to
wall-clock time is what 0013 rejected, and `8FFB.1` still would not let the raw
readings go; dropping the fields would break the duration and frame-offset math
0013 exists for. Bundles already uploaded carry uptime readings until the
one-day lifecycle rule on `captures/` deletes them (labels §5), and nothing
reads them in the meantime.

## What would change this decision

- **Apple revises the list or its terms.** Rebuild `VALID_REASONS` from the
  grouped JSON and compare it the same way — never from memory, and never from a
  summary. If `35F9.1`'s allowance for elapsed time narrows, the bundle's offsets
  are what it reaches.
- **Another stream on the device clock has to line up with the bundle** — a
  second upload, a sensor log. It is counted from the same capture start before
  it leaves the device; that is not a reason to send readings as taken. Absolute
  times need no change either: `started_at_wall_us` plus an offset gives them.
- **An App Group appears**, or **the sweeper starts showing a date**: `1C8F.1`
  or `DDA9.1` joins, for the calls that do.
