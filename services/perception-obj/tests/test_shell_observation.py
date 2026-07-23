"""Shell observation-layer invariants (decision 0069 — the bake demotion):
projection sampling, mask exclusion, median robustness, observed-fraction
accounting over the measured region, evidence-crop selection/rectification,
and determinism — on tiny synthetic planes and cameras with hand-computed
ground truth (the same fixture style the retired bake tests used).

Run: python -m pytest services/perception-obj/tests/test_shell_observation.py
"""
from __future__ import annotations

import math

import numpy as np
import pytest
import shell_observation
from room_planes import ShellPlaneGeom
from roomstudio_schemas import Intrinsics, Pose
from shell_observation import FrameSample, observe_plane

# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

def _wall_geom(width: float = 1.0, height: float = 1.0) -> ShellPlaneGeom:
    """1x1 m wall in the world XY plane at z=0, fronting +Z; plane
    origin at world (0, 0, 0), +U = +X, +V = +Y."""
    origin = np.array([0.0, 0.0, 0.0])
    u = np.array([1.0, 0.0, 0.0])
    v = np.array([0.0, 1.0, 0.0])
    corners = np.stack([
        origin, origin + width * u, origin + width * u + height * v, origin + height * v,
    ])
    return ShellPlaneGeom(
        kind="wall", corners_world=corners, normal=np.array([0.0, 0.0, 1.0]),
        origin=origin, axis_u=u, axis_v=v, width_m=width, height_m=height,
        classification="wall", member_indices=[0], wall_id="wall_00",
    )


def _floor_geom(width: float = 2.0, depth: float = 2.0) -> ShellPlaneGeom:
    """width x depth floor at y=0 spanning x in [0, w], z in [0, d];
    origin at (0, 0, d), +U = +X, +V = -Z (fronting +Y)."""
    origin = np.array([0.0, 0.0, depth])
    u = np.array([1.0, 0.0, 0.0])
    v = np.array([0.0, 0.0, -1.0])
    corners = np.stack([
        origin, origin + width * u, origin + width * u + depth * v, origin + depth * v,
    ])
    return ShellPlaneGeom(
        kind="floor", corners_world=corners, normal=np.array([0.0, 1.0, 0.0]),
        origin=origin, axis_u=u, axis_v=v, width_m=width, height_m=depth,
        classification="floor", member_indices=[0],
    )


def _pose(pos, quat=(0.0, 0.0, 0.0, 1.0)) -> Pose:
    p = Pose()
    p.pos_x, p.pos_y, p.pos_z = pos
    p.quat_x, p.quat_y, p.quat_z, p.quat_w = quat
    return p


def _intrinsics(fx=100.0, fy=100.0, cx=50.0, cy=50.0, w=100, h=100) -> Intrinsics:
    i = Intrinsics()
    i.fx, i.fy, i.cx, i.cy = fx, fy, cx, cy
    i.width, i.height = w, h
    return i


def _frame(
    color=(255, 0, 0),
    *,
    frame_index=0,
    pos=(0.5, 0.5, 2.0),
    quat=(0.0, 0.0, 0.0, 1.0),
    img: np.ndarray | None = None,
    exclusion: np.ndarray | None = None,
) -> FrameSample:
    """A camera at `pos` looking down -Z (identity quat) at the wall.
    Solid `color` image unless `img` is given."""
    if img is None:
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        img[:, :] = color
    if exclusion is None:
        exclusion = np.zeros(img.shape[:2], dtype=bool)
    return FrameSample(
        frame_index=frame_index, rgb=img, exclusion_mask=exclusion,
        pose=_pose(pos, quat), intrinsics=_intrinsics(w=img.shape[1], h=img.shape[0]),
    )


def _small_texels(monkeypatch, mpt=0.1):
    """Coarse texel grid so tests run on 10x10-ish planes."""
    monkeypatch.setattr(shell_observation, "SHELL_METERS_PER_TEXEL", mpt)


def _small_crops(monkeypatch, px=32):
    """Small crop rasters so rectification stays fast in tests."""
    monkeypatch.setattr(shell_observation, "SHELL_EVIDENCE_CROP_PX", px)


# ---------------------------------------------------------------------------
# Basic projection sampling + stats
# ---------------------------------------------------------------------------

class TestSampling:
    def test_full_view_observes_solid_color(self, monkeypatch):
        _small_texels(monkeypatch)
        _small_crops(monkeypatch)
        result = observe_plane(_wall_geom(), [_frame((200, 30, 40))])
        assert result.observed_fraction == 1.0
        assert result.texel_count == result.in_region_count == 100
        assert result.frames_used == 1
        assert result.grid_px == (10, 10)
        assert result.colors.shape == (100, 3)
        assert result.weights.shape == (100,)
        assert np.all(result.weights > 0)
        assert np.all(np.abs(result.colors[:, 0] - 200) <= 1)
        assert np.all(np.abs(result.colors[:, 1] - 30) <= 1)

    def test_back_face_view_is_unobserved(self, monkeypatch):
        """A camera BEHIND the wall (z=-2, wall fronts +Z) contributes
        nothing — the front-face gate."""
        _small_texels(monkeypatch)
        result = observe_plane(_wall_geom(), [_frame(pos=(0.5, 0.5, -2.0))])
        assert result.observed_fraction == 0.0
        assert result.texel_count == 0
        assert result.frames_used == 0
        assert result.colors.shape == (0, 3)
        assert result.crops == []

    def test_no_frames_is_unobserved(self, monkeypatch):
        _small_texels(monkeypatch)
        result = observe_plane(_wall_geom(), [])
        assert result.observed_fraction == 0.0
        assert result.crops == []

    def test_grid_long_edge_capped(self, monkeypatch):
        monkeypatch.setattr(shell_observation, "SHELL_OBS_MAX_PX", 8)
        result = observe_plane(
            _wall_geom(width=4.0, height=1.0), [_frame(pos=(2.0, 0.5, 4.0))]
        )
        assert max(result.grid_px) <= 8


class TestExclusion:
    def test_masked_half_reduces_observed_fraction(self, monkeypatch):
        _small_texels(monkeypatch)
        exclusion = np.zeros((100, 100), dtype=bool)
        exclusion[:, :50] = True
        result = observe_plane(
            _wall_geom(), [_frame((255, 0, 0), exclusion=exclusion)]
        )
        assert 0.3 < result.observed_fraction < 0.7
        # Only observed texels ship colors.
        assert len(result.colors) == result.texel_count

    def test_second_frame_fills_masked_first(self, monkeypatch):
        """A texel masked in one frame but clean in another is OBSERVED —
        exclusion is per-sample, not per-texel."""
        _small_texels(monkeypatch)
        exclusion = np.zeros((100, 100), dtype=bool)
        exclusion[:, :50] = True
        frames = [
            _frame((255, 0, 0), frame_index=0, exclusion=exclusion),
            _frame((255, 0, 0), frame_index=1),
        ]
        result = observe_plane(_wall_geom(), frames)
        assert result.observed_fraction == 1.0
        assert result.frames_used == 2


class TestMedianSelect:
    def test_outlier_frame_suppressed(self, monkeypatch):
        """Two agreeing frames + one outlier (a transient bake-in): the
        weighted median lands on the agreeing color."""
        _small_texels(monkeypatch)
        frames = [
            _frame((200, 0, 0), frame_index=0),
            _frame((200, 0, 0), frame_index=1),
            _frame((255, 255, 255), frame_index=2),
        ]
        result = observe_plane(_wall_geom(), frames)
        assert np.all(np.abs(result.colors[:, 0] - 200) <= 1)
        assert np.all(result.colors[:, 1] <= 1)

    def test_closer_frame_outweighs_far(self, monkeypatch):
        """Weights are incidence/distance-based: one close frame must beat
        one distant frame at the same incidence (weighted, not counted)."""
        _small_texels(monkeypatch)
        frames = [
            _frame((0, 0, 255), frame_index=0, pos=(0.5, 0.5, 1.0)),  # close
            _frame((255, 255, 0), frame_index=1, pos=(0.5, 0.5, 6.0)),  # far
        ]
        result = observe_plane(_wall_geom(), frames)
        assert np.all(result.colors[:, 2] >= 254), "close frame's color must win"


class TestFloorRegion:
    def test_member_polygon_bounds_the_denominator(self, monkeypatch):
        """An L-shaped floor (two rectangles over a 2x2 bbox): the missing
        quadrant is outside the measured region — not part of the
        observed-fraction denominator."""
        _small_texels(monkeypatch, mpt=0.25)
        geom = _floor_geom(2.0, 2.0)
        polys = [
            # x in [0, 2], z in [0, 1]
            np.array([[0, 0, 0], [2, 0, 0], [2, 0, 1], [0, 0, 1]], dtype=float),
            # x in [0, 1], z in [1, 2]
            np.array([[0, 0, 1], [1, 0, 1], [1, 0, 2], [0, 0, 2]], dtype=float),
        ]
        # Camera above, looking straight down: -90 deg about X maps camera
        # -Z (view) onto world -Y.
        r = 1.0 / math.sqrt(2.0)
        frame = _frame((120, 100, 80), pos=(1.0, 3.0, 1.0), quat=(-r, 0.0, 0.0, r))
        result = observe_plane(geom, [frame], floor_member_polygons=polys)
        # 8x8 grid over the 2x2 bbox; the L covers 3/4 of it.
        assert result.in_region_count == 48
        assert result.observed_fraction == 1.0
        assert result.texel_count == 48


class TestEvidenceCrops:
    def test_full_view_yields_solid_crops(self, monkeypatch):
        _small_texels(monkeypatch)
        _small_crops(monkeypatch)
        result = observe_plane(_wall_geom(), [_frame((10, 200, 30))])
        assert 1 <= len(result.crops) <= shell_observation.SHELL_EVIDENCE_MAX_CROPS
        for crop in result.crops:
            assert crop.rgb.shape == (32, 32, 3)
            assert crop.frame_index == 0
            assert crop.observed_fraction == 1.0
            assert crop.fill_fraction == 0.0
            assert np.all(np.abs(crop.rgb[:, :, 1].astype(int) - 200) <= 1)
            # Square in world space.
            assert (crop.u1 - crop.u0) == pytest.approx(crop.v1 - crop.v0, abs=1e-9)

    def test_crop_prefers_the_unmasked_frame(self, monkeypatch):
        """Two frames: one fully masked, one clean — every crop must come
        from the clean frame."""
        _small_texels(monkeypatch)
        _small_crops(monkeypatch)
        masked = np.ones((100, 100), dtype=bool)
        frames = [
            _frame((255, 0, 0), frame_index=0, exclusion=masked),
            _frame((0, 0, 255), frame_index=1),
        ]
        result = observe_plane(_wall_geom(), frames)
        assert len(result.crops) >= 1
        for crop in result.crops:
            assert crop.frame_index == 1
            assert np.all(crop.rgb[:, :, 2] >= 254)

    def test_underobserved_tile_yields_no_crop(self, monkeypatch):
        """A plane observed only in a thin strip (below the evidence
        min-observation gate in every tile) ships stats but no crops."""
        _small_texels(monkeypatch)
        _small_crops(monkeypatch)
        exclusion = np.ones((100, 100), dtype=bool)
        exclusion[:, :30] = False  # only the wall's left fifth observable
        result = observe_plane(_wall_geom(), [_frame(exclusion=exclusion)])
        assert 0 < result.observed_fraction < 0.5
        assert result.crops == []

    def test_crop_orientation_row0_is_plane_top(self, monkeypatch):
        """Crop rows follow the bake's convention: row 0 = far end of +V
        (the wall top). Feed a top-blue/bottom-yellow image."""
        _small_texels(monkeypatch)
        _small_crops(monkeypatch)
        # One tile spanning the whole 1x1 wall.
        monkeypatch.setattr(shell_observation, "SHELL_EVIDENCE_CROP_M", 1.0)
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        img[:50] = (0, 0, 255)  # image top = high world Y
        img[50:] = (255, 255, 0)
        result = observe_plane(_wall_geom(), [_frame(img=img)])
        assert len(result.crops) == 1
        crop = result.crops[0].rgb
        assert tuple(crop[0, 5]) == (0, 0, 255), "crop row 0 = wall top"
        assert tuple(crop[-1, 5]) == (255, 255, 0), "crop last row = wall bottom"

    def test_sliver_tiles_skipped(self, monkeypatch):
        """A plane narrower than the minimum crop side yields no crops."""
        _small_texels(monkeypatch, mpt=0.02)
        _small_crops(monkeypatch)
        result = observe_plane(
            _wall_geom(width=0.1, height=0.1), [_frame(pos=(0.05, 0.05, 1.0))]
        )
        assert result.crops == []


class TestDeterminism:
    def test_identical_inputs_identical_outputs(self, monkeypatch):
        _small_texels(monkeypatch)
        _small_crops(monkeypatch)
        exclusion = np.zeros((100, 100), dtype=bool)
        exclusion[:, 40:60] = True

        def frames():
            return [
                _frame((200, 10, 10), frame_index=0, exclusion=exclusion.copy()),
                _frame((10, 200, 10), frame_index=1, pos=(0.5, 0.5, 3.0)),
            ]

        r1 = observe_plane(_wall_geom(), frames())
        r2 = observe_plane(_wall_geom(), frames())
        np.testing.assert_array_equal(r1.colors, r2.colors)
        np.testing.assert_array_equal(r1.weights, r2.weights)
        assert len(r1.crops) == len(r2.crops)
        for c1, c2 in zip(r1.crops, r2.crops, strict=True):
            np.testing.assert_array_equal(c1.rgb, c2.rgb)
            assert (c1.frame_index, c1.u0, c1.v0) == (c2.frame_index, c2.u0, c2.v0)

    def test_frame_order_does_not_matter(self, monkeypatch):
        """Frames are sorted by frame_index internally — callers' list
        order can't change the observation."""
        _small_texels(monkeypatch)
        _small_crops(monkeypatch)

        def f0():
            return _frame((200, 10, 10), frame_index=0)

        def f1():
            return _frame((10, 200, 10), frame_index=1, pos=(0.5, 0.5, 3.0))

        r_a = observe_plane(_wall_geom(), [f0(), f1()])
        r_b = observe_plane(_wall_geom(), [f1(), f0()])
        np.testing.assert_array_equal(r_a.colors, r_b.colors)
        np.testing.assert_array_equal(r_a.weights, r_b.weights)
