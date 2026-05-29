"""Tests for the TaskDispatcher interface contract (InMemoryTaskDispatcher).

CloudTasksDispatcher is not instantiated here — its deferred import means
importing dispatcher.py is safe without google-cloud-tasks installed.

Tests verify:
  - enqueue records task_name, payload, and target_url
  - payload dict is a copy (caller mutations don't affect stored tasks)
  - multiple enqueues accumulate independently
  - task_name = scene_id pattern (the contract from 0003-async-perception-dispatch.md)

Run from repo root:
  pytest services/api/tests/test_dispatcher.py -v
"""
from __future__ import annotations

from dispatcher import InMemoryTaskDispatcher


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
