# 0074 — iCloud-backup migration: what carries over, and the phantom-room row

**Date:** 2026-07-26
**Status:** Decided; fix BUILT 2026-07-28 (branch `ios-0074-phantom-room`,
commits `8b063bc` fix / `e75de4a` sweep — both preferred directions below,
as recorded). Simulator-verified against production with the real `9fbe29b6`
record and a live 403; hardware verification on the 16 Pro (which carries the
live repro state) pending the next device session.

## Context

The first Pro device (iPhone 16 Pro) was set up from an iCloud backup of the
16e. On the app's first-ever launch on the new device — a fresh install that
had never captured anything — home showed "One room is on its way — check on
it." That row should be impossible on a fresh install. The session traced
exactly which per-device state migrates and what the restore logic does with
inherited state.

## What we observed (device store pulled via devicectl)

Migration matrix, established empirically on real hardware:

| State | Migrates? | Evidence |
|---|---|---|
| `UploadSessionStore` records (Application Support JSON) | YES — all 38 of the 16e's records arrived | store dump: 34 June-era + `42bba2b9` (Jul 21) + `9fbe29b6` (Jul 23) present on the 16 Pro |
| Capture blob directories | NO (backup-excluded by design, decision 0043) | dirs absent on the new device |
| Firebase anonymous identity (Keychain) | NO — fresh UID minted | 16e `j7gxP0HM…` vs 16 Pro `cHfMlULde2…` on the new scene docs |
| DeviceIdentity Keychain UUID | NO — fresh id | 16e `fb5271cb…` vs 16 Pro `2d600864…` |
| Camera TCC grant | YES | no permission prompt on first capture |

Second-order finding: the 34 June-era records predate P5's `uploadPhase`
field, fail the strict decode (migration shims were removed in the cleanup
pass), and are therefore invisible to restore — harmless dead files, never
cleaned. Only the two July records decode.

## The defect chain (every link verified)

1. `BundleRestore.pick` = newest non-failed, non-acknowledged record. The
   16e's July records are `.complete` and were finished under the OLD
   ContentView flow, which never wrote acknowledgments — so on every cold
   launch, pick adopts `9fbe29b6` and home advertises the 16e's July room.
2. Polling it 403s: `GET /scenes/by-bundle` enforces ownership and the new
   device holds a fresh UID (correct behavior — identity did not migrate).
3. A poll 403 routes to the connection-trouble screen, which says "your room
   is safe up there" (false for this identity) and has NO acknowledging
   exit — `onLeave` deliberately preserves the flight so that "leaving is
   free" for rooms that are genuinely processing.
4. Therefore the phantom recurs on every cold launch, forever. A new capture
   out-ranks it only until that capture's doorway "Done"; then it returns.

Observed live across three launches on the 16 Pro (phantom on launch 1;
correct pick of the in-flight bundle on launch 2's relaunch test; latch —
not absence of the defect — hid it on launch 3).

## What we chose

Record now, fix in a dedicated iOS pass (this session was the hardware-gate
walk; the fix touches ScenePoller/WaitFlowState semantics and deserves its
own tests). Fix direction, in order of preference:

1. Treat a by-bundle poll **403 as terminal-not-ours**: acknowledge the
   bundle (DismissedBundles) and reset the poller instead of the
   connection-trouble treatment. A 403 is definitive — this identity will
   never own that scene — so standing down is honest, self-healing, and
   needs no migration-specific code.
2. Optionally sweep undecodable (pre-P5) records at launch — cosmetic.

## Why

Device migration is a normal consumer event, not an edge case; every future
real user who upgrades phones walks this path. The matrix above is also the
factual substrate for any future cross-device continuity design: records
travel, blobs and identity do not — so continuity MUST come from the server
via a linked identity (decision 0051), never from local state.

## What would change this decision

If sign-in (0051) ships before the fix and account linking makes the old
rooms genuinely reachable from the new device, the 403 case narrows to
truly-foreign bundles and the fix's acknowledgment semantics still hold.
