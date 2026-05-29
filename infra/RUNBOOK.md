<!--
infra/RUNBOOK.md — Deploy runbook: two-service iOS upload path

Implements: decisions 0014, 0015, 0016, 0018, 0019, 0020.

Deliberately out of scope: all nine pre-launch gaps from decisions 0015 and 0018
(abuse-surface, contract-shape, production-hygiene categories) and the perception-obj SA
audit. They close on their own triggers; do not pull them forward here.

Prerequisites before executing: board item 1 (GET /scenes/by-bundle/{bundle_id} built)
must pass Phase 0 preflight. tools/upload_test_bundle.py is already written.
-->

# Deploy runbook: two-service iOS upload path

**Services:** `api-public` (client-facing) + `api-internal` (Eventarc-triggered)  
**Region:** `asia-southeast1`  
**Project:** `roomstudio`  
**Operator role:** human, step-by-step — no parent script wraps this runbook.

Do not skip phases. Each phase's "expect this" block must pass before proceeding.
Phase 0 is a hard gate: any preflight failure halts the entire runbook.

---

## Phase 0 — Preflight

**Halt on any failure. Do not proceed to Phase 1 until all checks below pass.**

**Resumability:** this runbook is safe to re-run from the top after a mid-run failure.
Phases 1 and 6 are explicitly idempotent — re-run the failing section without concern.
Phases 4 and 7 are read-only and re-runnable at any time. Phases 2 and 3 create a new
Cloud Run revision on each run; revision accumulation is harmless and cleaned up in
Phase 8a. Phase 5 (traffic flip) is the exception: if it fails mid-run, do not re-run
naively — follow the recovery guidance in Phase 5's block.

### 0a. Operator environment: gcloud auth

```bash
gcloud auth list
# Expect: one ACTIVE account listed. The account must be authenticated.

gcloud projects describe roomstudio --format='value(projectId)'
# Expect: roomstudio
```

The active account needs the following IAM roles on project `roomstudio`:
- `roles/run.admin`
- `roles/iam.serviceAccountUser` on `api-internal-runtime@roomstudio.iam.gserviceaccount.com`
  and `api-public-runtime@roomstudio.iam.gserviceaccount.com`
- `roles/eventarc.admin`
- `roles/datastore.indexAdmin`
- `roles/storage.admin` on `gs://roomstudio-captures` and `gs://roomstudio-perception-outputs`
- Firestore write access to `upload_sessions` and `scenes` (for smoke `--cleanup`)

Effective-permission check — proves the caller actually has the permissions, not just
that a role is bound by name (custom roles, or permissions removed from a predefined
role, would still grep green against a role-name check). `test-iam-permissions` returns
only the subset the caller actually holds; any permission absent from the response is
missing from the effective grants.

```bash
# Project-level permissions (maps to roles/run.admin, roles/iam.serviceAccountUser,
# roles/eventarc.admin, roles/datastore.indexAdmin).
MISSING=$(gcloud projects test-iam-permissions roomstudio \
  --permissions=\
run.services.create,run.services.update,run.services.setIamPolicy,\
iam.serviceAccounts.actAs,\
eventarc.triggers.create,eventarc.triggers.update,\
datastore.indexes.list \
  --format=json \
  | python3 -c "
import sys, json
want = {
    'run.services.create',       # roles/run.admin — deploy services
    'run.services.update',       # roles/run.admin — update + traffic flip
    'run.services.setIamPolicy', # roles/run.admin — Eventarc invoker binding
    'iam.serviceAccounts.actAs', # roles/iam.serviceAccountUser — deploy with runtime SA
    'eventarc.triggers.create',  # roles/eventarc.admin
    'eventarc.triggers.update',  # roles/eventarc.admin
    'datastore.indexes.list',    # roles/datastore.indexAdmin — Phase 1 index verify
}
got = set(json.load(sys.stdin).get('permissions', []))
for p in sorted(want - got):
    print(p)
")
if [ -n "${MISSING}" ]; then
  echo "FAIL: missing project-level permissions:"
  echo "${MISSING}" | sed 's/^/  /'
  echo "Grant the missing roles before continuing."
  exit 1
fi
echo "OK: all project-level permissions confirmed."

# Bucket-level storage.admin grants cannot be verified via test-iam-permissions —
# that API only tests permissions on the project resource, not resource-scoped
# (bucket-level) bindings. Probe with objects.list instead.
gcloud storage ls gs://roomstudio-captures/ > /dev/null 2>&1 \
  && echo "OK: storage access confirmed for gs://roomstudio-captures." \
  || { echo "FAIL: cannot list gs://roomstudio-captures — storage.admin on bucket missing."; exit 1; }

gcloud storage ls gs://roomstudio-perception-outputs/ > /dev/null 2>&1 \
  && echo "OK: storage access confirmed for gs://roomstudio-perception-outputs." \
  || { echo "FAIL: cannot list gs://roomstudio-perception-outputs — storage.admin on bucket missing."; exit 1; }
```

**If any check fails:** grant the missing role or bucket-level binding before continuing.
Do not proceed with insufficient IAM.

### 0b. Operator environment: Firebase credentials

The smoke tool (Phase 7) authenticates as a Firebase anonymous user to mint ID tokens.
This requires Firebase to be configured for the project and a web app registered.

**One-time setup — verify or perform once per project; skip if already done:**

**Step 1: Add Firebase to the GCP project.**
Firebase console (`console.firebase.google.com`) → "Add project" → select the existing
GCP project `roomstudio` → "Add Firebase to an existing Google Cloud project". Complete
the wizard.

**Step 2: Register a web app.**
Firebase console → Project settings (gear icon, top-left sidebar) → "Your apps" tab →
"Add app" → Web (`</>` icon). Nickname: `roomstudio-smoke-test`. Register without
Firebase Hosting. Note the `appId`; current registered value:
`1:502805861152:web:095d7e3b331e0e0ddcbd45`.

**Step 3: Enable anonymous sign-in.**
Firebase console → Authentication (left sidebar) → Sign-in method tab → Anonymous →
Enable → Save.

**Step 4: Verify required APIs are enabled.**
```bash
gcloud services list --enabled --project=roomstudio \
  --filter="name:firebase.googleapis.com OR name:identitytoolkit.googleapis.com" \
  --format="value(name)"
# Expect: both firebase.googleapis.com and identitytoolkit.googleapis.com
```

If either is missing:
```bash
gcloud services enable firebase.googleapis.com identitytoolkit.googleapis.com \
  --project=roomstudio
```

**Set env vars** (required in every shell session before reaching Phase 7):

```bash
export FIREBASE_API_KEY="<Web API key>"        # Firebase console → Project settings
                                                # → General → Your apps → Web API key
export FIREBASE_PROJECT_ID="roomstudio"
```

`FIREBASE_API_KEY` is not in `infra/secrets.md` (it's a client-side key, not a server secret).
Find it in the Firebase console under Project settings → General → Your apps → Web API key.
The project ID is always `roomstudio`.

**Set ADC quota project** (required for smoke `--cleanup`):

```bash
gcloud auth application-default set-quota-project roomstudio
```

The smoke tool's `--cleanup` flag uses Application Default Credentials for direct
Firestore and GCS calls (decision 0020). Without the quota project set, ADC calls are
routed through the ADC credential's own quota project — which may differ from `roomstudio`
if the credential was originally created for a different project — causing billing errors
or rejected requests.

### 0c. Repo state

```bash
git status
# Expect: nothing to commit, working tree clean

git rev-parse HEAD
# Record this commit hash. If a rollback is needed, this is the deployed commit.
```

**If the tree is dirty:** commit or stash before deploying. Do not deploy from a dirty tree.

### 0d. Code-level preconditions: api-public

```bash
grep -n "scenes/by-bundle" services/api-public/public_server.py
# Expect: a line matching GET /scenes/by-bundle/{bundle_id}

grep -n "upload_session\|health" services/api-public/public_server.py
# Expect: /upload_session route and /health route present.
```

**If `scenes/by-bundle` is absent:** board item 1 (`GET /scenes/by-bundle/{bundle_id}`)
has not been built yet. This runbook cannot proceed.

Trust-boundary check: Firebase verifier must be wired into api-public and must be
absent from api-internal and api-core (decision 0016: api-internal is IAM-gated only;
no in-app client auth anywhere on that side of the boundary).

```bash
grep -q "FirebaseTokenVerifier" services/api-public/public_server.py \
  && echo "OK: FirebaseTokenVerifier wired into api-public." \
  || { echo "FAIL: Firebase verifier not wired into api-public (trust boundary, decision 0016)."; exit 1; }

grep -rq "FirebaseTokenVerifier" services/api-internal/ \
  && { echo "FAIL: Firebase verifier present in api-internal — trust boundary violation (decision 0016: api-internal is IAM-gated only)."; exit 1; } \
  || echo "OK: FirebaseTokenVerifier absent from api-internal."

grep -rq "FirebaseTokenVerifier" packages/api-core/ \
  && { echo "FAIL: Firebase verifier present in api-core — would leak client auth into api-internal via shared import (decision 0016)."; exit 1; } \
  || echo "OK: FirebaseTokenVerifier absent from api-core."
```

### 0e. Code-level preconditions: api-internal

```bash
grep -n "def ingest\|ingest/eventarc\|health" services/api-internal/ingest_server.py
# Expect: /ingest route, /ingest/eventarc route, /health route all present.
```

### 0f. Code-level preconditions: eventarc_setup.sh

```bash
grep "INGESTER_SERVICE\|INGESTER_SA" infra/eventarc_setup.sh
# Expect:
#   INGESTER_SERVICE="api-internal"
#   INGESTER_SA="api-internal-runtime@roomstudio.iam.gserviceaccount.com"
```

**If the output shows `roomstudio-api`:** the stale-reference patch has not landed.
Do not run eventarc_setup.sh until it does.

```bash
test -d services/api && echo "FAIL: services/api/ still exists" || echo "OK: services/api/ absent"
# Expect: OK: services/api/ absent
```

### 0g. Infrastructure preconditions: captures bucket

```bash
gcloud storage buckets describe gs://roomstudio-captures --project=roomstudio
# Expect: bucket details printed (location, storageClass, etc.)
```

**If not found:** the captures bucket must exist before either service can be deployed.
It is created by `deploy_api_internal.sh` step 6 (idempotent). Run the deploy script
through step 6 and re-check.

### 0h. Infrastructure preconditions: perception-obj live and ready

This check gates liveness only. Phase 0h proves the Cloud Run revision is alive and
the service is reachable over HTTPS. It does not prove models are loaded — perception-obj
lazy-loads on first `/process` (decision 0007), so a cold container returns 503
`not_loaded` by design; that state is indistinguishable from broken at preflight. Broken-
model failures surface at Phase 7 happy-path (which triggers a real `/process`). See
decision 0024.

```bash
DESCRIBE_OUT=$(gcloud run services describe perception-obj \
  --region=asia-southeast1 --project=roomstudio \
  --format='value(status.conditions[0].type,status.conditions[0].status)' 2>/dev/null)
echo "${DESCRIBE_OUT}" | grep -qE "^Ready[[:space:]]+True" \
  && echo "OK: perception-obj Cloud Run revision is Ready." \
  || { echo "FAIL: perception-obj is not ready (got: '${DESCRIBE_OUT}')."; \
       echo "  If empty: service does not exist. Fix perception-obj first."; \
       echo "  If non-empty: container revision failed to start. Check startup logs:"; \
       echo "  gcloud logging read 'resource.type=\"cloud_run_revision\" resource.labels.service_name=\"perception-obj\" severity>=ERROR' --project=roomstudio --limit=50"; \
       exit 1; }
```

```bash
PERCEPTION_URL=$(gcloud run services describe perception-obj \
  --region=asia-southeast1 --project=roomstudio \
  --format='value(status.url)')

# Liveness check: any HTTP response (200/503/500) confirms the service is invokable.
# 200 = models loaded; 503 = cold/not yet triggered (normal scale-to-zero state);
# 500 = cached load failure in current instance (warning only — next cold container
# retries; Phase 7 surfaces this as a hard failure). Only connection failure halts.
# (perception-obj is --allow-unauthenticated; no auth token needed for /ready)
code=$(curl -s -o /tmp/ready_body -w "%{http_code}" "${PERCEPTION_URL}/ready")
if [ -z "${code}" ] || [ "${code}" = "000" ]; then
  echo "FAIL: perception-obj /ready unreachable (got: '${code}') — connection failure or service not responding."
  exit 1
elif [ "${code}" = "500" ]; then
  echo "WARNING: perception-obj /ready returned 500 (cached model-load failure in current instance)."
  echo "  Models will retry on the next cold container. Phase 7 will surface this as a hard failure."
  cat /tmp/ready_body
else
  echo "OK: perception-obj /ready reachable (HTTP ${code})."
  cat /tmp/ready_body
fi
```

### 0i. Infrastructure preconditions: Cloud Tasks queue

```bash
gcloud tasks queues describe perception-dispatch \
  --location=asia-southeast1 --project=roomstudio \
  --format='value(name,state)'
# Expect: the queue name and state=RUNNING (not PAUSED or DISABLED)
```

**If paused:** `gcloud tasks queues resume perception-dispatch --location=asia-southeast1 --project=roomstudio`
**If absent:** the queue is created by `deploy_api_internal.sh` step 4. Run that script first.

### 0j. Infrastructure preconditions: Eventarc API, Service Agent, and IAM grants

These four prerequisites are required for end-to-end Eventarc delivery. They were resolved
manually when the trigger was first created; `eventarc_setup.sh` now enforces them
explicitly (decision 0023).

```bash
# 1. Verify the Eventarc API is enabled.
gcloud services list --enabled --project=roomstudio \
  --filter="name:eventarc.googleapis.com" --format="value(name)"
# Expect: eventarc.googleapis.com

# 2. Resolve the project number (needed for service agent addresses).
PROJECT_NUMBER=$(gcloud projects describe roomstudio --format='value(projectNumber)')
echo "Project number: ${PROJECT_NUMBER}"

# 3. Verify the Eventarc Service Agent exists.
gcloud iam service-accounts describe \
  "service-${PROJECT_NUMBER}@gcp-sa-eventarc.iam.gserviceaccount.com" \
  --project=roomstudio --format="value(email)"
# Expect: service-<PROJECT_NUMBER>@gcp-sa-eventarc.iam.gserviceaccount.com

# 4. Verify roles/eventarc.eventReceiver is granted to the trigger SA.
gcloud projects get-iam-policy roomstudio \
  --flatten="bindings[].members" \
  --filter="bindings.role=roles/eventarc.eventReceiver AND bindings.members=serviceAccount:api-internal-runtime@roomstudio.iam.gserviceaccount.com" \
  --format="table(bindings.members,bindings.role)"
# Expect: one row with api-internal-runtime@roomstudio.iam.gserviceaccount.com

# 5. Verify roles/pubsub.publisher is granted to the GCS service agent.
gcloud projects get-iam-policy roomstudio \
  --flatten="bindings[].members" \
  --filter="bindings.role=roles/pubsub.publisher AND bindings.members=serviceAccount:service-${PROJECT_NUMBER}@gs-project-accounts.iam.gserviceaccount.com" \
  --format="table(bindings.members,bindings.role)"
# Expect: one row with service-<PROJECT_NUMBER>@gs-project-accounts.iam.gserviceaccount.com
```

**If any check produces empty output or an error:** run `./infra/eventarc_setup.sh --trigger-only`,
which enables the API, waits for the Service Agent, and grants all required bindings idempotently.

---

## Phase 1 — Pre-deploy infrastructure

Run the lifecycle rule and TTL sections of `eventarc_setup.sh` before deploying either
service. Both operations are infrastructure-level; neither requires a running Cloud Run
service. Run them first so they take effect immediately rather than after traffic flip.

```bash
./infra/eventarc_setup.sh --lifecycle-only --ttl-only
```

**Expect:**

Lifecycle rule output ends with:
```
Lifecycle rule applied to gs://roomstudio-captures.
```

Verify:
```bash
gsutil lifecycle get gs://roomstudio-captures
# Expect: JSON output showing a Delete rule with age=1 and matchesPrefix=["captures/"]
```

TTL output ends with: a JSON response from the Firestore REST API containing
`"done": true` (or `"state": "RUNNING"` if propagation is async). If the curl returns
an error body, re-run; the TTL REST call is idempotent.

Verify the TTL (30–60 seconds after setting):
```bash
curl -s \
  "https://firestore.googleapis.com/v1/projects/roomstudio/databases/(default)/collectionGroups/upload_sessions/fields/created_at" \
  -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('ttlConfig','MISSING'))"
# Expect: {} (an empty dict means TTL is enabled on this field)
```

**Firestore `scenes.bundle_id` index:**

Firestore automatically maintains single-field ascending indexes on all document fields.
For `WHERE bundle_id = X` equality queries (what `get_by_bundle_id` uses), the automatic
index is sufficient — no manual configuration is required.

Verify that no index exemption has been applied to `bundle_id` that would disable the
automatic index:

```bash
gcloud firestore indexes fields list \
  --collection-group=scenes \
  --project=roomstudio 2>/dev/null | grep bundle_id || echo "No exemption — automatic index active"
# Expect: "No exemption — automatic index active"
# If bundle_id appears in the output, check whether the listed config includes
# order=ASCENDING. If it explicitly excludes ASCENDING, re-enable:
#   gcloud firestore indexes fields update bundle_id \
#     --collection-group=scenes --project=roomstudio \
#     --index=order=ASCENDING,scope=COLLECTION \
#     --index=order=DESCENDING,scope=COLLECTION \
#     --clear-exemption
```

**If the `scenes` collection doesn't exist yet** (no documents have been ingested through
the new path), the field list may be empty. That's expected — the automatic index will be
created on first document write. Proceed.

**If not (lifecycle or TTL):** all three operations are idempotent. Re-run the failing
section individually (`--lifecycle-only` or `--ttl-only`) to isolate and fix.

---

## Phase 2 — Deploy api-internal (no traffic)

```bash
./infra/deploy_api_internal.sh
```

The script takes ~10 minutes (Cloud Build + image push). Copy-paste the printed export line
to record the candidate URL in your shell:

```bash
# copy-paste this from script output — do not type the URL by hand:
export API_INTERNAL_REVISION_URL=https://candidate---api-internal-<hash>-as.a.run.app
```

**Expect:**

**Subsequent deploy** (the normal case — service already exists):
```
[deploy] api-internal exists; deploying candidate revision held at 0% traffic. Promote in Phase 5.
...
Service URL: https://api-internal-<hash>-as.a.run.app
export API_INTERNAL_REVISION_URL=https://candidate---api-internal-<hash>-as.a.run.app
```

**First-ever deploy** (service did not exist — happens on initial setup or after a full teardown):
```
[deploy] WARNING: api-internal has no prior revision. --no-traffic cannot be honored; the new
revision serves 100% on creation. Phase 4 smoke runs against a live revision — acceptable,
no prior traffic to protect.
...
Service URL: https://api-internal-<hash>-as.a.run.app
export API_INTERNAL_REVISION_URL=https://candidate---api-internal-<hash>-as.a.run.app
```

In both cases the export line is printed and Phase 4 smoke applies. The difference is
whether the candidate revision is at 0% traffic (subsequent deploy) or 100% (first-ever).

Health check:
```bash
curl -s "${API_INTERNAL_REVISION_URL}/health"
# Expect: {"status": "ok"}  HTTP 200
```

**If the Cloud Build step times out locally:** the build may still be running remotely.
Check the build ID from the submission output and poll:
```bash
# From .claude/WORKFLOW.md Cloud Build pattern:
gcloud builds describe <BUILD_ID> --project=roomstudio --region=asia-southeast1 \
  --format='value(status,finishTime)'
```

**If health check fails:** check Cloud Run revision logs before proceeding. Do not move
to Phase 3 until `/health` returns 200. No traffic has been flipped; rollback is
safe — just fix and redeploy.

---

## Phase 3 — Deploy api-public (no traffic)

```bash
./infra/deploy_api_public.sh
```

Copy-paste the printed export line to record the candidate URL in your shell:

```bash
# copy-paste this from script output — do not type the URL by hand:
export API_PUBLIC_REVISION_URL=https://candidate---api-public-<hash>-as.a.run.app
```

**Expect:** same two-case shape as Phase 2 (subsequent deploy: held at 0%; first-ever deploy:
100% on creation with a WARNING line). In both cases the export line is printed. Health check:

```bash
curl -s "${API_PUBLIC_REVISION_URL}/health"
# Expect: {"status": "ok"}  HTTP 200
```

**If not:** same pattern as Phase 2. Fix and redeploy before continuing.

---

## Phase 4 — Revision-URL smoke checks

These checks verify auth wiring and platform configuration against the candidate revision
URLs **before traffic is flipped**. At this point, production traffic is still on the old
revisions (or, on a first-ever deploy, the candidate revision is already serving 100%;
there is no prior revision to protect, and the revision-URL smoke below still applies).

### 4a. api-public: Firebase verifier is wired

```bash
curl -s -o /dev/null -w "%{http_code}" -X POST \
  "${API_PUBLIC_REVISION_URL}/captures/00000000-0000-4000-8000-000000000001/upload_session" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer deliberately-malformed" \
  -d '{"manifest": []}'
# Expect: 401
```

Full response (including body):
```bash
curl -s -X POST \
  "${API_PUBLIC_REVISION_URL}/captures/00000000-0000-4000-8000-000000000001/upload_session" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer deliberately-malformed" \
  -d '{"manifest": []}'
# Expect body: {"error": "invalid_token", "detail": "..."}
# The "detail" value is the firebase_admin error message; it varies but is informational.
# The load-bearing fields are: HTTP 401 and "error": "invalid_token".
```

This proves: api-public is reachable, `ENVIRONMENT=production` fired the Firebase verifier,
and the platform is not blocking the request before it reaches the app.

**If HTTP 200 or 403 from the platform:** `--allow-unauthenticated` may not be set, or
the env var is missing. Check the revision's env config:
```bash
gcloud run revisions describe <REVISION_NAME> --region=asia-southeast1 --project=roomstudio \
  --format='yaml(spec.containers[0].env)'
```

**If HTTP 422:** the request body or header format was rejected by FastAPI before auth.
Use the exact `curl` command above verbatim — the bundle_id in the URL is a valid UUIDv4.

### 4b. api-internal: Cloud Run IAM is in effect

```bash
curl -s -o /dev/null -w "%{http_code}" \
  "${API_INTERNAL_REVISION_URL}/ingest/eventarc"
# Expect: 403
# The response body is platform-generated HTML, not JSON. HTTP 403 is the only check.
```

This proves `--no-allow-unauthenticated` is in effect on the revision. Eventarc's
service account holds `roles/run.invoker` and will pass; unauthenticated callers will not.

**If HTTP 200 or any other status:** `--no-allow-unauthenticated` is not set. Do NOT flip
traffic. Redeploy api-internal with the flag. The deploy script already sets it; if it's
missing, the script has been modified incorrectly.

---

## Phase 5 — Traffic flip

Flip each service to the new revision. Full flip — no staged rollout. (Staged flips
are deferred until the abuse-surface gap set closes, per decisions 0015/0018.)

```bash
# Flip api-internal first (no client traffic; Eventarc not wired yet)
gcloud run services update-traffic api-internal \
  --to-latest \
  --region=asia-southeast1 \
  --project=roomstudio

# Then flip api-public
gcloud run services update-traffic api-public \
  --to-latest \
  --region=asia-southeast1 \
  --project=roomstudio
```

**Expect:**

```bash
gcloud run services describe api-internal --region=asia-southeast1 --project=roomstudio \
  --format='value(status.traffic[0].percent,status.traffic[0].latestRevision)'
# Expect: 100    True

gcloud run services describe api-public --region=asia-southeast1 --project=roomstudio \
  --format='value(status.traffic[0].percent,status.traffic[0].latestRevision)'
# Expect: 100    True
```

Record the service URLs (now pointing at the new revisions):
```bash
API_PUBLIC_URL=$(gcloud run services describe api-public \
  --region=asia-southeast1 --project=roomstudio --format='value(status.url)')
API_INTERNAL_URL=$(gcloud run services describe api-internal \
  --region=asia-southeast1 --project=roomstudio --format='value(status.url)')
echo "api-public:   ${API_PUBLIC_URL}"
echo "api-internal: ${API_INTERNAL_URL}"
```

**Rollback (if the traffic flip itself fails or immediate issues appear):**

If Phase 5 fails between the api-internal flip and the api-public flip (api-internal
is on the new revision, api-public is still on the old): this split state is safe.
No consumer calls api-internal until the Eventarc trigger is created in Phase 6, so
nothing is affected. The correct recovery is to complete the api-public forward flip —
re-running `gcloud run services update-traffic api-public --to-latest` is idempotent.
Do NOT roll api-internal back. The rollback commands below are for the case where both
services have flipped and a real problem appears.

Cloud Run retains the prior revision. Flip back:
```bash
# Get the prior revision name
gcloud run revisions list --service=api-public --region=asia-southeast1 --project=roomstudio \
  --format='table(name,status.conditions[0].status)' --limit=5

# Roll back to the prior revision (replace <PRIOR_REVISION> with the actual name)
gcloud run services update-traffic api-public \
  --to-revisions=<PRIOR_REVISION>=100 \
  --region=asia-southeast1 --project=roomstudio

# Same for api-internal if needed
gcloud run services update-traffic api-internal \
  --to-revisions=<PRIOR_REVISION>=100 \
  --region=asia-southeast1 --project=roomstudio
```

---

## Phase 6 — Eventarc trigger

Create (or update) the Eventarc trigger pointing at `api-internal`. The trigger
section of `eventarc_setup.sh` grants `roles/run.invoker` to the Eventarc SA
before creating the trigger, then creates or updates the trigger.

**Step 1: check for a stale trigger from a prior deploy**

```bash
gcloud eventarc triggers describe captures-bundle-pb-finalized \
  --location=asia-southeast1 --project=roomstudio 2>/dev/null \
  | grep "destination\|service" || echo "No trigger exists yet"
```

- **No trigger exists:** proceed directly to step 2.
- **Trigger exists, destination is `api-internal`:** the trigger is already correct.
  Run step 2 anyway (the `|| update` path in the script handles this idempotently).
- **Trigger exists, destination is `roomstudio-api` (the pre-split service):**
  this trigger is stale. Delete and recreate:
  ```bash
  gcloud eventarc triggers delete captures-bundle-pb-finalized \
    --location=asia-southeast1 --project=roomstudio --quiet
  # The Eventarc delivery gap during recreate is acceptable. Per decision 0014,
  # the iOS client retains local capture data until Scene state reaches `ready`,
  # so any events that fire during the gap are not lost — they are re-triggered
  # when bundle.pb is re-uploaded. Proceed to step 2.
  ```

**Step 2: create/update the trigger**

```bash
./infra/eventarc_setup.sh --trigger-only
```

**Expect:**

```bash
gcloud eventarc triggers describe captures-bundle-pb-finalized \
  --location=asia-southeast1 --project=roomstudio
# Expect all of:
#   destination.cloudRun.service: api-internal
#   destination.cloudRun.region:  asia-southeast1
#   destination.cloudRun.path:    /ingest/eventarc
#   eventFilters: type=google.cloud.storage.object.v1.finalized
#   eventFilters: bucket=roomstudio-captures
#   serviceAccount: api-internal-runtime@roomstudio.iam.gserviceaccount.com
```

**If the trigger was created but the SA binding was missed** (e.g. the grant step failed
before the trigger step): re-run `--trigger-only` — the IAM grant is idempotent and runs
first.

**If trigger creation fails with "trigger already exists" despite the delete:**
Eventarc propagation can take 30–60 seconds. Wait and retry.

---

## Phase 7 — End-to-end verification via smoke tool

Run all four modes against the production service URLs (post-traffic-flip). The
`FIREBASE_API_KEY` and `FIREBASE_PROJECT_ID` env vars must be set (Phase 0b).

```bash
GCS_BUCKET="roomstudio-captures"
```

### Mode 1: happy-path

```bash
python3 tools/upload_test_bundle.py happy-path \
  --public-url="${API_PUBLIC_URL}" \
  --internal-url="${API_INTERNAL_URL}" \
  --firebase-api-key="${FIREBASE_API_KEY}" \
  --firebase-project-id="${FIREBASE_PROJECT_ID}" \
  --gcs-bucket="${GCS_BUCKET}" \
  --cleanup \
  --verbose
```

**Expect:** exit 0. The tool prints phase transitions culminating in `status=ready`.

### Mode 2: skip-blob

```bash
python3 tools/upload_test_bundle.py skip-blob \
  --public-url="${API_PUBLIC_URL}" \
  --internal-url="${API_INTERNAL_URL}" \
  --firebase-api-key="${FIREBASE_API_KEY}" \
  --firebase-project-id="${FIREBASE_PROJECT_ID}" \
  --gcs-bucket="${GCS_BUCKET}" \
  --drop-blob-kind=frame_jpeg \
  --cleanup \
  --verbose
```

**Expect:** exit 0. The tool reports `status=failed_incomplete` with the dropped path
present in `missing_paths`.

### Mode 3: duplicate-event

```bash
python3 tools/upload_test_bundle.py duplicate-event \
  --public-url="${API_PUBLIC_URL}" \
  --internal-url="${API_INTERNAL_URL}" \
  --firebase-api-key="${FIREBASE_API_KEY}" \
  --firebase-project-id="${FIREBASE_PROJECT_ID}" \
  --gcs-bucket="${GCS_BUCKET}" \
  --cleanup \
  --verbose
```

**Expect:** exit 0. The tool asserts `scene_id` is unchanged and `status=ready` after
re-upload of `bundle.pb`.

**Retry policy:** `duplicate-event` may be retried up to 2 additional times (3 attempts
total) to absorb Eventarc at-least-once delivery flake. Three consecutive failures is a
deploy failure. Log each attempt's exit code.

### Mode 4: auth-rejection

```bash
python3 tools/upload_test_bundle.py auth-rejection \
  --public-url="${API_PUBLIC_URL}" \
  --internal-url="${API_INTERNAL_URL}" \
  --firebase-api-key="${FIREBASE_API_KEY}" \
  --firebase-project-id="${FIREBASE_PROJECT_ID}" \
  --gcs-bucket="${GCS_BUCKET}" \
  --verbose
```

**Expect:** exit 0. The tool asserts `401 missing_token` from `/upload_session`
(no Authorization header sent) and never reaches upload or polling.

### TTL belt-and-braces check (after happy-path without --cleanup)

Run happy-path once more *without* `--cleanup` and record the `bundle_id` from the output.
Wait 60 seconds. Query Firestore:

```bash
BUNDLE_ID="<bundle_id from happy-path run>"
curl -s \
  "https://firestore.googleapis.com/v1/projects/roomstudio/databases/(default)/documents/upload_sessions/${BUNDLE_ID}" \
  -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print('EXISTS' if 'fields' in d else 'MISSING')"
# Expect: EXISTS
# (The document was just created; it should survive for 7 days. If MISSING immediately
# after creation, the TTL field semantics are wrong and this must be fixed before launch.)
```

**Accept:** all four modes exit 0 (with `duplicate-event` retry policy above), and the
TTL check returns EXISTS.

### Failure decision tree

- **Cloud Build succeeds but the Cloud Run revision never becomes healthy (`/health`
  does not return 200, or `gcloud run services describe` shows the revision unhealthy):**
  the container failed to start. Read the failed revision's import-time logs:
  ```bash
  gcloud logging read \
    'resource.type="cloud_run_revision" resource.labels.service_name="<service>" severity>=ERROR' \
    --project=roomstudio --limit=50
  ```
  Inspect the first error at container start. First suspects:
  (a) **Protobuf gencode/runtime `VersionError`** — see decision 0021; root cause was
  api-core install order in the Dockerfile downgrading protobuf.
  (b) **`FileNotFoundError` for a missing model or checkpoint path** — the current dead
  state of `perception-obj` (`/opt/sam3d/checkpoints/hf/pipeline.yaml` not found).
  Do not proceed to Phases 4–7 until the revision is healthy.

- **Smoke tool fails at `/upload_session` (before any upload):** api-public is broken.
  Roll back api-public traffic to prior revision (Phase 5 rollback). Leave api-internal
  at the new revision — it is compatible with the prior api-public.

- **Smoke tool fails during upload (PUT to session URI times out or 5xx):** a GCS
  configuration problem or IAM issue on api-public-runtime. Check api-public logs.
  Roll back api-public.

- **Smoke tool fails at polling (scene never reaches terminal state, times out):**
  Could be api-internal, Eventarc, perception-obj, or Cloud Tasks. Triage order:
  1. `gcloud logging read 'resource.type="cloud_run_revision" resource.labels.service_name="api-internal"' --project=roomstudio --limit=50`
  2. Check Eventarc trigger delivery metrics in the GCP console.
  3. Check perception-obj logs for the relevant `bundle_id`.
  Do not roll back until the layer is identified.

- **Smoke tool fails at `auth-rejection`:** auth boundary is broken. Roll back api-public.

- **TTL check returns MISSING immediately after creation:** `created_at` field semantics
  are wrong despite Phase 0's precondition. Document, halt further deploys, fix in a
  follow-up commit. This is a critical bug — a misconfigured TTL could delete documents
  before the upload flow completes.

---

## Phase 8 — Post-deploy cleanup

### 8a. Pre-split `roomstudio-api` Cloud Run service

The pre-split single-service revision (`services/api/`) may still be live in the project
with some or all traffic. Check:

```bash
gcloud run services describe roomstudio-api \
  --region=asia-southeast1 --project=roomstudio 2>/dev/null \
  | grep -E "traffic|url" || echo "roomstudio-api not found — nothing to do"
```

- **Not found:** nothing to do.
- **Found with no traffic:** leave it running as a rollback option for a 2-day window.
  After 2 days of smoke tool runs going green, delete:
  ```bash
  gcloud run services delete roomstudio-api \
    --region=asia-southeast1 --project=roomstudio --quiet
  ```
- **Found with traffic:** the Eventarc trigger may still be pointing at it (pre-Phase 6
  state). Confirm Phase 6 is complete (trigger points at `api-internal`), then move
  all traffic off `roomstudio-api` by updating traffic to 0:
  ```bash
  # Traffic should already be on api-internal/api-public from Phase 5.
  # If roomstudio-api still has traffic, it means the old trigger was delivering to it.
  # After Phase 6 is confirmed green, the old service gets no new events.
  # Leave it for the 2-day rollback window, then delete.
  ```

### 8b. Eventarc trigger cleanup

If Phase 6 required deleting a stale `roomstudio-api` trigger, that deletion is already
complete. If the trigger was updated in-place (destination was already `api-internal`),
no further cleanup is needed.

### 8c. Smoke tool confirmation run

24 hours after the initial deploy, run `happy-path` once more to confirm the system is
stable under the production configuration:

```bash
python3 tools/upload_test_bundle.py happy-path \
  --public-url="${API_PUBLIC_URL}" \
  --internal-url="${API_INTERNAL_URL}" \
  --firebase-api-key="${FIREBASE_API_KEY}" \
  --firebase-project-id="${FIREBASE_PROJECT_ID}" \
  --gcs-bucket="${GCS_BUCKET}" \
  --cleanup \
  --verbose
# Expect: exit 0, status=ready
```

If this passes, iOS code can begin.

---

## Quick reference

| Service     | URL (post-flip)                              | Auth model              |
|-------------|----------------------------------------------|-------------------------|
| api-public  | `${API_PUBLIC_URL}`                          | Firebase ID token       |
| api-internal| `${API_INTERNAL_URL}`                        | Cloud Run IAM (OIDC)    |
| perception-obj | `${PERCEPTION_URL}` (from Phase 0h)       | --allow-unauthenticated |

| Phase | Script / command                             | Idempotent? |
|-------|----------------------------------------------|-------------|
| 1     | `eventarc_setup.sh --lifecycle-only --ttl-only` | Yes      |
| 2     | `deploy_api_internal.sh`                     | Yes         |
| 3     | `deploy_api_public.sh`                       | Yes         |
| 4     | `curl` (smoke checks)                        | Yes         |
| 5     | `gcloud run services update-traffic`         | Yes         |
| 6     | `eventarc_setup.sh --trigger-only`           | Yes (create-or-update) |
| 7     | `tools/upload_test_bundle.py` (all 4 modes)  | Yes (with --cleanup)  |
