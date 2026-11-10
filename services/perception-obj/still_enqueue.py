"""Fire-and-forget /still task enqueue from /shell's success path
(decision 0363).

A room whose shell.json has just been written `ready` can be drawn, so this
asks scene-finish — a separate CPU service with the headless renderer — to
draw the room's still picture for the app. Same queue and OIDC invoker pattern
as shell_enqueue.py, pointed at scene-finish's /still: the target is
SCENE_FINISH_URL + "/still", which is also the token's audience (Cloud Tasks
defaults it to the URL), and scene-finish verifies it. The task name carries a
timestamp for the reason shell_enqueue.py gives; /still is idempotent, so a
redelivery draws the same picture again.

Environment (set by infra/deploy_perception.sh in production):
  SCENE_FINISH_URL — scene-finish's HTTPS URL. ABSENT -> skip with a log:
      that is the off switch, and the state of every image built before
      scene-finish existed.
  CLOUD_TASKS_PROJECT / CLOUD_TASKS_LOCATION / CLOUD_TASKS_QUEUE /
  CLOUD_TASKS_INVOKER_SA — as for shell_enqueue.py.

IAM: perception-obj-runtime's existing enqueuer grant on the queue and actAs
on the invoker cover the enqueue; tasks-invoker@ needs run.invoker on
scene-finish, which infra/deploy_scene_finish.sh grants.

Callers: shell_receiver.handle_shell, after run_shell wrote a ready shell.
"""
from __future__ import annotations

import json
import logging
import os
import time

logger = logging.getLogger(__name__)

# scene-finish's Cloud Run request timeout is 900 s, like this service's.
DISPATCH_DEADLINE_SECONDS = 930


def enqueue_still_task(*, scene_id: str) -> bool:
    """Enqueue one /still task. Returns True when a task was created, False
    when scene-finish or the queue is not configured. Raises on transport
    failures — the caller logs and carries on."""
    target = os.environ.get("SCENE_FINISH_URL", "").rstrip("/")
    project = os.environ.get("CLOUD_TASKS_PROJECT", "")
    location = os.environ.get("CLOUD_TASKS_LOCATION", "")
    queue = os.environ.get("CLOUD_TASKS_QUEUE", "")
    if not (target and project and location and queue):
        logger.info("still enqueue skipped (no scene-finish or queue configured) scene_id=%s", scene_id)
        return False

    from google.cloud import tasks_v2  # deferred: not installed in tests
    from google.protobuf import duration_pb2

    client = tasks_v2.CloudTasksClient()
    queue_path = client.queue_path(project, location, queue)
    http_request: dict = {
        "http_method": tasks_v2.HttpMethod.POST,
        "url": target + "/still",
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({"scene_id": scene_id}).encode("utf-8"),
    }
    invoker_sa = os.environ.get("CLOUD_TASKS_INVOKER_SA", "")
    if invoker_sa:
        http_request["oidc_token"] = {"service_account_email": invoker_sa}

    task_name = f"still-{scene_id}-{int(time.time())}"
    client.create_task(
        request={
            "parent": queue_path,
            "task": {
                "name": f"{queue_path}/tasks/{task_name}",
                "http_request": http_request,
                "dispatch_deadline": duration_pb2.Duration(seconds=DISPATCH_DEADLINE_SECONDS),
            },
        }
    )
    logger.info("still task enqueued scene_id=%s task=%s target=%s", scene_id, task_name, target + "/still")
    return True
