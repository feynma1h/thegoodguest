# 0042 — Upload-session record relaxes to CompleteUntilFirstUserAuthentication (addendum to 0037)

**Date:** 2026-06-01
**Status:** Decided — routed to and signed off by Chat

## Context

0037 persists the per-bundle upload-session record (`upload_sessions/<bundle_id>.json`)
with `NSFileProtectionComplete`. 0040 item 7 makes the premium guarantee that the user
can lock the phone and pocket it immediately after pressing stop: the Phase-1→Phase-2
gate check, `bundle.pb` finalize, `410` re-mint, and the staleness guard all run
OS-managed in the background URLSession completion delegate or on cold relaunch — while
the device may be locked.

These conflict. `NSFileProtectionComplete` evicts the file's key shortly after the device
locks, making the record unreadable while locked. The background completion path needs to
read the record to run the gate (`allNonBundlePbBlobsUploaded`) and to locate `bundle.pb`
and its `session_uri`. So on a locked device the finalize path silently stalls until the
next unlock — exactly the scenario 0040 item 7 promises to handle.

Code's protection-class readout (2026-06-01) confirmed the asymmetry: the record is
`Complete`, but the blob files (`frames/*.jpg`, `depth/*.f32`) and `bundle.pb` are already
`CompleteUntilFirstUserAuthentication` (CAFUFA) — the iOS default, written with no options
in the temp dir. The data the record indexes is already readable-while-locked; only the
index is not.

## What we chose

Relax the upload-session record (the `upload_sessions/` directory and its `.json` files)
from `NSFileProtectionComplete` to `NSFileProtectionCompleteUntilFirstUserAuthentication`,
matching the blobs it indexes.

- Dir create: `FileProtectionType.completeUntilFirstUserAuthentication`.
- File write: `Data.write(options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication])`.

## Why

- CAFUFA is the minimum protection class compatible with any background-while-locked
  upload design, and is the iOS default. Any design that finalizes after lock requires at
  least this; `Complete` is incompatible with the 0040 item 7 guarantee by construction.
- The record holds the `session_uri` bearer map. Its effective life is ≤ ~1 day, bounded
  by the captures bucket lifecycle (age=1) and the `upload_sessions` Firestore TTL (0035),
  not the 7-day GCS nominal — so the marginal at-rest exposure from CAFUFA vs Complete is
  small and time-bounded.
- The record is still encrypted at rest before first unlock (powered-off / pre-first-unlock
  extraction is protected). The relaxation only affects "readable while locked *after* the
  device has been unlocked once since boot" — always true immediately after a capture.
- Firebase's actual root secret (the anon refresh token) stays in Keychain, untouched by
  this change. The session URIs remain derived, regenerable capabilities (0037), not root
  secrets.
- Aligning the index's protection class with the data it points at removes a latent
  asymmetry: there is no security value in protecting the URI map more strongly than the
  blobs it addresses and the `bundle.pb` it finalizes.

## What would change this decision

- If the record ever needs to hold a true root secret, that field revisits Keychain
  specifically (per 0037's own escape clause), not the whole record.
- If background-while-locked finalize is ever dropped (0040 item 7 retracted), `Complete`
  becomes viable again and is the stronger default.

## Verification

True enforcement of the protection class is not deterministically testable in the
simulator. The locked-device finalize behavior is added as an on-device gate in 0041 and
MUST pass on hardware before the first real upload.
