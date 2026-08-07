# 0094 — Google as an additive web read-provider; never-create is provider-agnostic

**Date:** 2026-08-08
**Status:** Decided

## Context

Decision 0051 rooted identity on the phone: the iOS app mints an anonymous
Firebase UID, links Sign in with Apple to it (linking preserves the UID), and
the web signs in with that same Apple ID to READ the UID's scenes. 0064
recorded Apple as the provider choice.

That left the entire web auth path unverifiable. The Apple provider is gated
on Apple Developer Program enrollment — the live gate returns
`OPERATION_NOT_ALLOWED : Code flow is not enabled for Apple.` — so Gate B
(browser sign-in lists the operator's real rooms) has never run, and neither
has anything downstream of it. The operator reopened the provider choice
ADDITIVELY: add Google so the web path becomes testable now, with Apple
staying primary.

## What we chose

`signInWithGoogle()` alongside `signInWithApple()` in `web/src/lib/firebase.ts`,
sharing ONE body (`signInAsReader`) that carries the never-create guard.

**The never-create rule is provider-agnostic.** A Google sign-in that comes
back `isNewUser` is undone exactly as Apple's is — delete the fresh user (or
sign out if the delete fails) and throw a typed refusal. The web creates no
Firebase user under any provider.

Error types are now a small hierarchy: `IdentityNotLinkedError` (base, carries
`providerId`) with `AppleIdNotLinkedError` and `GoogleAccountNotLinkedError`
under it. `SignInPanel` (replacing `AppleSignInButton`) renders Apple first,
then Google, and catches the base type.

## Why

The failure the guard prevents is identical for Google. An empty web-born
Google account permanently claims that Google identity; the LATER iOS link
attempt — from the phone whose UID owns the actual rooms — then hits
`credential-already-in-use` against an account that owns nothing. Same
mechanism, same damage, so the same refusal. Writing the guard once rather
than twice is the point: a second copy is a second place for it to rot, and
this one is the security property of the whole web surface.

**The asymmetry, recorded because it is not obvious and it bites.** iOS links
*Apple only* — there is no `linkGoogleAccount`. So the two refusal branches
mean different things:

- Apple's refusal is TRANSIENT. "Sign in on your iPhone first" genuinely
  resolves it: the iOS link attaches apple.com to the room-owning UID, and
  the next web sign-in finds it.
- Google's refusal is PERMANENT until either (a) iOS ships Google linking, or
  (b) the account already carries a google.com credential. A Google sign-in
  can only ever *find* an account, never cause one to become findable.

The copy follows the mechanism rather than the symmetry: the Google refusal
deliberately does NOT say "open the capture app and sign in there" — that
would send the user somewhere that cannot help them. It says rooms live with
the account they signed into on the phone. A test pins that distinction, so a
future copy edit that collapses the two messages fails loudly.

Consequence for Gate B: because the operator's real UID
(`cHfMlULde2WO5x4i1kZ014VPPbI2`) is a *pure anonymous account* — verified
this session: no email, no `provider_data` — no web sign-in of any provider
can reach it as shipped. Gate B needs a google.com credential attached to
that UID out-of-band, which is the same operation the iOS link performs. That
bridge is an operator/dev action, not product behaviour, and it is recorded
with the gate rather than built into the app.

## What would change this decision

- **iOS ships Google linking.** Then Google's refusal becomes transient like
  Apple's, the two copy strings converge, and the pinned distinction should be
  retired deliberately (not silently). This is the single change that makes
  Google generally useful rather than test-useful.
- **Apple enrollment lands and Apple alone proves sufficient.** Google could
  then be dropped — but only if no real user has signed in with it, since
  removing a provider strands whoever used it.
- **A provider that does not verify email is added.** The guard still holds,
  but Firebase's same-email account linking (this project runs
  `allowDuplicateEmails: false`) gets a phishing surface that Apple and Google
  do not have. Re-examine before adding one.
