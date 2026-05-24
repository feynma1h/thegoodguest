"""Unit tests for InMemoryReceiverRepository.

Verifies the claim/release contract defined in receiver_repo.py:
  - claim on QUEUED → CLAIMED, scene transitions to processing
  - claim on PROCESSING with fresh lease → ALREADY_OWNED, no state change
  - claim on PROCESSING with stale lease → RECLAIMED, lease refreshed
  - claim on FAILED / READY → WRONG_STATE
  - claim on missing scene → NOT_FOUND
  - release_ready → scene ready, result_uri set, lease cleared
  - release_failed → scene failed, last_error set, lease cleared
  - concurrent claim race → exactly one winner

FirestoreReceiverRepository is NOT instantiated here; its deferred import means
importing receiver_repo.py is safe without google-cloud-firestore installed.

Run from repo root:
  pytest services/perception-obj/tests/test_receiver_repo.py -v
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone, timedelta

from receiver_repo import (
    ClaimStatus,
    InMemoryReceiverRepository,
)

_SCENE_ID = "scene-abc"
_BUNDLE_URI = "gs://bucket/captures/test/bundle.pb"
_DEVICE_ID = "device-xyz"

_future = datetime.now(tz=timezone.utc) + timedelta(hours=1)
_past   = datetime.now(tz=timezone.utc) - timedelta(hours=1)


# ---------------------------------------------------------------------------
# claim() — happy path
# ---------------------------------------------------------------------------

class TestClaimQueued:
    def test_returns_claimed(self):
        repo = InMemoryReceiverRepository()
        repo.seed(_SCENE_ID, status="queued", device_id=_DEVICE_ID)
        result = repo.claim(_SCENE_ID, lease_ttl_seconds=300)
        assert result.status == ClaimStatus.CLAIMED

    def test_scene_transitions_to_processing(self):
        repo = InMemoryReceiverRepository()
        repo.seed(_SCENE_ID, status="queued")
        repo.claim(_SCENE_ID, lease_ttl_seconds=300)
        assert repo.get_raw(_SCENE_ID)["status"] == "processing"

    def test_lease_is_written(self):
        repo = InMemoryReceiverRepository()
        repo.seed(_SCENE_ID, status="queued")
        before = datetime.now(tz=timezone.utc)
        repo.claim(_SCENE_ID, lease_ttl_seconds=300)
        after = datetime.now(tz=timezone.utc)
        lease = repo.get_raw(_SCENE_ID)["lease_expires_at"]
        assert lease is not None
        assert lease > before + timedelta(seconds=299)
        assert lease < after + timedelta(seconds=301)

    def test_carries_device_id(self):
        repo = InMemoryReceiverRepository()
        repo.seed(_SCENE_ID, status="queued", device_id=_DEVICE_ID)
        result = repo.claim(_SCENE_ID, lease_ttl_seconds=300)
        assert result.device_id == _DEVICE_ID


# ---------------------------------------------------------------------------
# claim() — PROCESSING with fresh lease
# ---------------------------------------------------------------------------

class TestClaimProcessingFreshLease:
    def test_returns_already_owned(self):
        repo = InMemoryReceiverRepository()
        repo.seed(_SCENE_ID, status="processing", lease_expires_at=_future)
        result = repo.claim(_SCENE_ID, lease_ttl_seconds=300)
        assert result.status == ClaimStatus.ALREADY_OWNED

    def test_no_state_change(self):
        repo = InMemoryReceiverRepository()
        repo.seed(_SCENE_ID, status="processing", lease_expires_at=_future)
        repo.claim(_SCENE_ID, lease_ttl_seconds=300)
        assert repo.get_raw(_SCENE_ID)["status"] == "processing"
        assert repo.get_raw(_SCENE_ID)["lease_expires_at"] == _future

    def test_device_id_empty(self):
        repo = InMemoryReceiverRepository()
        repo.seed(_SCENE_ID, status="processing", lease_expires_at=_future)
        result = repo.claim(_SCENE_ID, lease_ttl_seconds=300)
        assert result.device_id == ""


# ---------------------------------------------------------------------------
# claim() — PROCESSING with stale lease (crash recovery)
# ---------------------------------------------------------------------------

class TestClaimProcessingStale:
    def test_returns_reclaimed(self):
        repo = InMemoryReceiverRepository()
        repo.seed(_SCENE_ID, status="processing", device_id=_DEVICE_ID,
                  lease_expires_at=_past)
        result = repo.claim(_SCENE_ID, lease_ttl_seconds=300)
        assert result.status == ClaimStatus.RECLAIMED

    def test_lease_is_refreshed(self):
        repo = InMemoryReceiverRepository()
        repo.seed(_SCENE_ID, status="processing", lease_expires_at=_past)
        before = datetime.now(tz=timezone.utc)
        repo.claim(_SCENE_ID, lease_ttl_seconds=300)
        lease = repo.get_raw(_SCENE_ID)["lease_expires_at"]
        assert lease > before

    def test_status_remains_processing(self):
        """Stale reclaim keeps status at processing (no re-transition needed)."""
        repo = InMemoryReceiverRepository()
        repo.seed(_SCENE_ID, status="processing", lease_expires_at=_past)
        repo.claim(_SCENE_ID, lease_ttl_seconds=300)
        assert repo.get_raw(_SCENE_ID)["status"] == "processing"

    def test_carries_device_id(self):
        repo = InMemoryReceiverRepository()
        repo.seed(_SCENE_ID, status="processing", device_id=_DEVICE_ID,
                  lease_expires_at=_past)
        result = repo.claim(_SCENE_ID, lease_ttl_seconds=300)
        assert result.device_id == _DEVICE_ID

    def test_no_lease_treated_as_stale(self):
        """A PROCESSING scene with no lease_expires_at is treated as stale."""
        repo = InMemoryReceiverRepository()
        repo.seed(_SCENE_ID, status="processing", lease_expires_at=None)
        result = repo.claim(_SCENE_ID, lease_ttl_seconds=300)
        assert result.status == ClaimStatus.RECLAIMED


# ---------------------------------------------------------------------------
# claim() — wrong states
# ---------------------------------------------------------------------------

class TestClaimWrongState:
    def test_failed_returns_wrong_state(self):
        repo = InMemoryReceiverRepository()
        repo.seed(_SCENE_ID, status="failed")
        result = repo.claim(_SCENE_ID, lease_ttl_seconds=300)
        assert result.status == ClaimStatus.WRONG_STATE

    def test_ready_returns_wrong_state(self):
        repo = InMemoryReceiverRepository()
        repo.seed(_SCENE_ID, status="ready")
        result = repo.claim(_SCENE_ID, lease_ttl_seconds=300)
        assert result.status == ClaimStatus.WRONG_STATE

    def test_not_found(self):
        repo = InMemoryReceiverRepository()
        result = repo.claim("no-such-scene", lease_ttl_seconds=300)
        assert result.status == ClaimStatus.NOT_FOUND


# ---------------------------------------------------------------------------
# release_ready()
# ---------------------------------------------------------------------------

class TestReleaseReady:
    def _claimed_repo(self) -> InMemoryReceiverRepository:
        repo = InMemoryReceiverRepository()
        repo.seed(_SCENE_ID, status="queued", device_id=_DEVICE_ID)
        repo.claim(_SCENE_ID, lease_ttl_seconds=300)
        return repo

    def test_status_becomes_ready(self):
        repo = self._claimed_repo()
        repo.release_ready(_SCENE_ID, result_uri="gs://b/scenes/scene-abc/manifest.json")
        assert repo.get_raw(_SCENE_ID)["status"] == "ready"

    def test_result_uri_is_set(self):
        repo = self._claimed_repo()
        uri = "gs://b/scenes/scene-abc/manifest.json"
        repo.release_ready(_SCENE_ID, result_uri=uri)
        assert repo.get_raw(_SCENE_ID)["result_uri"] == uri

    def test_lease_is_cleared(self):
        repo = self._claimed_repo()
        repo.release_ready(_SCENE_ID, result_uri="gs://b/scenes/scene-abc/manifest.json")
        assert repo.get_raw(_SCENE_ID)["lease_expires_at"] is None

    def test_wrong_state_raises(self):
        repo = InMemoryReceiverRepository()
        repo.seed(_SCENE_ID, status="queued")
        try:
            repo.release_ready(_SCENE_ID, result_uri="gs://b/out.json")
            assert False, "should have raised"
        except ValueError:
            pass


# ---------------------------------------------------------------------------
# release_failed()
# ---------------------------------------------------------------------------

class TestReleaseFailed:
    def _claimed_repo(self) -> InMemoryReceiverRepository:
        repo = InMemoryReceiverRepository()
        repo.seed(_SCENE_ID, status="queued", device_id=_DEVICE_ID)
        repo.claim(_SCENE_ID, lease_ttl_seconds=300)
        return repo

    def test_status_becomes_failed(self):
        repo = self._claimed_repo()
        repo.release_failed(_SCENE_ID, last_error="something went wrong")
        assert repo.get_raw(_SCENE_ID)["status"] == "failed"

    def test_last_error_is_set(self):
        repo = self._claimed_repo()
        repo.release_failed(_SCENE_ID, last_error="bundle not found")
        assert repo.get_raw(_SCENE_ID)["last_error"] == "bundle not found"

    def test_lease_is_cleared(self):
        repo = self._claimed_repo()
        repo.release_failed(_SCENE_ID, last_error="err")
        assert repo.get_raw(_SCENE_ID)["lease_expires_at"] is None

    def test_wrong_state_raises(self):
        repo = InMemoryReceiverRepository()
        repo.seed(_SCENE_ID, status="queued")
        try:
            repo.release_failed(_SCENE_ID, last_error="err")
            assert False, "should have raised"
        except ValueError:
            pass


# ---------------------------------------------------------------------------
# release_lease()
# ---------------------------------------------------------------------------

class TestReleaseLease:
    def test_clears_lease_leaves_processing(self):
        repo = InMemoryReceiverRepository()
        repo.seed(_SCENE_ID, status="processing", lease_expires_at=_future)
        repo.release_lease(_SCENE_ID)
        raw = repo.get_raw(_SCENE_ID)
        assert raw["status"] == "processing"
        assert raw["lease_expires_at"] is None

    def test_clears_holder_id(self):
        repo = InMemoryReceiverRepository()
        repo.seed(_SCENE_ID, status="processing", lease_expires_at=_future,
                  lease_holder_id="worker-abc")
        repo.release_lease(_SCENE_ID)
        assert repo.get_raw(_SCENE_ID)["lease_holder_id"] == ""

    def test_noop_on_wrong_state(self):
        repo = InMemoryReceiverRepository()
        repo.seed(_SCENE_ID, status="ready", lease_expires_at=_future)
        repo.release_lease(_SCENE_ID)  # must not raise
        assert repo.get_raw(_SCENE_ID)["status"] == "ready"

    def test_noop_on_not_found(self):
        repo = InMemoryReceiverRepository()
        repo.release_lease("no-such-scene")  # must not raise


# ---------------------------------------------------------------------------
# release_queued()
# ---------------------------------------------------------------------------

class TestReleaseQueued:
    def test_status_becomes_queued(self):
        repo = InMemoryReceiverRepository()
        repo.seed(_SCENE_ID, status="processing", lease_expires_at=_future)
        repo.release_queued(_SCENE_ID)
        assert repo.get_raw(_SCENE_ID)["status"] == "queued"

    def test_lease_cleared(self):
        repo = InMemoryReceiverRepository()
        repo.seed(_SCENE_ID, status="processing", lease_expires_at=_future,
                  lease_holder_id="worker-xyz")
        repo.release_queued(_SCENE_ID, holder_id="worker-xyz")
        raw = repo.get_raw(_SCENE_ID)
        assert raw["lease_expires_at"] is None
        assert raw["lease_holder_id"] == ""

    def test_increments_shutdown_release_count(self):
        repo = InMemoryReceiverRepository()
        repo.seed(_SCENE_ID, status="processing", lease_expires_at=_future)
        repo.release_queued(_SCENE_ID)
        assert repo.get_raw(_SCENE_ID)["shutdown_release_count"] == 1

    def test_multiple_calls_accumulate(self):
        """Seeding processing each time simulates repeated SIGTERM scenarios."""
        repo = InMemoryReceiverRepository()
        repo.seed(_SCENE_ID, status="processing", lease_expires_at=_future)
        repo.release_queued(_SCENE_ID)
        # Re-seed as processing to test a second release.
        repo.seed(_SCENE_ID, status="processing", lease_expires_at=_future,
                  shutdown_release_count=1)
        repo.release_queued(_SCENE_ID)
        assert repo.get_raw(_SCENE_ID)["shutdown_release_count"] == 2

    def test_noop_if_not_processing(self):
        repo = InMemoryReceiverRepository()
        repo.seed(_SCENE_ID, status="ready")
        repo.release_queued(_SCENE_ID)  # must not raise or mutate
        assert repo.get_raw(_SCENE_ID)["status"] == "ready"

    def test_noop_on_not_found(self):
        repo = InMemoryReceiverRepository()
        repo.release_queued("no-such-scene")  # must not raise

    def test_noop_when_holder_id_does_not_match(self):
        """release_queued() is a no-op when the doc's lease_holder_id differs.

        Guards the reclaim-during-SIGTERM race: worker B may have reclaimed
        between worker A observing the scene and A's SIGTERM handler firing.
        A must not wipe B's lease.
        """
        repo = InMemoryReceiverRepository()
        repo.seed(_SCENE_ID, status="processing", lease_expires_at=_future,
                  lease_holder_id="worker-B")
        repo.release_queued(_SCENE_ID, holder_id="worker-A")
        raw = repo.get_raw(_SCENE_ID)
        assert raw["status"] == "processing"
        assert raw["lease_holder_id"] == "worker-B"
        assert raw["lease_expires_at"] == _future

    def test_releases_when_holder_id_matches(self):
        repo = InMemoryReceiverRepository()
        repo.seed(_SCENE_ID, status="processing", lease_expires_at=_future,
                  lease_holder_id="worker-A")
        repo.release_queued(_SCENE_ID, holder_id="worker-A")
        assert repo.get_raw(_SCENE_ID)["status"] == "queued"


# ---------------------------------------------------------------------------
# holder_id tracking
# ---------------------------------------------------------------------------

class TestHolderIdTracking:
    def test_claim_writes_holder_id(self):
        repo = InMemoryReceiverRepository()
        repo.seed(_SCENE_ID, status="queued")
        repo.claim(_SCENE_ID, 300, holder_id="worker-1")
        assert repo.get_raw(_SCENE_ID)["lease_holder_id"] == "worker-1"

    def test_reclaim_updates_holder_id(self):
        repo = InMemoryReceiverRepository()
        repo.seed(_SCENE_ID, status="processing", lease_expires_at=_past,
                  lease_holder_id="old-worker")
        repo.claim(_SCENE_ID, 300, holder_id="new-worker")
        assert repo.get_raw(_SCENE_ID)["lease_holder_id"] == "new-worker"

    def test_already_owned_does_not_change_holder_id(self):
        repo = InMemoryReceiverRepository()
        repo.seed(_SCENE_ID, status="processing", lease_expires_at=_future,
                  lease_holder_id="original-worker")
        repo.claim(_SCENE_ID, 300, holder_id="interloper")
        assert repo.get_raw(_SCENE_ID)["lease_holder_id"] == "original-worker"


# ---------------------------------------------------------------------------
# Concurrent stale-lease reclaim race
# ---------------------------------------------------------------------------

class TestConcurrentStaleReclaimRace:
    def test_exactly_one_wins_concurrent_stale_reclaim(self):
        """Two workers both see an expired lease and race to reclaim.

        The InMemoryReceiverRepository lock ensures exactly one gets RECLAIMED
        and the other gets ALREADY_OWNED (because the first reclaim refreshes
        the lease, so the second call sees a fresh lease).
        """
        repo = InMemoryReceiverRepository()
        repo.seed(_SCENE_ID, status="processing", lease_expires_at=_past,
                  device_id=_DEVICE_ID)

        results: list[ClaimStatus] = []
        lock = threading.Lock()

        def _worker():
            r = repo.claim(_SCENE_ID, lease_ttl_seconds=300, holder_id="w")
            with lock:
                results.append(r.status)

        threads = [threading.Thread(target=_worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 2
        reclaimed = results.count(ClaimStatus.RECLAIMED)
        nooped = results.count(ClaimStatus.ALREADY_OWNED)
        assert reclaimed == 1, f"Expected 1 RECLAIMED, got: {results}"
        assert nooped == 1, f"Expected 1 ALREADY_OWNED, got: {results}"


# ---------------------------------------------------------------------------
# Concurrent claim race
# ---------------------------------------------------------------------------

class TestConcurrentClaimRace:
    def test_exactly_one_thread_claims(self):
        """Two threads both try to claim the same QUEUED scene concurrently.
        The InMemoryReceiverRepository lock ensures exactly one gets CLAIMED
        and the other gets ALREADY_OWNED (the first thread's fresh lease blocks it).
        """
        repo = InMemoryReceiverRepository()
        repo.seed(_SCENE_ID, status="queued", device_id=_DEVICE_ID)

        results: list[ClaimStatus] = []
        lock = threading.Lock()

        def _worker():
            r = repo.claim(_SCENE_ID, lease_ttl_seconds=300)
            with lock:
                results.append(r.status)

        threads = [threading.Thread(target=_worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 2
        claimed_count = results.count(ClaimStatus.CLAIMED)
        already_owned_count = results.count(ClaimStatus.ALREADY_OWNED)
        assert claimed_count == 1, f"Expected exactly 1 CLAIMED, got: {results}"
        assert already_owned_count == 1, f"Expected exactly 1 ALREADY_OWNED, got: {results}"
