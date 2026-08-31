"""Bundle validation logic for the thegoodguest API ingester.

Pure functions: no I/O, no FastAPI. Takes a parsed CaptureBundle protobuf
(plus the bundle_id the caller derived from the upload URI) and returns
either None (passes all checks) or a (error_code, detail) pair describing
the first failing check.

Validation checks (in priority order):
  1. schema_version is in SUPPORTED_VERSIONS
  2. bundle.bundle_id matches the URI-derived bundle_id (exact,
     case-sensitive; skipped when the caller passes no expected id)
  3. device.device_id is populated (iOS Keychain per-device UUID)
  4. Every camera_pose quaternion is unit-norm within QUAT_NORM_TOLERANCE
  5. Depth fields require a LIDAR_* tier
  6. All GCS paths are relative (not full gs:// URIs)

Error codes are machine-readable strings. Details are human-readable and
include enough context (frame index, field name, observed value) to act on
without re-running.

Consumers: ingest_server.py (the FastAPI ingester).
"""
from __future__ import annotations

import math

SUPPORTED_VERSIONS: frozenset[str] = frozenset({"1"})
QUAT_NORM_TOLERANCE: float = 1e-3


def validate_bundle(
    bundle, expected_bundle_id: str | None = None
) -> tuple[str, str] | None:
    """Validate a parsed CaptureBundle.

    expected_bundle_id is the bundle_id the caller derived from the GCS
    upload URI (gs://…/captures/{bundle_id}/bundle.pb). None skips the
    cross-check (check 2) — that is only for callers with no upload URI in
    hand, e.g. fixture self-tests that validate bundle content in isolation.
    The ingest path always passes it.

    Returns None if all checks pass, or (error_code, detail) for the first
    failing check. Checks run in the order listed in the module docstring.

    Order is intentional and must be preserved:
      1. schema_version first — an unknown version means we can't trust any
         field interpretation, so there's no point running later checks.
      2. bundle_id cross-check — if the bundle's self-declared identity
         doesn't match where it was uploaded, every downstream join keyed on
         bundle_id is broken and content checks on a mis-identified bundle
         are noise. Cheapest check after schema_version (one string compare).
      3. Device identity — device_id must be populated (the iOS client's
         Keychain UUID); cheap, structural.
      4. Quaternion norms — cheap, purely structural, catches iOS bugs early.
      5. Tier-vs-depth — semantic consistency between tier and frame content.
      6. GCS paths — catches writer bugs; last because it's the most tedious
         to construct a bundle that fails only this check.

    Tests that assert a specific error code must construct a bundle that
    passes all earlier checks and fails only the one under test. See
    tests/test_ingest.py for examples.
    """
    return (
        _check_schema_version(bundle)
        or _check_bundle_id(bundle, expected_bundle_id)
        or _check_device_id(bundle)
        or _check_quaternion_norms(bundle)
        or _check_tier_depth_consistency(bundle)
        or _check_gcs_paths_relative(bundle)
    )


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def _check_schema_version(bundle) -> tuple[str, str] | None:
    v = bundle.schema_version
    if v not in SUPPORTED_VERSIONS:
        supported = sorted(SUPPORTED_VERSIONS)
        return (
            "unsupported_schema_version",
            f"schema_version {v!r} is not supported; supported: {supported}",
        )
    return None


def _check_bundle_id(bundle, expected_bundle_id: str | None) -> tuple[str, str] | None:
    """Cross-check the proto's self-declared bundle_id against the upload URI's.

    Comparison is exact and case-sensitive. Every downstream join on
    bundle_id — Firestore scenes.bundle_id queries, upload_sessions doc IDs,
    captures/{bundle_id}/ blob paths in GCS — is a byte-wise comparison, so a
    case-differing pair would break those joins exactly like a wholly
    different id and is rejected the same way, not normalized to a match.
    Conforming clients never hit this: the iOS client lowercases bundle_id at
    bundle assembly and builds the upload path from that same value.

    An empty proto bundle_id is caught here too — the ingest URI regex
    guarantees a non-empty expected value, so empty can never match.
    """
    if expected_bundle_id is None:
        return None
    if bundle.bundle_id != expected_bundle_id:
        return (
            "bundle_id_mismatch",
            f"bundle.bundle_id {bundle.bundle_id!r} does not match the "
            f"bundle_id {expected_bundle_id!r} derived from the upload URI; "
            "the proto must carry the exact bundle_id it was uploaded under",
        )
    return None


def _check_device_id(bundle) -> tuple[str, str] | None:
    if not bundle.device.device_id:
        return (
            "device_id_missing",
            "bundle.device.device_id is empty; the iOS client persists a "
            "per-device Keychain UUID and must populate this field",
        )
    return None


def _check_quaternion_norms(bundle) -> tuple[str, str] | None:
    from thegoodguest_schemas.pose_math import quat_norm, pose_quat

    for frame in bundle.frames:
        q = pose_quat(frame.camera_pose)
        norm = quat_norm(q)
        if abs(norm - 1.0) > QUAT_NORM_TOLERANCE:
            return (
                "quaternion_norm_out_of_range",
                f"frame {frame.frame_index}: camera_pose quaternion norm is "
                f"{norm:.6f}, expected 1.0 ± {QUAT_NORM_TOLERANCE}",
            )
    return None


def _check_tier_depth_consistency(bundle) -> tuple[str, str] | None:
    from thegoodguest_schemas import LIDAR_ARKIT, LIDAR_ROOMPLAN

    lidar_tiers = {LIDAR_ARKIT, LIDAR_ROOMPLAN}
    for frame in bundle.frames:
        if frame.HasField("depth") and bundle.tier not in lidar_tiers:
            tier_name = _tier_name(bundle.tier)
            return (
                "depth_requires_lidar_tier",
                f"frame {frame.frame_index} has depth but bundle tier is "
                f"{tier_name!r}; depth requires LIDAR_ARKIT or LIDAR_ROOMPLAN",
            )
    return None


def _check_gcs_paths_relative(bundle) -> tuple[str, str] | None:
    for frame in bundle.frames:
        if frame.rgb_gcs_path.startswith("gs://"):
            return (
                "absolute_gcs_path",
                f"frame {frame.frame_index}: rgb_gcs_path is an absolute GCS URI "
                f"({frame.rgb_gcs_path!r}); paths must be relative to the bundle prefix",
            )
        if frame.HasField("depth"):
            if frame.depth.depth_gcs_path.startswith("gs://"):
                return (
                    "absolute_gcs_path",
                    f"frame {frame.frame_index}: depth.depth_gcs_path is an absolute "
                    f"GCS URI ({frame.depth.depth_gcs_path!r}); paths must be relative",
                )
            if frame.depth.HasField("confidence_gcs_path"):
                if frame.depth.confidence_gcs_path.startswith("gs://"):
                    return (
                        "absolute_gcs_path",
                        f"frame {frame.frame_index}: depth.confidence_gcs_path is an "
                        f"absolute GCS URI ({frame.depth.confidence_gcs_path!r}); "
                        "paths must be relative",
                    )
    if bundle.HasField("room_plan"):
        usdz = bundle.room_plan.usdz_gcs_path
        if usdz.startswith("gs://"):
            return (
                "absolute_gcs_path",
                f"room_plan.usdz_gcs_path is an absolute GCS URI ({usdz!r}); "
                "paths must be relative",
            )
        room_json = bundle.room_plan.json_gcs_path
        if room_json.startswith("gs://"):
            return (
                "absolute_gcs_path",
                f"room_plan.json_gcs_path is an absolute GCS URI ({room_json!r}); "
                "paths must be relative",
            )
    return None


def _tier_name(tier_value: int) -> str:
    from thegoodguest_schemas import CaptureTier

    return CaptureTier.Name(tier_value)
