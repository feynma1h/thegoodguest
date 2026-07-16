"""Bundle validation logic for the roomstudio API ingester.

Pure functions: no I/O, no FastAPI. Takes a parsed CaptureBundle protobuf
and returns either None (passes all checks) or a (error_code, detail) pair
describing the first failing check.

Validation checks (in priority order):
  1. schema_version is in SUPPORTED_VERSIONS
  2. Every camera_pose quaternion is unit-norm within QUAT_NORM_TOLERANCE
  3. Depth fields require a LIDAR_* tier
  4. All GCS paths are relative (not full gs:// URIs)

Error codes are machine-readable strings. Details are human-readable and
include enough context (frame index, field name, observed value) to act on
without re-running.

Consumers: ingest_server.py (the FastAPI ingester).
"""
from __future__ import annotations

import math

SUPPORTED_VERSIONS: frozenset[str] = frozenset({"1"})
QUAT_NORM_TOLERANCE: float = 1e-3


def validate_bundle(bundle) -> tuple[str, str] | None:
    """Validate a parsed CaptureBundle.

    Returns None if all checks pass, or (error_code, detail) for the first
    failing check. Checks run in the order listed in the module docstring.

    Order is intentional and must be preserved:
      1. schema_version first — an unknown version means we can't trust any
         field interpretation, so there's no point running later checks.
      2. Quaternion norms — cheap, purely structural, catches iOS bugs early.
      3. Tier-vs-depth — semantic consistency between tier and frame content.
      4. GCS paths — catches writer bugs; last because it's the most tedious
         to construct a bundle that fails only this check.

    Tests that assert a specific error code must construct a bundle that
    passes all earlier checks and fails only the one under test. See
    tests/test_ingest.py for examples.
    """
    return (
        _check_schema_version(bundle)
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


def _check_quaternion_norms(bundle) -> tuple[str, str] | None:
    from roomstudio_schemas.pose_math import quat_norm, pose_quat

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
    from roomstudio_schemas import LIDAR_ARKIT, LIDAR_ROOMPLAN

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
    return None


def _tier_name(tier_value: int) -> str:
    from roomstudio_schemas import CaptureTier

    return CaptureTier.Name(tier_value)
