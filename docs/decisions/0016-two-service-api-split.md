# 0016 — Two-service split for API trust-boundary separation

**Date:** 2026-05-26
**Status:** Decided

## Context

The auth flip from the previous deploy-prep session (commit `830b76c`) put
`--no-allow-unauthenticated` on the API service. That gates `/ingest/eventarc`
correctly — Cloud Run IAM validates the Eventarc service account's OIDC token
at the platform boundary — but it also breaks Firebase-authenticated iOS
clients before they exist. Cloud Run platform auth validates Google-issued
OIDC tokens; Firebase ID tokens are a different kind of JWT, verified
application-side via `firebase_admin.auth.verify_id_token`. A single Cloud
Run service cannot be both platform-gated (for the Eventarc trigger, where
Cloud Run IAM is doing the work) and platform-open (for client traffic,
where in-app Firebase verification is doing the work).

The decision has to land before the deploy because the deploy script
currently flags the wrong thing. Resolving it is between us and unblocking
iOS code (CLAUDE.md board item 1).

## What we tried

Four options, weighed against the constraints: premium architectural shape,
scale-to-zero today, no $18/mo LB fixed cost yet, no drastic change later
unless quality demands it.

**A — Single service, `--allow-unauthenticated`, in-app OIDC verification
for `/ingest/eventarc`.** The Eventarc trust boundary moves into application
code on a public endpoint. The endpoint enqueues perception work and writes
Firestore state on success; a bug in the OIDC verifier (forgotten audience
check, wrong issuer URL, signature-library quirk) turns into "anyone on the
internet can forge an Eventarc event and enqueue arbitrary bundle_ids."
Cloud Run IAM exists precisely to remove this class of bug; reimplementing
it in application code pays a half-day in initial cost and an indefinite
review burden every time the verifier is touched.

**B — Two Cloud Run services split on the trust boundary.**
`services/api-public/` carries `--allow-unauthenticated` and the in-app
Firebase verifier (already implemented), hosts `/upload_session` and future
client endpoints. `services/api-internal/` carries
`--no-allow-unauthenticated`, hosts `/ingest/eventarc`, no in-app caller
check — Cloud Run IAM is the gate. Shared logic moves to
`packages/api-core/`. Both scale to zero. Eventarc trigger points at
internal. The split also encodes a distinction that already exists in the
system: client traffic and platform-trigger traffic have different scaling
profiles, different auth models, and different abuse surfaces. Cost today:
~half-day refactor, $0/mo.

**C — HTTPS LB with Cloud Armor for JWT validation + rate limiting, path-
based routing to a single Cloud Run service.** The right architecture for
launch, wrong time for it. $18/mo fixed cost from day one (forwarding rule
floor) violates the no-LB-now constraint. ~2-3 days of infra work plus
production domain + DNS plumbing. Cloud Armor does validate Firebase JWT
signature/claims at the edge, but resolution-to-UID and authorization still
happen application-side, so the in-app verifier doesn't actually go away.

**API Gateway as a middle path.** Free tier, no LB floor cost, edge JWT
validation. Rejected because per-API-key rate limiting (not per-UID) means
the transition to LB + Cloud Armor at launch is a replacement, not an
addition. That's the drastic-change-later the constraint was designed to
prevent.

## What we chose

Option B now. Evolve to C at launch when traffic justifies the LB.

**Phase 1 (gates the iOS-unblock deploy):** Refactor `services/api` into
`services/api-public/` + `services/api-internal/` + `packages/api-core/`.
Two deploy scripts, two cloudbuild configs. Eventarc trigger created
against api-internal's URL. `tools/upload_test_bundle.py` (when written)
takes two URLs.

**Phase 2 (the existing deploy plan, redirected at two services):** GCS
lifecycle + Firestore TTL first; deploy both services with `--no-traffic`;
revision-URL smoke tests; traffic flip; Eventarc trigger; Firestore single-
field index on `bundle_id`; end-to-end via `tools/upload_test_bundle.py`.

**Phase 3 (at launch, when traffic justifies the LB cost):** HTTPS LB in
front of api-public only. Cloud Armor: Firebase JWT signature/claims
validation at the edge (defense-in-depth — in-app verifier stays) +
per-IP rate limiting. Production domain + managed cert. api-public flips to
`--no-allow-unauthenticated` with the LB's NEG service account holding
`roles/run.invoker`. api-internal stays unchanged. The remaining 0015
closures land alongside: `bundle_id` ownership transaction in api-public's
repo layer, `expected_size_bytes` required in the manifest schema, FCM
token moves off `/upload_session` to a dedicated endpoint on api-public.

## Why

Two reasons, both load-bearing.

First, the trust boundary belongs in the Cloud Run control plane, not in
application code on a public endpoint. Option A's in-app OIDC verifier
costs a half-day to write and an indefinite review burden to maintain;
Cloud Run IAM eliminates both. For a premium product, "the trust boundary
is enforced by the platform, not by a library we maintain" is the right
default.

Second, the launch upgrade is strictly additive. Adding an LB in front of
api-public doesn't move any trust boundary, doesn't merge or split any
service, doesn't rewrite any handler. The service split is already in the
right shape; Phase 3 changes how api-public is reached, nothing else. That
is what "no drastic change later" looks like concretely.

The accepted cost of B is the operational tax of running two services from
day one — two deploy scripts, two revision streams, two log scopes, the
risk that shared-core coupling forces lockstep deploys. The tax is real
and called out here rather than discovered later. It's the honest version
of "premium architecture": paying with operational surface area now to buy
structural correctness and an additive upgrade path.

## What would change this decision

- LB fixed cost stops mattering (GCP pricing shift, or LB cost becomes
  negligible relative to other infrastructure): accelerate to C and skip
  B's intermediate phase. The Phase 3 work is already specified.
- API Gateway gains per-UID rate limiting (not per-API-key): reconsider as
  an alternative to the LB + Cloud Armor evolution. Wouldn't undo B; would
  change what Phase 3 looks like.
- The operational complexity of two services proves materially higher than
  estimated — e.g. shared-core coupling forces lockstep deploys, or the
  two services drift in subtle ways that cause incidents: collapse to A
  and pay the in-app OIDC verifier cost. Unlikely but not impossible.
- A second backend-trigger endpoint appears that should also be IAM-gated
  (a second Eventarc trigger, a Cloud Scheduler hook, an internal admin
  endpoint): confirms the split was correct, doesn't change anything.
- The web app's BFF needs a third trust profile (server-to-server with a
  third auth model): probably a third service, or the split generalizes
  into a clearer trust-tier convention. Re-examine then, not now.
