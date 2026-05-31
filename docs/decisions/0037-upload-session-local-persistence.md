# 0037 — Upload-session local persistence: protected file, not Keychain
Date: 2026-05-31  •  Status: Decided  •  Routed to and signed off by Chat

## Context
P3 must persist the /upload_session result locally so P4 can PUT to each
session_uri later. session_uri is a bearer capability — possession alone grants
write to captures/{bundle_id}/{relative_path}. A capture can carry up to ~200
entries.

## What we chose
Persist a per-bundle record {bundle_id, tier, client mint timestamp,
relative_path -> session_uri, manifest path-set} as a file in Application
Support with NSFileProtectionComplete. NOT Keychain.

Implementation:
- Directory: <Application Support>/<bundleIdentifier>/upload_sessions/
  Created with FileProtectionType.complete (= NSFileProtectionComplete).
- File: <bundle_id>.json, written with Data.write(options: [.atomic,
  .completeFileProtection]).
- NSFileProtectionComplete makes the file unreadable while the device is locked;
  the key is derived from the device passcode and discarded at lock time.

## Why
- session_uri is sensitive, so at-rest protection is required —
  NSFileProtectionComplete makes the file unreadable while the device is locked.
- A ~200-entry URI map is the wrong size/shape for Keychain (Keychain is for
  small secrets, not bulk structured data).
- Firebase already stores the actual auth secret (the anon refresh token) in
  Keychain; the session URIs are derived, regenerable capabilities (idempotent
  re-mint via /upload_session), not root secrets — losing the file is
  recoverable by re-calling the endpoint.
- Storing the manifest path-set alongside the URIs lets the client detect drift
  between on-disk artifacts and what was minted, and predict return-stored vs.
  re-mint under the path-set idempotency rule.

## What would change this decision
If the persisted record ever needs to hold a true root secret, revisit Keychain
for that field specifically. If capture sizes shrink to a handful of blobs,
Keychain becomes viable but offers no advantage.
