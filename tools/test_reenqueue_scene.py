"""Unit tests for tools/reenqueue_scene.py's pure logic.

Pins the safety guards (decide), the env-file parser, and the task-name
scheme. No GCP access — the GCP-touching functions defer their imports and
are exercised only live by the operator.

Run from repo root:
  pytest tools/test_reenqueue_scene.py -v
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from reenqueue_scene import decide, parse_env_file, task_name_for

_NOW = datetime(2026, 7, 21, 15, 0, 0, tzinfo=UTC)


def _scene(status: str, lease_delta_s: float | None = None) -> dict:
    lease = None
    if lease_delta_s is not None:
        lease = _NOW + timedelta(seconds=lease_delta_s)
    return {
        "status": status,
        "lease_expires_at": lease,
        "bundle_uri": "gs://bucket/captures/x/bundle.pb",
    }


class TestDecide:
    def test_missing_doc_refused(self):
        d = decide(None, _NOW, force=False)
        assert not d.proceed

    def test_stranded_processing_expired_lease_proceeds(self):
        d = decide(_scene("processing", lease_delta_s=-3600), _NOW, force=False)
        assert d.proceed and not d.forced

    def test_processing_absent_lease_proceeds(self):
        d = decide(_scene("processing", lease_delta_s=None), _NOW, force=False)
        assert d.proceed

    def test_processing_live_lease_refused_without_force(self):
        d = decide(_scene("processing", lease_delta_s=+120), _NOW, force=False)
        assert not d.proceed
        assert "--force" in d.reason

    def test_processing_live_lease_forced(self):
        d = decide(_scene("processing", lease_delta_s=+120), _NOW, force=True)
        assert d.proceed and d.forced

    def test_queued_proceeds(self):
        assert decide(_scene("queued"), _NOW, force=False).proceed

    def test_failed_proceeds(self):
        assert decide(_scene("failed"), _NOW, force=False).proceed

    def test_ready_refused_without_force(self):
        d = decide(_scene("ready"), _NOW, force=False)
        assert not d.proceed
        assert "--force" in d.reason

    def test_ready_forced_proceeds(self):
        d = decide(_scene("ready"), _NOW, force=True)
        assert d.proceed and d.forced

    def test_unknown_status_refused_even_with_force(self):
        assert not decide(_scene("what"), _NOW, force=True).proceed


class TestEnvFileParser:
    def test_parses_flat_yaml(self, tmp_path: Path):
        p = tmp_path / "env.yaml"
        p.write_text(
            "# comment\n"
            "\n"
            "ENVIRONMENT: production\n"
            "CLOUD_TASKS_PROJECT: roomstudio\n"
            "PERCEPTION_OBJ_PROCESS_URL: https://x.a.run.app/process\n"
        )
        env = parse_env_file(p)
        assert env["CLOUD_TASKS_PROJECT"] == "roomstudio"
        assert env["PERCEPTION_OBJ_PROCESS_URL"] == "https://x.a.run.app/process"
        assert "# comment" not in env

    def test_parses_the_real_env_file(self):
        real = Path(__file__).resolve().parents[1] / "infra/api-internal.env.yaml"
        env = parse_env_file(real)
        for key in ("CLOUD_TASKS_PROJECT", "CLOUD_TASKS_LOCATION",
                    "CLOUD_TASKS_QUEUE", "PERCEPTION_OBJ_PROCESS_URL"):
            assert env.get(key), f"{key} missing from the real env file"


class TestTaskName:
    def test_unique_per_timestamp_and_charset(self):
        sid = "25a14caf-db19-487d-9a60-3bd4034cd4c4"
        n1 = task_name_for(sid, _NOW)
        n2 = task_name_for(sid, _NOW + timedelta(seconds=1))
        assert n1 != n2
        assert n1.startswith(sid + "-r")
        # Cloud Tasks task ids: letters, digits, hyphens, underscores.
        assert all(c.isalnum() or c in "-_" for c in n1)
