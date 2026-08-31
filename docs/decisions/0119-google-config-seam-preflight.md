# 0119 — Google's config seam: committed URL scheme, gitignored client ID, preflight instead of a crash

**Date:** 2026-08-10
**Status:** Decided

## Context

Google Sign-In on iOS needs two config values that live in different places
with different git status: the iOS OAuth client ID (in the GITIGNORED
GoogleService-Info.plist) and its reversed form as a URL scheme in the app's
Info.plist (which must be COMMITTED — this project has no checked-in
Info.plist at all; every key is generated from INFOPLIST_KEY_* build
settings, and CFBundleURLTypes is an array-of-dicts no such setting can
express). Two traps sharpened the problem: the checked-in-adjacent local
plist was STALE — it predated the iOS OAuth client that Firebase auto-created
when the operator enabled the Google provider for Gate B (2026-08-08), so it
carried no CLIENT_ID/REVERSED_CLIENT_ID at all — and GIDSignIn raises an
NSException (uncatchable from Swift) at sign-in time when the scheme is
missing, read directly from the SDK source at `GIDSignIn.m:740`.

## What we tried

- **Confirming the OAuth client exists before building anything**: the
  Firebase Management API (`projects.iosApps.getConfig`, operator ADC +
  `x-goog-user-project: roomstudio`) returned the current config WITH
  CLIENT_ID and REVERSED_CLIENT_ID — so the blocker was a stale local file,
  not missing provisioning. The same call is the programmatic equivalent of
  the console re-download and refreshed the worktree's gitignored plist.
- **Putting the partial Info.plist inside the TheGoodGuestCapture/ synchronized
  folder** with a membership exception. Rejected: that is the exact
  "multiple commands produce Info.plist" trap the Live Activity hit (its
  exception set exists to escape it); a top-level file referenced only by
  build setting — the TheGoodGuestCapture.entitlements precedent — avoids the
  trap instead of managing it.
- **Failing (vs skipping) the drift test on a stale plist.** Rejected: on a
  machine whose plist predates the OAuth client, runtime already degrades
  honestly (preflight refuses with the re-download message), so a red suite
  would punish a state the product handles; the skip names the fix.

## What we chose

- `TheGoodGuestCapture-Info.plist` at the project top level, containing ONLY
  `CFBundleURLTypes` with the reversed-client-ID scheme (a public identifier
  — it ships in every app bundle; the web committed its Firebase config on
  the same reasoning). Wired via `INFOPLIST_FILE` alongside
  `GENERATE_INFOPLIST_FILE = YES` — the merge the Live Activity extension
  already relies on; verified in the built product (URL scheme AND generated
  keys present).
- `SignInWithGoogle.preflight(clientID:registeredURLSchemes:)` — pure,
  table-pinned — runs before every GIDSignIn start and turns both stale-
  config shapes into readable refusals: `missingClientID` ("re-download the
  plist") and `schemeNotRegistered` (the state the SDK would turn into an
  NSException). The client ID itself is read from `FirebaseApp` options at
  call time, never duplicated into Info.plist as GIDClientID — one source.
- `test_appBundle_registersRedirectSchemeForLiveClientID` is THE drift pin:
  it derives the scheme from the app bundle's real plist and asserts the
  bundle registers it — the only thing that notices when a regenerated OAuth
  client or a stale local plist splits the committed scheme from the
  gitignored client ID. It skips (with the named cure) when the plist or its
  CLIENT_ID is absent, per the worktree note in CLAUDE.md's iOS test policy.

## Why

The scheme and the client ID are one fact stored in two files owned by two
mechanisms (git vs console download). Every failure mode here is a quiet
divergence that surfaces as a crash in the SDK's code, not ours — so the
seam gets a preflight that makes divergence speak, and a pin that makes it
fail loudly on machines where it can be confirmed. The simulator walk proved
the happy path through the REAL seam: preflight passed, the
ASWebAuthenticationSession opened, and Google's server accepted the client
ID + redirect scheme ("Sign in to continue to roomstudio").

## What would change this decision

- **The OAuth client is regenerated** (new client ID): the drift pin goes
  red naming the fix — update TheGoodGuestCapture-Info.plist's scheme and
  re-download the plist. That is the designed failure, not a re-open.
- **A second URL scheme joins the app** (deep links, the QR bridge's real
  handoff): CFBundleURLTypes grows a sibling entry in the same file; the
  onOpenURL handler in TheGoodGuestCaptureApp then needs routing beyond the
  unconditional GIDSignIn handoff comment it carries today.
- **GoogleSignIn stops raising and starts throwing** on a missing scheme:
  preflight's schemeNotRegistered leg becomes defense-in-depth rather than
  crash prevention; keep it — the message is still better than the SDK's.
