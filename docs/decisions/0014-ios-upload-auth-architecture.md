# 0014 — iOS upload + auth architecture

**Date:** 2026-05-26
**Status:** accepted

## Context

Track B needs the iOS app to ingest captures into the existing backend without
degrading the experience that justifies the product. The capture flow has to
feel like: user sweeps the room, taps done, locks the phone, puts it in their
pocket, and a notification arrives when the scene is ready. That experience
constraint shapes the architecture more than any infrastructure argument.

Two coupled questions: how does the iOS client authenticate, and how does it
move ~hundreds of MB of pixel data + bundle.pb to the backend.

## What we considered

**Auth: Sign-in-with-Apple direct vs. Firebase Auth.** Apple-direct means
shipping no Google SDK in the iOS binary and 40 lines of JWT verification
backend-side. Firebase Auth means a ~3 MB SDK and one line of middleware.
Initially leaned Apple-direct on aesthetic grounds (Apple-feeling app),
walked back when the cost of building a token-refresh service became
explicit, and walked back further when the live-state experience (foreground
Firestore listeners + background FCM) made Firebase iOS SDK load-bearing
regardless of the auth choice.

**Upload: proxy through ingester vs. direct-to-GCS via signed URLs.**
Proxy keeps auth simple (one request, one JWT) but puts Cloud Run on the
pixel-data path and loses resumability. Direct-to-GCS matches the proto's
design intent and pairs cleanly with iOS `URLSession` background tasks.

**Bundle.pb routing: POST to /ingest as request body vs. upload to GCS like
everything else.** POSTing keeps the ingester as the validation gate.
Uploading bundle.pb to GCS keeps the iOS app out of the critical path
entirely — the upload can complete with the app suspended.

**Ingest trigger: client-initiated POST vs. Eventarc on bundle.pb finalize.**
Client-initiated requires the app to be alive to fire the final call.
Eventarc removes the app from the critical path.

**Existence-check race handling: patient retry (wait 30s, re-check) vs.
fail-fast with retry path.** Patient retry would handle a race condition
between blob finalize events and bundle.pb finalize event — but the race
doesn't exist if the client sequences bundle.pb to upload last, since
`URLSessionDelegate.didCompleteWithError` fires only after GCS finalizes the
object and GCS is strongly consistent for read-after-write. Patient retry
was solving an imaginary problem.

## What we chose

1. Firebase Auth, anonymous-first. App launches into a capture button, not a
   sign-in screen. Anonymous Firebase UID on first launch. Sign-in-with-Apple
   prompted at first persistence event (open library, share scene, open on
   web); `linkWithCredential` upgrades the anonymous UID without data loss.
   `user_id` in the proto is the Firebase UID.

2. All uploads direct-to-GCS via `URLSession` background tasks against
   resumable session URIs. Client requests session URIs upfront from a new
   ingester endpoint `/captures/{bundle_id}/upload_session` with the full
   manifest of paths and sizes.

3. Bundle.pb uploaded last by the client, deliberately. It's the
   manifest-finalization signal. Client sequences: all pixel-blob upload
   tasks complete (per `URLSessionDelegate` callbacks) → kick off bundle.pb
   upload task.

4. Eventarc trigger on `google.cloud.storage.object.v1.finalized` for
   `captures/*/bundle.pb` fires `/ingest` server-side. The iOS app is not in
   the critical path after handing tasks to `URLSession`.

5. Fail-fast existence check in `/ingest`. Any missing blob → Scene state
   `failed_incomplete` with missing-paths list → FCM user-visible push.
   Retry uses identical infrastructure: client re-uploads missing blobs and
   then bundle.pb, Eventarc re-fires, ingest re-checks. No special retry
   endpoint.

6. iOS app retains local capture data until Scene state reaches `ready`.
   This is the load-bearing principle that makes retry-without-special-paths
   possible. Real iOS storage policy to be detailed when iOS code starts.

7. Three client-visible Scene states (uploading, processing, ready) driven
   by Firestore listeners (foreground reactivity) + FCM (background state
   changes and terminal-state notifications). Firebase iOS SDK is
   load-bearing for this, independent of the auth choice.

8. Universal links from the FCM "ready" notification open the web app to
   the scene. This is the seam between iOS and web.

## Why

The experience constraint — "phone goes in pocket, work happens, notification
arrives" — forces every upload to be a `URLSession` background task and
forces the ingest trigger to be server-side. Those two forces collapse most
of the design space. Eventarc on bundle.pb finalize is the natural trigger
once bundle.pb is the last thing uploaded.

Firebase Auth becomes free once the live-state experience requires Firestore
listeners + FCM on iOS. The 3 MB SDK isn't a tradeoff for auth alone; it's
the cost of foreground reactivity and background notifications, which we
want regardless. Given the SDK is shipping anyway, adding Firebase Auth on
top has zero marginal cost, and skipping it would force building a
token-refresh service that earns nothing.

Fail-fast on the existence check rather than patient retry: the race
condition the patience would handle doesn't exist when bundle.pb is uploaded
after all referenced blobs complete. Every real failure mode (missing blob,
client bug, path mismatch) is structural — waiting doesn't help. Retry as
"re-upload + Eventarc re-fires" is uniform with initial upload, no special
code path.

## What would change this decision

- Firebase pricing or availability changes that make the SDK dependency
  costly (current free tier covers expected usage by orders of magnitude).
- Apple deprecates or restricts Sign-in-with-Apple in a way that breaks the
  anonymous-to-Apple upgrade path.
- A concrete need to support non-iOS clients writing bundles before the web
  app is built; this architecture is iOS+GCP-flavored. Photo-upload Android
  path would either reuse the GCS resumable upload mechanism (likely fine)
  or motivate a different shape.
- GCS Eventarc reliability or latency becomes a problem in practice
  (current SLA: events delivered within seconds, at-least-once). If we see
  duplicates causing scene-state issues, ingester needs idempotency on
  bundle_id (probably worth adding preemptively).
- The "ingester is patient" race turns out to be real for a reason not
  anticipated here — e.g. a future client implementation that uploads
  blobs in parallel without strict sequencing of bundle.pb-last. The fix
  would be to enforce the sequencing in the upload-session endpoint
  (refuse to mint a bundle.pb session URI until all other blobs are
  finalized), not to add patience to ingest.
