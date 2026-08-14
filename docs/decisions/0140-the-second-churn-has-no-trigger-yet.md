# 0140 — the second churn has no trigger yet

**Date:** 2026-08-14
**Status:** Decided

## Context

Decision 0139 names the mechanism by which a lost Firebase credential becomes
a new anonymous UID, and measures the trigger for the first churn: Gate B's
administrative touch on `cHfMlUL` revoked its refresh token, and the app minted
a replacement at the next launch.

The second churn — `j9UJyV6s` → `u4AmDs2V`, at **2026-08-12 07:21:49 UTC** —
has no such trigger, and a story that fits one churn is a lead rather than an
answer. This note records what the second churn is not, so the next session
starts from the surviving branches instead of re-running the eliminations.

## What we tried

The account itself refuses every server-side explanation. `j9UJyV6s` is
present in the project today, is not disabled, and — unlike `cHfMlUL` — carries
**no `validSince`**. So none of `userNotFound`, `userDisabled` or a revocation
can have produced the invalid-token response that 0139's chain begins with.

The window is 2026-08-08 09:22:13 UTC, its last successful token refresh, to
2026-08-12 07:21:49 UTC, when the replacement was minted. In that window:

- The Identity Toolkit **admin audit log is silent** after 2026-08-08 17:20.
- **api-public saw no request from the phone at all**, so the app was not
  launched. Its first request of 08-12 is at 07:21:52 — three seconds *after*
  the new uid exists, and it is a by-bundle poll returning 403, which is 0074's
  stand-down running under the new identity. The 403 burst is the consequence
  of the churn, not its cause.
- The plist, `GOOGLE_APP_ID`, API key, team, App ID and keychain access group
  are all measured constant across the boundary (0139).
- The Live Activity extension, added 08-08 and first installed on a device in
  this window, imports no Firebase in either the extension or the shared
  target, so it cannot have touched the credential.

A failed refresh would not have updated `lastRefreshAt`, so its value pins the
last *successful* use and cannot distinguish "never tried again" from "tried
and was rejected".

## What we chose

Churn 2's trigger stays **open**, with three named survivors and the instrument
for each. It is recorded as open rather than assimilated into 0139, because
the evidence that closed churn 1 is precisely the evidence churn 2 lacks.

**(a) A rejected refresh at the 08-12 launch itself**, from a code 0139 lists
but whose server-side cause left no trace on the account. Consistent with
everything observed: no successful refresh after 08-08, the mint at launch, no
admin activity. *Instrument:* the `auth.continuity` fault added in 0141, plus
the SDK's own `I-AUT000016` notice, which names an automatic sign-out at the
moment it happens. Neither existed on 08-12.

**(b) A Keychain read that failed rather than a credential that was deleted.**
The SDK anticipates this explicitly — on a Keychain error it leaves
`currentUser` nil, logs, and waits for `protectedDataDidBecomeAvailable` — and
`signInIfNeeded` does not wait with it. This branch needs no server-side event
at all, which is why it survives the eliminations above. It sits awkwardly with
the phone being in the operator's hands at the time, freshly installed and
presumably unlocked. *Instrument:* 0141's reading separates it by construction
— a readable device UUID beside a missing credential is a deletion, an
unreadable one on an install that carries capture records is a read failure.

**(c) A launch between 08-08 and 08-12 that left no server trace**, such as a
background relaunch for a URLSession event. It would have had to fail its
refresh without succeeding at one, since `lastRefreshAt` never moved.
*Instrument:* the `StagingHooks` breadcrumb file already distinguishes a
background OS-relaunch from a foreground open, and it is written where os_log
is not trustworthy under suspension.

Two eliminations are worth stating positively, because both were plausible
enough to have been reported as findings. **The re-sign is not the cause** —
0139 refutes it directly, with a reinstall that kept its credential. And the
**app never deletes the credential itself**: `signOut`, `SecItemDelete` and
`useUserAccessGroup` appear nowhere in the iOS tree, so no app-side path can
produce the deletion.

## Why

All three survivors converge on the same app-side defect, which is why the
investigation is not blocked on telling them apart: whatever leaves
`currentUser` nil, the app's response is to mint over it silently. The
distinction changes the *cure* — (a) and (c) are recoverable only by not
minting, (b) is recoverable by waiting — but not the severity, and not the
instrument that would settle it.

Recording the eliminations is the durable part. Each of the three dead
hypotheses here cost real measurement, and each would otherwise look live to
the next reader of 0115.

## What would change this decision

The next churn, observed with 0141's reading in the log, decides between (a),
(b) and (c) on its own. Until one happens, the trigger is not knowable from
data that exists: the phone's own logs for 08-12 are gone, and no server-side
record distinguishes a refresh that was never attempted from one that was
rejected.

## Follow-on work this creates

The instrument is 0141's. Nothing else is owed here — this note exists so the
absence of a second trigger is a recorded state rather than an oversight.
