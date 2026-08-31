# 0088 — Launch-hardening IAM audit: perception-obj SA + storage findings

**Date:** 2026-08-07
**Status:** Spent — both recommendations executed and recorded inline; finding 4 revoked, remediation 1 shipped as 0090.

## Context

Decision 0018's audit item: verify the perception-obj Cloud Run service runs
under the correct runtime service account with storage IAM scoped to the
intended buckets at minimum necessary permissions. Audited read-only
2026-08-07 with the operator's gcloud; nothing was mutated.

## Findings

**1. perception-obj runs as the DEFAULT COMPUTE service account with
project-level Editor.** `spec.serviceAccountName =
502805861152-compute@developer.gserviceaccount.com`, which holds
`roles/editor` on the project. This is how it reads captures and writes
outputs today (no bucket-scoped grants needed — Editor covers everything),
and it means the service that parses untrusted capture bundles and runs the
heaviest third-party model code can write ANY project resource. api-public
and api-internal both have dedicated least-privilege runtime SAs; perception
predates that discipline. **Remediation (a perception deploy-cycle change,
not this session's):** create `perception-obj-runtime`, grant
`storage.objectViewer` on gs://roomstudio-captures, `storage.objectAdmin` on
gs://roomstudio-perception-outputs, `roles/datastore.user`, re-point
`deploy_perception.sh --service-account` (its idempotent shell-IAM grants
must move to the new SA in the same pass), redeploy, then consider removing
Editor from the default compute SA project-wide (verify nothing else rides
it first — Cloud Build workers use their own SA).

**2. Stale pre-split grant + orphan SA.**
`api-runtime@roomstudio.iam.gserviceaccount.com` (the deleted pre-split `api`
service's runtime SA, service removed 2026-07-21) still exists and still
holds `storage.objectViewer` on gs://roomstudio-captures. Recommend: revoke
the binding and delete the SA. Not done (mutation outside a read-only audit).

**3. Expected bindings all verified present and correctly scoped.**
- gs://roomstudio-captures: `api-public-runtime` objectAdmin (mint needs
  objects.create; objectAdmin is the minimal managed role including it —
  rationale recorded in deploy_api_public.sh), `api-internal-runtime`
  objectViewer at bucket scope (matches the CLAUDE.md note that project-level
  checks won't show it).
- gs://roomstudio-perception-outputs: `api-public-runtime` objectViewer
  (assets signing), default-compute objectAdmin (redundant with Editor;
  becomes the dedicated SA's grant under remediation 1).
- `api-public-runtime` holds `iam.serviceAccountTokenCreator` on itself (V4
  signBlob) and grants Cloud Build `serviceAccountUser` (deploy-as). Both
  expected.

**4. Flagged, decision deliberately left to the operator: the standing
tokenCreator grant from RP-8.** `user:23singhutkarsh@gmail.com` holds
`roles/iam.serviceAccountTokenCreator` on
`firebase-adminsdk-fbsvc@roomstudio.iam.gserviceaccount.com` (granted
2026-08-06, operator-approved, for the RP-8 custom-token mint under the real
uid). While it stands, anyone with the operator's local gcloud credential can
mint a Firebase custom token FOR ANY UID — a full user-impersonation
primitive gated only by the laptop's ADC. **Recommendation: revoke now,
re-grant per walk** (each direction is one command, seconds of overhead on a
walk day):

    # revoke
    gcloud iam service-accounts remove-iam-policy-binding \
      firebase-adminsdk-fbsvc@roomstudio.iam.gserviceaccount.com \
      --member=user:23singhutkarsh@gmail.com \
      --role=roles/iam.serviceAccountTokenCreator --project=roomstudio
    # re-grant on a walk day: same command with add-iam-policy-binding

Left in place pending the operator's call — future operator walks (the
memory-noted identity-token flow) are the reason to keep it.

**OUTCOME — the operator ruled REVOKE, 2026-08-08.** Recorded here because
this note's own trigger asks for it and the ask went unanswered for a day; an
audit on 2026-08-09 found all three "revoke" mentions above still reading as
the recommendation while CLAUDE.md already carried the result, so the note
read open when it was closed. Verified live 2026-08-09 rather than restated:
`get-iam-policy` on the SA returns **no bindings at all**. Impersonation was
confirmed 403 twice at revocation time, and two things learned there are worth
keeping — `roles/owner` does NOT confer `getAccessToken`, so an owner is not a
back door to this; and an interim "the revocation didn't work" reading was IAM
propagation lag, not a failed command. The re-grant line above stands as the
walk-day procedure.

## What would change this decision

- ~~Remediation 1 executed → perception joins the per-service SA discipline.~~
  **DONE** — decision 0090's dedicated SA shipped on `perception-obj-00036-l9l`;
  verified live 2026-08-09, the service runs as
  `perception-obj-runtime@roomstudio.iam.gserviceaccount.com`, not the default
  compute SA. This note's open half is closed. What remains deliberately NOT done
  is removing `roles/editor` from the default compute SA — other workloads may
  ride it, and that verification is its own pass.
- ~~The operator rules on finding 4 either way → record the outcome here.~~
  **DONE** — revoked, recorded above, verified live 2026-08-09.
- Any new service ships → it gets a dedicated runtime SA from day one; the
  default compute SA never again acquires a workload.
