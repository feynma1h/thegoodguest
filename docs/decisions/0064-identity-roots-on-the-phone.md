# 0064 — 0051 implementation: identity roots on the phone

**Date:** 2026-07-22
**Status:** Decided

## Context

Decision 0051 chose upgrade-and-link: iOS upgrades its anonymous Firebase user to a
real sign-in by LINKING (UID preserved), and the web signs in with the same method,
Apple-only first. Building it (branch `ios-0051-signin`) forced three edge-behavior
decisions the code cannot explain by itself — plus one shipping decision when the
personal Apple team turned out unable to provision any of it.

## What we tried

- **Letting web sign-in create the Firebase user when the Apple ID has no account
  yet** (the SDK's default). Rejected: capture is iOS-only, so a web-born account
  owns nothing and can never own anything — but it permanently claims the Apple ID.
  The phone's later link attempt (from the anonymous UID that owns the actual rooms)
  then hits `credentialAlreadyInUse` against an empty account: the user must either
  abandon their rooms or keep an Apple ID welded to a dead account. A deadlock
  manufactured entirely by sign-in order.
- **iOS sign-out, for symmetry with the web.** Rejected: `signInIfNeeded()` at
  launch mints a fresh anonymous UID whenever there is no current user, so sign-out
  + relaunch = a new UID and every local record orphaned — 0036's churn,
  self-inflicted.
- **Silent adoption on link conflict** (auto-sign-in with the SDK's updated
  credential when the Apple ID already belongs to another account). Rejected: it
  swaps the UID out from under the install; rooms scanned before sign-in silently
  vanish with no explanation.
- **Switching to Google Sign-In when the personal team couldn't provision Sign in
  with Apple** (2026-07-22: the SIWA entitlement AND the web Services ID both
  require the paid Developer Program). Rejected: App Store guideline 4.8 forces
  offering Sign in with Apple eventually anyway, so Google-now means building and
  maintaining both flows for a delay, not a saving; enrollment also unblocks
  APNs/FCM (board item 2) and TestFlight, which the board already needs.

## What we chose

- **The web is a reader of identity, never a creator.** `signInWithApple()` deletes
  any just-created user (`isNewUser`) and throws `AppleIdNotLinkedError`, whose copy
  points at the iPhone. The Apple ID is claimed exactly once, on iOS, by linking.
  (If the delete itself fails, sign out and still refuse — a stray empty user is the
  lesser evil, and the retry copy re-points at iOS.)
- **No sign-out on iOS.** The install keeps its identity; the web is where sign-out
  lives.
- **Conflict = explicit choice.** SignInSheet offers "Use that account" with the
  cost stated (rooms scanned on this phone before signing in won't appear there)
  against "Keep this phone's rooms". `switchToExistingAccount()` is the one
  deliberate UID-change path in the app.
- **Enroll in the Apple Developer Program** rather than reopen 0051's provider
  choice. The branch is committed code-complete with both verification gates
  (on-device link, web E2E) blocked on approval; the post-enrollment runbook lives
  in CLAUDE.md's What-does-NOT-work entry.

## Why

One invariant underneath all of it: **the UID that owns the captures must never
change without the user knowingly choosing it, and accounts must be born where the
rooms are.** Every rejected path violates that invariant in a way that surfaces
weeks later as "my rooms are gone" — the least debuggable failure a user can
report, because nothing crashed and every system behaved as designed.

## What would change this decision

- A non-iOS capture path (web upload, Android). Web-born accounts stop being empty
  by definition, and the never-create guard needs a real design instead of refusal.
- Server-side scene re-parenting (a backend op moving scenes between UIDs).
  Conflict resolution becomes a merge instead of an either/or.
- A redesigned launch flow with an explicit signed-out state (no auto-mint at
  launch). iOS sign-out becomes buildable — but only as a coupled change with that
  flow, never alone.
