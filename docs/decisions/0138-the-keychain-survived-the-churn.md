# 0138 — the Keychain survived the churn

**Date:** 2026-08-13
**Status:** Decided

## Context

Decision 0115 recorded that the iOS capture app's Firebase anonymous UID
changed twice on one iPhone 16 Pro, orphaning each period's captured rooms.
Decision 0036 makes "the anonymous UID never churns" a hard invariant, so this
is a real defect, and 0115 left the cause unknown while naming a leading
suspect: that the personal-team entitlements-drop workaround altered the app's
Keychain access group, taking Firebase's credential with it.

That suspicion carried a heavy consequence. If it were right, every device
build destroys user identity, and the stalled Apple Developer Program
enrollment is not merely an inconvenience but an active source of data loss.

## What we tried

First the premise was checked rather than the conclusion.
`TheGoodGuestCapture.entitlements` declares only
`com.apple.developer.applesignin` — there is no `keychain-access-groups` key —
and `kSecAttrAccessGroup` appears nowhere in the iOS tree, nor does
`useUserAccessGroup`. Both the app's own Keychain item and Firebase Auth's
therefore live in the default team-prefixed group. Dropping
`CODE_SIGN_ENTITLEMENTS` does not itself move that group; a change of signing
team or App ID prefix would.

That made a cheap decisive test available, needing no device at all.
`DeviceIdentity` mints a UUID into `kSecClassGenericPassword` in that same
default group, and `device_id` is copied onto every Scene document at ingest —
where it outlives the capture blobs, which sweep at age one day. If the
Keychain partition was lost, `device_id` and the Firebase credential were lost
together.

A read-only sweep of all 63 `scenes` documents tabulated
`(user_id, device_id, created_at)`.

## What we chose

The access-group hypothesis is abandoned.

`device_id = 2d600864-fa63-4459-a317-de22f616d08f` is byte-identical on both
sides of both UID changes — one UUID spanning 13 scenes over 19 days and three
Firebase identities:

| churn | last scene before | first scene after | device_id |
|---|---|---|---|
| `cHfMlUL` → `j9UJyV6s` | `a71d125f`, 08-05 19:27 | `0e2ec151`, 08-08 07:42 | unchanged |
| `j9UJyV6s` → `u4AmDs2V` | `b12538fa`, 08-08 08:46 | `7bbdbaf1`, 08-12 07:27 | unchanged |

The sweep also rules out the third possible signature: `device_id` does not
churn per launch, so the Keychain *writes* are succeeding and
`mintAndStore`'s unpersisted-fallback path is not firing.

## Why

The Keychain was reachable across both churns and the default access group did
not change — otherwise the two items, which sit in the same group, would have
been orphaned together. They were orphaned neither.

So the mechanism is **differential**: something took Firebase's Keychain item
and spared ours. A whole-partition explanation cannot produce that, which
eliminates the entitlements drop, a signing-team change, and an App-ID-prefix
change in one stroke. A deliberate sign-out is eliminated separately — there
is no `signOut` call anywhere in app code, which is 0051's deliberate design
rather than an accident.

Two traps in the data are recorded because either would have manufactured a
false verdict for a reader working from the era list alone. Scene `a7e073ae`
sits inside the first era carrying a *different* `device_id`, which reads
exactly like a third churn; it is the RP-8 Mac-side spike upload, and its id is
synthesized by `tools/convert_roomplan_spike.py` (confirmed against the
preserved `bundle.pb`, which also carries `app_version: "RoomPlanSpike"`). And
a fourth uid, `6DiYzw9a`, falls precisely between the first two eras on
2026-08-07; it is the smoke tool, on the literal `test-device-uuid`.

The redirect matters more than the elimination. The remaining explanations are
all things that can happen to a real user with no workaround to blame — which
promotes the churn from a developer-workflow artifact to a launch blocker.

## What would change this decision

The verdict is confined to the two churns that produced captures on both
sides. A churn that occurred and reverted without a capture in between would
be invisible to this instrument, so evidence of a UID change with no scene
either side reopens the question of how many there were — though not the
mechanism, which is settled for the two we can see.

If Firebase Auth is ever configured with `useUserAccessGroup`, the two items
stop sharing a group and `device_id` stops being a proxy for the Firebase
credential's fate; this test would have to be rebuilt on a different signal.

## Follow-on work this creates

`ingest_server.py` copies only `device_id` from `DeviceInfo` onto the Scene,
so hardware attribution is possible only by correlating device ids. The proto
already carries `hardware_id`, `os_version` and `app_version`; persisting
`hardware_id` would have made this sweep a single query instead of an
inference chain, and would pay off for every future cross-device question.
