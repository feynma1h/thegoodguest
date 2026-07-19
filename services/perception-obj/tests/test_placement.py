"""Unit tests for services/perception-obj/placement.py and the placement
wiring in process_receiver's frame loop.

The pure geometry is pinned in packages/schemas/tests/test_placement_math.py;
these tests cover the service-side layer: PLY parsing, defensive SAM 3D
layout extraction, the per-object placement entry point's degradation
behavior, and the end-to-end frame loop writing placement fields into
objects.json / the scene manifest.

Run from repo root:

    python -m pytest services/perception-obj/tests/test_placement.py -v
"""
from __future__ import annotations

import io
import json
import struct
from unittest.mock import patch

import numpy as np
import pytest

import placement
from roomstudio_schemas import CaptureBundle


# -----------------------------------------------------------------------------
# PLY builders
# -----------------------------------------------------------------------------

GAUSSIAN_PROPS = [
    "x", "y", "z",
    "f_dc_0", "f_dc_1", "f_dc_2",
    "opacity",
    "scale_0", "scale_1", "scale_2",
    "rot_0", "rot_1", "rot_2", "rot_3",
]


def make_gaussian_ply(positions: np.ndarray, ascii_format: bool = False) -> bytes:
    """Minimal 3DGS-style PLY: float32 vertex records with the standard
    gaussian attribute layout; non-position attributes zero-filled."""
    n = positions.shape[0]
    fmt = "ascii 1.0" if ascii_format else "binary_little_endian 1.0"
    header = ["ply", f"format {fmt}", f"element vertex {n}"]
    header += [f"property float {name}" for name in GAUSSIAN_PROPS]
    header += ["end_header", ""]
    head = "\n".join(header).encode("ascii")
    if ascii_format:
        lines = []
        for p in positions:
            vals = [f"{p[0]}", f"{p[1]}", f"{p[2]}"] + ["0"] * (len(GAUSSIAN_PROPS) - 3)
            lines.append(" ".join(vals))
        return head + "\n".join(lines).encode("ascii")
    body = b""
    for p in positions:
        vals = [float(p[0]), float(p[1]), float(p[2])] + [0.0] * (len(GAUSSIAN_PROPS) - 3)
        body += struct.pack("<" + "f" * len(GAUSSIAN_PROPS), *vals)
    return head + body


# -----------------------------------------------------------------------------
# parse_ply_vertices
# -----------------------------------------------------------------------------

def test_parse_binary_gaussian_ply_roundtrip():
    pos = np.array([[0.1, -0.2, 0.3], [1.5, 2.5, -3.5], [0.0, 0.0, 0.0]])
    out = placement.parse_ply_vertices(make_gaussian_ply(pos))
    assert np.allclose(out, pos, atol=1e-6)  # float32 storage precision


def test_parse_ascii_ply_roundtrip():
    pos = np.array([[0.25, 0.5, -0.75], [-1.0, 2.0, 3.0]])
    out = placement.parse_ply_vertices(make_gaussian_ply(pos, ascii_format=True))
    assert np.allclose(out, pos, atol=1e-9)


def test_parse_ply_rejects_list_property():
    ply = (
        b"ply\nformat binary_little_endian 1.0\nelement vertex 1\n"
        b"property list uchar int vertex_indices\nend_header\n"
    )
    with pytest.raises(ValueError, match="list property"):
        placement.parse_ply_vertices(ply)


def test_parse_ply_rejects_missing_xyz():
    ply = (
        b"ply\nformat binary_little_endian 1.0\nelement vertex 1\n"
        b"property float x\nproperty float y\nend_header\n" + b"\x00" * 8
    )
    with pytest.raises(ValueError, match="missing property 'z'"):
        placement.parse_ply_vertices(ply)


def test_parse_ply_rejects_truncated_data():
    pos = np.zeros((5, 3))
    full = make_gaussian_ply(pos)
    with pytest.raises(ValueError, match="truncated"):
        placement.parse_ply_vertices(full[:-10])


def test_parse_ply_rejects_non_vertex_first_element():
    ply = (
        b"ply\nformat binary_little_endian 1.0\nelement face 1\n"
        b"end_header\n"
    )
    with pytest.raises(ValueError, match="not 'vertex'"):
        placement.parse_ply_vertices(ply)


# -----------------------------------------------------------------------------
# extract_layout
# -----------------------------------------------------------------------------

class FakeTensor:
    """Duck-typed torch tensor: detach/cpu/numpy chain."""

    def __init__(self, arr):
        self._arr = np.asarray(arr)

    def detach(self):
        return self

    def cpu(self):
        return self

    def numpy(self):
        return self._arr


def test_extract_layout_wxyz_identity_maps_to_xyzw():
    """Layout (1,0,0,0) in the assumed wxyz order is the identity rotation,
    which is (0,0,0,1) in the proto's xyzw order."""
    out = placement.extract_layout({"rotation": [1.0, 0.0, 0.0, 0.0]})
    assert out is not None
    assert np.allclose(out["rotation_xyzw"], [0.0, 0.0, 0.0, 1.0])
    assert out["raw_rotation"] == [1.0, 0.0, 0.0, 0.0]


def test_extract_layout_from_fake_tensors():
    out = placement.extract_layout({
        "rotation": FakeTensor([[1.0, 0.0, 0.0, 0.0]]),  # leading batch dim
        "translation": FakeTensor([0.1, 0.2, 0.3]),
        "scale": FakeTensor([2.0]),
    })
    assert out is not None
    assert np.allclose(out["rotation_xyzw"], [0.0, 0.0, 0.0, 1.0])
    assert out["translation"] == pytest.approx([0.1, 0.2, 0.3])
    assert out["scale"] == pytest.approx(2.0)


def test_extract_layout_accepts_rotation_matrix():
    out = placement.extract_layout({"rotation": np.eye(3)})
    assert out is not None
    assert np.allclose(out["rotation_xyzw"], [0.0, 0.0, 0.0, 1.0])


def test_extract_layout_missing_or_degenerate_rotation():
    assert placement.extract_layout({}) is None
    assert placement.extract_layout({"rotation": [0.0, 0.0, 0.0, 0.0]}) is None
    assert placement.extract_layout({"rotation": [1.0, 2.0]}) is None
    assert placement.extract_layout({"rotation": object()}) is None


def test_rotation_world_from_layout_identity_is_basis_change():
    """Identity layout rotation + identity camera pose leaves exactly the
    CV→ARKit camera basis change."""
    frame = CaptureBundle().frames.add()
    frame.camera_pose.quat_w = 1.0
    layout = {"rotation_xyzw": [0.0, 0.0, 0.0, 1.0]}
    R = placement.rotation_world_from_layout(layout, frame.camera_pose)
    assert np.allclose(R, np.diag([1.0, -1.0, -1.0]), atol=1e-12)


# -----------------------------------------------------------------------------
# object_view_ray
# -----------------------------------------------------------------------------

def _identity_frame(fx=100.0, fy=100.0, cx=32.0, cy=24.0, w=64, h=48):
    frame = CaptureBundle().frames.add()
    frame.camera_pose.quat_w = 1.0
    frame.intrinsics.fx = fx
    frame.intrinsics.fy = fy
    frame.intrinsics.cx = cx
    frame.intrinsics.cy = cy
    frame.intrinsics.width = w
    frame.intrinsics.height = h
    return frame


def test_object_view_ray_centroid_at_principal_point():
    frame = _identity_frame()
    mask = np.zeros((48, 64), dtype=bool)
    mask[23:26, 31:34] = True  # centroid at (u=32, v=24) = principal point
    ray = placement.object_view_ray(mask, frame.intrinsics, frame.camera_pose)
    assert ray is not None
    assert np.allclose(ray["origin"], [0.0, 0.0, 0.0])
    assert np.allclose(ray["direction"], [0.0, 0.0, -1.0], atol=1e-9)
    assert ray["angular_extent_rad"] == pytest.approx(3.0 / 100.0)


def test_object_view_ray_empty_mask():
    frame = _identity_frame()
    assert placement.object_view_ray(
        np.zeros((48, 64), dtype=bool), frame.intrinsics, frame.camera_pose
    ) is None


# -----------------------------------------------------------------------------
# compute_frame_placement degradation behavior
# -----------------------------------------------------------------------------

def _depth_frame(dw=32, dh=24, dfx=20.0, dfy=20.0):
    frame = _identity_frame()
    frame.depth.width = dw
    frame.depth.height = dh
    frame.depth.depth_gcs_path = "depth/000000.f32"
    frame.depth.intrinsics.fx = dfx
    frame.depth.intrinsics.fy = dfy
    frame.depth.intrinsics.cx = dw / 2.0
    frame.depth.intrinsics.cy = dh / 2.0
    frame.depth.intrinsics.width = dw
    frame.depth.intrinsics.height = dh
    return frame


def _box_cloud(n=400, dims=(0.6, 0.4, 0.3), seed=5):
    rng = np.random.default_rng(seed)
    return (rng.random((n, 3)) - 0.5) * np.array(dims)


def test_compute_frame_placement_no_depth_pending():
    out = placement.compute_frame_placement(
        ply_bytes=b"irrelevant",
        layout=None,
        mask_rgb=np.ones((48, 64), dtype=bool),
        depth_raster=None,
        depth_confidence=None,
        depth_intrinsics=None,
        camera_pose=_identity_frame().camera_pose,
    )
    assert out["placed"] is False
    assert out["reason"] == "no_depth_pending_triangulation"


def test_compute_frame_placement_bad_ply_unplaced():
    frame = _depth_frame()
    out = placement.compute_frame_placement(
        ply_bytes=b"not a ply at all",
        layout=None,
        mask_rgb=np.ones((48, 64), dtype=bool),
        depth_raster=np.full((24, 32), 2.0, dtype=np.float32),
        depth_confidence=None,
        depth_intrinsics=frame.depth.intrinsics,
        camera_pose=frame.camera_pose,
    )
    assert out["placed"] is False
    assert out["reason"] == "ply_parse_failed"


def test_place_object_happy_path_structure():
    """Identity camera, flat depth wall 2m ahead under a rectangular mask,
    box splat: must place with method depth_fit, a position in front of
    the camera (z ≈ -2), positive scale, and populated quality fields."""
    frame = _depth_frame()
    depth = np.full((24, 32), np.nan, dtype=np.float32)
    depth[6:18, 8:24] = 2.0
    mask_rgb = np.zeros((48, 64), dtype=bool)
    mask_rgb[12:36, 16:48] = True  # same region at RGB resolution (2x)
    layout = {"rotation_xyzw": [0.0, 0.0, 0.0, 1.0], "translation": None,
              "scale": None, "raw_rotation": [1.0, 0.0, 0.0, 0.0]}
    out = placement.place_object(
        splat_xyz=_box_cloud(),
        layout=layout,
        mask_rgb=mask_rgb,
        depth_raster=depth,
        depth_confidence=None,
        depth_intrinsics=frame.depth.intrinsics,
        camera_pose=frame.camera_pose,
    )
    assert out["placed"] is True
    assert out["method"] == "depth_fit"
    assert out["rotation_source"] == "sam3d_layout"
    wt = out["world_transform"]
    assert wt["scale"] > 0
    assert -2.6 < wt["position"][2] < -1.4
    assert abs(np.linalg.norm(wt["rotation_xyzw"]) - 1.0) < 1e-6
    q = out["quality"]
    assert q["depth_points"] > 0
    assert q["gravity_deviation_deg"] is not None
    assert q["frames_observed"] == 1


def test_place_object_without_layout_uses_identity_rotation():
    frame = _depth_frame()
    depth = np.full((24, 32), 2.0, dtype=np.float32)
    out = placement.place_object(
        splat_xyz=_box_cloud(),
        layout=None,
        mask_rgb=np.ones((48, 64), dtype=bool),
        depth_raster=depth,
        depth_confidence=None,
        depth_intrinsics=frame.depth.intrinsics,
        camera_pose=frame.camera_pose,
    )
    assert out["placed"] is True
    assert out["rotation_source"] == "none"
    assert out["quality"]["gravity_deviation_deg"] is None


def test_place_object_sparse_depth_unplaced():
    frame = _depth_frame()
    depth = np.full((24, 32), np.nan, dtype=np.float32)
    depth[0, 0] = 2.0  # a single valid pixel
    out = placement.place_object(
        splat_xyz=_box_cloud(),
        layout=None,
        mask_rgb=np.ones((48, 64), dtype=bool),
        depth_raster=depth,
        depth_confidence=None,
        depth_intrinsics=frame.depth.intrinsics,
        camera_pose=frame.camera_pose,
    )
    assert out["placed"] is False
    assert out["reason"] == "insufficient_depth_points"


def test_place_object_low_confidence_depth_unplaced():
    """All-low-confidence depth is filtered out entirely -> unplaced."""
    frame = _depth_frame()
    depth = np.full((24, 32), 2.0, dtype=np.float32)
    conf = np.zeros((24, 32), dtype=np.uint8)
    out = placement.place_object(
        splat_xyz=_box_cloud(),
        layout=None,
        mask_rgb=np.ones((48, 64), dtype=bool),
        depth_raster=depth,
        depth_confidence=conf,
        depth_intrinsics=frame.depth.intrinsics,
        camera_pose=frame.camera_pose,
    )
    assert out["placed"] is False
    assert out["reason"] == "insufficient_depth_points"


# -----------------------------------------------------------------------------
# Frame-loop integration: placement fields land in objects.json + manifest
# -----------------------------------------------------------------------------

class FakeGS:
    def __init__(self, positions):
        self._ply = make_gaussian_ply(positions)

    def save_ply(self, path):
        with open(path, "wb") as f:
            f.write(self._ply)


class FakeSam3:
    """One full-frame detection per image."""

    def segment(self, image, prompt):
        w, h = image.size
        mask = np.zeros((h, w), dtype=bool)
        mask[h // 4: 3 * h // 4, w // 4: 3 * w // 4] = True
        return [{
            "label": "chair",
            "instance_idx": 0,
            "bbox": [w // 4, h // 4, 3 * w // 4, 3 * h // 4],
            "score": 0.9,
            "mask": mask,
        }]


class FakeSam3D:
    def __init__(self, with_layout=True):
        self.with_layout = with_layout

    def reconstruct(self, image, mask, seed=42):
        out = {"gs": FakeGS(_box_cloud())}
        if self.with_layout:
            out["rotation"] = [1.0, 0.0, 0.0, 0.0]  # identity in wxyz
            out["translation"] = [0.0, 0.0, 0.0]
            out["scale"] = 1.0
        return out


def _jpeg_bytes(w=64, h=48):
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (w, h), (128, 100, 90)).save(buf, format="JPEG")
    return buf.getvalue()


def _two_frame_bundle():
    """Frame 0: LiDAR depth. Frame 1: ARKIT_ONLY (no depth)."""
    bundle = CaptureBundle()
    bundle.schema_version = "1"
    for idx in range(2):
        f = bundle.frames.add()
        f.frame_index = idx
        f.rgb_gcs_path = f"frames/{idx:06d}.jpg"
        f.camera_pose.quat_w = 1.0
        f.camera_pose.pos_x = 0.1 * idx
        f.intrinsics.fx = 100.0
        f.intrinsics.fy = 100.0
        f.intrinsics.cx = 32.0
        f.intrinsics.cy = 24.0
        f.intrinsics.width = 64
        f.intrinsics.height = 48
        f.gravity.y = -1.0
    d = bundle.frames[0].depth
    d.width, d.height = 32, 24
    d.depth_gcs_path = "depth/000000.f32"
    d.intrinsics.fx = 50.0
    d.intrinsics.fy = 50.0
    d.intrinsics.cx = 16.0
    d.intrinsics.cy = 12.0
    d.intrinsics.width = 32
    d.intrinsics.height = 24
    return bundle


def test_run_perception_writes_placement_fields():
    from process_receiver import run_perception

    bundle = _two_frame_bundle()
    depth_bytes = np.full((24, 32), 2.0, dtype="<f4").tobytes()
    blobs = {
        "gs://caps/captures/b1/bundle.pb": bundle.SerializeToString(),
        "gs://caps/captures/b1/frames/000000.jpg": _jpeg_bytes(),
        "gs://caps/captures/b1/frames/000001.jpg": _jpeg_bytes(),
        "gs://caps/captures/b1/depth/000000.f32": depth_bytes,
    }
    uploads: dict[str, bytes] = {}

    def fake_download(uri):
        if uri not in blobs:
            from process_receiver import PoisonError
            raise PoisonError(f"missing test blob {uri}")
        return blobs[uri]

    def fake_upload(prefix, blob_path, data, content_type):
        uploads[blob_path] = data
        return f"gs://outputs/{blob_path}"

    with patch("process_receiver._download_gcs_uri", side_effect=fake_download), \
         patch("process_receiver._gcs_upload_for_scene", side_effect=fake_upload), \
         patch("process_receiver._gcs_blob_exists_and_get", return_value=None), \
         patch("process_receiver._gcs_blob_exists", return_value=False):
        result_uri = run_perception(
            scene_id="scene-1",
            bundle_uri="gs://caps/captures/b1/bundle.pb",
            outputs_bucket="outputs",
            sam3_model=FakeSam3(),
            sam3d_model=FakeSam3D(),
            object_prompt="furniture",
        )

    assert result_uri == "gs://outputs/scenes/scene-1/manifest.json"
    manifest = json.loads(uploads["scenes/scene-1/manifest.json"])
    frames = manifest["frames"]
    assert len(frames) == 2

    obj_depth = frames[0]["objects"][0]
    assert obj_depth["ok"] is True
    assert "view_ray" in obj_depth
    p = obj_depth["placement"]
    assert p["placed"] is True
    assert p["method"] == "depth_fit"
    assert p["rotation_source"] == "sam3d_layout"
    assert p["world_transform"]["scale"] > 0

    obj_nodepth = frames[1]["objects"][0]
    assert obj_nodepth["ok"] is True
    assert "view_ray" in obj_nodepth
    assert obj_nodepth["placement"]["placed"] is False
    assert obj_nodepth["placement"]["reason"] == "no_depth_pending_triangulation"

    # Per-frame cache carries the same fields.
    frame0_cached = json.loads(uploads["scenes/scene-1/frames/0000/objects.json"])
    assert frame0_cached["objects"][0]["placement"]["placed"] is True


def test_run_perception_malformed_depth_is_poison():
    from process_receiver import PoisonError, run_perception

    bundle = _two_frame_bundle()
    blobs = {
        "gs://caps/captures/b1/bundle.pb": bundle.SerializeToString(),
        "gs://caps/captures/b1/frames/000000.jpg": _jpeg_bytes(),
        "gs://caps/captures/b1/depth/000000.f32": b"\x00" * 17,  # wrong size
    }

    def fake_download(uri):
        if uri not in blobs:
            raise PoisonError(f"missing test blob {uri}")
        return blobs[uri]

    with patch("process_receiver._download_gcs_uri", side_effect=fake_download), \
         patch("process_receiver._gcs_upload_for_scene", return_value="gs://x/y"), \
         patch("process_receiver._gcs_blob_exists_and_get", return_value=None):
        with pytest.raises(PoisonError, match="Depth raster"):
            run_perception(
                scene_id="scene-2",
                bundle_uri="gs://caps/captures/b1/bundle.pb",
                outputs_bucket="outputs",
                sam3_model=FakeSam3(),
                sam3d_model=FakeSam3D(),
                object_prompt="furniture",
            )
