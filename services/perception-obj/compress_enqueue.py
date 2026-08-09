"""Fire-and-forget /compress task enqueue from /process's success path
(decisions 0125/0126 — the "new captures are born slow" residue).

Deliberately a copy of shell_enqueue.py's shape rather than a shared
helper: the two stages are independent, and the value of the duplication
is that neither can change the other's dispatch behaviour by accident.
Same queue, same invoker SA, same tombstone-avoiding task name — see
shell_enqueue.py for why the timestamp is in the name (decision 0060:
Cloud Tasks tombstones names for ~1h, so a bare scene_id would silently
dedupe an operator re-drive).

Ordering: enqueued AFTER the /shell enqueue, itself after release_ready.
Both are fire-and-forget; a failure here logs and leaves the ready room
intact, and the room renders from PLY exactly as it does today. The
compressed tier is an optimisation, never a precondition.

Environment (all set by infra/deploy_perception.sh in production):
  CLOUD_TASKS_PROJECT / CLOUD_TASKS_LOCATION / CLOUD_TASKS_QUEUE —
      queue coordinates; ANY missing → enqueue skips with a log.
  RECEIVER_URL            — this service's HTTPS URL; target is
                            RECEIVER_URL + "/compress" (also the OIDC aud).
  CLOUD_TASKS_INVOKER_SA  — OIDC token SA (absent → unauthenticated,
                            local dev only).

IAM prerequisite: none beyond /shell's — the same runtime SA needs
roles/cloudtasks.enqueuer on the same queue and roles/iam.serviceAccountUser
on the same invoker SA, both already granted idempotently at deploy.

Callers: process_receiver.handle_process (success path, AFTER
release_ready).
"""
from __future__ import annotations

import json
import logging
import os
import time

logger = logging.getLogger(__name__)

# Mirror /shell's deadline: must cover the receiver's full Cloud Run
# request timeout so Cloud Tasks never retries an attempt still running.
DISPATCH_DEADLINE_SECONDS = 930


def enqueue_compress_task(*, scene_id: str) -> bool:
    """Enqueue one /compress task. Returns True when a task was created,
    False when queue config is absent (local dev). Raises on transport
    failures — the caller treats any exception as log-and-continue."""
    project = os.environ.get("CLOUD_TASKS_PROJECT", "")
    location = os.environ.get("CLOUD_TASKS_LOCATION", "")
    queue = os.environ.get("CLOUD_TASKS_QUEUE", "")
    receiver_url = os.environ.get("RECEIVER_URL", "")
    if not (project and location and queue and receiver_url):
        logger.info(
            "compress enqueue skipped (no queue configured) scene_id=%s", scene_id
        )
        return False

    from google.cloud import tasks_v2  # deferred: not installed in tests
    from google.protobuf import duration_pb2

    client = tasks_v2.CloudTasksClient()
    queue_path = client.queue_path(project, location, queue)
    target_url = receiver_url.rstrip("/") + "/compress"

    http_request: dict = {
        "http_method": tasks_v2.HttpMethod.POST,
        "url": target_url,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({"scene_id": scene_id}).encode("utf-8"),
    }
    invoker_sa = os.environ.get("CLOUD_TASKS_INVOKER_SA", "")
    if invoker_sa:
        http_request["oidc_token"] = {"service_account_email": invoker_sa}

    task_name = f"compress-{scene_id}-{int(time.time())}"
    client.create_task(
        request={
            "parent": queue_path,
            "task": {
                "name": f"{queue_path}/tasks/{task_name}",
                "http_request": http_request,
                "dispatch_deadline": duration_pb2.Duration(
                    seconds=DISPATCH_DEADLINE_SECONDS
                ),
            },
        }
    )
    logger.info(
        "compress task enqueued scene_id=%s task=%s target=%s",
        scene_id, task_name, target_url,
    )
    return True
