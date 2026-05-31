"""Inspect a serialized CaptureBundle. Read-only — verifies the wire format
parses, the optional fields resolve correctly, and prints what a perception
orchestrator would see when ingesting this bundle.

    python tools/inspect_bundle.py outputs/test_bundle/bundle.pb

This is the inverse of build_test_bundle.py. Use the two together to
iterate on the schema without depending on any client.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "packages/schemas"))
from roomstudio_schemas import CaptureBundle, CaptureTier  # noqa: E402
from roomstudio_schemas.pose_math import (  # noqa: E402
    conjugate_quat,
    pose_position,
    pose_quat,
    quat_norm,
    rotate_vec_by_quat,
)


def _tier_name(t: int) -> str:
    return CaptureTier.Name(t)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("bundle", type=Path, help="Path to a serialized .pb bundle.")
    ap.add_argument(
        "--show-frames", type=int, default=3,
        help="How many frames to print in full (default 3; -1 for all)."
    )
    args = ap.parse_args()

    if not args.bundle.exists():
        print(f"ERROR: {args.bundle} not found")
        sys.exit(1)

    wire = args.bundle.read_bytes()
    b = CaptureBundle()
    b.ParseFromString(wire)

    print(f"=== CaptureBundle ({len(wire)} bytes on the wire) ===")
    print(f"  schema_version:  {b.schema_version}")
    print(f"  bundle_id:       {b.bundle_id}")
    print(f"  user_id:         {b.user_id}")
    print(f"  tier:            {_tier_name(b.tier)}")
    print(f"  device:          {b.device.hardware_id} / iOS {b.device.os_version}")
    print(f"                   app {b.device.app_version}, has_lidar={b.device.has_lidar}")
    duration_s = (b.ended_at_device_us - b.started_at_device_us) / 1_000_000
    print(f"  duration:        {duration_s:.1f}s")
    if b.started_at_wall_us:
        import datetime
        wall_dt = datetime.datetime.fromtimestamp(
            b.started_at_wall_us / 1_000_000, tz=datetime.timezone.utc
        )
        print(f"  captured at:     {wall_dt.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"  frames:          {len(b.frames)}")
    print(f"  has room_plan:   {b.HasField('room_plan')}")
    if b.client_notes:
        print(f"  client_notes:    {dict(b.client_notes)}")

    # Per-frame summary table.
    if not b.frames:
        return
    print()
    print("=== Frames ===")
    print(f"{'idx':>3}  {'t (s)':>7}  {'rgb_path':<24}  {'pose pos (x,y,z)':<28}  "
          f"{'gravity (x,y,z)':<28}  depth")
    n_with_depth = 0
    t0 = b.frames[0].timestamp_us
    limit = len(b.frames) if args.show_frames < 0 else args.show_frames
    for i, f in enumerate(b.frames):
        if i >= limit and i < len(b.frames) - 1:
            if i == limit:
                print(f"  ... {len(b.frames) - limit - 1} frames elided ...")
            if f.HasField("depth"):
                n_with_depth += 1
            continue
        pos = pose_position(f.camera_pose)
        g = (f.gravity.x, f.gravity.y, f.gravity.z)
        depth_s = f.depth.depth_gcs_path if f.HasField("depth") else "-"
        if f.HasField("depth"):
            n_with_depth += 1
        t_rel = (f.timestamp_us - t0) / 1_000_000
        print(
            f"{f.frame_index:>3}  {t_rel:>7.3f}  {f.rgb_gcs_path[:24]:<24}  "
            f"({pos[0]:+.2f},{pos[1]:+.2f},{pos[2]:+.2f})       "
            f"({g[0]:+.2f},{g[1]:+.2f},{g[2]:+.2f})       {depth_s}"
        )

    print()
    print("=== Aggregate ===")
    positions = np.array([pose_position(f.camera_pose) for f in b.frames])
    extent = positions.max(0) - positions.min(0)
    print(
        f"  camera path extent (m): "
        f"x={extent[0]:.2f}  y={extent[1]:.2f}  z={extent[2]:.2f}"
    )
    print(f"  frames with depth:     {n_with_depth}/{len(b.frames)}")

    intr = b.frames[0].intrinsics
    print(
        f"  intrinsics (frame 0):  fx={intr.fx:.1f} fy={intr.fy:.1f} "
        f"cx={intr.cx:.1f} cy={intr.cy:.1f} size={intr.width}x{intr.height}"
    )

    # Depth intrinsics sanity — only meaningful for LiDAR bundles.
    # fx should be ~fx_rgb * (depth_w / rgb_w). For 256-wide depth / 1920-wide
    # RGB: expected ~200. If you see ~1500 the intrinsics are unscaled RGB — bug.
    first_depth = next((f for f in b.frames if f.HasField("depth")), None)
    if first_depth is not None:
        di = first_depth.depth.intrinsics
        print(
            f"  depth  intrinsics (frame {first_depth.frame_index}): "
            f"fx={di.fx:.1f} fy={di.fy:.1f} "
            f"cx={di.cx:.1f} cy={di.cy:.1f} size={di.width}x{di.height}"
        )
        if intr.width > 0 and di.width > 0:
            expected_fx = intr.fx * (di.width / intr.width)
            if abs(di.fx - expected_fx) > expected_fx * 0.2:
                print(
                    f"    WARN: depth fx={di.fx:.1f} far from "
                    f"scaled-RGB expected {expected_fx:.1f} — capture client bug?"
                )

    # Quaternion unit-norm check. The proto contract requires unit-norm
    # quaternions within 1e-3; the orchestrator runs this on every ingest.
    quat_norms = np.array([quat_norm(pose_quat(f.camera_pose)) for f in b.frames])
    max_q_err = float(np.abs(quat_norms - 1.0).max())
    print(f"  quaternion norm:       max ||q|| - 1 = {max_q_err:.6f}")
    if max_q_err > 1e-3:
        print("    WARN: quaternion outside unit-norm tolerance. Capture client bug?")

    # Gravity sanity check. The Pose quaternion rotates camera-local vectors
    # into world; the conjugate takes world->camera. Apply it to world-down
    # (0, -1, 0) and compare to the reported camera-local gravity. This is
    # the same computation the iOS client did when writing the bundle, run
    # back as verification on read — if the two disagree, either the client
    # has a bug or the bundle was corrupted.
    world_down = (0.0, -1.0, 0.0)
    max_err = 0.0
    for f in b.frames:
        q = pose_quat(f.camera_pose)
        expected = np.array(rotate_vec_by_quat(world_down, conjugate_quat(q)))
        got = np.array([f.gravity.x, f.gravity.y, f.gravity.z])
        err = float(np.linalg.norm(expected - got))
        max_err = max(max_err, err)
    print(f"  gravity vs pose check: max ||expected - reported|| = {max_err:.4f}")
    if max_err > 0.05:
        print("    WARN: gravity field doesn't agree with pose. Capture client bug?")

    if b.HasField("room_plan"):
        print()
        print("=== RoomPlan ===")
        rp = b.room_plan
        print(f"  usdz_gcs_path:   {rp.usdz_gcs_path}")
        print(f"  roomplan_version: {rp.roomplan_version}")
        if rp.HasField("summary"):
            s = rp.summary
            print(f"  walls/doors/windows: {s.wall_count}/{s.door_count}/{s.window_count}")
            print(f"  objects:")
            for o in s.objects:
                print(
                    f"    {o.category:<14}  center=({o.center_x:+.2f},{o.center_y:+.2f},{o.center_z:+.2f})  "
                    f"extent=({o.extent_x:.2f},{o.extent_y:.2f},{o.extent_z:.2f})  yaw={o.yaw_rad:+.2f}rad"
                )


if __name__ == "__main__":
    main()
