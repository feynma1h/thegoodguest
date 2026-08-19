"""Tests for object_color.py — the measured per-object colour (decision 0184).

Two halves. The unit half pins the gate's behaviour on constructed
gaussians; the real-data half runs the shipping function over two committed
subsamples of real reconstructions from the spike room — the chair the
operator called "the red chair", and a mirror, whose gaussians carry whatever
it reflected and which must be refused.

A third, heavier check lives outside this file by necessity: the cross-view
stability measurement behind the naming rule reads 2.2 GB of cached splats
(decision 0184 records its numbers). What is pinned here is that the chair
reads red and the mirror reads nothing.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import object_color
import pytest
import reproject

FIXTURES = Path(__file__).parent / "fixtures" / "object_color"


def _uniform(rgb, n=5000, opacity=0.9):
    colors = np.tile(np.asarray(rgb, dtype=np.float64), (n, 1))
    return colors, np.full(n, float(opacity))


class TestGate:
    def test_a_uniform_object_reads_its_own_colour(self):
        color = object_color.read_object_color(*_uniform([0.53, 0.02, 0.03]))
        assert color["hex"] == "#870508"
        assert color["concentration"] == 1.0
        assert color["visible_points"] == 5000

    def test_a_mottled_object_is_refused(self):
        rng = np.random.default_rng(0)
        colors = rng.random((5000, 3))
        assert object_color.read_object_color(colors, np.full(5000, 0.9)) is None

    def test_too_few_visible_gaussians_is_refused(self):
        colors, opacity = _uniform([0.5, 0.5, 0.5], n=1000)
        assert object_color.read_object_color(colors, opacity) is None

    def test_a_mostly_transparent_object_is_refused(self):
        """Opacity is the whole point of the visible-mass floor: a splat that
        is almost entirely see-through is not what the person is looking at."""
        colors, _ = _uniform([0.5, 0.5, 0.5], n=100000)
        opacity = np.full(100000, 0.05)
        opacity[:9000] = 0.9  # enough points, far too small a share
        assert object_color.read_object_color(colors, opacity) is None

    def test_transparent_gaussians_do_not_vote(self):
        """The visible mass decides the reading; near-invisible gaussians of
        another colour must not drag it."""
        colors = np.vstack([
            np.tile([0.8, 0.1, 0.1], (6000, 1)),
            np.tile([0.1, 0.1, 0.8], (4000, 1)),
        ])
        opacity = np.concatenate([np.full(6000, 0.9), np.full(4000, 0.02)])
        color = object_color.read_object_color(colors, opacity)
        assert color is not None and color["hex"] == "#cc1a1a"

    def test_a_two_tone_object_is_refused_rather_than_averaged(self):
        """Half red and half blue is not purple, and it is not red either."""
        colors = np.vstack([
            np.tile([0.8, 0.1, 0.1], (5000, 1)),
            np.tile([0.1, 0.1, 0.8], (5000, 1)),
        ])
        assert object_color.read_object_color(colors, np.full(10000, 0.9)) is None

    def test_it_is_deterministic(self):
        rng = np.random.default_rng(7)
        colors = np.clip(rng.normal([0.4, 0.2, 0.1], 0.03, (8000, 3)), 0, 1)
        opacity = np.full(8000, 0.8)
        first = object_color.read_object_color(colors, opacity)
        assert first is not None
        assert first == object_color.read_object_color(colors, opacity)

    def test_malformed_input_is_refused_not_raised(self):
        for colors, opacity in (
            (None, None),
            (np.zeros((0, 3)), np.zeros(0)),
            (np.zeros((10, 2)), np.zeros(10)),
            (np.zeros((10, 3)), np.zeros(5)),
            (np.full((5000, 3), np.nan), np.full(5000, 0.9)),
        ):
            assert object_color.read_object_color(colors, opacity) is None


class TestApplyPass:
    class _Ctx:
        def __init__(self, appearances):
            self.appearances = appearances

        def get_appearance(self, uri):
            return self.appearances.get(uri)

    def test_it_attaches_only_where_a_reading_survives(self):
        colors, opacity = _uniform([0.53, 0.02, 0.03])
        rng = np.random.default_rng(1)
        good = reproject.SplatAppearance(colors=colors, opacity=opacity)
        bad = reproject.SplatAppearance(
            colors=rng.random((5000, 3)), opacity=np.full(5000, 0.9)
        )
        fused = [
            {"object_id": "a", "splat_gcs_uri": "gs://b/a.ply"},
            {"object_id": "b", "splat_gcs_uri": "gs://b/b.ply"},
            {"object_id": "c", "splat_gcs_uri": None},
        ]
        object_color.apply_object_colors(
            fused, self._Ctx({"gs://b/a.ply": good, "gs://b/b.ply": bad})
        )
        assert fused[0]["color"]["hex"] == "#870508"
        assert "color" not in fused[1] and "color" not in fused[2]

    def test_an_unplaced_piece_still_gets_a_colour(self):
        """The case that most needs it: an unplaced piece cannot be moved or
        turned, so a colour is the only handle a person has for saying which
        one they mean."""
        colors, opacity = _uniform([0.53, 0.02, 0.03])
        fused = [{
            "object_id": "a", "placed": False, "reason": "insufficient_observations",
            "splat_gcs_uri": "gs://b/a.ply", "world_transform": None,
        }]
        object_color.apply_object_colors(fused, self._Ctx({
            "gs://b/a.ply": reproject.SplatAppearance(colors=colors, opacity=opacity)
        }))
        assert fused[0]["color"]["hex"] == "#870508"

    def test_a_context_without_appearance_leaves_everything_alone(self):
        fused = [{"object_id": "a", "splat_gcs_uri": "gs://b/a.ply"}]

        class _Bare:
            get_appearance = None

        object_color.apply_object_colors(fused, _Bare())
        assert fused == [{"object_id": "a", "splat_gcs_uri": "gs://b/a.ply"}]

    def test_an_unreadable_splat_does_not_take_the_pass_down(self):
        class _Boom:
            def get_appearance(self, uri):
                raise RuntimeError("gone")

        fused = [{"object_id": "a", "splat_gcs_uri": "gs://b/a.ply"}]
        object_color.apply_object_colors(fused, _Boom())
        assert "color" not in fused[0]


_needs_fixtures = pytest.mark.skipif(
    not (FIXTURES / "red_chair.ply").exists(),
    reason="colour fixtures absent",
)


@_needs_fixtures
class TestRealReconstructions:
    def _read(self, name):
        appearance = reproject.load_splat_appearance(
            (FIXTURES / name).read_bytes()
        )
        return object_color.read_object_color(
            appearance.colors, appearance.opacity
        )

    def test_the_red_chair_reads_red(self):
        """a7e073ae obj_006, subsampled by a deterministic stride from the
        310,400-gaussian original. The operator asked the deployed guest to
        "move the red chair" and was told no colours came through in the scan
        at all; this is that chair, and this is its colour.

        The full splat reads #880607 at concentration 0.7401 — the fixture's
        one-count difference in red is the subsample, and both name red.
        """
        color = self._read("red_chair.ply")
        assert color is not None
        assert color["hex"] == "#880708"
        assert color["concentration"] == pytest.approx(0.7267, abs=1e-4)
        assert color["visible_points"] == 7203

    def test_a_mirror_is_refused(self):
        """A mirror's gaussians carry what it reflected, so it has no colour
        of its own to report. Every mirror in the four walk rooms is refused;
        this is one of them."""
        assert self._read("mirror.ply") is None
