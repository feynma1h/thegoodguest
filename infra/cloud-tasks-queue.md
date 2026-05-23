# Cloud Tasks queue — perception-dispatch

The `perception-dispatch` queue is created automatically by `infra/deploy_api.sh`
(idempotent). Application code (services/api) enqueues tasks but never creates
or configures the queue itself.

## Queue configuration

```
maxAttempts:   3
minBackoff:    30s
maxBackoff:    300s
maxDoublings:  3   (30s → 60s → 120s → cap at 300s)
target:        HTTP (not App Engine)
```

Retry policy rationale: 3 attempts with 30s start matches the decision in
docs/decisions/0003-async-perception-dispatch.md — bounded retry, then
surface `failed` to iOS for user-driven retry.

## Create manually (if needed)

The deploy script handles this. Use this command only for out-of-band repair:

```bash
gcloud tasks queues create perception-dispatch \
  --location=asia-southeast1 \
  --project=roomstudio \
  --max-attempts=3 \
  --min-backoff=30s \
  --max-backoff=300s \
  --max-doublings=3
```

## Environment variables in services/api

All values are set by `infra/api.env.yaml` for the deployed service.

| Variable                    | Value                                                    |
|-----------------------------|----------------------------------------------------------|
| ENVIRONMENT                 | production                                               |
| FIRESTORE_PROJECT           | roomstudio                                               |
| CLOUD_TASKS_PROJECT         | roomstudio                                               |
| CLOUD_TASKS_LOCATION        | asia-southeast1                                          |
| CLOUD_TASKS_QUEUE           | perception-dispatch                                      |
| CLOUD_TASKS_INVOKER_SA      | tasks-invoker@roomstudio.iam.gserviceaccount.com         |
| PERCEPTION_OBJ_PROCESS_URL  | https://perception-obj-q62kcditqa-as.a.run.app/process   |

`CLOUD_TASKS_INVOKER_SA` is the service-account email Cloud Tasks uses to mint
the OIDC token attached to each task delivery. The receiver (`perception-obj`)
verifies this claim. If absent, no OIDC token is attached (appropriate for
local dev; the receiver also skips verification when its own
`CLOUD_TASKS_INVOKER_SA` is unset).

`tasks-invoker` SA must have `roles/run.invoker` on the perception-obj Cloud
Run service. `infra/deploy_api.sh` asserts this binding on every run.

`api-runtime` SA must have `roles/cloudtasks.enqueuer` project-wide and
`roles/iam.serviceAccountUser` on `tasks-invoker` so it can specify the OIDC
token SA when enqueueing. Both are asserted by `infra/deploy_api.sh`.

When any Cloud Tasks variable is absent (and `ENVIRONMENT` ≠ `production`),
the ingester falls back to an in-memory dispatcher (local dev only).

## Environment variables in services/perception-obj

| Variable                    | Value                                                    |
|-----------------------------|----------------------------------------------------------|
| FIRESTORE_PROJECT           | roomstudio                                               |
| RECEIVER_URL                | https://perception-obj-q62kcditqa-as.a.run.app           |
| CLOUD_TASKS_INVOKER_SA      | tasks-invoker@roomstudio.iam.gserviceaccount.com         |
| PERCEPTION_OUTPUTS_BUCKET   | roomstudio-perception-outputs                            |
| SCENE_LEASE_TTL_SECONDS     | 300 (default)                                            |

When `FIRESTORE_PROJECT` is absent, the receiver uses in-memory state (local dev).
When `CLOUD_TASKS_INVOKER_SA` is absent, OIDC verification is skipped (local dev).
