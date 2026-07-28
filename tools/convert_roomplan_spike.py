"""Convert a RoomPlan co-run spike recording into a real LIDAR_ROOMPLAN
CaptureBundle — the first fixture of that tier (RP-0, decision 0077).

The spike app (ios/RoomPlanSpike, decision 0076) records what the production
capture app WILL record once RP-6 ships: per-keyframe RGB/depth/confidence
with poses + intrinsics (keyframes.ndjson), the session's final plane-anchor
set (plane_anchors.json), and the RoomBuilder [.beautifyObjects] output as
Apple's CapturedRoom Codable JSON (captured_room_built.json) plus the
parametric USDZ. This tool assembles those into the GCS bundle-prefix layout
with a valid bundle.pb, so every server chunk (RP-2..RP-5) runs against real
LiDAR+RoomPlan data OFFLINE, and RP-8 can upload the same bundle for the
live E2E on the room with operator-verified 9/9 ground truth.

What is converted vs carried verbatim:
  - Frame poses / intrinsics / gravity: VERBATIM floats from keyframes.ndjson
    (the wire spot-check gate compares against those lines byte-for-byte).
    The spike serialized components at 3 decimals; the worst quaternion
    |norm-1| in the probe run is 6.9e-4, inside the 1e-3 wire contract — the
    tool FAILS loudly if any frame breaches it rather than normalizing
    (normalizing would break byte-consistency with the recording).
  - captured_room_built.json: byte-verbatim copy to roomplan/room.json — the
    0077 wire contract IS Apple's JSON untouched (coreModel stays opaque).
  - room_parametric.usdz: copied to roomplan/room.usdz (the optional
    debugging artifact; room_mesh.usdz is NOT wire material).
  - Plane anchors: the spike's 16-float column-major simd transforms become
    Pose quaternions via rotmat_to_quat (3-decimal column rounding lands
    within the unit-norm contract; verified per anchor). The spike's
    `String(describing:)` for unclassified planes ("none(…ARPlaneAnchor…)")
    normalizes to "" — matching PlaneAnchorExtractor.classificationString,
    which maps .none to "" on the production wire.
  - Tier: LIDAR_ROOMPLAN iff the built CapturedRoom carries >= 1 wall or
    floor (the 0077 tier condition, evaluated, not assumed); a run without
    a usable room converts as LIDAR_ARKIT with no room_plan field.

Blob copies use APFS clonefile (cp -c) when available so the ~600 MB of
pixel data costs no real disk; falls back to plain copies elsewhere.

Run from the repo root:

    python tools/convert_roomplan_spike.py
    python tools/inspect_bundle.py outputs/roomplan-spike-bundle/bundle.pb

Consumers: RP-2..RP-5 offline gates, RP-8's upload, tests that need a real
LIDAR_ROOMPLAN bundle. Re-run with --user-id <firebase-uid> before an RP-8
upload so the bundle belongs to the uploading identity.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "packages/schemas"))
from roomstudio_schemas import (  # noqa: E402
    LIDAR_ARKIT,
    LIDAR_ROOMPLAN,
    PLANE_HORIZONTAL,
    PLANE_VERTICAL,
    SCHEMA_VERSION,
    CaptureBundle,
)
from roomstudio_schemas.pose_math import quat_norm, rotmat_to_quat  # noqa: E402

DEFAULT_RUN = Path("outputs/roomplan-spike/probe-20260728-143602")
DEFAULT_OUT = Path("outputs/roomplan-spike-bundle")

QUAT_NORM_TOLERANCE = 1e-3  # mirrors services/api-internal/validation.py

# Namespace for deriving stable bundle/device ids from the run id, so two
# conversions of the same recording produce the same identifiers.
_ID_NAMESPACE = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")  # uuid.NAMESPACE_DNS


def _fail(msg: str) -> None:
    print(f"ERROR: {msg}")
    sys.exit(1)


def _read_run_start(events_path: Path) -> dict:
    """First run_start line of events.ndjson: machine, os, wall clock."""
    with events_path.open() as fh:
        for line in fh:
            d = json.loads(line)
            if d.get("type") == "run_start":
                return d
    _fail(f"no run_start event in {events_path}")
    raise AssertionError  # unreachable


def _normalize_classification(raw: str) -> str:
    """Spike recordings serialize ARPlaneAnchor.Classification via
    String(describing:), so unclassified planes read like
    "none((extension in ARKit):…)". The production wire maps .none to ""
    (PlaneAnchorExtractor.classificationString); match it exactly."""
    return "" if raw.startswith("none") else raw


def _clone_tree(src: Path, dst: Path) -> None:
    """Copy a blob directory, preferring APFS clonefile (instant, no disk)."""
    if dst.exists():
        shutil.rmtree(dst)
    if sys.platform == "darwin":
        r = subprocess.run(
            ["cp", "-c", "-R", str(src), str(dst)], capture_output=True
        )
        if r.returncode == 0:
            return
    shutil.copytree(src, dst)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run", type=Path, default=DEFAULT_RUN,
                    help=f"Spike run directory (default {DEFAULT_RUN})")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT,
                    help=f"Output bundle directory (default {DEFAULT_OUT})")
    ap.add_argument("--user-id", default=None,
                    help="CaptureBundle.user_id (default spike:{run_id}; pass a "
                         "real Firebase UID before an RP-8 upload)")
    ap.add_argument("--bundle-id", default=None,
                    help="Override the bundle_id (default: stable uuid5 of the run_id)")
    args = ap.parse_args()

    run: Path = args.run
    for name in ("keyframes.ndjson", "events.ndjson", "captured_room_built.json",
                 "plane_anchors.json", "frames", "depth", "confidence"):
        if not (run / name).exists():
            _fail(f"{run / name} not found — is --run a spike run directory?")

    run_start = _read_run_start(run / "events.ndjson")
    run_id = run_start["run_id"]
    wall_dt = _dt.datetime.fromisoformat(run_start["wall"].replace("Z", "+00:00"))

    bundle_id = (args.bundle_id or str(uuid.uuid5(_ID_NAMESPACE, f"roomstudio-spike:{run_id}"))).lower()
    user_id = args.user_id or f"spike:{run_id}"
    device_id = str(uuid.uuid5(_ID_NAMESPACE, f"roomstudio-spike-device:{run_id}")).lower()

    keyframes = [json.loads(line) for line in (run / "keyframes.ndjson").open()]
    if not keyframes:
        _fail("keyframes.ndjson is empty")
    if [d["i"] for d in keyframes] != list(range(len(keyframes))):
        _fail("keyframe indices are not contiguous 0..N-1")

    room_json_bytes = (run / "captured_room_built.json").read_bytes()
    room = json.loads(room_json_bytes)
    has_room = bool(room.get("walls")) or bool(room.get("floors"))
    tier = LIDAR_ROOMPLAN if has_room else LIDAR_ARKIT

    print(f"Converting spike run {run_id}")
    print(f"  bundle_id: {bundle_id}")
    print(f"  keyframes: {len(keyframes)}")
    print(f"  room:      {len(room.get('walls', []))} walls, "
          f"{len(room.get('floors', []))} floors, {len(room.get('objects', []))} objects "
          f"-> tier {'LIDAR_ROOMPLAN' if has_room else 'LIDAR_ARKIT (no usable room)'}")

    bundle = CaptureBundle()
    bundle.schema_version = SCHEMA_VERSION
    bundle.bundle_id = bundle_id
    bundle.user_id = user_id
    bundle.device.hardware_id = run_start.get("machine", "unknown")
    bundle.device.os_version = run_start.get("os", "unknown")
    bundle.device.app_version = "RoomPlanSpike (tools/convert_roomplan_spike.py)"
    bundle.device.has_lidar = True
    bundle.device.device_id = device_id
    bundle.tier = tier
    bundle.started_at_device_us = int(keyframes[0]["t_us"])
    bundle.ended_at_device_us = int(keyframes[-1]["t_us"])
    bundle.started_at_wall_us = int(wall_dt.timestamp() * 1_000_000)
    bundle.client_notes["source"] = "tools/convert_roomplan_spike.py"
    bundle.client_notes["spike_run_id"] = run_id

    # --- Frames: verbatim floats from the recording ---------------------------
    worst_quat_err = 0.0
    for kf in keyframes:
        i = kf["i"]
        q = kf["quat"]  # xyzw, as ARKit hands it over
        err = abs(quat_norm(tuple(q)) - 1.0)
        worst_quat_err = max(worst_quat_err, err)
        if err > QUAT_NORM_TOLERANCE:
            _fail(
                f"frame {i}: quaternion norm err {err:.2e} breaches the "
                f"{QUAT_NORM_TOLERANCE} wire contract — the recording's rounding "
                "is too coarse to convert verbatim"
            )

        for rel, kind in ((kf["rgb"], "rgb"), (kf.get("depth_rel"), "depth"),
                          (kf.get("conf_rel"), "confidence")):
            if rel and not (run / rel).exists():
                _fail(f"frame {i}: referenced {kind} blob {rel} missing on disk")
        if kf.get("depth_present"):
            dsize = (run / kf["depth_rel"]).stat().st_size
            want = kf["depth_w"] * kf["depth_h"] * 4
            if dsize != want:
                _fail(f"frame {i}: depth blob is {dsize} bytes, expected {want}")
            csize = (run / kf["conf_rel"]).stat().st_size
            if csize != kf["depth_w"] * kf["depth_h"]:
                _fail(f"frame {i}: confidence blob is {csize} bytes, "
                      f"expected {kf['depth_w'] * kf['depth_h']}")

        f = bundle.frames.add()
        f.frame_index = i
        f.timestamp_us = int(kf["t_us"])
        f.rgb_gcs_path = kf["rgb"]
        f.camera_pose.pos_x, f.camera_pose.pos_y, f.camera_pose.pos_z = kf["pos"]
        f.camera_pose.quat_x, f.camera_pose.quat_y, f.camera_pose.quat_z, f.camera_pose.quat_w = q
        f.intrinsics.fx = kf["fx"]
        f.intrinsics.fy = kf["fy"]
        f.intrinsics.cx = kf["cx"]
        f.intrinsics.cy = kf["cy"]
        f.intrinsics.width = kf["w"]
        f.intrinsics.height = kf["h"]
        f.gravity.x, f.gravity.y, f.gravity.z = kf["gravity"]
        if kf.get("depth_present"):
            f.depth.depth_gcs_path = kf["depth_rel"]
            f.depth.confidence_gcs_path = kf["conf_rel"]
            f.depth.width = kf["depth_w"]
            f.depth.height = kf["depth_h"]
            f.depth.intrinsics.fx = kf["depth_fx"]
            f.depth.intrinsics.fy = kf["depth_fy"]
            f.depth.intrinsics.cx = kf["depth_cx"]
            f.depth.intrinsics.cy = kf["depth_cy"]
            f.depth.intrinsics.width = kf["depth_w"]
            f.depth.intrinsics.height = kf["depth_h"]

    # --- Plane anchors (kept on every tier — decision 0077) -------------------
    anchors = json.loads((run / "plane_anchors.json").read_text())["plane_anchors"]
    for a in anchors:
        t = np.array(a["transform"], dtype=np.float64).reshape(4, 4, order="F")
        R = t[:3, :3]
        qa = rotmat_to_quat(R)  # renormalizes; rounded columns are fine
        pa = bundle.plane_anchors.add()
        pa.pose.pos_x, pa.pose.pos_y, pa.pose.pos_z = t[:3, 3]
        pa.pose.quat_x, pa.pose.quat_y, pa.pose.quat_z, pa.pose.quat_w = qa
        pa.center_x, pa.center_y, pa.center_z = a["center"]
        pa.extent_width = a["extent_w"]
        pa.extent_height = a["extent_h"]
        pa.rotation_on_y_rad = a["rot_y"]
        pa.alignment = PLANE_HORIZONTAL if a["alignment"] == "horizontal" else PLANE_VERTICAL
        pa.classification = _normalize_classification(a["classification"])

    # --- RoomPlan model (JSON verbatim; USDZ optional) ------------------------
    usdz_src = run / "room_parametric.usdz"
    if has_room:
        bundle.room_plan.json_gcs_path = "roomplan/room.json"
        if usdz_src.exists():
            bundle.room_plan.usdz_gcs_path = "roomplan/room.usdz"
        bundle.room_plan.roomplan_version = (
            f"ios{run_start.get('os', 'unknown')};"
            f"CapturedRoom.v{room.get('version', '?')};beautifyObjects"
        )

    # --- Write the bundle directory in the GCS prefix layout ------------------
    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)
    for sub in ("frames", "depth", "confidence"):
        print(f"  copying {sub}/ ...")
        _clone_tree(run / sub, out / sub)
    if has_room:
        (out / "roomplan").mkdir(exist_ok=True)
        (out / "roomplan" / "room.json").write_bytes(room_json_bytes)
        if usdz_src.exists():
            shutil.copy2(usdz_src, out / "roomplan" / "room.usdz")

    wire = bundle.SerializeToString()
    (out / "bundle.pb").write_bytes(wire)

    n_depth = sum(1 for f in bundle.frames if f.HasField("depth"))
    duration_s = (bundle.ended_at_device_us - bundle.started_at_device_us) / 1e6
    summary = [
        f"source run:     {run}",
        f"schema_version: {bundle.schema_version}",
        f"bundle_id:      {bundle.bundle_id}",
        f"user_id:        {bundle.user_id}",
        f"tier:           {'LIDAR_ROOMPLAN' if tier == LIDAR_ROOMPLAN else 'LIDAR_ARKIT'}",
        f"device:         {bundle.device.hardware_id} / iOS {bundle.device.os_version}",
        f"frames:         {len(bundle.frames)} ({n_depth} with depth), {duration_s:.1f}s",
        f"plane_anchors:  {len(bundle.plane_anchors)}",
        f"room_plan:      json={bundle.room_plan.json_gcs_path or '-'} "
        f"usdz={bundle.room_plan.usdz_gcs_path or '-'} "
        f"version={bundle.room_plan.roomplan_version or '-'}",
        f"worst quat err: {worst_quat_err:.2e} (contract {QUAT_NORM_TOLERANCE})",
        f"bundle.pb:      {len(wire)} bytes",
    ]
    (out / "manifest.txt").write_text("\n".join(summary) + "\n")
    print("Done.")
    for line in summary:
        print(f"  {line}")
    print(f"  out:            {out}/")
    print(f"Verify: python tools/inspect_bundle.py {out / 'bundle.pb'}")


if __name__ == "__main__":
    main()
