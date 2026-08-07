"""Tests for the backfill tool's stamping decision (gap F6, decision 0086).

Only the pure decision function is tested — the Firestore walk is a thin
stream-and-update the dry-run default keeps safe to rehearse live.

Run from repo root:
  pytest tools/test_backfill_scene_expiry.py -v
"""
from __future__ import annotations

from datetime import datetime, timezone

from backfill_scene_expiry import should_stamp


class TestShouldStamp:
    def test_terminal_failures_without_expiry_stamp(self) -> None:
        for status in ("failed", "failed_invalid", "failed_incomplete"):
            assert should_stamp(status, None) is True

    def test_live_states_never_stamp(self) -> None:
        # Includes the deliberate stuck-scene reference (processing).
        for status in ("queued", "processing", "ready"):
            assert should_stamp(status, None) is False

    def test_already_stamped_docs_left_alone(self) -> None:
        existing = datetime(2026, 9, 1, tzinfo=timezone.utc)
        assert should_stamp("failed_invalid", existing) is False

    def test_unknown_status_left_alone(self) -> None:
        assert should_stamp("", None) is False
        assert should_stamp("some_future_status", None) is False
