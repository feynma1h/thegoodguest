"""Shell texture bake invariants (decision 0066): projection sampling,
mask exclusion, median robustness, observed/inpainted fractions, the
floor alpha shape, orientation, and determinism — on tiny synthetic
planes and cameras with hand-computed ground truth.

Run: python -m pytest services/perception-obj/tests/test_shell_texture.py
"""
from __future__ import annotations

import io
import math

import numpy as np
import pytest
import shell_texture
from PIL import Image
from roomstudio_schemas import Intrinsics, Pose
from shell_geometry import ShellPlaneGeom
from shell_texture import FrameSample, bake_plane_texture

# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

def _wall_geom(width: float = 1.0, height: float = 1.0) -> ShellPlaneGeom:
    """1x1 m wall in the world XY plane at z=0, fronting +Z; texture
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


def _fail_inpaint(rgb: np.ndarray, holes: np.ndarray) -> np.ndarray:
    raise AssertionError("inpaint_fn must not be called when there are no holes")


def _green_inpaint(rgb: np.ndarray, holes: np.ndarray) -> np.ndarray:
    out = rgb.copy()
    out[holes] = (0, 255, 0)
    return out


def _decode(png_bytes: bytes) -> np.ndarray:
    return np.array(Image.open(io.BytesIO(png_bytes)))


def _small_texels(monkeypatch, mpt=0.1):
    """Coarse texel grid so tests run on 10x10-ish planes."""
    monkeypatch.setattr(shell_texture, "SHELL_METERS_PER_TEXEL", mpt)


# ---------------------------------------------------------------------------
# Basic projection sampling
# ---------------------------------------------------------------------------

class TestSampling:
    def test_full_view_bakes_solid_color(self, monkeypatch):
        _small_texels(monkeypatch)
        result = bake_plane_texture(
            _wall_geom(), [_frame((200, 30, 40))], inpaint_fn=_fail_inpaint
        )
        assert result.source == "baked"
        assert result.observed_fraction == 1.0
        assert result.inpainted_fraction == 0.0
        img = _decode(result.png_bytes)
        assert img.shape == (10, 10, 4)
        np.testing.assert_array_equal(img[:, :, 3], 255)
        assert np.all(np.abs(img[:, :, 0].astype(int) - 200) <= 1)
        assert np.all(np.abs(img[:, :, 1].astype(int) - 30) <= 1)

    def test_back_face_view_is_unobserved(self, monkeypatch):
        """A camera BEHIND the wall (z=-2, wall fronts +Z) contributes
        nothing — the front-face gate."""
        _small_texels(monkeypatch)
        result = bake_plane_texture(
            _wall_geom(), [_frame(pos=(0.5, 0.5, -2.0))], inpaint_fn=_green_inpaint
        )
        assert result.source == "unobserved"
        assert result.png_bytes is None
        assert result.observed_fraction == 0.0

    def test_no_frames_is_unobserved(self, monkeypatch):
        _small_texels(monkeypatch)
        result = bake_plane_texture(_wall_geom(), [], inpaint_fn=_green_inpaint)
        assert result.source == "unobserved"
        assert result.png_bytes is None

    def test_texture_orientation_v_axis(self, monkeypatch):
        """Image rows: PNG row 0 must be the FAR end of +V (the wall top).
        The camera at +Z sees the wall top in the image's upper rows; feed
        a top-blue/bottom-yellow image and expect PNG row 0 blue."""
        _small_texels(monkeypatch)
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        img[:50] = (0, 0, 255)  # image top = high world Y (v = cy - fy*y/d)
        img[50:] = (255, 255, 0)
        result = bake_plane_texture(
            _wall_geom(), [_frame(img=img)], inpaint_fn=_fail_inpaint
        )
        png = _decode(result.png_bytes)
        assert tuple(png[0, 5, :3]) == (0, 0, 255), "PNG top = +V far = wall top"
        assert tuple(png[-1, 5, :3]) == (255, 255, 0), "PNG bottom = V origin"

    def test_long_edge_capped(self, monkeypatch):
        monkeypatch.setattr(shell_texture, "SHELL_TEXTURE_MAX_PX", 8)
        result = bake_plane_texture(
            _wall_geom(width=4.0, height=1.0),
            [_frame(pos=(2.0, 0.5, 4.0))],
            inpaint_fn=_green_inpaint,
        )
        assert max(result.texture_px) <= 8


# ---------------------------------------------------------------------------
# Mask exclusion + inpainting
# ---------------------------------------------------------------------------

class TestExclusionAndInpaint:
    def test_masked_pixels_become_inpainted_holes(self, monkeypatch):
        """Exclude the left half of the image; those texels must come back
        from the inpaint_fn (green), the rest from RGB (red). The wall's
        left half projects to the image's left half."""
        _small_texels(monkeypatch)
        exclusion = np.zeros((100, 100), dtype=bool)
        exclusion[:, :50] = True
        result = bake_plane_texture(
            _wall_geom(), [_frame((255, 0, 0), exclusion=exclusion)],
            inpaint_fn=_green_inpaint,
        )
        assert result.source == "baked"
        assert 0.3 < result.observed_fraction < 0.7
        assert result.inpainted_fraction == pytest.approx(
            1.0 - result.observed_fraction, abs=1e-6
        )
        img = _decode(result.png_bytes)
        # Texel column 0 = world x ~0.05 -> u ~27 (left half, masked).
        assert tuple(img[5, 0, :3]) == (0, 255, 0)
        # Texel column 9 = world x ~0.95 -> u ~72 (right half, observed).
        assert tuple(img[5, 9, :3]) == (255, 0, 0)

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
        result = bake_plane_texture(_wall_geom(), frames, inpaint_fn=_fail_inpaint)
        assert result.observed_fraction == 1.0
        assert result.inpainted_fraction == 0.0

    def test_min_observed_fraction_gate(self, monkeypatch):
        """Below the observation floor the plane ships untextured — a
        neutral treatment beats texturing from (mostly) nothing."""
        _small_texels(monkeypatch)
        exclusion = np.ones((100, 100), dtype=bool)
        # The wall projects to u in [25, 75]; leave only u < 35 clean, so
        # roughly the wall's left fifth is observable.
        exclusion[:, :35] = False
        result = bake_plane_texture(
            _wall_geom(), [_frame(exclusion=exclusion)],
            inpaint_fn=_green_inpaint, min_observed_fraction=0.5,
        )
        assert result.source == "unobserved"
        assert result.png_bytes is None
        assert 0 < result.observed_fraction < 0.5


# ---------------------------------------------------------------------------
# Median blending
# ---------------------------------------------------------------------------

class TestMedianBlend:
    def test_outlier_frame_suppressed(self, monkeypatch):
        """Two agreeing frames + one outlier (a transient bake-in): the
        weighted median lands on the agreeing color."""
        _small_texels(monkeypatch)
        frames = [
            _frame((200, 0, 0), frame_index=0),
            _frame((200, 0, 0), frame_index=1),
            _frame((255, 255, 255), frame_index=2),
        ]
        result = bake_plane_texture(_wall_geom(), frames, inpaint_fn=_fail_inpaint)
        img = _decode(result.png_bytes)
        assert np.all(np.abs(img[:, :, 0].astype(int) - 200) <= 1)
        assert np.all(img[:, :, 1] <= 1)

    def test_closer_frame_outweighs_far(self, monkeypatch):
        """Weights are incidence/distance-based: one close frame must beat
        one distant frame at the same incidence (weighted, not counted)."""
        _small_texels(monkeypatch)
        frames = [
            _frame((0, 0, 255), frame_index=0, pos=(0.5, 0.5, 1.0)),  # close
            _frame((255, 255, 0), frame_index=1, pos=(0.5, 0.5, 6.0)),  # far
        ]
        result = bake_plane_texture(_wall_geom(), frames, inpaint_fn=_fail_inpaint)
        img = _decode(result.png_bytes)
        assert np.all(img[:, :, 2] >= 254), "close frame's color must win"


# ---------------------------------------------------------------------------
# Floor alpha shape
# ---------------------------------------------------------------------------

class TestFloorAlpha:
    def test_alpha_follows_member_polygon_union(self, monkeypatch):
        """An L-shaped floor (two rectangles) must be opaque exactly on
        the union, transparent on the missing quadrant."""
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
        result = bake_plane_texture(
            geom, [frame], inpaint_fn=_green_inpaint, floor_member_polygons=polys,
        )
        img = _decode(result.png_bytes)
        h, w = img.shape[:2]
        # Missing quadrant: x in (1, 2], z in (1, 2] -> u in (1,2], v maps
        # z=2 -> v=0 (origin at z=2). Texel at u~1.75, z~1.75 -> col ~7,
        # row: v = (2 - z) = 0.25 -> row index from top = h-1 - 1 = near
        # bottom. Use world coords directly: alpha at col 7, row h-2.
        assert img[h - 2, 7, 3] == 0, "missing quadrant transparent"
        assert img[h - 2, 1, 3] == 255, "kept quadrant opaque"
        assert img[1, 7, 3] == 255, "far strip opaque"

    def test_wall_clip_zeroes_beyond(self, monkeypatch):
        """A wall crossing the floor bbox clips alpha beyond it (the
        interior side of the wall keeps its floor)."""
        _small_texels(monkeypatch, mpt=0.25)
        geom = _floor_geom(2.0, 2.0)
        polys = [np.array([[0, 0, 0], [2, 0, 0], [2, 0, 2], [0, 0, 2]], dtype=float)]
        # Wall at x=1.5 fronting -X (interior is x < 1.5).
        wall_planes = [(np.array([-1.0, 0.0, 0.0]), np.array([1.5, 0.0, 1.0]))]
        r = 1.0 / math.sqrt(2.0)
        frame = _frame((120, 100, 80), pos=(1.0, 3.0, 1.0), quat=(-r, 0.0, 0.0, r))
        result = bake_plane_texture(
            geom, [frame], inpaint_fn=_green_inpaint,
            floor_member_polygons=polys, wall_planes=wall_planes,
        )
        img = _decode(result.png_bytes)
        # u=1.9 (beyond the wall) -> col 7; u=0.9 -> col 3.
        assert img[4, 7, 3] == 0, "beyond the wall transparent"
        assert img[4, 3, 3] == 255, "interior side opaque"


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------

class TestDeterminism:
    def test_identical_inputs_identical_png(self, monkeypatch):
        _small_texels(monkeypatch)
        exclusion = np.zeros((100, 100), dtype=bool)
        exclusion[:, 40:60] = True
        frames = lambda: [  # noqa: E731 — fresh arrays each call
            _frame((200, 10, 10), frame_index=0, exclusion=exclusion.copy()),
            _frame((10, 200, 10), frame_index=1, pos=(0.5, 0.5, 3.0)),
        ]
        r1 = bake_plane_texture(_wall_geom(), frames(), inpaint_fn=_green_inpaint)
        r2 = bake_plane_texture(_wall_geom(), frames(), inpaint_fn=_green_inpaint)
        assert r1.png_bytes == r2.png_bytes
        assert r1.observed_fraction == r2.observed_fraction
        assert r1.inpainted_fraction == r2.inpainted_fraction

    def test_frame_order_does_not_matter(self, monkeypatch):
        """Frames are sorted by frame_index internally — callers' list
        order can't change the texture."""
        _small_texels(monkeypatch)
        f0 = lambda: _frame((200, 10, 10), frame_index=0)  # noqa: E731
        f1 = lambda: _frame((10, 200, 10), frame_index=1, pos=(0.5, 0.5, 3.0))  # noqa: E731
        r_a = bake_plane_texture(_wall_geom(), [f0(), f1()], inpaint_fn=_fail_inpaint)
        r_b = bake_plane_texture(_wall_geom(), [f1(), f0()], inpaint_fn=_fail_inpaint)
        assert r_a.png_bytes == r_b.png_bytes
