"""Per-object world placement: anchor SAM 3D splats into the ARKit world frame.

SAM 3D hands back each object as an origin-centered, unit-normalized
Gaussian splat in its own local frame, plus (when the upstream pipeline
provides them) layout predictions — rotation/translation/scale relative to
the input view. This module combines that with what the CaptureBundle
measured directly — per-frame camera pose, intrinsics, gravity, and LiDAR
depth — to produce a world transform per object:

  * Rotation comes from the SAM 3D layout prior (the model's canonical-
    frame orientation estimate), lifted camera→world with the frame's pose.
  * Scale and translation come from the LiDAR depth cloud under the
    object's mask (the metric authority), via the single-view-aware fit in
    roomstudio_schemas.placement_math, plus a translation-only NN polish.
  * Frames without depth (ARKIT_ONLY tier) get a world-space view ray per
    object instead; the scene-level fusion pass triangulates object
    centers from those rays across keyframes.

Two conventions here are assumptions about SAM 3D's output, flagged for
runtime verification (no GPU exists in dev; reconstruct() result keys are
logged by process_receiver on every call):
  * LAYOUT_QUAT_ORDER: layout quaternions are taken as (w, x, y, z) —
    the pytorch3d/Meta-3D-codebase convention.
  * _SAM3D_CAM_TO_ARKIT_CAM: the layout rotation is expressed in a CV
    camera frame (+X right, +Y down, +Z forward); ARKit's camera frame is
    (+X right, +Y up, -Z forward), so the basis change is diag(1, -1, -1).
A wrong assumption shows up as systematic gravity_deviation_deg values in
placement quality — it degrades orientation, never crashes.

Everything degrades explicitly: missing layout → identity rotation with
rotation_source "none"; sparse/degenerate depth → placed: false with a
reason. A guessed transform is never emitted.

Consumers: process_receiver.py (per-frame loop and scene-level fusion).
"""
from __future__ import annotations

import logging
import math
import os
from typing import Any, Optional

import numpy as np

from roomstudio_schemas.placement_math import (
    MIN_CLOUD_POINTS,
    DegenerateGeometryError,
    camera_to_world,
    fit_single_view,
    ray_through_pixel,
    refine_similarity_nn,
    resize_mask_to,
    unproject_depth,
)
from roomstudio_schemas.pose_math import (
    pose_quat,
    quat_to_rotmat,
    rotmat_to_quat,
)

logger = logging.getLogger(__name__)

# Layout quaternion component order assumption (see module docstring).
LAYOUT_QUAT_ORDER = "wxyz"

# CV camera frame (+Z forward, +Y down) -> ARKit camera frame (-Z forward,
# +Y up). Assumption pending runtime verification; see module docstring.
_SAM3D_CAM_TO_ARKIT_CAM = np.diag([1.0, -1.0, -1.0])

# Translation-only NN polish after the single-view fit (evaluated in the
# schemas suite: tightens translation, never touches scale/rotation).
# Disable with PLACEMENT_NN_POLISH=0 if it misbehaves on real data.
_NN_POLISH_ENABLED = os.environ.get("PLACEMENT_NN_POLISH", "1") == "1"

_WORLD_UP = np.array([0.0, 1.0, 0.0])


# ---------------------------------------------------------------------------
# SAM 3D layout extraction (defensive)
# ---------------------------------------------------------------------------

def _to_numpy(x: Any) -> Optional[np.ndarray]:
    """Best-effort conversion of tensors/arrays/lists to float64 numpy.

    Duck-types torch tensors (detach/cpu/numpy) so this module never
    imports torch. Returns None if conversion fails."""
    if x is None:
        return None
    try:
        if hasattr(x, "detach"):
            x = x.detach()
        if hasattr(x, "cpu"):
            x = x.cpu()
        if hasattr(x, "numpy"):
            x = x.numpy()
        return np.asarray(x, dtype=np.float64)
    except Exception:
        return None


def extract_layout(result: dict) -> Optional[dict]:
    """Pull the layout prior (rotation/translation/scale) out of a SAM 3D
    reconstruct() result, if present.

    Returns None when no usable rotation exists. Otherwise a dict:
      rotation_xyzw: list[4]   — converted per LAYOUT_QUAT_ORDER, or taken
                                 directly from a (3,3) rotation matrix
      translation:   list[3] | None
      scale:         list | float | None
      raw_rotation:  list      — verbatim values for offline analysis
    """
    rot = _to_numpy(result.get("rotation"))
    if rot is None:
        return None
    rot = np.squeeze(rot)
    if rot.shape == (4,):
        raw = rot.tolist()
        if LAYOUT_QUAT_ORDER == "wxyz":
            q_xyzw = [float(rot[1]), float(rot[2]), float(rot[3]), float(rot[0])]
        else:
            q_xyzw = [float(c) for c in rot]
        norm = math.sqrt(sum(c * c for c in q_xyzw))
        if norm < 1e-6:
            return None
        q_xyzw = [c / norm for c in q_xyzw]
    elif rot.shape == (3, 3):
        raw = rot.tolist()
        q_xyzw = list(rotmat_to_quat(rot))
    else:
        logger.warning("sam3d layout rotation has unexpected shape %s", rot.shape)
        return None

    trans = _to_numpy(result.get("translation"))
    scale = _to_numpy(result.get("scale"))
    return {
        "rotation_xyzw": q_xyzw,
        "translation": np.squeeze(trans).tolist() if trans is not None else None,
        "scale": np.squeeze(scale).tolist() if scale is not None else None,
        "raw_rotation": raw,
    }


def rotation_world_from_layout(layout: dict, camera_pose) -> np.ndarray:
    """World-from-object rotation: lift the layout's camera-frame rotation
    through the frame's world-from-camera pose (with the CV→ARKit camera
    basis change in between)."""
    R_layout = quat_to_rotmat(tuple(layout["rotation_xyzw"]))
    R_wc = quat_to_rotmat(pose_quat(camera_pose))
    return R_wc @ _SAM3D_CAM_TO_ARKIT_CAM @ R_layout


# ---------------------------------------------------------------------------
# Splat PLY vertex reader
# ---------------------------------------------------------------------------

_PLY_TYPE_SIZES = {
    "char": 1, "int8": 1, "uchar": 1, "uint8": 1,
    "short": 2, "int16": 2, "ushort": 2, "uint16": 2,
    "int": 4, "int32": 4, "uint": 4, "uint32": 4,
    "float": 4, "float32": 4, "double": 8, "float64": 8,
}
_PLY_NP_TYPES = {
    "char": "i1", "int8": "i1", "uchar": "u1", "uint8": "u1",
    "short": "i2", "int16": "i2", "ushort": "u2", "uint16": "u2",
    "int": "i4", "int32": "i4", "uint": "u4", "uint32": "u4",
    "float": "f4", "float32": "f4", "double": "f8", "float64": "f8",
}


def parse_ply_vertices(ply_bytes: bytes) -> np.ndarray:
    """Read the x/y/z vertex positions out of a 3DGS PLY.

    Supports the layouts SAM 3D emits: a single leading `vertex` element
    with fixed-size scalar properties (x, y, z, f_dc_*, opacity, scale_*,
    rot_* ...), binary little-endian or ascii. Raises ValueError on
    anything else (list properties, vertex not first, missing x/y/z) —
    callers treat a parse failure as an unplaced object, not a crash.

    Returns (N, 3) float64 positions in the splat's local frame.
    """
    end = ply_bytes.find(b"end_header")
    if end < 0:
        raise ValueError("ply: no end_header")
    header = ply_bytes[:end].decode("ascii", errors="replace")
    data_start = ply_bytes.index(b"\n", end) + 1

    fmt = None
    elements: list[tuple[str, int]] = []
    props: list[tuple[str, str]] = []  # (type, name) for the FIRST element only
    for line in header.splitlines():
        parts = line.strip().split()
        if not parts:
            continue
        if parts[0] == "format":
            fmt = parts[1]
        elif parts[0] == "element":
            elements.append((parts[1], int(parts[2])))
        elif parts[0] == "property" and len(elements) == 1:
            if parts[1] == "list":
                raise ValueError("ply: list property in vertex element unsupported")
            props.append((parts[1], parts[2]))
    if not elements or elements[0][0] != "vertex":
        raise ValueError("ply: first element is not 'vertex'")
    if fmt not in ("binary_little_endian", "ascii"):
        raise ValueError(f"ply: unsupported format {fmt!r}")
    names = [n for _, n in props]
    for req in ("x", "y", "z"):
        if req not in names:
            raise ValueError(f"ply: vertex element missing property {req!r}")
    count = elements[0][1]

    if fmt == "ascii":
        rows = []
        text = ply_bytes[data_start:].decode("ascii", errors="replace").splitlines()
        ix, iy, iz = names.index("x"), names.index("y"), names.index("z")
        for line in text[:count]:
            vals = line.split()
            rows.append((float(vals[ix]), float(vals[iy]), float(vals[iz])))
        if len(rows) != count:
            raise ValueError(f"ply: expected {count} ascii vertices, got {len(rows)}")
        return np.array(rows, dtype=np.float64)

    dtype = np.dtype([(n, "<" + _PLY_NP_TYPES[t]) for t, n in props])
    needed = count * dtype.itemsize
    buf = ply_bytes[data_start:data_start + needed]
    if len(buf) < needed:
        raise ValueError(
            f"ply: truncated vertex data ({len(buf)} bytes, need {needed})"
        )
    verts = np.frombuffer(buf, dtype=dtype, count=count)
    return np.column_stack([
        verts["x"].astype(np.float64),
        verts["y"].astype(np.float64),
        verts["z"].astype(np.float64),
    ])


# ---------------------------------------------------------------------------
# Per-object placement
# ---------------------------------------------------------------------------

def unplaced(reason: str, layout_prior: Optional[dict] = None, **quality) -> dict:
    """Placement record for an object that could not be placed. Explicit
    reason, never a guessed transform."""
    return {
        "placed": False,
        "world_transform": None,
        "method": None,
        "reason": reason,
        "quality": {**quality},
        "layout_prior": layout_prior,
    }


def object_view_ray(mask: np.ndarray, intrinsics, camera_pose) -> Optional[dict]:
    """World-space ray through the mask centroid, plus the object's angular
    size — the per-frame observation the ARKIT_ONLY triangulation path
    fuses across keyframes. Returns None for an empty mask."""
    vs, us = np.nonzero(np.asarray(mask, dtype=bool))
    if us.size == 0:
        return None
    origin, direction = ray_through_pixel(
        float(us.mean()), float(vs.mean()), intrinsics, camera_pose
    )
    ang_w = (float(us.max()) - float(us.min()) + 1.0) / intrinsics.fx
    ang_h = (float(vs.max()) - float(vs.min()) + 1.0) / intrinsics.fy
    return {
        "origin": [float(c) for c in origin],
        "direction": [float(c) for c in direction],
        "angular_extent_rad": float(max(ang_w, ang_h)),
    }


def _gravity_deviation_deg(R_world_obj: np.ndarray) -> float:
    """Angle between the object's layout-implied up axis and world up.

    ARKit's world frame is gravity-aligned (+Y up) and SAM 3D's canonical
    object frame is taken as +Y up, so for most household objects standing
    normally this should be small; systematically large values indicate a
    wrong layout-frame assumption (see module docstring)."""
    up = R_world_obj @ _WORLD_UP
    cosang = float(np.clip(np.dot(up, _WORLD_UP), -1.0, 1.0))
    return math.degrees(math.acos(cosang))


def compute_frame_placement(
    *,
    ply_bytes: bytes,
    layout: Optional[dict],
    mask_rgb: np.ndarray,
    depth_raster: Optional[np.ndarray],
    depth_confidence: Optional[np.ndarray],
    depth_intrinsics,
    camera_pose,
) -> dict:
    """Per-frame placement entry point for the perception loop. Never
    raises: any failure becomes an unplaced record with a reason, so a
    placement bug can degrade a scene but never abort it."""
    if depth_raster is None:
        # ARKIT_ONLY tier: no metric depth in this frame. The scene-level
        # fusion pass triangulates a center from view rays across frames.
        return unplaced("no_depth_pending_triangulation", layout)
    try:
        splat_xyz = parse_ply_vertices(ply_bytes)
    except Exception as exc:
        logger.warning("splat ply parse failed; object unplaced: %s", exc)
        return unplaced("ply_parse_failed", layout)
    try:
        return place_object(
            splat_xyz=splat_xyz,
            layout=layout,
            mask_rgb=mask_rgb,
            depth_raster=depth_raster,
            depth_confidence=depth_confidence,
            depth_intrinsics=depth_intrinsics,
            camera_pose=camera_pose,
        )
    except Exception as exc:
        logger.exception("placement failed; object unplaced: %s", exc)
        return unplaced(f"placement_error: {exc}", layout)


def place_object(
    *,
    splat_xyz: np.ndarray,
    layout: Optional[dict],
    mask_rgb: np.ndarray,
    depth_raster: np.ndarray,
    depth_confidence: Optional[np.ndarray],
    depth_intrinsics,
    camera_pose,
) -> dict:
    """Place one object into the world frame from one frame's LiDAR depth.

    splat_xyz: (N, 3) splat vertex positions in the object's local frame.
    layout: extract_layout() output or None.
    mask_rgb: (H, W) bool segmentation mask at RGB resolution.
    depth_raster / depth_confidence / depth_intrinsics: the frame's Depth
        payload (raster at its own resolution).
    camera_pose: the frame's world-from-camera Pose.

    Returns a placement dict (see the manifest contract in
    process_receiver's docstring).
    """
    layout_prior = layout if layout is not None else None

    if layout is not None:
        R_world = rotation_world_from_layout(layout, camera_pose)
        rotation_source = "sam3d_layout"
    else:
        R_world = np.eye(3)
        rotation_source = "none"

    dh, dw = depth_raster.shape
    mask_d = resize_mask_to(mask_rgb, (dw, dh))
    cam_pts = unproject_depth(
        depth_raster, depth_intrinsics, mask=mask_d, confidence=depth_confidence
    )
    if cam_pts.shape[0] < MIN_CLOUD_POINTS:
        return unplaced(
            "insufficient_depth_points",
            layout_prior,
            depth_points=int(cam_pts.shape[0]),
        )
    world_pts = camera_to_world(cam_pts, camera_pose)

    R_wc = quat_to_rotmat(pose_quat(camera_pose))
    view_dir_world = R_wc @ np.array([0.0, 0.0, -1.0])

    try:
        s, t = fit_single_view(splat_xyz, world_pts, R_world, view_dir_world)
    except DegenerateGeometryError as exc:
        return unplaced(
            f"degenerate_fit: {exc}", layout_prior, depth_points=int(cam_pts.shape[0])
        )

    nn_rms = None
    if _NN_POLISH_ENABLED:
        try:
            s, R_world, t, nn_rms = refine_similarity_nn(
                splat_xyz, world_pts, s, R_world, t, mode="translation"
            )
        except DegenerateGeometryError:
            pass  # polish is optional; the view-aware fit stands on its own

    quality = {
        "depth_points": int(cam_pts.shape[0]),
        "nn_rms_m": float(nn_rms) if nn_rms is not None else None,
        "gravity_deviation_deg": (
            _gravity_deviation_deg(R_world) if rotation_source == "sam3d_layout" else None
        ),
        "frames_observed": 1,
    }
    return {
        "placed": True,
        "world_transform": {
            "position": [float(c) for c in t],
            "rotation_xyzw": [float(c) for c in rotmat_to_quat(R_world)],
            "scale": float(s),
        },
        "method": "depth_fit",
        "rotation_source": rotation_source,
        "quality": quality,
        "layout_prior": layout_prior,
    }
