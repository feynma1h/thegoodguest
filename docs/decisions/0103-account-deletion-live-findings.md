# 0103 — Account deletion: two defects that only a live probe could find

**Date:** 2026-08-08
**Status:** Decided
**Relates to:** 0095 (account deletion), 0088/0090 (IAM least privilege), 0098

## Context

`DELETE /account` (0095) was built, unit-tested and committed, but had never
run against the real project. Shipping it meant a first execution against a
real Firebase Auth user and two real GCS buckets. So before trusting it, the
endpoint was probed on the deployed service with a **throwaway** anonymous
account seeded with one record in every target named in `account_deletion.py`'s
map — including the two that the module itself flags as easy to get wrong: the
`turns` SUBCOLLECTION (Firestore does not cascade) and the bundle-id UNION
across `scenes` ∪ `upload_sessions`.

The data half was correct on the first attempt, union and subcollection
included. Two defects sat past it, and **neither is visible to the unit
tests**, because those inject fakes for exactly the two clients that failed.

## Defect 1 — the runtime SA could not delete the identity

The first probe returned:

```
500 {"error": "deletion_failed", "detail": "nothing was left in a partial state;
     try again (... insufficient permissions ... (INSUFFICIENT_PERMISSION).)"}
```

with every Firestore record and every GCS blob **already gone** and the user
still able to sign in. `api-public-runtime` had no permission to delete a
Firebase Auth user, so `auth.delete_user()` raised at the last step of the pass.

Two things make this worse than a missing grant usually is. The failure lands
*after* the irreversible part, so the account is unrecoverable and the login
survives — the worst possible half. And the message says "nothing was left in a
partial state", which was flatly untrue: everything but the identity was gone.

Fixed with a **custom role**, `apiPublicIdentityDeleter`, holding exactly
`firebaseauth.users.delete`, granted in `deploy_api_public.sh`. The predefined
`roles/firebaseauth.admin` would also grant `users.create/update/get/sendEmail`
and the auth-config surface; this service only ever removes the caller's own
identity, after their data is gone. Same reasoning and same shape as
`perceptionFcmSender` (0090).

The sibling grant — `objectAdmin` on the outputs bucket, previously
`objectViewer` — was a known precondition and is now applied by the deploy
script rather than left as a manual step, so a fresh project cannot get a
deletion path that silently no-ops.

## Defect 2 — the second call 500'd on an account deleted perfectly

With the grant in place the first call returned `200 {"deleted": true,
"identity_deleted": true, "counts": {"rooms": 1, "conversations": 1,
"conversation_messages": 2, "upload_sessions": 1, "files": 5}}` and every
target verified empty. The **second** call returned:

```
500 {"error": "deletion_failed", "detail": "... (No user record found for the
     given identifier (USER_NOT_FOUND).)"}
```

against the endpoint's own docstring: *"Idempotent and resumable: a second call
on an already-deleted account finds nothing left and returns 200 with zero
counts."* Firebase raises `UserNotFoundError` once the user is gone, and the
route's blanket `except Exception` reported it as failure.

This is not a probe artifact. A Firebase ID token stays cryptographically valid
for **up to an hour** after its user is deleted, so any client retry inside that
window returns an error for an operation that succeeded — and a retry is exactly
what the 202 "call again" contract asks the client to do.

Fixed in the deleter: an absent identity **is** the desired end state, so it
counts as success. The catch is deliberately narrow — any other auth failure
still propagates, pinned by a test, so the Defect-1 class stays loud.

## Why the tests passed anyway

`test_is_idempotent` existed and was green the whole time. Its `FakeAuth`
never raises, so it asserted idempotency against a double that could not
express the failure. The lesson generalises past this file: **a fake that
cannot fail the way the real client fails turns a test into a tautology.** The
two new tests use a double that raises, named exactly as Firebase names the
class — load-bearing, because `firebase_admin` is not installed in the test
environment (the same "deferred: not installed in tests" shape `auth.py` uses),
so the deleter matches on `__name__` rather than isinstance.

## What would change this decision

- If `firebase_admin` ever becomes a test-environment dependency, replace the
  `__name__` match with a real isinstance check and delete the naming
  constraint from the test double's docstring.
- If deletion grows a step after the identity (it should not — the module
  argues identity goes last), the "absent is success" rule has to be
  re-examined for that step too.
- If Firebase renames `UserNotFoundError`, the narrow catch silently becomes a
  re-raise and the 500 returns. That is the safe direction to fail, but the
  symptom would be the second call 500ing again.
