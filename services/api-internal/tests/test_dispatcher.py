"""Tests for the TaskDispatcher interface contract.

google-cloud-tasks is not installed in the test environment; dispatcher.py's
deferred import keeps it importable regardless. InMemoryTaskDispatcher is
exercised directly; CloudTasksDispatcher is exercised against a stubbed
tasks_v2 module injected into sys.modules.

Tests verify:
  - enqueue records task_name, payload, and target_url
  - payload dict is a copy (caller mutations don't affect stored tasks)
  - multiple enqueues accumulate independently
  - task_name = scene_id pattern (the contract from 0003-async-perception-dispatch.md)
  - CloudTasksDispatcher sets a dispatch_deadline covering the receiver's
    Cloud Run request timeout (900s), so Cloud Tasks never retries a live attempt

Run from repo root:
  pytest services/api-internal/tests/test_dispatcher.py -v
"""
from __future__ import annotations

import sys
import types

import dispatcher
from dispatcher import CloudTasksDispatcher, InMemoryTaskDispatcher


class TestInMemoryTaskDispatcher:

    def test_enqueue_records_task(self):
        d = InMemoryTaskDispatcher()
        d.enqueue(
            task_name="scene-abc",
            payload={"scene_id": "scene-abc", "bundle_uri": "gs://b/bundle.pb"},
            target_url="http://localhost:8081/process",
        )
        assert len(d.tasks) == 1
        task = d.tasks[0]
        assert task["task_name"] == "scene-abc"
        assert task["payload"] == {"scene_id": "scene-abc", "bundle_uri": "gs://b/bundle.pb"}
        assert task["target_url"] == "http://localhost:8081/process"

    def test_enqueue_multiple_accumulates(self):
        d = InMemoryTaskDispatcher()
        d.enqueue(task_name="s1", payload={"scene_id": "s1", "bundle_uri": "gs://b/1.pb"}, target_url="http://x/process")
        d.enqueue(task_name="s2", payload={"scene_id": "s2", "bundle_uri": "gs://b/2.pb"}, target_url="http://x/process")
        assert len(d.tasks) == 2
        assert d.tasks[0]["task_name"] == "s1"
        assert d.tasks[1]["task_name"] == "s2"

    def test_enqueue_copies_payload(self):
        """Mutating the original payload dict after enqueue must not affect the stored task."""
        d = InMemoryTaskDispatcher()
        payload = {"scene_id": "s1", "bundle_uri": "gs://b/1.pb"}
        d.enqueue(task_name="s1", payload=payload, target_url="http://x/process")
        payload["extra"] = "injected"
        assert "extra" not in d.tasks[0]["payload"]

    def test_task_name_equals_scene_id(self):
        """The dispatch contract: task_name must equal scene_id for Cloud Tasks dedup."""
        d = InMemoryTaskDispatcher()
        scene_id = "3f2504e0-4f89-11d3-9a0c-0305e82c3301"
        d.enqueue(
            task_name=scene_id,
            payload={"scene_id": scene_id, "bundle_uri": "gs://b/bundle.pb"},
            target_url="http://x/process",
        )
        task = d.tasks[0]
        assert task["task_name"] == task["payload"]["scene_id"]

    def test_empty_task_list_on_init(self):
        d = InMemoryTaskDispatcher()
        assert d.tasks == []

    def test_payload_contains_scene_id_and_bundle_uri(self):
        """Every enqueued task must carry scene_id and bundle_uri — the minimum
        the perception-obj receiver needs to do its job."""
        d = InMemoryTaskDispatcher()
        d.enqueue(
            task_name="sid",
            payload={"scene_id": "sid", "bundle_uri": "gs://bucket/path/bundle.pb"},
            target_url="https://perception-obj.run.app/process",
        )
        payload = d.tasks[0]["payload"]
        assert "scene_id" in payload
        assert "bundle_uri" in payload
        assert payload["bundle_uri"].startswith("gs://")


class TestCloudTasksDispatcher:

    def _enqueue_with_stub(self, monkeypatch) -> dict:
        """Run CloudTasksDispatcher.enqueue against a stubbed tasks_v2 module
        and return the captured create_task request."""
        captured: dict = {}

        class _StubClient:
            def queue_path(self, project, location, queue):
                return f"projects/{project}/locations/{location}/queues/{queue}"

            def create_task(self, request):
                captured.update(request)

        stub = types.SimpleNamespace(
            CloudTasksClient=_StubClient,
            HttpMethod=types.SimpleNamespace(POST="POST"),
        )
        monkeypatch.setitem(sys.modules, "google.cloud.tasks_v2", stub)

        d = CloudTasksDispatcher(project="p", location="asia-southeast1", queue="q")
        d.enqueue(
            task_name="scene-abc",
            payload={"scene_id": "scene-abc", "bundle_uri": "gs://b/bundle.pb"},
            target_url="https://perception-obj.run.app/process",
        )
        return captured

    def test_dispatch_deadline_covers_cloud_run_timeout(self, monkeypatch):
        """dispatch_deadline must be >= perception-obj's 900s Cloud Run request
        timeout (infra/deploy_perception.sh --timeout=900). A shorter deadline
        makes Cloud Tasks retry attempts that are still running: the retry
        no-ops via the lease but burns a retry slot, and its 200 completes the
        task — stranding the scene if the original attempt later crashes."""
        request = self._enqueue_with_stub(monkeypatch)
        deadline = request["task"]["dispatch_deadline"]
        assert deadline.seconds == dispatcher.DISPATCH_DEADLINE_SECONDS
        assert deadline.seconds >= 900

    def test_task_name_pins_dedup_id(self, monkeypatch):
        """The full task resource name embeds task_name for Cloud Tasks dedup."""
        request = self._enqueue_with_stub(monkeypatch)
        assert request["task"]["name"].endswith("/tasks/scene-abc")
        assert request["parent"] == "projects/p/locations/asia-southeast1/queues/q"
