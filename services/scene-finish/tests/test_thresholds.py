"""The gate tolerances must stay clear of the renderer's own noise."""

import thresholds as t


def test_every_tolerance_is_several_times_the_measured_renderer_noise():
    for tol in (t.FINISH_ACCEPT_GAIN_L, t.FINISH_REGION_WORSEN_L, t.FURNITURE_L_TOLERANCE):
        assert tol >= 3 * t.RENDER_NOISE_L


def test_region_minimums_match_the_room_look_code():
    import inspect

    from thegoodguest_room_look import finish_compare

    src = inspect.getsource(finish_compare.calibrate)
    assert f"mask.sum() < {t.MIN_REGION_PIXELS}" in src
    assert f"frac < {t.MIN_DOMINANT_SHARE}" in src
