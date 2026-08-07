"""Scene TTL stamping tests (gap F6, decisions 0018/0086).

Pins the retention invariants on api-internal's write path:
  - terminal-failure transitions (failed / failed_invalid / failed_incomplete)
    schedule expiry at now + SCENES_FAILED_TTL_DAYS
  - revival to queued CLEARS a pending expiry
  - processing and ready-bound paths never touch the field
  - a newly created scene has no expiry
  - the env knob is honored

The Firestore TTL policy itself lives in infra/eventarc_setup.sh
(--scenes-ttl-only); these tests pin what the policy will act on.

Run from repo root:
  pytest services/api-internal/tests/test_scene_expiry.py -v
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from repository import InMemorySceneRepository, expiry_for_transition
from scene import SceneStatus, new_scene


def _make_scene(repo: InMemorySceneRepository, scene_id: str = "s1"):
    scene = new_scene(
        scene_id=scene_id,
        device_id="device-1",
        bundle_uri="gs://bucket/captures/b1/bundle.pb",
    )
    repo.create(scene)
    return scene


class TestExpiryForTransition:
    def test_terminal_failures_schedule_expiry(self) -> None:
        now = datetime(2026, 8, 7, tzinfo=timezone.utc)
        for status in (
            SceneStatus.FAILED,
            SceneStatus.FAILED_INVALID,
            SceneStatus.FAILED_INCOMPLETE,
        ):
            touch, value = expiry_for_transition(status, now)
            assert touch is True
            assert value == now + timedelta(days=90)

    def test_queued_clears(self) -> None:
        now = datetime(2026, 8, 7, tzinfo=timezone.utc)
        touch, value = expiry_for_transition(SceneStatus.QUEUED, now)
        assert touch is True
        assert value is None

    def test_processing_and_ready_leave_untouched(self) -> None:
        now = datetime(2026, 8, 7, tzinfo=timezone.utc)
        for status in (SceneStatus.PROCESSING, SceneStatus.READY):
            touch, _ = expiry_for_transition(status, now)
            assert touch is False

    def test_env_knob_honored(self, monkeypatch) -> None:
        monkeypatch.setenv("SCENES_FAILED_TTL_DAYS", "7")
        now = datetime(2026, 8, 7, tzinfo=timezone.utc)
        _, value = expiry_for_transition(SceneStatus.FAILED_INVALID, now)
        assert value == now + timedelta(days=7)


class TestRepositoryExpiryStamping:
    def test_new_scene_has_no_expiry(self) -> None:
        repo = InMemorySceneRepository()
        scene = _make_scene(repo)
        assert repo.get(scene.scene_id).expire_at is None

    def test_failed_invalid_sets_expiry(self) -> None:
        repo = InMemorySceneRepository()
        scene = _make_scene(repo)
        updated = repo.update_status(scene.scene_id, SceneStatus.FAILED_INVALID)
        assert updated.expire_at is not None
        assert updated.expire_at.tzinfo is not None
        delta = updated.expire_at - updated.updated_at
        assert delta == timedelta(days=90)

    def test_failed_incomplete_sets_expiry(self) -> None:
        repo = InMemorySceneRepository()
        scene = _make_scene(repo)
        updated = repo.update_status(
            scene.scene_id, SceneStatus.FAILED_INCOMPLETE,
            missing_paths=["frames/000001.jpg"],
        )
        assert updated.expire_at is not None

    def test_dispatch_failed_sets_expiry(self) -> None:
        repo = InMemorySceneRepository()
        scene = _make_scene(repo)
        updated = repo.update_status(
            scene.scene_id, SceneStatus.FAILED, last_error="dispatch_failed: boom"
        )
        assert updated.expire_at is not None

    def test_revival_to_queued_clears_expiry(self) -> None:
        # failed_incomplete → queued is the re-upload retry path
        # (ingest_server's existing_scene_id branch): the revived scene must
        # not carry the old deletion clock into its second life.
        repo = InMemorySceneRepository()
        scene = _make_scene(repo)
        repo.update_status(scene.scene_id, SceneStatus.FAILED_INCOMPLETE)
        assert repo.get(scene.scene_id).expire_at is not None
        revived = repo.update_status(scene.scene_id, SceneStatus.QUEUED)
        assert revived.expire_at is None

    def test_ready_path_never_stamps(self) -> None:
        # queued → processing → ready must leave expire_at absent end-to-end:
        # ready rooms are product data and never age out.
        repo = InMemorySceneRepository()
        scene = _make_scene(repo)
        repo.update_status(scene.scene_id, SceneStatus.PROCESSING)
        assert repo.get(scene.scene_id).expire_at is None
        done = repo.update_status(
            scene.scene_id, SceneStatus.READY,
            result_uri="gs://outputs/scenes/s1/manifest.json",
        )
        assert done.expire_at is None

    def test_revived_then_refailed_gets_fresh_expiry(self) -> None:
        repo = InMemorySceneRepository()
        scene = _make_scene(repo)
        first = repo.update_status(scene.scene_id, SceneStatus.FAILED_INCOMPLETE)
        repo.update_status(scene.scene_id, SceneStatus.QUEUED)
        second = repo.update_status(scene.scene_id, SceneStatus.FAILED_INCOMPLETE)
        assert second.expire_at is not None
        assert second.expire_at >= first.expire_at
