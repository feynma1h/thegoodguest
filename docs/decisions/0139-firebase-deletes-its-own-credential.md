# 0139 — Firebase deletes its own credential

**Date:** 2026-08-14
**Status:** Decided

## Context

Decision 0138 established that the anonymous UID churn is **differential**:
across both UID changes on the iPhone 16 Pro the app's own Keychain item
survived byte-identical, so something took Firebase's credential and spared
ours. A whole-partition explanation cannot produce that, which left the
mechanism unnamed and the defect a launch blocker — every surviving
explanation was something that can happen to a real user.

Four leads were ranked, strongest first: the Keychain item's key derivation,
the `GoogleService-Info.plist` change inside the window, error paths that clear
the credential, and a stricter accessibility class on Firebase's item.

## What we tried

The Firebase iOS SDK 11.15.0 source pins the item's identity exactly. The
persisted user is a generic password under

```
service    = "firebase_auth_" + app.options.googleAppID
account    = "firebase_auth_1_" + "[DEFAULT]_firebase_user"
accessible = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
```

Three leads died against measurements.

- **The service name derives from `GOOGLE_APP_ID`**, so a changed app
  registration would relocate the item. It never changed:
  `1:502805861152:ios:ad09186f22d91480dcbd45` is identical in the plist baked
  into every build product from 2026-07-21 to 2026-08-12, including the builds
  either side of both churns and either side of the 08-10 plist refresh, which
  added `CLIENT_ID`/`REVERSED_CLIENT_ID` and touched nothing else.
- **The accessibility class is the same one `DeviceIdentity` uses**, not a
  stricter one, so a pre-first-unlock launch cannot read one and not the other.
- **The API key restriction of 08-08 hit the web key.** The plist carries the
  iOS key, which has no referrer restriction.

Team, App ID and keychain access group are constant across the boundary
(`3HU2SP8346.*` in both device builds), confirming 0138's stability claim on a
second, independent signal.

The fourth lead was the answer, and the SDK is explicit about it.
`User.signOutIfTokenIsInvalid` runs from twelve call sites — every token
refresh and every profile update, so it is on the path of every
`getIDToken()` the app makes. On four server responses it force-signs-out:

```swift
if code == AuthErrorCode.userNotFound.rawValue ||
   code == AuthErrorCode.userDisabled.rawValue ||
   code == AuthErrorCode.invalidUserToken.rawValue ||
   code == AuthErrorCode.userTokenExpired.rawValue {
  try? auth?.signOutByForce(withUserID: uid)
}
```

`signOutByForce` calls `updateCurrentUser(nil, byForce: true, savingToDisk: true)`,
whose nil branch is `keychainServices.removeData(forKey: userKey)`.

## What we chose

The mechanism is named: **Firebase deletes its own Keychain item when the
server rejects the stored token, and the app then mints a replacement over
it.**

1. A token refresh returns one of the four codes.
2. The SDK removes its credential from the Keychain. `DeviceIdentity`'s item
   is a different `(service, account)` pair; nothing in the SDK or in app code
   removes it — `signOut`, `SecItemDelete` and `useUserAccessGroup` appear
   nowhere in the iOS tree. **This is the differential, and it requires no
   whole-partition event at all.**
3. `signInIfNeeded()` finds `currentUser == nil` and mints a fresh anonymous
   user, which Firebase persists over the deleted item. `ScenePoller` calls
   `signInIfNeeded` every tick, so no relaunch is needed for step 3 to happen.

**Churn 1 is measured end to end.** Identity Toolkit dates it at
2026-08-08 07:16:01 UTC, and the account records carry the trigger: of every
anonymous uid in the project, `cHfMlUL` — the one that churned — is the only
one with a `validSince`, set at **2026-08-07 22:26:55 UTC**. The admin audit
log puts `CreateDefaultSupportedIdpConfig` 93 seconds earlier at 22:25:22,
which is Gate B enabling the Google provider. The new uid appears 8.8 hours
later, at the next launch.

Gate B's next step was setting a verified email on that anonymous user via the
Admin SDK. Replicated on throwaway users against the real project, that exact
action invalidates the refresh token immediately:

| action on a throwaway anonymous user | refresh before | refresh after |
|---|---|---|
| set verified email (Gate B's action) | 200 | 400 `TOKEN_EXPIRED` |
| `revokeRefreshTokens` | 200 | 400 `TOKEN_EXPIRED` |
| set `displayName` (control) | 200 | 200 |
| nothing (control) | 200 | 200 |

`AuthBackend` maps `TOKEN_EXPIRED` to `userTokenExpired` — one of the four
codes above. Every link in the chain is either measured or read from source.

**A revoked token is not sufficient on its own.** Driven against the real app
on a clean simulator, revoking the credential and relaunching did *not* churn:
`signInIfNeeded` returns early on a loaded user, so nothing attempts a refresh,
and the cached access token is good for an hour regardless. The churn needs
something to actually spend the token. That is why churn 1 surfaced 8.8 hours
later rather than at the moment of revocation, and it is why the loss is
invisible until the app next needs the network.

## Why

The chain explains the differential without needing anything exotic, and every
alternative that could produce a differential has been eliminated by
measurement rather than by argument. It also explains the shape of the failure:
silent, delayed, and indistinguishable from a first run at the point where the
app acts on it.

The re-sign correlation is a **sampling artifact and not a cause**. Both new
uids appear five to seven minutes after a fresh provisioning profile
(2026-08-12's profile is stamped 07:15:53 UTC; the uid is minted 07:21:49), which
reads as causal until you notice the app is unlaunchable between re-signs, so
the first launch after one is the only opportunity to observe *or* to mint.
The direct refutation: on 2026-08-08 at 09:22 UTC the app was rebuilt,
reinstalled and relaunched, and it kept `j9UJyV6s` — a reinstall with a fresh
signature does not lose the credential.

## What would change this decision

A churn on an account with no `validSince`, no deletion and no disablement
would mean a fifth path to a nil `currentUser` — which is exactly what churn 2
is, and why 0140 keeps that half open. The mechanism above is confined to the
churn whose trigger was measured; the *local* half is general, since it depends
only on the SDK's source, but the trigger surface is not closed.

## Follow-on work this creates

Anonymous accounts are ordinary accounts: any administrative touch that
invalidates a session — an email set, a revocation, a disablement, a deletion —
silently destroys the identity of the install holding it, and the app converts
that into permanent orphaning. Two consequences are recorded separately:
0140 for churn 2's open trigger, 0141 for the app's inability to tell a lost
identity from a first run.

Project-level anonymous-user auto-cleanup would fire this for every user on a
schedule. It is **off** on this project (verified in the Identity Platform
config); it must stay off, and turning it on is a decision with data loss on
the other side of it.
