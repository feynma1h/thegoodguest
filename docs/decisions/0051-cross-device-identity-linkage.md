# 0051 — Cross-device identity: upgrade anonymous auth to a linked real sign-in

**Date:** 2026-07-17
**Status:** Decided

## Context

The web app needs a login, since it's the surface where users browse/edit/share the scenes
captured on their phone. The iOS app (decision 0036 and CLAUDE.md's iOS P3 entry) uses
Firebase **anonymous** auth: a UID scoped to that one device install, cached and never
churned. Opening the web app in a browser mints a separate, unrelated anonymous UID with no
connection to the phone's captures. Without solving this, "log in on the web" has no answer
for "log into what."

## What we tried

- **QR-code / pairing-code handoff**: web app displays a code; the already-signed-in-anonymously
  iOS app scans or enters it, granting that browser session access to its scenes via a custom
  backend pairing endpoint. Would work, but requires new backend infrastructure (a pairing
  endpoint, a grant/token model) and has no real "account" concept — revocation, multi-device
  access, and re-pairing all need bespoke design with no precedent elsewhere in the stack.
- **Defer entirely**: scaffold the web app against a fixed dev scene or dev-only auth, decide
  cross-device identity later. Rejected because "login" was explicitly in scope for the first
  version of the web app, not a v2 concern.
- **Upgrade anonymous auth to a real sign-in, linked to the existing credential**: iOS gains
  a "Sign in with Google/Apple" option that calls Firebase's account-linking API on the
  *existing* anonymous user (not a fresh sign-in) — the UID stays the same, it just gains a
  persistent credential. The web app signs in with that same method and reads that UID's
  scenes directly; no new backend infrastructure needed.

## What we chose

Upgrade-and-link: add a real sign-in method on iOS that links to the existing anonymous
credential, and have the web app authenticate with the same method against the same Firebase
project.

## Why

This is a standard, well-supported Firebase pattern (`linkWithCredential`) rather than a
bespoke pairing protocol — no new backend surface, no new revocation/grant model to design
and secure. It also means every scene created under the anonymous UID before the user ever
signs in stays reachable after linking, since linking preserves the UID rather than replacing
it. The pairing-code alternative would have required building and securing a whole parallel
authorization mechanism for a problem Firebase already solves natively.

One real constraint surfaced during this decision: if iOS offers Google Sign-In, Apple's App
Store review guidelines (4.8) generally require also offering Sign in with Apple as an
equivalent option. The simplest compliant path is to ship Sign in with Apple only first (it
also works in-browser via Apple's JS SDK, so it's consistent across both iOS and web), and
add Google later only if the convenience is worth the added App Store obligation.

This is new iOS scope with no prior board entry — the linking UI, the "why am I being asked
to sign in" moment, and the migration for any pre-existing anonymous users all need design
before the web app's login screen can actually work end-to-end. It is not yet built on either
side (see "Next on the board", item 6).

## What would change this decision

- If Firebase deprecates or changes anonymous-to-real account linking semantics.
- If product direction shifts to wanting the phone and the browser to be independently
  authenticated (e.g. a household/shared-scene model rather than one-user-one-account),
  which would reopen the pairing-code design instead of strict account linking.
