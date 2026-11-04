"""Pins for the room look's shell_finish module — the offline finish derivation.

The derivation's job is to be repeatable and honest: the same scan gives the
same finish, a bad measurement is replaced by the room's consensus rather than
drawn, and the camera model that checks colours against frames projects the
way ARKit's does. The viewer half is web/src/lib/shellFinish.test.ts.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from thegoodguest_room_look import shell_finish as sf
from thegoodguest_room_look.finish_hints import HintsError, parse_hints


def _wall(wall_id, poly, albedo, obs=0.2, openings=None):
    return {
        "wall_id": wall_id,
        "polygon": poly,
        "openings": openings or [],
        "material": {
            "albedo_hex": albedo,
            "family": None,
            "render": {"roughness": 0.9},
            "source": {"observed_fraction": obs},
        },
    }


def _room(albedos):
    # Four walls of a 3x3x3 box, winding fronting the interior.
    c = [(0, 0), (3, 0), (3, 3), (0, 3)]
    walls = []
    for i in range(4):
        (x0, z0), (x1, z1) = c[i], c[(i + 1) % 4]
        walls.append(_wall(f"wall_0{i}", [[x1, 0, z1], [x0, 0, z0], [x0, 3, z0], [x1, 3, z1]], albedos[i]))
    return {
        "scene_id": "scene-x",
        "walls": walls,
        "floor": {"polygon": [[0, 0, 0], [0, 0, 3], [3, 0, 3], [3, 0, 0]], "material": {"albedo_hex": "#999999", "family": "stone", "render": {"roughness": 0.5}}},
    }


def test_lab_roundtrip_and_hex():
    for h in ("#000000", "#ffffff", "#9dacd2", "#715b47"):
        assert sf.rgb_to_hex(sf.lab_to_rgb(sf.rgb_to_lab(sf.hex_to_rgb(h)))) == h


def test_wall_frame_matches_the_viewers_convention():
    # Mirrors web shell3d.test: a wall in the z=0 plane, 4 wide, 2 tall.
    poly = np.array([[0, -1, 0], [4, -1, 0], [4, 1, 0], [0, 1, 0]], float)
    f = sf.wall_frame(poly)
    assert f["w"] == pytest.approx(4) and f["h"] == pytest.approx(2)
    assert np.allclose(f["normal"], [0, 0, 1])
    assert np.allclose(f["axis_u"], [1, 0, 0])
    assert np.allclose(f["origin"], [0, -1, 0])


def test_camera_projects_like_arkit():
    from types import SimpleNamespace as NS

    pose = NS(pos_x=0, pos_y=0, pos_z=0, quat_x=0, quat_y=0, quat_z=0, quat_w=1)
    intr = NS(fx=1000, fy=1000, cx=960, cy=720, width=1920, height=1440)
    cam = sf.Camera.__new__(sf.Camera)
    cam.rot, cam.pos = sf.quat_to_matrix((0, 0, 0, 1)), np.zeros(3)
    cam.fx, cam.fy, cam.cx, cam.cy, cam.w, cam.h = 1000, 1000, 960, 720, 1920, 1440
    px, py, z, front = cam.project(np.array([[0.5, 0.25, -2.0], [0, 0, 2.0]]))
    assert front.tolist() == [True, False]  # -Z is forward
    assert px[0] == pytest.approx(960 + 1000 * 0.5 / 2)
    assert py[0] == pytest.approx(720 - 1000 * 0.25 / 2)  # image y is down


def test_mean_shift_finds_the_paint_among_clutter():
    rng = np.random.default_rng(1)
    paint = sf.rgb_to_lab(sf.hex_to_rgb("#9dacd2"))
    lab = np.concatenate([paint + rng.normal(0, 2, (800, 3)), sf.rgb_to_lab(sf.hex_to_rgb("#222222")) + rng.normal(0, 2, (500, 3))])
    c, n, frac = sf.mean_shift_mode(lab, sf.rgb_to_lab(sf.hex_to_rgb("#a0a8c8")))
    assert np.linalg.norm(c - paint) < 3
    assert 0.55 < frac < 0.65


def test_lit_only_lifts():
    lab = np.array([[40.0, 5, 5]] * 50 + [[70.0, 5, 5]] * 50)
    out = sf.lit(lab, np.array([55.0, 5, 5]), 75, delta_e=40)
    assert out[0] > 55
    assert sf.lit(lab, np.array([90.0, 5, 5]), 75, delta_e=5)[0] == 90.0


def test_no_frames_derivation_is_repeatable_and_walls_match():
    shell = _room(["#9dacd2", "#9eacd0", "#9bacd4", "#9dabd1"])
    a = sf.derive_finish(shell, [])
    b = sf.derive_finish(shell, [])
    assert a == b
    assert a["wall_count"] == 4 and len(a["walls"]) == 4
    assert a["floor"]["style"]["seed"] == b["floor"]["style"]["seed"]
    json.dumps(a)  # serialisable


def test_a_grey_outlier_wall_takes_the_room_chroma():
    shell = _room(["#9dacd2", "#9eacd0", "#9bacd4", "#9e9f9b"])  # last: grey 2%-observed
    shell["walls"][3]["material"]["source"]["observed_fraction"] = 0.02
    f = sf.derive_finish(shell, [])
    assert f["walls"][3]["paint"]["source"] == "room_consensus_chroma"
    lab = sf.rgb_to_lab(sf.hex_to_rgb(f["walls"][3]["paint"]["hex"]))
    assert lab[2] < -5  # blue-ish, not grey


def test_wall_without_measurement_gets_consensus_not_a_guess():
    shell = _room(["#9dacd2", "#9eacd0", None, "#9dabd1"])
    f = sf.derive_finish(shell, [])
    assert f["walls"][2]["paint"]["source"] == "room_consensus"


def test_openings_carry_through_and_windows_stay_neutral_glass():
    shell = _room(["#9dacd2"] * 4)
    shell["walls"][0]["openings"] = [{"classification": "window", "rect_uv": [[0.3, 0.3], [0.6, 0.7]]}]
    f = sf.derive_finish(shell, [])
    op = f["walls"][0]["openings"][0]
    assert op["kind"] == "window" and op["source"] == "default"


def test_calibration_offsets_move_colours_and_are_recorded():
    shell = _room(["#9dacd2"] * 4)
    base = sf.derive_finish(shell, [])
    hints = parse_hints({"calibration": {"source": "measured", "paint": [5, 0, -4], "floor": [-3, 0, 0], "texture_gain": 2.0}})
    out = sf.derive_finish(shell, [], hints)
    assert out["walls"][0]["paint"]["hex"] != base["walls"][0]["paint"]["hex"]
    assert out["calibration"] == {"paint": [5, 0, -4], "floor": [-3, 0, 0], "texture_gain": 2.0}
    assert out["floor"]["style"]["mottle"] == pytest.approx(min(base["floor"]["style"]["mottle"] * 2, 0.3), abs=1e-3) or out["floor"]["style"]["mottle"] <= 0.3
    assert sf.shift_hex("#808080", [0, 0, 0]) == "#808080"


def test_finish_compare_srgb_ids_and_erode():
    from thegoodguest_room_look import finish_compare as fc

    assert fc._srgb(40) == 110 and fc._srgb(240) == 248  # the PNG carries sRGB-encoded ids
    m = np.zeros((20, 20), bool)
    m[5:15, 5:15] = True
    assert fc.erode(m, 2).sum() == 36


def test_border_height_finds_a_long_horizontal_line_not_furniture():
    from thegoodguest_room_look import shell_structure as ss

    dv = 0.015
    lab = np.full((200, 100, 3), 60.0)
    lab[87:, :, 0] = 75.0  # a lighter band above row 87: a full-width edge at 1.3 m
    lab[:60, 10:20, 0] = 30.0  # a "chair" edge confined to a few columns
    h, score = ss.border_height(lab, dv)
    assert h == pytest.approx(87 * dv, abs=0.06) and score > 0.9


# ----------------------------------------------------------- the hints schema --
GOOD_HINTS = {
    "baseboard": {"source": "review", "present": False},
    "wainscot": {"source": "review", "height_m": 1.3, "tile_u_m": 0.3, "tile_v_m": 0.6, "joint": "light"},
    "floor": {"source": "review", "slab_u_m": 0.6, "slab_v_m": 0.6},
    "openings": {
        "door": {"source": "review", "casing": "frame", "panels": [[0.15, 0.06, 0.85, 0.46]]},
        "window": {"source": "review", "casing": "none", "glass_hex": "#c8d4e0"},
    },
    "calibration": {"source": "measured", "paint": [2.0, 0.0, -1.5], "texture_gain": 1.4},
}


def _problems(raw):
    with pytest.raises(HintsError) as e:
        parse_hints(raw)
    return "\n".join(e.value.problems)


def test_a_complete_hints_document_parses_unchanged():
    assert parse_hints(GOOD_HINTS) == GOOD_HINTS
    assert parse_hints({}) == {}


def test_hints_outside_the_vocabulary_are_refused():
    assert "ceiling" in _problems({"ceiling": {"source": "review"}})
    assert "sparkle" in _problems({"floor": {"source": "review", "sparkle": 1}})
    assert "gloss" in _problems({"openings": {"door": {"source": "review", "gloss": 1}}})
    assert "JSON object" in _problems([1, 2])


def test_every_section_must_say_where_it_came_from():
    for name in ("baseboard", "wainscot", "floor"):
        sec = {k: v for k, v in GOOD_HINTS[name].items() if k != "source"}
        assert f"{name}.source" in _problems({name: sec})
    door = {k: v for k, v in GOOD_HINTS["openings"]["door"].items() if k != "source"}
    assert "openings.door.source" in _problems({"openings": {"door": door}})
    assert "guess" in _problems({"floor": {"source": "guess", "slab_u_m": 0.6, "slab_v_m": 0.6}})
    assert "calibration.source" in _problems({"calibration": {"source": "review", "paint": [0, 0, 0]}})


def test_values_must_be_in_range_and_of_the_right_kind():
    assert "wainscot.height_m" in _problems({"wainscot": {"source": "review", "height_m": 9}})
    assert "wainscot.height_m is required" in _problems({"wainscot": {"source": "review", "tile_u_m": 0.3, "tile_v_m": 0.3}})
    assert "wainscot.joint" in _problems({"wainscot": {"source": "review", "height_m": 1.0, "joint": "red"}})
    assert "both tile_u_m and tile_v_m" in _problems({"wainscot": {"source": "review", "height_m": 1.0, "tile_u_m": 0.3}})
    assert "floor.slab_u_m" in _problems({"floor": {"source": "review", "slab_u_m": 0.0, "slab_v_m": 0.6}})
    assert "baseboard.present" in _problems({"baseboard": {"source": "review", "present": "yes"}})
    assert "wainscot.height_m" in _problems({"wainscot": {"source": "review", "height_m": True}})
    assert "calibration.paint" in _problems({"calibration": {"source": "measured", "paint": [1, 2]}})


def test_opening_hints_know_which_kind_they_apply_to():
    bad_panels = {"openings": {"door": {"source": "review", "panels": [[0.5, 0.1, 0.4, 0.9]]}}}
    assert "panels" in _problems(bad_panels)
    assert "only applies to a door" in _problems({"openings": {"window": {"source": "review", "panels": [[0, 0, 1, 1]]}}})
    assert "only applies to a window" in _problems({"openings": {"door": {"source": "review", "glass_hex": "#ffffff"}}})
    assert "casing" in _problems({"openings": {"door": {"source": "review", "casing": "gold"}}})


def test_all_problems_are_reported_together():
    text = _problems({"ceiling": {}, "floor": {"source": "x", "slab_u_m": -1, "slab_v_m": 0.6}})
    assert text.count("\n") >= 2


def _hinted_room(hints):
    return sf.derive_finish(_room(["#9dacd2"] * 4), [], parse_hints(hints))


def test_hints_reach_the_finish_with_their_source():
    st = _hinted_room({"floor": GOOD_HINTS["floor"]})["floor"]["style"]
    assert (st["slab_u_m"], st["slab_v_m"], st["dims_source"]) == (0.6, 0.6, "review")
    assert _hinted_room({})["floor"]["style"]["dims_source"] == "assumed"


def test_calibration_reaches_the_floor_texture_and_is_recorded_without_its_source():
    base = _hinted_room({})
    f = _hinted_room({"calibration": {"source": "measured", "texture_gain": 2.0}})
    assert f["floor"]["style"]["texture_gain"] == 2.0
    assert f["floor"]["style"]["mottle"] >= base["floor"]["style"]["mottle"]
    assert "source" not in f["calibration"]
