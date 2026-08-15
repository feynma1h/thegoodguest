"""Tests for placement.sam3d_pointmap — one frame's measured LiDAR depth
expressed in the camera frame SAM 3D Objects reads a scene point map in.

What these pin is the FRAME, because that is the only part a caller cannot
check by eye and the part a sign error hides in: a mirrored pointmap is a
plausible-looking array that would silently reconstruct a mirrored object.
The frame is the pytorch3d camera convention, established two independent
ways in docs/decisions/0180 — from the pipeline's own
camera_to_pytorch3d_camera rotation, and from decision 0065's
_SAM3D_CAM_TO_ARKIT_CAM, which was fitted to real rooms.

Run from repo root:

    python -m pytest services/perception-obj/tests/test_sam3d_pointmap.py -v
"""
from __future__ import annotations

import numpy as np

import placement
from roomstudio_schemas.placement_math import depth_pointmap, unproject_depth


class _Intrinsics:
    """Depth-raster intrinsics, at the depth raster's own resolution."""

    def __init__(self, fx, fy, cx, cy):
        self.fx, self.fy, self.cx, self.cy = fx, fy, cx, cy


# The real thing, from a LIDAR_ARKIT capture: 256x192 depth whose intrinsics
# are the RGB frame's scaled by 256/1920 (decision 0032, byte-exact on
# hardware). Used so the shapes and magnitudes under test are the ones that
# would actually be passed.
_LIDAR = _Intrinsics(fx=181.55, fy=181.55, cx=127.5, cy=95.5)


def _depth_frame(seed=3):
    rng = np.random.default_rng(seed)
    depth = rng.uniform(0.5, 4.1, size=(192, 256))
    depth[rng.random((192, 256)) < 0.08] = np.nan  # dropouts
    conf = rng.integers(0, 3, size=(192, 256)).astype(np.uint8)
    return depth, conf


def test_frame_is_the_arkit_map_with_x_and_z_negated():
    """+X left, +Y up, +Z forward, against ARKit's +X right, +Y up, -Z
    forward. Stated as an explicit expectation rather than by reapplying
    the basis, so that flipping the constant fails this test."""
    depth, conf = _depth_frame()
    arkit = depth_pointmap(depth, _LIDAR, confidence=conf)
    sam3d = placement.sam3d_pointmap(depth, conf, _LIDAR)

    valid = np.isfinite(arkit).all(axis=-1)
    assert np.allclose(sam3d[valid][:, 0], -arkit[valid][:, 0], atol=1e-5)
    assert np.allclose(sam3d[valid][:, 1], +arkit[valid][:, 1], atol=1e-5)
    assert np.allclose(sam3d[valid][:, 2], -arkit[valid][:, 2], atol=1e-5)


def test_the_basis_is_the_one_decision_0065_fitted_to_real_rooms():
    """The pointmap frame and the layout frame are the same camera space —
    the layout translation is re-metrised by the pointmap's own scale and
    shift — so this must be 0065's basis and not a second opinion."""
    depth, conf = _depth_frame()
    sam3d = placement.sam3d_pointmap(depth, conf, _LIDAR)
    back = sam3d @ placement._SAM3D_CAM_TO_ARKIT_CAM.T
    arkit = depth_pointmap(depth, _LIDAR, confidence=conf)
    valid = np.isfinite(arkit).all(axis=-1)
    assert np.allclose(back[valid], arkit[valid], atol=1e-5)


def test_everything_in_front_of_the_camera_has_positive_z():
    """The sign that decides whether the object is reconstructed in front
    of the camera or behind it. ARKit depth is positive metres along the
    viewing axis, and SAM 3D's +Z is forward, so every measured point must
    land at +Z equal to that depth."""
    depth, conf = _depth_frame()
    sam3d = placement.sam3d_pointmap(depth, conf, _LIDAR)
    valid = np.isfinite(sam3d).all(axis=-1)
    assert valid.any()
    assert (sam3d[valid][:, 2] > 0).all()
    assert np.allclose(sam3d[valid][:, 2], depth[valid], atol=1e-5)


def test_a_pixel_right_of_centre_lands_left_of_the_axis():
    """One hand-computed pixel. In the image the point is to the RIGHT of
    the principal point and BELOW it; in SAM 3D's frame that is -X (its X
    grows left) and -Y (its Y grows up)."""
    depth = np.full((4, 4), np.nan)
    depth[3, 3] = 2.0  # u=3 > cx, v=3 > cy
    intr = _Intrinsics(fx=100.0, fy=100.0, cx=1.0, cy=1.0)
    pm = placement.sam3d_pointmap(depth, None, intr)
    assert np.allclose(pm[3, 3], [-0.04, -0.04, 2.0], atol=1e-6)


def test_holes_stay_nan_because_that_is_how_the_model_reads_them():
    """PointPatchEmbed computes its valid mask as xyz.isfinite().all(-1)
    and substitutes a learned invalid token. A zero-filled hole would be
    read as a real measurement at the camera's optical centre."""
    depth, conf = _depth_frame()
    pm = placement.sam3d_pointmap(depth, conf, _LIDAR, min_confidence=1)
    dropped = ~(np.isfinite(depth) & (depth > 0) & (conf >= 1))
    assert dropped.any()
    assert np.isnan(pm[dropped]).all()
    assert pm.dtype == np.float32
    assert pm.shape == (192, 256, 3)


def test_confidence_floor_matches_the_cloud_the_pipeline_already_trusts():
    """Whatever confidence the placement cloud accepts, the pointmap must
    accept the same pixels — two different floors would mean the model and
    the placement fit disagree about what was measured."""
    depth, conf = _depth_frame()
    for floor in (0, 1, 2):
        pm = placement.sam3d_pointmap(depth, conf, _LIDAR, min_confidence=floor)
        cloud = unproject_depth(depth, _LIDAR, confidence=conf, min_confidence=floor)
        assert int(np.isfinite(pm).all(axis=-1).sum()) == cloud.shape[0]


def test_it_is_not_masked_to_an_object():
    """The pipeline crops around the mask itself and its normaliser reads
    unmasked pixels for the scene scale, so this returns the whole frame
    and takes no mask argument at all."""
    depth = np.full((8, 8), 1.5)
    pm = placement.sam3d_pointmap(depth, None, _Intrinsics(50.0, 50.0, 3.5, 3.5))
    assert np.isfinite(pm).all()
    assert pm.shape == (8, 8, 3)
