"""Fire-and-forget /shell task enqueue from /process's success path
(decision 0066).

Same queue + OIDC invoker pattern as the /process dispatch
(services/api-internal/dispatcher.py), pointed at this service's own
/shell endpoint. The task name is "shell-{scene_id}-{ts}": Cloud Tasks
tombstones task names for ~1h after completion (decision 0060), so a
bare scene_id name would silently dedupe operator re-drives — the
timestamp makes every enqueue a fresh task, and /shell's own
already-present fast-path provides the idempotency instead.

Environment (all set by infra/deploy_perception.sh in production):
  CLOUD_TASKS_PROJECT / CLOUD_TASKS_LOCATION / CLOUD_TASKS_QUEUE —
      queue coordinates; ANY missing → enqueue skips with a log (local
      dev has no queue; the scene stays ready without a shell).
  RECEIVER_URL            — this service's HTTPS URL; target is
                            RECEIVER_URL + "/shell" (also the OIDC aud).
  CLOUD_TASKS_INVOKER_SA  — OIDC token SA (absent → unauthenticated,
                            local dev only).

IAM prerequisite (deploy-time, idempotent in deploy_perception.sh): the
perception-obj runtime SA needs roles/cloudtasks.enqueuer on the queue
and roles/iam.serviceAccountUser on the invoker SA.

Callers: process_receiver.handle_process (success path, AFTER
release_ready — an enqueue failure logs and leaves the ready room
intact; the client's grace window absorbs a missing shell).
"""
from __future__ import annotations

import json
import logging
import os
import time

logger = logging.getLogger(__name__)

# Mirror the /process dispatch deadline (api-internal dispatcher.py): must
# cover the receiver's full Cloud Run request timeout (900s) so Cloud
# Tasks never retries an attempt that is still running.
DISPATCH_DEADLINE_SECONDS = 930


def enqueue_shell_task(*, scene_id: str, bundle_uri: str) -> bool:
    """Enqueue one /shell task. Returns True when a task was created,
    False when queue config is absent (local dev). Raises on transport
    failures — the caller treats any exception as log-and-continue."""
    project = os.environ.get("CLOUD_TASKS_PROJECT", "")
    location = os.environ.get("CLOUD_TASKS_LOCATION", "")
    queue = os.environ.get("CLOUD_TASKS_QUEUE", "")
    receiver_url = os.environ.get("RECEIVER_URL", "")
    if not (project and location and queue and receiver_url):
        logger.info(
            "shell enqueue skipped (no queue configured) scene_id=%s", scene_id
        )
        return False

    from google.cloud import tasks_v2  # deferred: not installed in tests
    from google.protobuf import duration_pb2

    client = tasks_v2.CloudTasksClient()
    queue_path = client.queue_path(project, location, queue)
    target_url = receiver_url.rstrip("/") + "/shell"

    http_request: dict = {
        "http_method": tasks_v2.HttpMethod.POST,
        "url": target_url,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(
            {"scene_id": scene_id, "bundle_uri": bundle_uri}
        ).encode("utf-8"),
    }
    invoker_sa = os.environ.get("CLOUD_TASKS_INVOKER_SA", "")
    if invoker_sa:
        http_request["oidc_token"] = {"service_account_email": invoker_sa}

    task_name = f"shell-{scene_id}-{int(time.time())}"
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
        "shell task enqueued scene_id=%s task=%s target=%s",
        scene_id, task_name, target_url,
    )
    return True
