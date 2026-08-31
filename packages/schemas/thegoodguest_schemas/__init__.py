"""thegoodguest capture-bundle schemas.

The capture bundle is the contract between the iOS capture app and the
perception backend. The proto source of truth is
`packages/schemas/capture_bundle.proto`; this module re-exports the
generated Python types under stable names, and exposes the pose math
that interprets the Pose message's quaternion fields.

Usage:

    from thegoodguest_schemas import (
        CaptureBundle, Frame, Pose, Intrinsics, Gravity, Depth,
        Device, CaptureTier, RoomPlanModel,
    )
    from thegoodguest_schemas.pose_math import (
        rotate_vec_by_quat, conjugate_quat, rotmat_to_quat,
        pose_quat, pose_position, quat_norm,
    )

Regenerate after editing the .proto:

    ./tools/gen_proto.sh
"""
from .capture_bundle_pb2 import (  # noqa: F401
    CaptureBundle,
    CaptureTier,
    Depth,
    Device,
    Frame,
    Gravity,
    Intrinsics,
    PlaneAlignment,
    PlaneAnchor,
    Pose,
    RoomPlanModel,
)
from . import pose_math  # noqa: F401

# Surface the enum members at package level so callers can write
# `CaptureTier.LIDAR_ROOMPLAN` without the protobuf-specific incantation.
ARKIT_ONLY = CaptureTier.Value("ARKIT_ONLY")
LIDAR_ARKIT = CaptureTier.Value("LIDAR_ARKIT")
LIDAR_ROOMPLAN = CaptureTier.Value("LIDAR_ROOMPLAN")

# Plane-anchor alignment (decision 0066: the room-shell geometry source).
PLANE_HORIZONTAL = PlaneAlignment.Value("HORIZONTAL")
PLANE_VERTICAL = PlaneAlignment.Value("VERTICAL")

SCHEMA_VERSION = "1"
