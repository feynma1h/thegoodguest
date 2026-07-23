"""Shell material-inference invariants (decision 0069): the measured
albedo estimator, THE load-bearing fallback rule (below gate / "other" /
call failure / no crops / no key → family = None → clean neutral, never
wrong-specific), the roughness lookup, and plank direction — all offline;
no test ever touches the network or the anthropic SDK.

Run: python -m pytest services/perception-obj/tests/test_shell_material.py
"""
from __future__ import annotations

import numpy as np
import pytest
import shell_material
from shell_material import (
    FLOOR_FAMILIES,
    WALL_FAMILIES,
    MaterialResult,
    classify_family_via_api,
    compute_albedo,
    infer_material,
    plank_direction,
)
from shell_observation import EvidenceCrop, ObservationResult

# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

def _texels(color, n=500, weight=1.0):
    colors = np.tile(np.asarray(color, dtype=np.float32), (n, 1))
    weights = np.full(n, weight, dtype=np.float32)
    return colors, weights


def _crop(img: np.ndarray, side_m: float = 0.64) -> EvidenceCrop:
    return EvidenceCrop(
        rgb=img, frame_index=0, u0=0.0, v0=0.0, u1=side_m, v1=side_m,
        observed_fraction=1.0, fill_fraction=0.0,
    )


def _observation(colors, weights, crops) -> ObservationResult:
    return ObservationResult(
        observed_fraction=1.0,
        texel_count=len(colors),
        in_region_count=len(colors),
        frames_used=1,
        grid_px=(32, 32),
        colors=colors,
        weights=weights,
        crops=crops,
    )


def _solid_crop(color=(150, 120, 90)) -> EvidenceCrop:
    img = np.zeros((32, 32, 3), dtype=np.uint8)
    img[:, :] = color
    return _crop(img)


# ---------------------------------------------------------------------------
# Albedo
# ---------------------------------------------------------------------------

class TestAlbedo:
    def test_uniform_color_recovered_exactly(self):
        colors, weights = _texels((180, 140, 100))
        assert compute_albedo(colors, weights) == "#b48c64"

    def test_shadowed_texels_do_not_darken_albedo(self):
        """70% of the surface in shadow (x0.4): the high-lightness band
        keeps the albedo at the lit color."""
        lit, w_lit = _texels((200, 160, 120), n=150)
        shade, w_shade = _texels((80, 64, 48), n=350)
        colors = np.vstack([shade, lit])
        weights = np.concatenate([w_shade, w_lit])
        assert compute_albedo(colors, weights) == "#c8a078"

    def test_specular_highlights_excluded(self):
        """A blown-white sliver above the band cap must not brighten the
        albedo."""
        base, w_base = _texels((120, 110, 100), n=450)
        spec, w_spec = _texels((255, 255, 255), n=50)
        colors = np.vstack([base, spec])
        weights = np.concatenate([w_base, w_spec])
        assert compute_albedo(colors, weights) == "#786e64"

    def test_below_min_texels_is_none(self):
        colors, weights = _texels((180, 140, 100), n=50)
        assert compute_albedo(colors, weights) is None

    def test_deterministic(self):
        rng = np.random.default_rng(7)
        colors = rng.uniform(60, 220, size=(400, 3)).astype(np.float32)
        weights = rng.uniform(0.1, 2.0, size=400).astype(np.float32)
        assert compute_albedo(colors, weights) == compute_albedo(
            colors.copy(), weights.copy()
        )


# ---------------------------------------------------------------------------
# THE fallback rule (0069, test-pinned): family = None -> clean neutral
# ---------------------------------------------------------------------------

class TestFallbackRule:
    def _obs(self):
        colors, weights = _texels((150, 120, 90))
        return _observation(colors, weights, [_solid_crop()])

    def test_confident_family_ships(self):
        result = infer_material(
            self._obs(), "floor", classify_fn=lambda c, k: ("wood", 0.9)
        )
        assert result.family == "wood"
        assert result.family_confidence == 0.9
        assert result.model == shell_material.SHELL_MATERIAL_MODEL
        assert result.roughness == 0.6

    def test_below_gate_family_is_null(self):
        result = infer_material(
            self._obs(), "floor", classify_fn=lambda c, k: ("wood", 0.5)
        )
        assert result.family is None
        assert result.family_confidence is None
        assert result.model is None
        # The measured albedo SURVIVES — clean matte in the measured color.
        assert result.albedo_hex is not None
        assert result.roughness == shell_material._ROUGHNESS[None]

    def test_other_family_is_null(self):
        result = infer_material(
            self._obs(), "floor", classify_fn=lambda c, k: ("other", 0.95)
        )
        assert result.family is None
        assert result.family_confidence is None

    def test_classifier_returning_none_is_null(self):
        result = infer_material(self._obs(), "floor", classify_fn=lambda c, k: None)
        assert result.family is None
        assert result.albedo_hex is not None

    def test_classifier_raising_is_null_never_raises(self):
        def _boom(crops, kind):
            raise RuntimeError("network down")

        result = infer_material(self._obs(), "floor", classify_fn=_boom)
        assert result.family is None
        assert result.albedo_hex is not None

    def test_no_crops_never_calls_classifier(self):
        colors, weights = _texels((150, 120, 90))
        obs = _observation(colors, weights, [])

        def _fail(crops, kind):
            raise AssertionError("classifier must not run without evidence")

        result = infer_material(obs, "floor", classify_fn=_fail)
        assert result.family is None

    def test_no_api_key_returns_none_without_network(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        assert classify_family_via_api([_solid_crop()], "floor") is None

    def test_no_crops_api_path_returns_none(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        assert classify_family_via_api([], "floor") is None


# ---------------------------------------------------------------------------
# Vocabulary + roughness lookup
# ---------------------------------------------------------------------------

class TestVocabulary:
    def test_closed_vocabularies_pinned(self):
        assert FLOOR_FAMILIES == ("wood", "tile", "stone", "carpet", "concrete")
        assert WALL_FAMILIES == ("painted", "wallpaper", "tile", "exposed")

    def test_every_family_has_a_roughness(self):
        for fam in FLOOR_FAMILIES + WALL_FAMILIES + (None,):
            assert 0.0 <= shell_material._ROUGHNESS[fam] <= 1.0


# ---------------------------------------------------------------------------
# Plank direction
# ---------------------------------------------------------------------------

def _stripe_crop(axis: str, period: int = 8) -> EvidenceCrop:
    """Stripes along the given crop axis: 'columns' = seams run vertically
    in the raster (plank direction +V), 'rows' = seams run horizontally
    (plank direction +U)."""
    img = np.zeros((64, 64, 3), dtype=np.uint8)
    idx = np.arange(64)
    stripe = (100 + 60 * ((idx // period) % 2)).astype(np.uint8)
    if axis == "columns":
        img[:, :, :] = stripe[None, :, None]
    else:
        img[:, :, :] = stripe[:, None, None]
    return _crop(img)


class TestPlankDirection:
    def test_vertical_stripes_mean_plank_along_v(self):
        deg = plank_direction([_stripe_crop("columns")])
        assert deg == pytest.approx(90.0, abs=2.0)

    def test_horizontal_stripes_mean_plank_along_u(self):
        deg = plank_direction([_stripe_crop("rows")])
        assert deg is not None
        assert min(deg, 180.0 - deg) == pytest.approx(0.0, abs=2.0)

    def test_noise_has_no_consensus(self):
        rng = np.random.default_rng(3)
        img = rng.integers(0, 255, size=(64, 64, 3), dtype=np.uint8)
        assert plank_direction([_crop(img)]) is None

    def test_no_crops_is_none(self):
        assert plank_direction([]) is None

    def test_only_wood_floors_get_plank_direction(self):
        colors, weights = _texels((150, 120, 90))
        obs = _observation(colors, weights, [_stripe_crop("columns")])
        wood = infer_material(obs, "floor", classify_fn=lambda c, k: ("wood", 0.9))
        assert wood.plank_direction_deg is not None
        carpet = infer_material(
            obs, "floor", classify_fn=lambda c, k: ("carpet", 0.9)
        )
        assert carpet.plank_direction_deg is None
        wall = infer_material(
            obs, "wall", classify_fn=lambda c, k: ("painted", 0.9)
        )
        assert wall.plank_direction_deg is None


# ---------------------------------------------------------------------------
# Result shape
# ---------------------------------------------------------------------------

class TestResultShape:
    def test_secondary_hex_always_none_in_v1(self):
        colors, weights = _texels((150, 120, 90))
        obs = _observation(colors, weights, [_solid_crop()])
        result = infer_material(obs, "wall", classify_fn=lambda c, k: ("painted", 0.9))
        assert isinstance(result, MaterialResult)
        assert result.secondary_hex is None
