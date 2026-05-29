"""Tests for tools/smoke_test_e2e.py.

Only --dry-run behaviour is tested here. The full pipeline requires live GCS,
Firestore, and Cloud Run — mocking those would verify the mock, not the system.
Run the real script against staging when you need end-to-end confidence.
"""
from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

import smoke_test_e2e as sut


# ---------------------------------------------------------------------------
# _ts / _elapsed — pure formatting
# ---------------------------------------------------------------------------

def test_ts_format():
    ts = sut._ts()
    assert ts.startswith("[") and ts.endswith("]")
    # [HH:MM:SS] → 10 chars
    assert len(ts) == 10


def test_elapsed_returns_string_ending_in_s():
    import time
    start = time.time() - 5
    result = sut._elapsed(start)
    assert result.endswith("s")
    assert int(result[:-1]) >= 5


# ---------------------------------------------------------------------------
# _extra_info — field extraction
# ---------------------------------------------------------------------------

def test_extra_info_ready():
    fields = {"status": "ready", "result_uri": "gs://bucket/scene/"}
    assert sut._extra_info(fields, "ready") == "gs://bucket/scene/"


def test_extra_info_failed_short():
    fields = {"last_error": "RuntimeError: CUDA not available"}
    assert sut._extra_info(fields, "failed") == "RuntimeError: CUDA not available"


def test_extra_info_failed_truncates_long_error():
    fields = {"last_error": "x" * 200}
    result = sut._extra_info(fields, "failed")
    assert len(result) <= 81  # 80 chars + ellipsis
    assert result.endswith("…")


def test_extra_info_processing_is_empty():
    assert sut._extra_info({}, "processing") == ""


# ---------------------------------------------------------------------------
# --dry-run end-to-end (no real I/O)
# ---------------------------------------------------------------------------

def test_dry_run_exits_zero(tmp_path, capsys):
    """--dry-run should print commands and exit 0 without touching GCS or network."""
    # Create a minimal fake bundle
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    bundle_pb = bundle_dir / "bundle.pb"
    bundle_pb.write_bytes(b"\x00" * 16)
    frames_dir = bundle_dir / "frames"
    frames_dir.mkdir()
    (frames_dir / "000000.jpg").write_bytes(b"\xff\xd8\xff")

    # Patch sys.argv
    test_args = [
        "smoke_test_e2e.py",
        "--bundle", str(bundle_pb),
        "--bucket", "test-bucket",
        "--prefix", "smoke-test/dry",
        "--ingester-url", "https://api.example.com",
        "--dry-run",
    ]
    with patch("sys.argv", test_args):
        rc = sut.main()

    assert rc == 0
    out = capsys.readouterr().out
    assert "dry-run" in out
    assert "bundle.pb" in out
    assert "000000.jpg" in out
    assert "/ingest" in out


def test_dry_run_missing_bundle_exits_one(tmp_path, capsys):
    """--dry-run with a missing bundle file should exit 1 with a helpful message."""
    test_args = [
        "smoke_test_e2e.py",
        "--bundle", str(tmp_path / "nonexistent.pb"),
        "--dry-run",
    ]
    with patch("sys.argv", test_args):
        rc = sut.main()

    assert rc == 1
    err = capsys.readouterr().err
    assert "bundle not found" in err
