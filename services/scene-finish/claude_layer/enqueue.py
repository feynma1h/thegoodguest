"""Handing work to the next task. A route never calls another route directly.

  TaskList          collects tasks in memory (tests, and the local run, which
                    drains the list itself)
  CloudTasksEnqueuer the queue the other stages use, same OIDC pattern as
                    perception-obj's shell_enqueue.py; the target is
                    RECEIVER_URL + path. Task names carry a timestamp because
                    Cloud Tasks tombstones names for about an hour.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Protocol

DISPATCH_DEADLINE_S = 930


class Enqueuer(Protocol):
    def enqueue(self, path: str, payload: dict, *, name: str, delay_s: float = 0.0) -> None: ...


@dataclass
class TaskList:
    tasks: list[dict] = field(default_factory=list)

    def enqueue(self, path: str, payload: dict, *, name: str, delay_s: float = 0.0) -> None:
        self.tasks.append({"path": path, "payload": payload, "name": name, "delay_s": delay_s})


class CloudTasksEnqueuer:
    def __init__(self) -> None:
        self.project = os.environ["CLOUD_TASKS_PROJECT"]
        self.location = os.environ["CLOUD_TASKS_LOCATION"]
        self.queue = os.environ["CLOUD_TASKS_QUEUE"]
        self.receiver_url = os.environ["RECEIVER_URL"].rstrip("/")
        self.invoker_sa = os.environ.get("CLOUD_TASKS_INVOKER_SA", "")

    def enqueue(self, path: str, payload: dict, *, name: str, delay_s: float = 0.0) -> None:
        from google.cloud import tasks_v2  # deferred: not installed in tests
        from google.protobuf import duration_pb2, timestamp_pb2

        client = tasks_v2.CloudTasksClient()
        parent = client.queue_path(self.project, self.location, self.queue)
        http: dict = {"http_method": tasks_v2.HttpMethod.POST, "url": self.receiver_url + path,
                      "headers": {"Content-Type": "application/json"}, "body": json.dumps(payload).encode()}
        if self.invoker_sa:
            http["oidc_token"] = {"service_account_email": self.invoker_sa}
        task: dict = {"name": f"{parent}/tasks/{name}-{int(time.time())}", "http_request": http,
                      "dispatch_deadline": duration_pb2.Duration(seconds=DISPATCH_DEADLINE_S)}
        if delay_s > 0:
            ts = timestamp_pb2.Timestamp()
            ts.FromSeconds(int(time.time() + delay_s))
            task["schedule_time"] = ts
        client.create_task(request={"parent": parent, "task": task})
