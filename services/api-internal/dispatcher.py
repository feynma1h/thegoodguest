"""Task dispatch abstraction for the roomstudio perception pipeline.

Wraps Google Cloud Tasks behind a thin interface so tests can swap in an
in-memory fake without any GCP credentials or the library installed.

The queue must be pre-created out-of-band (see infra/cloud-tasks-queue.md).
Application code never creates or manages the queue itself.

No google-cloud-tasks types leak outside CloudTasksDispatcher. The rest of
the codebase works entirely with plain dicts and strings.

Required environment variables (when running with the Cloud Tasks backend):
  CLOUD_TASKS_PROJECT   — GCP project ID (e.g. "roomstudio-prod")
  CLOUD_TASKS_LOCATION  — queue region (e.g. "asia-southeast1")
  CLOUD_TASKS_QUEUE     — queue name (e.g. "perception-dispatch")
  PERCEPTION_OBJ_PROCESS_URL — full URL of the perception-obj receiver
                               endpoint (e.g. https://perception-obj-xxx.run.app/process).

When these env vars are absent, ingest_server.py falls back to
InMemoryTaskDispatcher, which is appropriate for local dev and tests.

Consumers: ingest_server.py (the ingest dispatch step).
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

# Cloud Tasks stops waiting for a response after dispatch_deadline and schedules
# a retry — even if Cloud Run is still executing the attempt (its request
# timeout is 900s: infra/deploy_perception.sh --timeout=900). Keep this ≥ the
# Cloud Run timeout so Cloud Tasks never retries an attempt that is still
# alive. A premature retry would no-op via the lease (ALREADY_OWNED) but burns
# one of maxAttempts=3, and its 200 completes the task — leaving no retry to
# reclaim the scene if the original attempt later crashes. The 30s buffer over
# the Cloud Run timeout covers response-delivery overhead. (Cloud Tasks allows
# 15s–30min.)
DISPATCH_DEADLINE_SECONDS = 930


# ---------------------------------------------------------------------------
# Interface
# ---------------------------------------------------------------------------

class TaskDispatcher(ABC):
    """Interface for enqueueing perception jobs. Implementations must be
    thread-safe."""

    @abstractmethod
    def enqueue(
        self,
        *,
        task_name: str,
        payload: dict[str, Any],
        target_url: str,
    ) -> None:
        """Enqueue a single task.

        task_name:  Unique identifier for this task; used as the Cloud Tasks
                    task ID for deduplication within the 1-hour dedup window.
                    Must contain only letters, digits, hyphens, or underscores
                    (max 500 chars). Using scene_id satisfies this.
        payload:    JSON-serializable dict sent as the HTTP POST body to
                    target_url. The perception-obj receiver deserializes this.
        target_url: Full HTTPS URL the Cloud Tasks worker will POST to.

        Raises on any enqueue failure (duplicate task within dedup window is
        silently accepted by Cloud Tasks, not treated as an error here).
        """


# ---------------------------------------------------------------------------
# In-memory implementation (local dev / tests)
# ---------------------------------------------------------------------------

class InMemoryTaskDispatcher(TaskDispatcher):
    """Records every enqueued task in memory. For tests and local dev.

    Inspect .tasks after a call to assert on payload shape, task_name,
    and target_url.
    """

    def __init__(self) -> None:
        self.tasks: list[dict[str, Any]] = []

    def enqueue(
        self,
        *,
        task_name: str,
        payload: dict[str, Any],
        target_url: str,
    ) -> None:
        self.tasks.append({
            "task_name": task_name,
            "payload": dict(payload),  # shallow copy — callers shouldn't mutate
            "target_url": target_url,
        })


# ---------------------------------------------------------------------------
# Cloud Tasks implementation (production)
# ---------------------------------------------------------------------------

class CloudTasksDispatcher(TaskDispatcher):
    """Google Cloud Tasks-backed dispatcher.

    Sends an HTTP POST task to the configured queue. The task body is the
    JSON-serialized payload. OIDC auth is conditional: when
    CLOUD_TASKS_INVOKER_SA is set (as it is in production —
    infra/api-internal.env.yaml), enqueue() attaches an OIDC token minted for
    that service account, which perception-obj's receiver verifies. When the
    var is absent, tasks are sent unauthenticated (local dev against an
    --allow-unauthenticated target).

    Task name format: {queue_path}/tasks/{task_name}, where task_name is the
    scene_id. Cloud Tasks deduplicates on this name within a 1-hour window,
    implementing the idempotency guarantee from 0003-async-perception-dispatch.

    google.cloud.tasks_v2 is imported lazily so that importing this module in
    a test environment (no GCP credentials, library may not be installed) is
    safe — provided CloudTasksDispatcher is never instantiated.
    """

    def __init__(self, *, project: str, location: str, queue: str) -> None:
        self._project = project
        self._location = location
        self._queue = queue

    def enqueue(
        self,
        *,
        task_name: str,
        payload: dict[str, Any],
        target_url: str,
    ) -> None:
        from google.cloud import tasks_v2  # deferred: not installed in tests
        from google.protobuf import duration_pb2

        client = tasks_v2.CloudTasksClient()
        queue_path = client.queue_path(self._project, self._location, self._queue)

        http_request: dict[str, Any] = {
            "http_method": tasks_v2.HttpMethod.POST,
            "url": target_url,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(payload).encode("utf-8"),
        }

        # Attach OIDC token so the receiver can verify the request came from
        # Cloud Tasks (not an unauthenticated caller). The token's `email` claim
        # will equal CLOUD_TASKS_INVOKER_SA; the receiver checks this against its
        # CLOUD_TASKS_INVOKER_SA env var. If the env var is unset (local dev),
        # skip OIDC — the receiver also skips verification when its own
        # CLOUD_TASKS_INVOKER_SA is unset.
        import os as _os
        invoker_sa = _os.environ.get("CLOUD_TASKS_INVOKER_SA", "")
        if invoker_sa:
            http_request["oidc_token"] = {"service_account_email": invoker_sa}

        task = {
            # Full resource name pins the task ID for Cloud Tasks dedup.
            "name": f"{queue_path}/tasks/{task_name}",
            "http_request": http_request,
            # See DISPATCH_DEADLINE_SECONDS: must cover the receiver's full
            # Cloud Run request timeout so a live attempt is never retried.
            "dispatch_deadline": duration_pb2.Duration(
                seconds=DISPATCH_DEADLINE_SECONDS
            ),
        }
        client.create_task(request={"parent": queue_path, "task": task})
