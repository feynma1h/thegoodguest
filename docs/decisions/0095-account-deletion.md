# 0095 — Account deletion: the map, the ordering, and why the identity goes last

**Date:** 2026-08-08
**Status:** Decided

## Context

App Store guideline 5.1.1(v) requires an in-app account-deletion path for any
app that offers account creation, and Sign in with Apple (0051) makes
roomstudio one of those. There is deliberately no iOS sign-out (0064:
launch-time `signInIfNeeded` would immediately re-mint a fresh anonymous UID),
so deletion — not sign-out — is the account operation a user actually gets,
and the web is where it lives.

Firestore never cascades. Deleting a document leaves its subcollections
intact, and no query returns "everything belonging to user X" across
collections. Every collection and every GCS prefix has to be enumerated by
hand, which makes the completeness of that list the whole problem.

## What we chose

`DELETE /account` on api-public, with the map and logic in
`services/api-public/account_deletion.py`.

**The map**, verified against the live project:

| Store | Location | Keyed by |
|---|---|---|
| Firestore | `scenes/{scene_id}` | `user_id` field |
| Firestore | `upload_sessions/{bundle_id}` | `user_id` field |
| Firestore | `upload_mint_quotas/{uid}` | doc id IS the uid |
| Firestore | `conversations/{scene_id}__{uid}` | `user_id` field |
| Firestore | `conversations/…/turns/{index}` | **subcollection — no cascade** |
| GCS | `gs://roomstudio-captures/captures/{bundle_id}/**` | bundle union (below) |
| GCS | `gs://roomstudio-perception-outputs/scenes/{scene_id}/**` | scene id |
| Firebase Auth | the user record | uid |

**Order:** GCS → Firestore → Firebase Auth user.

The token is the target: there is no uid path or query parameter, so the route
cannot be pointed at another account. `confirm_user_id` in the body must match
the token; it is an accident control, not a security one.

## Why

**The bundle-id union is load-bearing.** Bundle ids reach us from two
independent places with different lifetimes: `upload_sessions` carries a
7-day TTL while `scenes` persist. A capture uploaded eight days ago has a
scene and no session; one uploaded thirty seconds ago may have a session and
no scene. Taking either source alone leaks capture blobs, so the plan unions
them.

**The ordering is the recoverability property, and it is not the fast-looking
one.** Deleting Firestore first would make the account *look* gone sooner, but
the deletion plan is DERIVED from those Firestore records — so a failure
between the two steps would leave GCS blobs with nothing anywhere pointing at
them. Unrecoverable by construction. Doing GCS first means any failure leaves
every record intact, a retry re-derives the identical plan, and nothing is
stranded. A storage error therefore aborts the pass *before* Firestore is
touched at all.

**The identity goes last for the mirror-image reason on the user's side.**
While the Firebase user exists they can still sign in and retry. Delete it
first and a mid-way failure locks them out of their own leftovers with no way
back in — the worst possible state, and the one a "delete the login first"
instinct produces.

Everything is idempotent and resumable, so a partial pass is reported as 202
"call again" rather than as damage. The web copy follows that: a partial pass
says the account is intact, never that something went wrong, because nothing
did.

**Two consequences the user is told, not just one.** Everything goes — rooms,
reconstructions, measurements, conversations. AND the phone starts over: the
account being deleted is the iPhone's account, so the capture app opens to a
new empty anonymous identity on its next launch. Users delete from the web but
notice on the phone, so the phone consequence is stated at the point of
decision. Both claims live in `web/src/lib/account.ts` as pure functions with
tests, because understated consequence copy is exactly the kind of thing that
survives review-by-reading.

**`PERCEPTION_OUTPUTS_BUCKET` is production-required and startup-enforced.**
It is the one place the outputs bucket is named by config rather than by data
(the assets route uses each scene's recorded `result_uri`). Absent or wrong,
deletion would report success while every reconstruction survived — a silent
lie of exactly the kind this note exists to prevent. Failing at startup is
strictly better.

## Known residue

- **A scene racing us.** A scene in `processing` holds a perception lease;
  blobs it writes after we sweep its prefix are orphaned under a
  `scenes/{id}/` path with no Firestore doc and no owner. Refusing to delete
  while a scene is processing was rejected: a stuck scene would block deletion
  forever, which is user-hostile and defeats the guideline's intent. The
  `masks.npz` lifecycle rule (0086, 180d) covers part of it.
- **The iOS app does not yet handle its user being deleted underneath it.** Its
  cached credential goes invalid at the next token refresh. Surfacing that as
  "this account is gone, starting fresh" is the iOS follow-up.

## What would change this decision

- **A new per-user collection anywhere in the system.** Add it to
  `plan_account_deletion` and to `test_plan_names_every_known_collection`. The
  test exists so that forgetting fails a build rather than a promise.
- **Accounts big enough that one request cannot finish.** The current pass is
  synchronous with a 32-way pooled blob delete; measured scene footprints are
  87–147 blobs, so a 7-scene account is ~1k deletes in a couple of seconds. At
  a scale where 202s become routine rather than exceptional, this wants to
  become a marked-then-swept background job — the ordering argument above
  carries over unchanged.
- **A retention or legal-hold requirement.** Immediate hard deletion is the
  right default for a consumer product with no such requirement; a grace
  period would change the shape entirely.
