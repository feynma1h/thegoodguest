# 0022 — Ingest must propagate `user_id` to scene on all ingest branches

**Date:** 2026-05-27
**Status:** Accepted

## Context

First end-to-end execution of `infra/RUNBOOK.md` Phase 7 mode 2 (`skip-blob`) surfaced
that ingest's failed-incomplete branch creates a scene document without populating
`user_id`. `GET /scenes/by-bundle/{bundle_id}` then returns 403 `"scene has no owner"`
— the defensive 403 from decision 0019, which was designed to fire exactly when
`scene.user_id is None`.

Decision 0019 framed this 403 as a diagnostic signal: *"the case shouldn't happen in
normal operation and is a diagnostic signal when it does."* The signal fired on the
first real run of the failure path. The happy-path scene from mode 1 had `user_id`
set correctly (polling returned 200/queued, not 403), so the bug is specific to the
existence-check-failure branch — happy and failed-incomplete are using different scene-
creation code paths, and only one of them propagates `user_id`.

The `upload_sessions/{bundle_id}` document does have `user_id` (Firebase UID resolved
at `/upload_session` time, per decision 0017). Ingest has the data; it's not reading
or not writing it on the failed branch.

## What we tried

Considered treating this as a contract change to `/scenes/by-bundle/{bundle_id}` —
relaxing the 403-on-`user_id=None` defense to a 200 with some null marker. Rejected
immediately: the 403 worked as designed. The endpoint is correct; the ingest writer
is wrong.

Considered whether the two ingest branches should be unified into one
scene-creation code path. Likely the right shape but out of scope for this decision —
the immediate fix is "the failed branch reads `user_id` from the upload_sessions doc
and writes it to the scene." Unification belongs in a follow-up if the divergence
turns out to be load-bearing for other reasons.

Confirmed there are exactly two scene-creation sites in the ingest handler
(since renamed `services/api-internal/ingest_server.py`), both via
`new_scene()` + `repo.create()`. No third site means
no shared helper is required; the fix is a one-liner in `_handle_failed_incomplete`.

## What we chose

In `_handle_failed_incomplete`, after `scene.bundle_id = bundle_id`, read `user_id`
from `_get_upload_session_repo().get_user_id(bundle_id)` and assign it to
`scene.user_id` before `repo.create(scene)`. The `get_user_id` method is already
on the `UploadSessionRepository` interface (both in-memory and Firestore
implementations). The pattern mirrors the existing FCM token lookup in the same
function.

Verification: `skip-blob` smoke mode reaches `status=failed_incomplete` with
`missing_paths` containing the dropped path, and `GET /scenes/by-bundle/{bundle_id}`
returns 200 (not 403). The defensive 403 in api-public stays in place as the
diagnostic signal it was designed to be.

## Why

The bug is a missed invariant, not a design question. Every scene the system creates
has an owner, by construction — the upload that produced it was authenticated.
Decision 0019's 403 was scaffolding to catch exactly this class of bug, and it did.
Removing the 403 would silence the alarm; fixing the writer addresses the cause.

## What would change this decision

- A future ingest branch needs to create a scene without an associated upload
  (e.g. an admin-initiated re-ingest, a backfill job). At that point `user_id`'s
  invariant changes from "always set" to "set or explicitly system-owned," and
  the 403's semantics need to be revisited alongside.
- The two ingest branches turn out to share enough state that unifying them into
  one scene-creation code path is cheaper than coordinating the invariant across
  both. Doesn't change this decision but supersedes it.
