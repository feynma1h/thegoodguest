# 0118 — iOS Google linking: the second provider rides Apple's rails

**Date:** 2026-08-10
**Status:** Decided

## Context

Decision 0094 added Google as a web read-provider and named its one structural
asymmetry: iOS linked Apple ONLY, so Google's web refusal was PERMANENT — a
Google sign-in could find an account but never cause one to become findable.
0094 also named the single change that fixes it: iOS ships Google linking.
The case was live, not theoretical: the operator's rooms sit across two
identities (the Gate-B UID carrying google.com, the 16 Pro's anonymous UID
carrying the newer captures), Apple linking is enrollment-gated on the paid
Developer Program, and there was no path to unify.

## What we tried

- **A parallel Google path** (its own result enum, its own error classifier,
  a `GoogleAuthManager`). Rejected before writing it: the failure set that
  matters is defined by the Firebase LINK stage, which is provider-
  independent; each provider contributes only its own "user closed the sheet"
  code. Two copies of conflict/cancel/retry classification are two places for
  the conflict case to rot — the argument 0094 already made for the web's
  single `signInAsReader` body, applied to iOS.
- **Hiding the second provider once one is linked.** Rejected: the web reads
  either provider (0094), so an identity carrying both is strictly more
  reachable, and the operator's split-identity situation is exactly the state
  where adding the second provider to one UID matters.
- **Hand-drawing the Google button.** Rejected: the sheet already uses
  Apple's native `SignInWithAppleButton` on the reasoning that identity
  buttons are not re-drawn in-house; `GoogleSignInButton` from
  GoogleSignInSwift is the same choice for Google (branding compliance for
  free, one extra product from the same package).

## What we chose

Google is a second LINK provider through the SAME core, with every 0051/0064
invariant intact:

- `AuthManager.link(credential:)` is the one private core both
  `linkAppleAccount` and the new `linkGoogleAccount` run through: link(with:)
  on the EXISTING user, UID asserted unchanged (a mismatch refuses + logs
  `fault` rather than adopting a new identity), failures classified by the
  shared `AccountLinking.classifyLinkError` (three domains: Apple
  authorization, Google sign-in flow, Firebase link stage). `AppleLinkResult`
  became the provider-generic `LinkResult`.
- A conflict surfaces as the explicit switch/keep choice with the cost
  stated; the alert copy names the provider that was attempted ("This Google
  account already has a home"). `switchToExistingAccount` is unchanged and
  remains the app's only deliberate UID-change path.
- There is still NO iOS sign-out.
- `LinkedProviders` (pure, table-pinned) derives per-provider flags from
  `providerData`; the new `isLinked` (any provider) is what "signed in"
  surfaces read — ProfileView, DoorwayView's `signedIntoWeb`, ContentView's
  rollback control. `isAppleLinked`/`isGoogleLinked` stay for per-provider
  display.
- Sheet order is Apple first, Google second — matching the web's SignInPanel
  and App Store guideline 4.8's posture (Google-only sign-in obligates
  offering Apple; keeping Apple primary is the compliant shape even while the
  SIWA entitlement is enrollment-gated). A user linked with one provider is
  offered the other, with copy saying either reaches the same rooms.
- `classifyLinkError` gained `.emailAlreadyInUse` awareness in documentation
  only: it stays `.other` (test-pinned) because it carries no switchable
  credential — Google's email colliding with another account's DIFFERENT
  provider must not masquerade as a switchable conflict.

Notably absent from the entitlements story: Google needs NO Apple
entitlement, so the real on-device link works under the personal-team
entitlements workaround TODAY — the first provider verifiable on hardware
before enrollment lands.

## Why

One sentence from 0064 governs everything: the UID that owns the captures
must never change without the user knowingly choosing it, and accounts must
be born where the rooms are. Google inherits that by running through the same
code that enforces it, not through a copy that promises to. The simulator
walk proved the integration seam end-to-end short of a real login (Google's
OAuth page rendered "to continue to roomstudio", so Google's server accepted
the client ID + redirect scheme; cancel returned silently through the shared
classifier), and 12 new pins hold the pure parts.

## What would change this decision

- **This ships to the phone.** Then 0094's pinned web copy distinction
  (Google's refusal deliberately does NOT point at the capture app) must be
  retired DELIBERATELY on the web side — that retirement is deferred until
  the phone carries this build, and web/ is another session's lane.
- **Apple enrollment lands.** Gate A (on-device Apple link) proceeds
  unchanged; nothing here blocks or is blocked by it.
- **A third provider.** The classifier and LinkedProviders extend by one case
  each; if the provider does not verify email, 0094's same-email phishing
  caveat applies before adding it.
