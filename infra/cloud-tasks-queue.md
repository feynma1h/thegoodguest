# Cloud Tasks queue — perception-dispatch

`perception-dispatch` (location `asia-southeast1`, project `roomstudio`) is the
one queue in the system. Three producers enqueue onto it and one service
receives from it:

| Producer                                   | Task target               |
|--------------------------------------------|---------------------------|
| `api-internal` (`dispatcher.py`), at ingest | `perception-obj /process` |
| `perception-obj` (`shell_enqueue.py`)       | `perception-obj /shell`   |
| `perception-obj` (`compress_enqueue.py`)    | `perception-obj /compress`|

The two `perception-obj` producers fire-and-forget after a scene reaches
`ready`, so the derived-asset stages do not extend the reconstruction request.

## Who creates it

`infra/deploy_api_internal.sh` (step 4/10), idempotently — it describes the
queue and creates it only if absent. No application code creates or configures
the queue.

Config, as created and as live:

```
maxAttempts:   3
minBackoff:    30s
maxBackoff:    300s
maxDoublings:  3   (30s → 60s → 120s → cap at 300s)
target:        HTTP (not App Engine)
```

Retry policy rationale: bounded retry, then surface `failed` to the client for
a user-driven retry, per
`docs/decisions/0003-async-perception-dispatch.md`.

To repair out of band, the same command the deploy script runs:

```bash
gcloud tasks queues create perception-dispatch \
  --location=asia-southeast1 \
  --project=roomstudio \
  --max-attempts=3 \
  --min-backoff=30s \
  --max-backoff=300s \
  --max-doublings=3
```

## dispatch_deadline is set per task, not on the queue

Each producer sets `dispatch_deadline` on the task itself. It must be at least
`perception-obj`'s Cloud Run request timeout (900 s) — otherwise Cloud Tasks
gives up on a request the receiver is still working on and schedules a retry
against a scene whose lease is still held.
`services/api-internal/tests/test_dispatcher.py` pins that relationship.

## The OIDC chain

`CLOUD_TASKS_INVOKER_SA` is the service account Cloud Tasks uses to mint the
OIDC token attached to each delivery; `perception-obj` verifies that claim in
`oidc.py`. When it is unset on the producer, no token is attached, and when it
is unset on the receiver, verification is skipped — the local-dev path, not a
production one.

Two bindings make the chain work, both asserted on every run of the deploy
scripts that own them:

- `tasks-invoker@roomstudio.iam.gserviceaccount.com` needs `roles/run.invoker`
  on `perception-obj` (`infra/deploy_api_internal.sh`, step 3/10 — it skips the
  binding with a notice if `perception-obj` does not exist yet, so a first-time
  deploy runs it again afterwards).
- Each producer's runtime SA needs `roles/cloudtasks.enqueuer` and
  `roles/iam.serviceAccountUser` on `tasks-invoker`, so it may name that SA as
  the token minter when enqueueing — `api-internal-runtime@` via
  `infra/deploy_api_internal.sh`, `perception-obj-runtime@` via
  `ensure_obj_runtime_iam` in `infra/deploy_perception.sh`.

## Environment variables

Not duplicated here — they drift. `api-internal`'s are in
`infra/api-internal.env.yaml`; `perception-obj`'s are set inline by
`infra/deploy_perception.sh` (it takes no env-vars file). Both are the values
actually deployed.

When any Cloud Tasks variable is absent and `ENVIRONMENT` is not `production`,
`api-internal` falls back to an in-memory dispatcher. That is a local-dev
convenience; production startup requires the full set.
