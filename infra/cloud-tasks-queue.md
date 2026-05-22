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

| Variable                    | Example value                                       |
|-----------------------------|-----------------------------------------------------|
| CLOUD_TASKS_PROJECT         | roomstudio-prod                                     |
| CLOUD_TASKS_LOCATION        | asia-southeast1                                     |
| CLOUD_TASKS_QUEUE           | perception-dispatch                                 |
| PERCEPTION_OBJ_PROCESS_URL  | https://perception-obj-xxx.a.run.app/process        |

`PERCEPTION_OBJ_PROCESS_URL` targets the `/process` endpoint on perception-obj,
which does not exist yet. It is the subject of the next session
(perception-obj receiver endpoint).

When any Cloud Tasks variable is absent, the ingester falls back to an
in-memory dispatcher (appropriate for local dev; tasks are logged but not
actually enqueued).
