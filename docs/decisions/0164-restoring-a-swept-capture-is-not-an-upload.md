# 0164 — restoring a swept capture is not an upload

**Date:** 2026-08-13
**Status:** Decided

## Context

The captures bucket sweeps at age=1d, so the four preserved walk rooms are
never in it. Any re-drive needs their bundles back first —
`tools/reenqueue_scene.py` existence-checks the bundle blob and refuses with
exit 3 when it is gone — and this lane needed all four back at once.

The recorded procedure, used at RP-8 and again on 2026-08-08, is to re-upload
as the client would: mint a custom token for the owning uid, exchange it for
an idToken, call `POST /captures/{id}/upload_session`, and PUT every blob to
its signed resumable URI. That needs `roles/iam.serviceAccountTokenCreator`
on `firebase-adminsdk-fbsvc`, which was deliberately REVOKED on 2026-08-08
on 0088's recommendation, with re-granting recorded as an operator decision
made per walk.

## What we tried

Copying the preserved local bundles straight into
`gs://roomstudio-captures/captures/<bundle_id>/` with `gcloud storage rsync`
under operator ADC. Four bundles, 4,447 objects, ~950 MB, 952 s total.

Then checking what that skipped. Every blob's finalize event reached the
Eventarc trigger; the non-`bundle.pb` ones were dropped by the app-side path
filter (0023's `eventarc_ignored`), and all four `bundle.pb` events were
handled by ingest with the READY-idempotency rule, each naming the scene it
already had:

    Eventarc: bundle_id=223aca8e-… already has scene a71d125f-… in status
    SceneStatus.READY — skipping

Firestore afterwards holds exactly one scene per bundle_id, each with its
original scene id. All three comparable rooms then re-drove warm and reached
`ready` — rp7 in one round, rp6g1 in 61 s, spike in 101 s.

## What we chose

For a re-drive of a scene that already exists, restore the bundle by writing
the blobs directly. Keep the mint path for what it is for.

## Why

The mint is not a storage mechanism, it is a trust boundary. It exists so an
untrusted client can get scoped, size-declared, quota-charged write access to
a prefix it does not own: it claims the bundle_id atomically for a uid (0086),
charges a mint against the per-UID daily quota (0087) and a capture against
the daily ceiling (0098), and requires `expected_size_bytes` so GCS enforces
the declared size. An operator restoring a capture that this project captured,
for a scene that already exists and already belongs to the right uid, is not
that actor and needs none of those protections — the ownership question was
settled when the capture was first made.

Nothing downstream consults the session. `/process` resolves blobs by the
relative paths inside `bundle.pb`, so bytes at the right path are the whole
requirement, and the two gates that matter — the ingest validation gate and
`/process` itself — run identically either way.

The practical gain is that a routine operation stops requiring a revoked
impersonation grant to be re-granted. 0088 revoked it because a standing
ability to mint tokens for arbitrary users is a large surface for a small
convenience; every re-grant is a chance to forget the revoke. It also avoids
charging the operator's own daily capture ceiling for restoring a room they
captured three weeks ago, and sidesteps the canonical-UUIDv4 check that the
spike bundle's deterministic id tripped at RP-8.

The honest cost: a direct write bypasses `validate_manifest`'s path grammar
and the declared-size enforcement, so a botched restore puts a malformed blob
set in place instead of being refused at the door. That is acceptable here
because the failure is visible immediately and locally — the next re-drive
fails or produces a wrong manifest, on a scene whose correct manifest is
already recorded — and because the operator is copying bytes this repo
preserved rather than composing a manifest by hand.

## What would change this decision

A capture that has NO scene is an upload, not a restore, and belongs on the
mint path: ingest's skip is what makes this safe, and it only fires because
the scene exists and is terminal. A scene in a non-terminal state would be
re-ingested rather than skipped.

If the captures bucket ever gains a consumer that trusts upload-session
metadata rather than reading the bundle, the two paths stop being
interchangeable and this reverts.

If `force_remint` (0116) ever becomes the operator's restore path — it now
vends fresh URIs for a consumed session — the mint route would no longer need
an impersonation grant, at which point it is a fair competitor again. It
still charges quota, so this would remain the cheaper route.
