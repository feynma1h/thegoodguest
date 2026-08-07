"""Unit tests for roomstudio_api_core.manifest_validation (gaps c + F3).

Pins the invariants, not the wording of error details:
  - every path shape the deployed clients emit is accepted
  - unknown directories / extensions / nesting / traversal are rejected
  - expected_size_bytes is required, an int >= 1, and capped (per-blob,
    bundle.pb-specific, and whole-manifest totals)
  - exactly one bundle.pb per manifest; duplicates rejected
  - the env caps are read per call

Run from repo root:
  pytest packages/api-core/tests/test_manifest_validation.py -v
"""
from __future__ import annotations

from roomstudio_api_core.manifest_validation import (
    BUNDLE_PB_MAX_BYTES,
    validate_manifest,
)


def _entry(path: str, size: int = 100) -> dict:
    return {"relative_path": path, "expected_size_bytes": size}


def _with_bundle(*entries: dict) -> list[dict]:
    return [*entries, _entry("bundle.pb", 64)]


# ---------------------------------------------------------------------------
# Accepted shapes — the full inventory every deployed client emits
# ---------------------------------------------------------------------------

class TestAcceptedShapes:
    def test_minimal_bundle_only(self) -> None:
        assert validate_manifest([_entry("bundle.pb", 1)]) is None

    def test_every_real_client_path_shape(self) -> None:
        manifest = _with_bundle(
            _entry("frames/000000.jpg", 350_000),
            _entry("frames/001234.jpg", 350_000),
            _entry("depth/000000.f32", 196_608),
            _entry("confidence/000000.png", 12_288),
            _entry("roomplan/room.json", 81_900),
            _entry("roomplan/room.usdz", 4_200_000),
        )
        assert validate_manifest(manifest) is None

    def test_bundle_pb_position_is_free(self) -> None:
        # Clients send bundle.pb last by convention (decision 0017), but the
        # server must not care about position — only presence.
        manifest = [_entry("bundle.pb", 64), _entry("frames/000000.jpg")]
        assert validate_manifest(manifest) is None

    def test_unknown_extra_entry_keys_ignored(self) -> None:
        manifest = [
            {"relative_path": "bundle.pb", "expected_size_bytes": 64,
             "future_field": "x"},
        ]
        assert validate_manifest(manifest) is None


# ---------------------------------------------------------------------------
# Path grammar rejections
# ---------------------------------------------------------------------------

class TestPathGrammar:
    def test_unknown_directory_rejected(self) -> None:
        err = validate_manifest(_with_bundle(_entry("exfil/x.jpg")))
        assert err is not None and "exfil" in err

    def test_wrong_extension_for_directory_rejected(self) -> None:
        err = validate_manifest(_with_bundle(_entry("frames/000000.png")))
        assert err is not None

    def test_executable_extension_rejected(self) -> None:
        err = validate_manifest(_with_bundle(_entry("frames/payload.exe")))
        assert err is not None

    def test_nested_path_rejected(self) -> None:
        err = validate_manifest(_with_bundle(_entry("frames/a/000000.jpg")))
        assert err is not None

    def test_root_level_non_bundle_rejected(self) -> None:
        err = validate_manifest(_with_bundle(_entry("stray.jpg")))
        assert err is not None

    def test_hidden_file_rejected(self) -> None:
        err = validate_manifest(_with_bundle(_entry("frames/.hidden.jpg")))
        assert err is not None

    def test_traversal_rejected(self) -> None:
        err = validate_manifest(_with_bundle(_entry("frames/../../x.jpg")))
        assert err is not None

    def test_leading_slash_rejected(self) -> None:
        err = validate_manifest(_with_bundle(_entry("/frames/000000.jpg")))
        assert err is not None

    def test_overlong_path_rejected(self) -> None:
        err = validate_manifest(_with_bundle(_entry("frames/" + "a" * 200 + ".jpg")))
        assert err is not None

    def test_non_dict_entry_rejected(self) -> None:
        err = validate_manifest([_entry("bundle.pb", 64), "frames/000000.jpg"])
        assert err is not None


# ---------------------------------------------------------------------------
# bundle.pb presence
# ---------------------------------------------------------------------------

class TestBundlePbRule:
    def test_missing_bundle_pb_rejected(self) -> None:
        err = validate_manifest([_entry("frames/000000.jpg")])
        assert err is not None and "bundle.pb" in err

    def test_duplicate_bundle_pb_rejected_as_duplicate(self) -> None:
        err = validate_manifest([_entry("bundle.pb", 64), _entry("bundle.pb", 64)])
        assert err is not None and "duplicate" in err


# ---------------------------------------------------------------------------
# Size rules
# ---------------------------------------------------------------------------

class TestSizeRules:
    def test_missing_size_rejected(self) -> None:
        err = validate_manifest([{"relative_path": "bundle.pb"}])
        assert err is not None and "expected_size_bytes" in err

    def test_zero_size_rejected(self) -> None:
        err = validate_manifest([_entry("bundle.pb", 0)])
        assert err is not None

    def test_negative_size_rejected(self) -> None:
        err = validate_manifest([_entry("bundle.pb", -5)])
        assert err is not None

    def test_bool_size_rejected(self) -> None:
        # bool is an int subclass; True must not read as size 1.
        err = validate_manifest([{"relative_path": "bundle.pb",
                                  "expected_size_bytes": True}])
        assert err is not None

    def test_float_size_rejected(self) -> None:
        err = validate_manifest([_entry("bundle.pb", 64.5)])  # type: ignore[arg-type]
        assert err is not None

    def test_bundle_pb_over_10mib_rejected(self) -> None:
        err = validate_manifest([_entry("bundle.pb", BUNDLE_PB_MAX_BYTES + 1)])
        assert err is not None

    def test_bundle_pb_at_10mib_accepted(self) -> None:
        assert validate_manifest([_entry("bundle.pb", BUNDLE_PB_MAX_BYTES)]) is None

    def test_blob_over_cap_rejected(self, monkeypatch) -> None:
        monkeypatch.setenv("UPLOAD_SESSION_MAX_BLOB_BYTES", "1000")
        err = validate_manifest(_with_bundle(_entry("frames/000000.jpg", 1001)))
        assert err is not None

    def test_total_over_cap_rejected(self, monkeypatch) -> None:
        monkeypatch.setenv("UPLOAD_SESSION_MAX_TOTAL_BYTES", "500")
        err = validate_manifest(_with_bundle(
            _entry("frames/000000.jpg", 300),
            _entry("frames/000001.jpg", 300),
        ))
        assert err is not None and "total" in err

    def test_path_count_cap(self, monkeypatch) -> None:
        monkeypatch.setenv("UPLOAD_SESSION_MAX_PATHS", "3")
        manifest = _with_bundle(
            _entry("frames/000000.jpg"),
            _entry("frames/000001.jpg"),
            _entry("frames/000002.jpg"),
        )
        err = validate_manifest(manifest)
        assert err is not None and "entries" in err

    def test_realistic_long_walk_within_default_caps(self) -> None:
        # RP-8's 2,170-path manifest is the largest real one to date; a
        # same-shaped manifest must clear the default caps with headroom.
        manifest = [_entry(f"frames/{i:06d}.jpg", 400_000) for i in range(722)]
        manifest += [_entry(f"depth/{i:06d}.f32", 196_608) for i in range(722)]
        manifest += [_entry(f"confidence/{i:06d}.png", 15_000) for i in range(722)]
        manifest += [
            _entry("roomplan/room.json", 81_900),
            _entry("roomplan/room.usdz", 4_200_000),
            _entry("bundle.pb", 600_000),
        ]
        assert validate_manifest(manifest) is None
