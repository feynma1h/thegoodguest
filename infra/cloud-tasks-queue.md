# Cloud Tasks queue — perception-dispatch

The `perception-dispatch` queue must be created out-of-band before deploying
the ingester. Application code (services/api) enqueues tasks but never creates
or configures the queue.

## Required configuration

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

## Create via gcloud

```bash
gcloud tasks queues create perception-dispatch \
  --location=asia-southeast1 \
  --max-attempts=3 \
  --min-backoff=30s \
  --max-backoff=300s \
  --max-doublings=3
```

## Required environment variables in services/api

| Variable                    | Example value                                            |
|-----------------------------|----------------------------------------------------------|
| CLOUD_TASKS_PROJECT         | roomstudio-prod                                          |
| CLOUD_TASKS_LOCATION        | asia-southeast1                                          |
| CLOUD_TASKS_QUEUE           | perception-dispatch                                      |
| PERCEPTION_OBJ_PROCESS_URL  | https://perception-obj-xxx.a.run.app/process             |
| CLOUD_TASKS_INVOKER_SA      | cloud-tasks-invoker@roomstudio-prod.iam.gserviceaccount.com |

`CLOUD_TASKS_INVOKER_SA` is the service-account email Cloud Tasks uses to mint
the OIDC token attached to each task delivery. The receiver (`perception-obj`)
verifies this claim. If absent, no OIDC token is attached (appropriate for
local dev; the receiver also skips verification when its own
`CLOUD_TASKS_INVOKER_SA` is unset).

The invoker SA must have the `roles/run.invoker` role on the perception-obj
Cloud Run service.

When any Cloud Tasks variable is absent, the ingester falls back to an
in-memory dispatcher (appropriate for local dev; tasks are logged but not
actually enqueued).

## Required environment variables in services/perception-obj

| Variable                    | Example value                                            |
|-----------------------------|----------------------------------------------------------|
| FIRESTORE_PROJECT           | roomstudio-prod                                          |
| RECEIVER_URL                | https://perception-obj-xxx.a.run.app                     |
| CLOUD_TASKS_INVOKER_SA      | cloud-tasks-invoker@roomstudio-prod.iam.gserviceaccount.com |
| PERCEPTION_OUTPUTS_BUCKET   | roomstudio-perception-outputs                            |
| SCENE_LEASE_TTL_SECONDS     | 300 (default)                                            |

When `FIRESTORE_PROJECT` is absent, the receiver uses in-memory state (local dev).
When `CLOUD_TASKS_INVOKER_SA` is absent, OIDC verification is skipped (local dev).
