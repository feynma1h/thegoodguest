"""Unit tests for thegoodguest_api_core.upload_session_repo.

Tests the module directly — no FastAPI, no HTTP, no GCS credentials.

Covers:
  validate_manifest_path:
    - valid relative paths → None
    - empty path → error string
    - leading slash → error string
    - gs:// prefix → error string
    - .. traversal → error string

  InMemoryUploadSessionRepository:
    - get_user_id: None for unknown bundle_id, stored uid after create_or_get
    - create_or_get: mints URIs, returns entries
    - create_or_get idempotency: same manifest paths → same entries
    - create_or_get replacement: different paths → new entries
    - get_fcm_token: None for unknown, stored token after create_or_get
    - parallel minting: manifest order preserved, real overlap, first error
      aborts without storing, UPLOAD_SESSION_MINT_CONCURRENCY=1 serial path
    - force_remint (decision 0116): absent → replay unchanged (the deployed
      client's behaviour), true → fresh URIs for the SAME path-set, stored
      entries replaced, mint quota charged, no second capture charged,
      ownership still fatal first, a refused re-mint leaves the stored URIs
      intact; plus the two parity pins that catch the Firestore mirror
      drifting away from the in-memory oracle

Run from repo root:
  pytest packages/api-core/tests/ -v
"""
from __future__ import annotations

import itertools
import threading
import time

import pytest

from datetime import datetime, timezone

from thegoodguest_api_core.upload_session_repo import (
    ForeignBundleError,
    InMemoryUploadSessionRepository,
    CaptureLimitError,
    MintRateLimitedError,
    validate_manifest_path,
)


# ---------------------------------------------------------------------------
# validate_manifest_path
# ---------------------------------------------------------------------------

class TestValidateManifestPath:
    def test_valid_simple_path(self) -> None:
        assert validate_manifest_path("bundle.pb") is None

    def test_valid_nested_path(self) -> None:
        assert validate_manifest_path("frames/000000.jpg") is None

    def test_valid_deeply_nested(self) -> None:
        assert validate_manifest_path("depth/raw/000000.f32") is None

    def test_empty_path_returns_error(self) -> None:
        err = validate_manifest_path("")
        assert err is not None
        assert "empty" in err

    def test_leading_slash_returns_error(self) -> None:
        err = validate_manifest_path("/frames/000000.jpg")
        assert err is not None
        assert "relative" in err

    def test_gcs_prefix_returns_error(self) -> None:
        err = validate_manifest_path("gs://bucket/frames/000000.jpg")
        assert err is not None
        assert "relative" in err

    def test_dotdot_traversal_returns_error(self) -> None:
        err = validate_manifest_path("../other/bundle.pb")
        assert err is not None
        assert ".." in err

    def test_dotdot_in_middle_returns_error(self) -> None:
        err = validate_manifest_path("frames/../../../etc/passwd")
        assert err is not None

    def test_single_dot_is_valid(self) -> None:
        # A single dot is not a traversal — just an unusual path segment.
        assert validate_manifest_path("./frames/000000.jpg") is None


# ---------------------------------------------------------------------------
# InMemoryUploadSessionRepository
# ---------------------------------------------------------------------------

def _fake_mint(bucket: str, blob_path: str, size_bytes: int) -> str:
    return f"https://fake/{blob_path}"


class TestInMemoryUploadSessionRepository:
    def test_get_user_id_unknown_returns_none(self) -> None:
        repo = InMemoryUploadSessionRepository()
        assert repo.get_user_id("unknown-bundle-id") is None

    def test_create_or_get_returns_entries(self) -> None:
        repo = InMemoryUploadSessionRepository()
        manifest = [
            {"relative_path": "frames/000000.jpg", "expected_size_bytes": 512},
            {"relative_path": "bundle.pb", "expected_size_bytes": 128},
        ]
        entries = repo.create_or_get(
            "bundle-1", "user-a", manifest, None,
            mint_uri_fn=_fake_mint, bucket="test-bucket",
        )
        assert len(entries) == 2
        paths = {e["relative_path"] for e in entries}
        assert paths == {"frames/000000.jpg", "bundle.pb"}
        for e in entries:
            assert e["session_uri"].startswith("https://fake/")

    def test_get_user_id_after_create(self) -> None:
        repo = InMemoryUploadSessionRepository()
        manifest = [{"relative_path": "bundle.pb", "expected_size_bytes": 128}]
        repo.create_or_get("b1", "user-abc", manifest, None, mint_uri_fn=_fake_mint, bucket="b")
        assert repo.get_user_id("b1") == "user-abc"

    def test_idempotency_same_paths_returns_same_entries(self) -> None:
        repo = InMemoryUploadSessionRepository()
        manifest = [{"relative_path": "bundle.pb", "expected_size_bytes": 128}]
        e1 = repo.create_or_get("b1", "user-a", manifest, None, mint_uri_fn=_fake_mint, bucket="bkt")
        e2 = repo.create_or_get("b1", "user-a", manifest, None, mint_uri_fn=_fake_mint, bucket="bkt")
        assert e1 == e2

    def test_different_paths_replaces_entries(self) -> None:
        repo = InMemoryUploadSessionRepository()
        m1 = [{"relative_path": "a.jpg", "expected_size_bytes": 100}]
        m2 = [{"relative_path": "b.jpg", "expected_size_bytes": 100}]
        e1 = repo.create_or_get("b1", "u", m1, None, mint_uri_fn=_fake_mint, bucket="bkt")
        e2 = repo.create_or_get("b1", "u", m2, None, mint_uri_fn=_fake_mint, bucket="bkt")
        assert {x["relative_path"] for x in e1} == {"a.jpg"}
        assert {x["relative_path"] for x in e2} == {"b.jpg"}

    def test_get_fcm_token_unknown_returns_none(self) -> None:
        repo = InMemoryUploadSessionRepository()
        assert repo.get_fcm_token("unknown") is None

    def test_get_fcm_token_stored(self) -> None:
        repo = InMemoryUploadSessionRepository()
        manifest = [{"relative_path": "bundle.pb", "expected_size_bytes": 128}]
        repo.create_or_get("b1", "u", manifest, "fcm-tok-xyz", mint_uri_fn=_fake_mint, bucket="bkt")
        assert repo.get_fcm_token("b1") == "fcm-tok-xyz"

    def test_get_fcm_token_none_when_not_provided(self) -> None:
        repo = InMemoryUploadSessionRepository()
        manifest = [{"relative_path": "bundle.pb", "expected_size_bytes": 128}]
        repo.create_or_get("b1", "u", manifest, None, mint_uri_fn=_fake_mint, bucket="bkt")
        assert repo.get_fcm_token("b1") is None

    def test_uri_includes_bundle_id_and_path(self) -> None:
        repo = InMemoryUploadSessionRepository()
        manifest = [{"relative_path": "frames/000000.jpg", "expected_size_bytes": 0}]
        entries = repo.create_or_get(
            "my-bundle-id", "u", manifest, None,
            mint_uri_fn=_fake_mint, bucket="bkt",
        )
        assert "my-bundle-id" in entries[0]["session_uri"]
        assert "frames/000000.jpg" in entries[0]["session_uri"]


# ---------------------------------------------------------------------------
# Parallel minting (invariants of create_or_get, through the public interface)
# ---------------------------------------------------------------------------

def _sized_manifest(n: int) -> list[dict]:
    return [
        {"relative_path": f"frames/{i:06d}.jpg", "expected_size_bytes": i}
        for i in range(n)
    ]


class TestParallelMinting:
    """Minting runs on a bounded pool since the 878-path serial mint took ~80 s
    in production (2026-07-26) and blew the client's 60 s timeout. These pin
    the contract, not the pool: order, real overlap, abort-without-store, and
    the serial fallback all must survive any reimplementation.
    """

    def test_entries_preserve_manifest_order(self) -> None:
        # Per-path jitter makes later entries finish earlier; the returned
        # list must still be in manifest order with each URI matching its own
        # path.
        def jittered_mint(bucket: str, blob_path: str, size_bytes: int) -> str:
            time.sleep((hash(blob_path) % 5) / 1000)
            return f"https://fake/{blob_path}"

        repo = InMemoryUploadSessionRepository()
        manifest = _sized_manifest(64)
        entries = repo.create_or_get(
            "b1", "u", manifest, None, mint_uri_fn=jittered_mint, bucket="bkt",
        )
        assert [e["relative_path"] for e in entries] == [
            m["relative_path"] for m in manifest
        ]
        for e in entries:
            assert e["session_uri"].endswith(f"captures/b1/{e['relative_path']}")

    def test_minting_actually_overlaps(self) -> None:
        lock = threading.Lock()
        in_flight = 0
        max_in_flight = 0

        def counting_mint(bucket: str, blob_path: str, size_bytes: int) -> str:
            nonlocal in_flight, max_in_flight
            with lock:
                in_flight += 1
                max_in_flight = max(max_in_flight, in_flight)
            time.sleep(0.02)
            with lock:
                in_flight -= 1
            return f"https://fake/{blob_path}"

        repo = InMemoryUploadSessionRepository()
        repo.create_or_get(
            "b1", "u", _sized_manifest(8), None,
            mint_uri_fn=counting_mint, bucket="bkt",
        )
        assert max_in_flight > 1

    def test_first_error_aborts_and_stores_no_entries(self) -> None:
        def failing_mint(bucket: str, blob_path: str, size_bytes: int) -> str:
            if blob_path.endswith("000003.jpg"):
                raise RuntimeError("mint boom")
            return f"https://fake/{blob_path}"

        repo = InMemoryUploadSessionRepository()
        with pytest.raises(RuntimeError, match="mint boom"):
            repo.create_or_get(
                "b1", "u", _sized_manifest(16), None,
                mint_uri_fn=failing_mint, bucket="bkt",
            )
        # The atomic claim (gap a) keeps ownership — but a failed mint must
        # never leave servable entries: the retry must take the
        # mint-everything path, not the idempotent short-circuit.
        assert repo.get_user_id("b1") == "u"
        entries = repo.create_or_get(
            "b1", "u", _sized_manifest(16), None,
            mint_uri_fn=_fake_mint, bucket="bkt",
        )
        assert len(entries) == 16
        assert all(e["session_uri"].startswith("https://fake/") for e in entries)

    def test_concurrency_one_is_serial_and_correct(self, monkeypatch) -> None:
        monkeypatch.setenv("UPLOAD_SESSION_MINT_CONCURRENCY", "1")
        lock = threading.Lock()
        in_flight = 0
        max_in_flight = 0

        def counting_mint(bucket: str, blob_path: str, size_bytes: int) -> str:
            nonlocal in_flight, max_in_flight
            with lock:
                in_flight += 1
                max_in_flight = max(max_in_flight, in_flight)
            time.sleep(0.005)
            with lock:
                in_flight -= 1
            return f"https://fake/{blob_path}"

        repo = InMemoryUploadSessionRepository()
        manifest = _sized_manifest(6)
        entries = repo.create_or_get(
            "b1", "u", manifest, None, mint_uri_fn=counting_mint, bucket="bkt",
        )
        assert max_in_flight == 1
        assert [e["relative_path"] for e in entries] == [
            m["relative_path"] for m in manifest
        ]

    def test_empty_manifest_returns_empty_list(self) -> None:
        repo = InMemoryUploadSessionRepository()
        entries = repo.create_or_get(
            "b1", "u", [], None, mint_uri_fn=_fake_mint, bucket="bkt",
        )
        assert entries == []


# ---------------------------------------------------------------------------
# Atomic ownership claim (gap a)
# ---------------------------------------------------------------------------

class TestOwnershipClaim:
    def test_foreign_uid_raises(self) -> None:
        repo = InMemoryUploadSessionRepository()
        manifest = [{"relative_path": "bundle.pb", "expected_size_bytes": 128}]
        repo.create_or_get("b1", "user-a", manifest, None,
                           mint_uri_fn=_fake_mint, bucket="bkt")
        with pytest.raises(ForeignBundleError):
            repo.create_or_get("b1", "user-b", manifest, None,
                               mint_uri_fn=_fake_mint, bucket="bkt")

    def test_foreign_uid_raises_even_mid_mint(self) -> None:
        # The claim lands BEFORE minting: a foreign caller arriving while the
        # owner's mint is still in flight (entries not yet stored) must be
        # rejected, not allowed to race for ownership.
        repo = InMemoryUploadSessionRepository()
        manifest = [{"relative_path": "bundle.pb", "expected_size_bytes": 128}]

        started = threading.Event()
        release = threading.Event()

        def slow_mint(bucket: str, blob_path: str, size_bytes: int) -> str:
            started.set()
            release.wait(timeout=5)
            return f"https://fake/{blob_path}"

        result: dict = {}

        def owner_call() -> None:
            result["entries"] = repo.create_or_get(
                "b1", "user-a", manifest, None,
                mint_uri_fn=slow_mint, bucket="bkt",
            )

        t = threading.Thread(target=owner_call)
        t.start()
        assert started.wait(timeout=5)
        try:
            with pytest.raises(ForeignBundleError):
                repo.create_or_get("b1", "user-b", manifest, None,
                                   mint_uri_fn=_fake_mint, bucket="bkt")
        finally:
            release.set()
            t.join(timeout=5)
        assert len(result["entries"]) == 1

    def test_owner_can_remint_after_partial_claim(self) -> None:
        # Crash-mid-mint recovery: same-UID retry with the same path set
        # mints fresh entries instead of replaying the empty claim.
        repo = InMemoryUploadSessionRepository()
        manifest = [{"relative_path": "bundle.pb", "expected_size_bytes": 128}]

        def boom(bucket: str, blob_path: str, size_bytes: int) -> str:
            raise RuntimeError("mint died")

        with pytest.raises(RuntimeError):
            repo.create_or_get("b1", "user-a", manifest, None,
                               mint_uri_fn=boom, bucket="bkt")
        entries = repo.create_or_get("b1", "user-a", manifest, None,
                                     mint_uri_fn=_fake_mint, bucket="bkt")
        assert len(entries) == 1


# ---------------------------------------------------------------------------
# Per-UID daily mint quota (gap b)
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 8, 7, 10, 0, 0, tzinfo=timezone.utc)


def _mint_once(repo, bundle_id: str, uid: str, quota: int, now=_NOW):
    manifest = [{"relative_path": "bundle.pb", "expected_size_bytes": 128}]
    return repo.create_or_get(
        bundle_id, uid, manifest, None,
        mint_uri_fn=_fake_mint, bucket="bkt",
        daily_mint_quota=quota, now=now,
    )


class TestMintQuota:
    def test_at_cap_raises_with_resets_at(self) -> None:
        repo = InMemoryUploadSessionRepository()
        _mint_once(repo, "b1", "u", quota=2)
        _mint_once(repo, "b2", "u", quota=2)
        with pytest.raises(MintRateLimitedError) as exc_info:
            _mint_once(repo, "b3", "u", quota=2)
        resets_at = exc_info.value.resets_at
        assert resets_at == datetime(2026, 8, 8, 0, 0, 0, tzinfo=timezone.utc)

    def test_replay_is_free(self) -> None:
        repo = InMemoryUploadSessionRepository()
        first = _mint_once(repo, "b1", "u", quota=1)
        for _ in range(3):
            assert _mint_once(repo, "b1", "u", quota=1) == first

    def test_rejected_call_claims_nothing(self) -> None:
        # A 429'd first-mint must not leave a claim record: retrying tomorrow
        # (or after a cap raise) is a fresh mint, and the bundle_id is not
        # burned.
        repo = InMemoryUploadSessionRepository()
        _mint_once(repo, "b1", "u", quota=1)
        with pytest.raises(MintRateLimitedError):
            _mint_once(repo, "b2", "u", quota=1)
        assert repo.get_user_id("b2") is None

    def test_day_roll_resets_count(self) -> None:
        repo = InMemoryUploadSessionRepository()
        _mint_once(repo, "b1", "u", quota=1, now=_NOW)
        next_day = datetime(2026, 8, 8, 0, 0, 1, tzinfo=timezone.utc)
        entries = _mint_once(repo, "b2", "u", quota=1, now=next_day)
        assert len(entries) == 1

    def test_quota_is_per_uid(self) -> None:
        repo = InMemoryUploadSessionRepository()
        _mint_once(repo, "b1", "user-a", quota=1)
        entries = _mint_once(repo, "b2", "user-b", quota=1)
        assert len(entries) == 1

    def test_none_quota_is_unlimited(self) -> None:
        repo = InMemoryUploadSessionRepository()
        for i in range(5):
            manifest = [{"relative_path": "bundle.pb", "expected_size_bytes": 128}]
            repo.create_or_get(f"b{i}", "u", manifest, None,
                               mint_uri_fn=_fake_mint, bucket="bkt")


# ---------------------------------------------------------------------------
# Per-UID daily CAPTURE ceiling (decision 0098)
#
# The mint quota bounds API calls; this bounds GPU spend. The pair of tests
# that matter are the ones separating the two: a re-mint of a capture already
# started today is free (it commits no new GPU), and a refused capture must
# not burn mint quota (or the user loses two allowances for one refusal).
# ---------------------------------------------------------------------------

def _capture(repo, bundle_id: str, uid: str, *, captures: int,
             mints: int | None = None, now=_NOW, paths=("bundle.pb",)):
    manifest = [{"relative_path": p, "expected_size_bytes": 128} for p in paths]
    return repo.create_or_get(
        bundle_id, uid, manifest, None,
        mint_uri_fn=_fake_mint, bucket="bkt",
        daily_mint_quota=mints, daily_capture_quota=captures, now=now,
    )


class TestCaptureCeiling:
    def test_at_cap_raises_with_resets_at(self) -> None:
        repo = InMemoryUploadSessionRepository()
        _capture(repo, "b1", "u", captures=2)
        _capture(repo, "b2", "u", captures=2)
        with pytest.raises(CaptureLimitError) as exc_info:
            _capture(repo, "b3", "u", captures=2)
        assert exc_info.value.resets_at == datetime(
            2026, 8, 8, 0, 0, 0, tzinfo=timezone.utc
        )

    def test_re_minting_the_same_capture_is_free(self) -> None:
        """A re-mint (0049 session expiry) sends a DIFFERENT path set for a
        bundle already claimed. It commits no new GPU, so it must not consume
        a capture — otherwise a user with flaky uploads runs out of captures
        without ever starting a second one."""
        repo = InMemoryUploadSessionRepository()
        _capture(repo, "b1", "u", captures=1, paths=("bundle.pb",))
        _capture(repo, "b1", "u", captures=1, paths=("bundle.pb", "frames/0.jpg"))
        # Still exactly one capture spent: a second bundle would now be the
        # one refused.
        with pytest.raises(CaptureLimitError):
            _capture(repo, "b2", "u", captures=1)

    def test_replay_is_free(self) -> None:
        repo = InMemoryUploadSessionRepository()
        first = _capture(repo, "b1", "u", captures=1)
        for _ in range(3):
            assert _capture(repo, "b1", "u", captures=1) == first

    def test_refused_capture_does_not_burn_mint_quota(self) -> None:
        """The capture cap is evaluated FIRST for exactly this reason."""
        repo = InMemoryUploadSessionRepository()
        _capture(repo, "b1", "u", captures=1, mints=10)
        with pytest.raises(CaptureLimitError):
            _capture(repo, "b2", "u", captures=1, mints=10)
        # 9 mints must remain against the SAME bundle (b1 is claimed, so no
        # capture is charged); the 10th would be the mint cap, not the capture.
        for i in range(9):
            _capture(repo, "b1", "u", captures=1, mints=10,
                     paths=("bundle.pb", f"frames/{i}.jpg"))
        with pytest.raises(MintRateLimitedError):
            _capture(repo, "b1", "u", captures=1, mints=10, paths=("x.jpg",))

    def test_refused_capture_claims_nothing(self) -> None:
        repo = InMemoryUploadSessionRepository()
        _capture(repo, "b1", "u", captures=1)
        with pytest.raises(CaptureLimitError):
            _capture(repo, "b2", "u", captures=1)
        assert repo.get_user_id("b2") is None

    def test_day_roll_resets_captures(self) -> None:
        repo = InMemoryUploadSessionRepository()
        _capture(repo, "b1", "u", captures=1, now=_NOW)
        next_day = datetime(2026, 8, 8, 0, 0, 1, tzinfo=timezone.utc)
        assert len(_capture(repo, "b2", "u", captures=1, now=next_day)) == 1

    def test_ceiling_is_per_uid(self) -> None:
        repo = InMemoryUploadSessionRepository()
        _capture(repo, "b1", "user-a", captures=1)
        assert len(_capture(repo, "b2", "user-b", captures=1)) == 1

    def test_none_ceiling_is_unlimited(self) -> None:
        repo = InMemoryUploadSessionRepository()
        for i in range(5):
            manifest = [{"relative_path": "bundle.pb", "expected_size_bytes": 128}]
            repo.create_or_get(f"b{i}", "u", manifest, None,
                               mint_uri_fn=_fake_mint, bucket="bkt")

    def test_both_counters_share_one_day_roll(self) -> None:
        repo = InMemoryUploadSessionRepository()
        _capture(repo, "b1", "u", captures=5, mints=5)
        next_day = datetime(2026, 8, 8, 0, 0, 1, tzinfo=timezone.utc)
        for i in range(5):
            _capture(repo, f"n{i}", "u", captures=5, mints=5, now=next_day)
        with pytest.raises(CaptureLimitError):
            _capture(repo, "n9", "u", captures=5, mints=5, now=next_day)


# ---------------------------------------------------------------------------
# force_remint — vending fresh URIs for a consumed session (decision 0116)
#
# The boundary under test: the path-set says WHAT the caller intends to
# upload, force_remint says WHETHER the URIs it already holds still work.
# Before this flag those were one input, so "I am retrying my POST" and "the
# session you gave me is dead" were the same request.
#
# The case that matters is same-path-set. A caller can already get fresh URIs
# by sending a DIFFERENT path-set (a subset falls through the replay branch),
# but a capture whose blobs the age=1d lifecycle rule swept needs the FULL
# path-set back, which is exactly the one that replays.
# ---------------------------------------------------------------------------

def _remint(repo, bundle_id: str, uid: str, *, force: bool,
            paths=("frames/000000.jpg", "bundle.pb"),
            mints=None, captures=None, now=_NOW):
    manifest = [{"relative_path": p, "expected_size_bytes": 128} for p in paths]
    return repo.create_or_get(
        bundle_id, uid, manifest, None,
        mint_uri_fn=_unique_mint, bucket="bkt",
        daily_mint_quota=mints, daily_capture_quota=captures,
        force_remint=force, now=now,
    )


_mint_serial = itertools.count()


def _unique_mint(bucket: str, blob_path: str, size_bytes: int) -> str:
    """A minter whose every call is distinguishable.

    _fake_mint is a pure function of the path, so it cannot tell a replay of
    stored URIs apart from a genuine re-mint that happened to produce the
    same string — the exact distinction these tests exist to make.
    """
    return f"https://fake/{next(_mint_serial)}/{blob_path}"


class TestForceRemint:
    def test_absent_flag_replays_exactly_as_before(self) -> None:
        """The deployed-client compatibility pin.

        Every shipped client omits this field, so the default must reproduce
        the old semantics: same path-set → the STORED URIs, byte for byte.
        """
        repo = InMemoryUploadSessionRepository()
        first = _remint(repo, "b1", "u", force=False)
        again = _remint(repo, "b1", "u", force=False)
        assert again == first

    def test_force_remint_same_pathset_returns_fresh_uris(self) -> None:
        """The gap being closed: same paths, genuinely new sessions."""
        repo = InMemoryUploadSessionRepository()
        first = _remint(repo, "b1", "u", force=False)
        forced = _remint(repo, "b1", "u", force=True)

        assert [e["relative_path"] for e in forced] == \
               [e["relative_path"] for e in first]
        first_uris = {e["session_uri"] for e in first}
        forced_uris = {e["session_uri"] for e in forced}
        assert not (first_uris & forced_uris), "no stored URI may survive"

    def test_stored_entries_are_replaced_so_the_dead_ones_never_come_back(
        self,
    ) -> None:
        """A later ordinary replay must serve the NEW URIs.

        If the re-mint did not overwrite the record, the next replay would
        hand the client back the dead sessions it just escaped.
        """
        repo = InMemoryUploadSessionRepository()
        dead = _remint(repo, "b1", "u", force=False)
        forced = _remint(repo, "b1", "u", force=True)
        replay = _remint(repo, "b1", "u", force=False)

        assert replay == forced
        assert replay != dead

    def test_force_remint_charges_mint_quota(self) -> None:
        """It is a real mint, so it is bounded like one.

        This is what makes trusting the client's claim safe: a client that
        sets the flag when it did not need to spends its own allowance.
        """
        repo = InMemoryUploadSessionRepository()
        _remint(repo, "b1", "u", force=False, mints=2)   # 1st
        _remint(repo, "b1", "u", force=True, mints=2)    # 2nd
        with pytest.raises(MintRateLimitedError):
            _remint(repo, "b1", "u", force=True, mints=2)

    def test_replay_stays_free_when_the_flag_is_absent(self) -> None:
        """Charging the quota must not leak into the ordinary replay path."""
        repo = InMemoryUploadSessionRepository()
        _remint(repo, "b1", "u", force=False, mints=1)
        for _ in range(5):
            _remint(repo, "b1", "u", force=False, mints=1)

    def test_force_remint_does_not_charge_a_second_capture(self) -> None:
        """Finishing an existing capture commits no new GPU.

        The whole point of the recovery loop is to complete a capture that
        already exists; charging it again would make recovery cost the user
        a scan they never took.
        """
        repo = InMemoryUploadSessionRepository()
        _remint(repo, "b1", "u", force=False, captures=1)
        forced = _remint(repo, "b1", "u", force=True, captures=1)
        assert len(forced) == 2

    def test_force_remint_of_an_unclaimed_bundle_is_a_first_claim(self) -> None:
        """No existing record → ordinary first claim, capture charged.

        The flag suppresses a replay; it does not exempt anyone from the
        ceiling. Otherwise it would be a free way past the GPU budget.
        """
        repo = InMemoryUploadSessionRepository()
        _remint(repo, "b1", "u", force=True, captures=1)
        with pytest.raises(CaptureLimitError):
            _remint(repo, "b2", "u", force=True, captures=1)

    def test_force_remint_cannot_reach_a_foreign_bundle(self) -> None:
        """Ownership is evaluated BEFORE the flag, and stays fatal.

        The security property: the flag is a recovery affordance, never a
        route to someone else's capture.
        """
        repo = InMemoryUploadSessionRepository()
        _remint(repo, "b1", "owner", force=False)
        with pytest.raises(ForeignBundleError):
            _remint(repo, "b1", "attacker", force=True)

    def test_a_refused_force_remint_leaves_the_stored_uris_intact(self) -> None:
        """A 429'd re-mint must not destroy what the client still holds."""
        repo = InMemoryUploadSessionRepository()
        first = _remint(repo, "b1", "u", force=False, mints=1)
        with pytest.raises(MintRateLimitedError):
            _remint(repo, "b1", "u", force=True, mints=1)
        assert _remint(repo, "b1", "u", force=False, mints=None) == first


class TestForceRemintImplementationParity:
    """The Firestore impl mirrors the in-memory oracle BY HAND.

    Nothing in this suite executes FirestoreUploadSessionRepository (it needs
    a live Firestore), so the mirroring is only as good as the next person's
    care. These two pins catch the drift that would actually hurt: a
    force_remint that silently does nothing in production while every
    in-memory test above stays green.
    """

    def test_both_implementations_accept_the_same_arguments(self) -> None:
        import inspect

        from thegoodguest_api_core.upload_session_repo import (
            FirestoreUploadSessionRepository,
            UploadSessionRepository,
        )

        abc_sig = inspect.signature(UploadSessionRepository.create_or_get)
        for impl in (InMemoryUploadSessionRepository,
                     FirestoreUploadSessionRepository):
            assert inspect.signature(impl.create_or_get) == abc_sig, impl.__name__

    def test_the_firestore_replay_branch_is_gated_on_force_remint(self) -> None:
        """Source-level, because behaviour is not reachable offline here.

        Pins the one line that matters: if the transaction's replay return is
        not guarded by the flag, production replays dead URIs forever.
        """
        import ast
        import inspect
        import textwrap

        from thegoodguest_api_core.upload_session_repo import (
            FirestoreUploadSessionRepository,
        )

        src = textwrap.dedent(
            inspect.getsource(FirestoreUploadSessionRepository.create_or_get)
        )
        guarded = [
            node
            for node in ast.walk(ast.parse(src))
            if isinstance(node, ast.If)
            and "force_remint" in ast.dump(node.test)
            and any(
                isinstance(inner, ast.Return)
                and "replay" in ast.dump(inner)
                for inner in ast.walk(node)
            )
        ]
        assert guarded, "the 'replay' return must sit under a force_remint guard"


# ---------------------------------------------------------------------------
# gcs_mint_resumable_uri session caching
# ---------------------------------------------------------------------------

class TestMintSessionCache:
    """The production minter reuses one AuthorizedSession per thread.

    Pins the credential-caching fix: per-call google.auth.default() + AuthorizedSession
    construction OOM-killed the 512 MiB api-public instance on a 2,170-path
    manifest at mint concurrency 64. Credentials resolution and session
    construction must happen at most once per thread, not once per path.
    """

    def _patch_auth(self, monkeypatch):
        import google.auth
        import google.auth.transport.requests as gatr

        counts = {"default": 0, "session": 0}

        class _FakeResponse:
            headers = {"Location": "https://fake-session-uri"}

            @staticmethod
            def raise_for_status() -> None:
                return None

        class _FakeSession:
            def __init__(self, credentials) -> None:
                counts["session"] += 1

            def post(self, url, headers=None, json=None):
                return _FakeResponse()

        def _fake_default(scopes=None):
            counts["default"] += 1
            return object(), "proj"

        monkeypatch.setattr(google.auth, "default", _fake_default)
        monkeypatch.setattr(gatr, "AuthorizedSession", _FakeSession)
        return counts

    def test_same_thread_constructs_one_session(self, monkeypatch) -> None:
        from thegoodguest_api_core import upload_session_repo as usr

        counts = self._patch_auth(monkeypatch)
        monkeypatch.setattr(usr, "_mint_thread_local", threading.local())

        for i in range(5):
            uri = usr.gcs_mint_resumable_uri("bkt", f"captures/b/{i}.jpg", 10)
            assert uri == "https://fake-session-uri"
        assert counts["default"] == 1
        assert counts["session"] == 1

    def test_distinct_threads_get_distinct_sessions(self, monkeypatch) -> None:
        from thegoodguest_api_core import upload_session_repo as usr

        counts = self._patch_auth(monkeypatch)
        monkeypatch.setattr(usr, "_mint_thread_local", threading.local())

        def _mint_two() -> None:
            usr.gcs_mint_resumable_uri("bkt", "captures/b/a.jpg", 10)
            usr.gcs_mint_resumable_uri("bkt", "captures/b/b.jpg", 10)

        threads = [threading.Thread(target=_mint_two) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        # One construction per thread — not per call (6 calls total).
        assert counts["session"] == 3
