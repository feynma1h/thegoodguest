# 0141 — a lost identity is not a first run

**Date:** 2026-08-14
**Status:** Decided

## Context

`AuthManager.signInIfNeeded()` guards decision 0036's no-churn invariant with
one condition:

```swift
if Auth.auth().currentUser != nil { return }
```

That condition is true of a genuine first run and equally true of an install
whose stored credential was discarded. Decision 0139 shows the second is a
thing that happens — twice, on the operator's phone, from an ordinary
administrative action — and that the app's response is to mint a fresh
anonymous user which Firebase then persists over whatever was there.

The guard is not wrong; it is under-informed. It is asked a question it has no
way to answer, and it answers the same way either way.

## What we tried

The app already holds two signals that fail independently of each other and of
Firebase's credential:

- the **device UUID**, in the Keychain, in the same access group as Firebase's
  item — so reading it back proves the Keychain is answering;
- **capture records**, in Application Support, outside the Keychain entirely —
  so they outlive a Keychain read failure.

Reading them costs nothing and required only one new affordance: a non-minting
`DeviceIdentity.existingDeviceId()`. A minting read would have destroyed the
signal, since every launch after the first would then look like an install that
had captured, and it would create the item long before a bundle needs it.

## What we chose

`IdentityContinuity.read(hasFirebaseUser:hasDeviceIdentity:hasCaptureRecords:)`
— a pure function, table-pinned, in the house pattern — classifies the launch:

| user | device UUID | records | reading | meaning |
|---|---|---|---|---|
| yes | any | any | `continuous` | nothing to report |
| no | yes | any | `credentialLost` | the Keychain answers; the credential is gone |
| no | no | yes | `keychainUnavailable` | the Keychain is silent; the credential may be intact |
| no | no | no | `firstRun` | genuinely new |

`AuthManager` logs the reading immediately before minting, at `fault` level for
the two loss cases. **It does not change whether the app signs in.** Both known
churns would have been reported as `credentialLost` — the device UUID was
readable across both (0138) and capture records were on disk — and that
reading is the pin that would fail if the classification ever regressed.

The call sits inside the single-flight task rather than beside the guard. The
store is an actor, so awaiting it beside the guard would put a suspension
between the `currentUser` check and the `signInTask` assignment, which is
exactly the double-sign-in race that assignment exists to close.

## Why

The two loss readings want different cures, so collapsing them would throw away
the distinction that decides 0140's open question. `keychainUnavailable` is
recoverable by waiting — the SDK is already waiting, on
`protectedDataDidBecomeAvailable` — and minting is the one thing that makes it
unrecoverable. `credentialLost` is not recoverable locally at all; the old UID
is intact server-side and owns real rooms, but nothing on the device can prove
which UID that was.

Instrumenting rather than deciding is deliberate. Diagnosis was this thread's
deliverable, and the behavioural question below is genuinely the operator's:
both plausible answers cost a real user something.

## What would change this decision

An install that has never completed a capture has no device UUID, because
`DeviceIdentity` mints only at bundle assembly. A credential lost on such an
install reads as `firstRun` and is invisible to this instrument. That is the
same blind spot 0138 recorded for the Firestore sweep, and it matters less:
an install with nothing captured has nothing to orphan.

If Firebase is ever configured with `useUserAccessGroup`, the device UUID stops
sharing a group with Firebase's credential and stops being evidence that the
Keychain is answering. The reading would need rebuilding on a different signal.

## Follow-on work this creates

**One question for the operator, and it is a product question.** Today a lost
identity passes silently into `signInAnonymously()`. The alternatives:

- **Keep minting, and say so.** The app carries on, but the person is told
  their previous rooms are no longer reachable from this phone. Honest, and it
  makes a silent failure visible — at the cost of a frightening message that,
  in the `keychainUnavailable` case, may be wrong.
- **Refuse to mint on a loss reading, and offer sign-in.** No second identity is
  created, so nothing is orphaned and a linked account would restore the rooms
  outright. At the cost of an app that will not capture until the person acts,
  on a phone that may be perfectly healthy.
- **Split by reading**: wait on `keychainUnavailable` (the SDK is already
  waiting, and minting is what makes it permanent), surface on
  `credentialLost`. Most faithful to the evidence, most work, and it commits to
  a classification that has never yet run in production.

The third depends on 0140 resolving, since it acts on a distinction no observed
churn has exercised. The first two do not.

Separately: the churn is a strong argument for signing in early rather than at
first share. A linked account survives every path in 0139 — the rooms follow
the account, not the install — which turns this from data loss into an
inconvenience.
