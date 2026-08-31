# 0026 — Operator accounts cannot call certain GCP APIs that scripts assumed they could

**Date:** 2026-05-29
**Status:** Decided

## Context

During Phase 0–7 execution on 2026-05-29, four infra scripts silently failed or produced
false positives because they called GCP APIs that an operator account structurally cannot
invoke — either due to missing permissions that GCP withholds from all non-service-account
principals, or because the gcloud CLI subcommand cited simply does not exist. In each case
the script appeared to succeed (empty output, no error exit) while actually doing nothing.

## The four instances

1. **Phase 0a — `gcloud projects test-iam-permissions`**: This subcommand does not exist in
   the gcloud CLI. It fails with "Invalid choice: 'test-iam-permissions'" and produces empty
   stdout. A check built around the empty output always passes, falsely confirming IAM.
   Fix: replaced with a REST call to
   `cloudresourcemanager.googleapis.com/v1/projects/thegoodguest:testIamPermissions` via curl
   + `gcloud auth print-access-token`.

2. **Phase 2 health check — unauthenticated curl on `--no-allow-unauthenticated` service**:
   `api-internal` is deployed with `--no-allow-unauthenticated`. An unauthenticated `curl
   /health` always gets a platform 403 (returned by Cloud Run's IAM layer, before the app).
   The check expected 200, so it always failed — but the failure message was easily mistaken
   for a real app error. Fix: added `Authorization: Bearer $(gcloud auth print-identity-token)`
   to the curl call.

3. **Phase 0j (eventarc_setup.sh Step 2) — `gcloud iam service-accounts describe` on a
   Google-managed service agent**: The Eventarc Service Agent
   (`service-{N}@gcp-sa-eventarc.iam.gserviceaccount.com`) is Google-managed. An operator
   account calling `gcloud iam service-accounts describe` on it gets `PERMISSION_DENIED`,
   which the script misread as "agent not yet provisioned" and retried 10 × 15 s = 2.5 min
   before giving up — even when the agent had existed for months.

4. **eventarc_setup.sh Step 2 is also redundant**: The Step 6 trigger-create retry loop
   already handles Service-Agent-not-ready as a transient error. Removing Step 2 entirely
   is the correct fix; Step 6 is the authoritative guard.

## What we chose

- Replace the non-existent gcloud subcommand with the equivalent REST API call (item 1).
- Add authentication to the Phase 2 health check (item 2).
- Delete Step 2 from `eventarc_setup.sh` entirely; leave Step 6's retry loop as the sole
  Service-Agent guard (items 3 + 4).

## Why

In each case the root cause is the same pattern: a script assumed the operator account has
the same visibility into GCP internals as a service account or Google-internal tooling.
Google-managed service agents are owned by Google's infrastructure, not the project; project
IAM roles grant access to project resources, not to Google's internal agent registry.
Similarly, some gcloud subcommands listed in documentation are backed by APIs only accessible
to specific account types.

## What would change this decision

If a script needs to verify Eventarc Service Agent existence in the future (e.g. for a
first-ever project setup where the agent may genuinely not exist yet), use the Eventarc API
directly:
`curl -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  "https://eventarc.googleapis.com/v1/projects/{PROJECT}/locations/-/channels"`
A 403 there means the API is not enabled; a 200/404 means it is enabled and the agent exists.
Do not use `gcloud iam service-accounts describe` on Google-managed agents.
