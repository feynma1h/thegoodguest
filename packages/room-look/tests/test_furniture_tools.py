"""Pins for the furniture twin tools: the boxes they read, the placement rules
that put each twin in the room, and the checks that it clears the walls and
its neighbours. The renderer half is web/src/lib/furniture.ts.
"""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path

import numpy as np
import pytest

from thegoodguest_room_look import furniture_boxes as fb
from thegoodguest_room_look import furniture_clearance as fcl
from thegoodguest_room_look import furniture_geometry as fg
from thegoodguest_room_look import furniture_models as fm
from thegoodguest_room_look import furniture_placement as fp

EXAMPLE = Path(__file__).resolve().parent / "example"

# A 4 m x 4 m room, x and z from 0 to 4, floor at y = 0, walls 2.5 m tall.
POLY = np.array([[0, 0], [4, 0], [4, 4], [0, 4]], float)


def _shell(openings_on_wall0=None):
    c = [(0, 0), (4, 0), (4, 4), (0, 4)]
    walls = []
    for i in range(4):
        (x0, z0), (x1, z1) = c[i], c[(i + 1) % 4]
        walls.append({
            "wall_id": f"wall_0{i}",
            "polygon": [[x0, 0, z0], [x1, 0, z1], [x1, 2.5, z1], [x0, 2.5, z0]],
            "openings": openings_on_wall0 if i == 0 and openings_on_wall0 else [],
        })
    return {"scene_id": "scene-test", "walls": walls,
            "floor": {"y": 0.0, "polygon": [[0, 0, 0], [0, 0, 4], [4, 0, 4], [4, 0, 0]]}}


def _box(bid, centre, size, yaw=0.0, category="thing"):
    return {"id": bid, "category": category, "center": list(centre), "yaw": yaw, "size": list(size)}


def _spec(key, obj, size, rule="floor", parts=None, **place):
    w, h, d = size
    return {
        "key": key, "object": obj, "box_dims": [w, h, d],
        "materials": {"m": {"color": "#aaaaaa"}},
        "parts": parts or [{"kind": "box", "name": "body", "mat": "m", "size": [w, h, d], "at": [0, h / 2, 0]}],
        "place": {"rule": rule, **place},
    }


def _place(specs, boxes, floor_y=0.0):
    return fp.place_all(specs, {b["id"]: b for b in boxes}, POLY, floor_y)


# ------------------------------------------------------------------- boxes --
def test_a_boxes_document_parses_and_reports_every_problem():
    doc = {"boxes_version": 1, "boxes": [_box("a", (1, 0.5, 1), (1, 1, 1))]}
    assert fb.parse_boxes(doc)["a"]["category"] == "thing"
    bad = {"boxes_version": 1, "boxes": [
        {"id": "a", "category": "x", "center": [0, 0], "yaw": "no", "size": [1, 1, 0]},
        _box("a", (0, 0, 0), (1, 1, 1)),
        _box("b", (0, 0, 0), (1, 1, 1)) | {"colour": "red"},
    ]}
    with pytest.raises(fb.BoxesError) as e:
        fb.parse_boxes(bad)
    text = "\n".join(e.value.problems)
    for needle in ("center", "yaw", "size", "duplicate id", "unknown keys"):
        assert needle in text
    with pytest.raises(fb.BoxesError):
        fb.parse_boxes({"boxes": []})


def test_box_pose_and_corners_use_the_documented_yaw():
    b = _box("a", (2, 0.5, 3), (2, 1, 1), yaw=math.pi / 2)
    centre, yaw, size = fb.box_pose(b)
    assert centre.tolist() == [2, 0.0, 3] and size.tolist() == [2, 1, 1]
    # yaw +90 degrees: local +x goes to (cos, 0, -sin) = (0, 0, -1)
    world, _, rot = fb.box_corners(b)
    assert np.allclose(rot @ [1, 0, 0], [0, 0, -1], atol=1e-9)
    assert world[:, 2].max() - world[:, 2].min() == pytest.approx(2.0)


def test_windows_and_doors_come_from_the_shells_openings_facing_the_room():
    ops = [{"classification": "window", "rect_uv": [[0.25, 0.4], [0.75, 0.8]]},
           {"classification": "door", "rect_uv": [[0.0, 0.0], [0.2, 0.8]]},
           {"classification": "opening", "rect_uv": [[0.8, 0.0], [0.9, 0.5]]}]
    boxes = fb.opening_boxes(_shell(ops))
    assert sorted(boxes) == ["door_0", "window_0"]
    w = boxes["window_0"]
    assert w["size"] == [pytest.approx(2.0), pytest.approx(1.0), fb.OPENING_DEPTH_M]
    assert w["center"][1] == pytest.approx(0.6 * 2.5)
    # wall_00 lies on z = 0; the room is at +z, so local +z must point there
    _, _, rot = fb.box_corners(w)
    assert (rot @ [0, 0, 1])[2] > 0.99
    assert abs(w["center"][2]) < 1e-6


def test_load_shell_unwraps_an_assets_response(tmp_path):
    (tmp_path / "shell.json").write_text(json.dumps({"scene_id": "s", "shell": _shell()}))
    assert len(fb.load_shell(tmp_path)["walls"]) == 4
    (tmp_path / "shell.json").write_text(json.dumps(_shell()))
    assert len(fb.load_shell(tmp_path)["walls"]) == 4


def test_load_boxes_merges_the_file_and_the_openings(tmp_path):
    (tmp_path / "boxes.json").write_text(json.dumps({"boxes_version": 1, "boxes": [_box("a", (1, 0.5, 1), (1, 1, 1))]}))
    (tmp_path / "shell.json").write_text(json.dumps(_shell([{"classification": "door", "rect_uv": [[0.1, 0], [0.3, 0.8]]}])))
    assert sorted(fb.load_boxes(tmp_path)) == ["a", "door_0"]
    assert fb.load_boxes(tmp_path / "nowhere") == {}


# ---------------------------------------------------------------- geometry --
def test_obb_penetration_gives_the_way_out():
    def obb(c, h):
        return np.array(c, float), np.eye(3), np.array(h, float)

    depth, axis = fg.obb_penetration(obb([0, 0, 0], [1, 1, 1]), obb([1.5, 0, 0], [1, 1, 1]))
    assert depth == pytest.approx(0.5) and np.allclose(axis, [1, 0, 0])
    assert fg.obb_overlap(obb([0, 0, 0], [1, 1, 1]), obb([3, 0, 0], [1, 1, 1])) < 0
    assert fg.worst_edge(np.array([4.3, 2.0]), POLY)[0] == pytest.approx(0.3)
    assert fg.worst_edge(np.array([1.0, 1.0]), POLY)[0] == 0.0


def test_part_extent_covers_each_kind_of_part():
    lo, hi = fg.part_extent({"kind": "cyl", "r": 0.1, "h": 0.4, "at": [0, 0.2, 0]})
    assert lo.tolist() == pytest.approx([-0.1, 0.0, -0.1]) and hi.tolist() == pytest.approx([0.1, 0.4, 0.1])
    lo, hi = fg.part_extent({"kind": "books", "w": 0.5, "depth": 0.2, "hmin": 0.1, "hmax": 0.3, "mats": []})
    assert hi[1] == pytest.approx(0.3)


# --------------------------------------------------------------- placement --
def test_a_floor_piece_stands_where_its_box_is():
    objs, problems = _place([_spec("a", "a", (1, 1, 1))], [_box("a", (2, 0.5, 2), (1, 1, 1), yaw=0.3)])
    assert objs[0]["position"] == pytest.approx([2, 0, 2]) and objs[0]["yaw"] == pytest.approx(0.3)
    assert "fixes" not in objs[0] and objs[0]["source"] == "boxes" and not problems


def test_a_flat_piece_faces_the_room_and_backs_onto_the_nearest_wall():
    # a board 1 m wide, 0.1 deep, hung roughly near the z = 0 wall but slanted and a little off it
    spec = _spec("board", "b", (1, 1, 0.1), rule="wall", gap=0.01)
    objs, problems = _place([spec], [_box("b", (2, 0.5, 0.4), (1, 1, 0.1), yaw=0.2)])
    o = objs[0]
    assert o["yaw"] == pytest.approx(0.0, abs=1e-6)  # +z faces the room (towards +z)
    assert o["position"][2] == pytest.approx(0.01 + 0.05)  # back part 1 cm off the wall at z = 0
    assert o["position"][0] == pytest.approx(2.0)  # its place along the wall is kept
    assert o["mount"] == "wall" and o["fixes"][0]["rule"] == "wall" and not problems


def test_wall_pieces_on_the_far_wall_turn_to_face_the_room():
    spec = _spec("board", "b", (1, 1, 0.1), rule="wall")
    objs, _ = _place([spec], [_box("b", (2, 0.5, 3.8), (1, 1, 0.1), yaw=0.0)])
    o = objs[0]
    assert math.cos(o["yaw"]) == pytest.approx(-1.0, abs=1e-6)  # +z now points to -z
    assert o["position"][2] == pytest.approx(4 - 0.005 - 0.05)


def test_a_piece_hung_over_another_clears_its_front():
    window = _spec("win", "w", (1, 1, 0.12), rule="opening")
    curtain = _spec("curtain", "c", (1.2, 2, 0.05), rule="over", target="win")
    boxes = [_box("w", (2, 1.5, 0.0), (1, 1, 0.12)), _box("c", (2, 1.0, 0.3), (1.2, 2, 0.05))]
    objs, problems = _place([curtain, window], boxes)  # the target comes second: order must not matter
    win, cur = objs[1], objs[0]
    assert win["position"][2] == pytest.approx(0.0) and "fixes" not in win and win["mount"] == "wall"
    # window front at z = 0.06; curtain back 5 mm in front of that
    assert cur["position"][2] - 0.025 == pytest.approx(0.06 + 0.005, abs=1e-6)
    assert cur["target"] == "win" and not problems


def test_a_piece_on_another_stands_on_its_top_and_inside_its_footprint():
    table = _spec("table", "t", (1, 0.7, 0.6))
    lamp = _spec("lamp", "l", (0.2, 0.4, 0.2), rule="on", target="table")
    boxes = [_box("t", (2, 0.35, 2), (1, 0.7, 0.6)), _box("l", (3.2, 0.2, 2.0), (0.2, 0.4, 0.2))]
    objs, problems = _place([table, lamp], boxes)
    assert objs[1]["position"][1] == pytest.approx(0.7)
    assert 1.5 <= objs[1]["position"][0] <= 2.5  # was 3.2: brought onto the table
    assert {f["rule"] for f in objs[1]["fixes"]} == {"on"} and not problems


def test_the_piece_on_another_travels_with_it_when_the_support_is_moved():
    table = _spec("table", "t", (1, 0.7, 0.6))
    lamp = _spec("lamp", "l", (0.2, 0.4, 0.2), rule="on", target="table")
    # the table is half through the +x wall: the rules push it in and the lamp follows
    boxes = [_box("t", (3.9, 0.35, 2), (1, 0.7, 0.6)), _box("l", (3.9, 0.2, 2.0), (0.2, 0.4, 0.2))]
    objs, problems = _place([table, lamp], boxes)
    assert objs[0]["position"][0] == pytest.approx(3.5 - 0.002, abs=0.01)
    assert objs[1]["position"][0] == pytest.approx(objs[0]["position"][0], abs=1e-6)
    assert not problems


def test_nothing_stands_below_the_floor_or_through_a_wall():
    a = _spec("a", "a", (1, 1, 1))
    objs, problems = _place([a], [_box("a", (3.8, 0.3, 2.0), (1, 1, 1))])  # centre y 0.3: 0.2 m underground, 0.3 m into the wall
    o = objs[0]
    assert o["position"][1] == pytest.approx(0.0, abs=1e-6) or o["position"][1] >= 0  # box_pose puts the base at -0.2
    assert o["position"][1] >= -1e-6
    assert o["position"][0] <= 3.5 + 1e-6
    assert {f["rule"] for f in o["fixes"]} >= {"floor", "wall"} and not problems
    assert all(f["why"] for f in o["fixes"])


def test_overlapping_floor_pieces_are_pushed_apart_and_the_push_is_recorded():
    a, b = _spec("a", "a", (1, 1, 1)), _spec("b", "b", (1, 1, 1))
    objs, problems = _place([a, b], [_box("a", (1.5, 0.5, 2), (1, 1, 1)), _box("b", (2.2, 0.5, 2), (1, 1, 1))])
    assert objs[0]["position"][0] == pytest.approx(1.5)  # the earlier piece stays
    assert objs[1]["position"][0] >= 2.5  # the later one cleared it
    assert objs[1]["fixes"][0] == {"rule": "overlap", "why": "clear of a", "moved_m": pytest.approx(0.3, abs=0.02)}
    assert not problems


def test_an_overlap_between_pieces_that_may_not_move_is_reported_not_guessed():
    a, b = _spec("a", "a", (1, 1, 1), rule="opening"), _spec("b", "b", (1, 1, 1), rule="opening")
    _, problems = _place([a, b], [_box("a", (2, 0.5, 2), (1, 1, 1)), _box("b", (2, 1.0, 2), (1, 1, 1))])
    assert [p["kind"] for p in problems] == ["overlap"]


def test_a_vertical_overlap_is_not_pushed_sideways():
    # b sits half inside a's top; only a stack declared with `on` is allowed to touch
    a, b = _spec("a", "a", (1, 1, 1)), _spec("b", "b", (1, 1, 1))
    objs, problems = _place([a, b], [_box("a", (2, 0.5, 2), (1, 1, 1)), _box("b", (2, 1.45, 2), (1, 1, 1))])
    assert [p["kind"] for p in problems] == ["overlap"]
    assert objs[1]["position"][0] == pytest.approx(2.0) and objs[1]["position"][2] == pytest.approx(2.0)


def test_openings_stay_exactly_where_their_box_is():
    w = _spec("win", "w", (1, 1, 0.12), rule="opening")
    objs, problems = _place([w], [_box("w", (2, 1.5, -0.02), (1, 1, 0.12))])
    assert objs[0]["position"][2] == pytest.approx(-0.02) and not problems and "fixes" not in objs[0]


def test_a_hand_fix_is_applied_in_the_box_frame_and_recorded_with_its_reason():
    a = _spec("a", "a", (1, 1, 1), fix={"dx": 0.1, "dz": 0.0, "dyaw_deg": 90, "why": "scan has it touching the bed"})
    objs, _ = _place([a], [_box("a", (2, 0.5, 2), (1, 1, 1), yaw=math.pi / 2)])
    # box yaw 90 degrees: local +x is world -z
    assert objs[0]["position"][2] == pytest.approx(2 - 0.1) and objs[0]["position"][0] == pytest.approx(2)
    assert objs[0]["yaw"] == pytest.approx(math.pi)
    assert objs[0]["fixes"][0]["why"] == "scan has it touching the bed" and objs[0]["source"] == "boxes+fixed"
    assert any("reason" in m for m in fp.validate_place(_spec("a", "a", (1, 1, 1), fix={"dx": 0.1})))


def test_place_blocks_are_validated():
    assert fp.validate_place(_spec("a", "a", (1, 1, 1))) == []
    text = "\n".join(
        fp.validate_place(_spec("a", "a", (1, 1, 1), rule="sideways", sparkle=1))
        + fp.validate_place(_spec("a", "a", (1, 1, 1), rule="on"))
        + fp.validate_place(_spec("a", "a", (1, 1, 1), target="b"))
    )
    for needle in ("sparkle", "rule must be one of", "needs a place.target", "only applies"):
        assert needle in text


def test_bad_targets_and_missing_boxes_are_refused_with_the_reason():
    with pytest.raises(fp.PlacementError, match="not a twin"):
        _place([_spec("a", "a", (1, 1, 1), rule="on", target="ghost")], [_box("a", (2, 0.5, 2), (1, 1, 1))])
    loop = [_spec("a", "a", (1, 1, 1), rule="on", target="b"), _spec("b", "b", (1, 1, 1), rule="on", target="a")]
    with pytest.raises(fp.PlacementError, match="loops"):
        _place(loop, [_box("a", (2, 0.5, 2), (1, 1, 1)), _box("b", (3, 0.5, 2), (1, 1, 1))])
    with pytest.raises(fp.PlacementError, match="not in boxes.json"):
        _place([_spec("a", "nobody", (1, 1, 1))], [])


# --------------------------------------------------------------- clearance --
def test_clearance_flags_overlap_wall_and_inside_but_not_declared_contact():
    def obj(key, x, z, **kw):
        spec = _spec(key, key, (1, 1, 1))
        return {"key": key, "position": [x, 0, z], "yaw": 0.0, "spec": spec, **kw}

    objs = [obj("a", 1.0, 2.0), obj("b", 1.8, 2.0), obj("c", 3.9, 2.0)]
    kinds = sorted((p["kind"], p["a"]) for p in fcl.find_problems(objs, POLY, 0.0))
    assert ("overlap", "a") in kinds and ("wall", "c") in kinds
    resting = [obj("a", 1.0, 2.0), obj("b", 1.8, 2.0, rule="on", target="a")]
    assert not [p for p in fcl.find_problems(resting, POLY, 0.0) if p["kind"] == "overlap"]
    openings = [obj("c", 3.9, 2.0, rule="opening")]
    assert fcl.find_problems(openings, POLY, 0.0) == []
    grouped = obj("d", 2.0, 2.0)
    grouped["spec"] = copy.deepcopy(grouped["spec"])
    grouped["spec"]["parts"].append({"kind": "box", "name": "stool", "mat": "m", "size": [0.3, 0.3, 0.3], "at": [0, 0.5, 0]})
    grouped["spec"]["separate_groups"] = [["stool"]]
    assert [p["kind"] for p in fcl.find_problems([grouped], POLY, 0.0)] == ["inside"]


# ------------------------------------------------------------------- specs --
def test_the_example_spec_and_boxes_are_a_valid_format_fixture():
    spec = json.loads((EXAMPLE / "specs" / "side-table.json").read_text())
    assert fm.validate_spec(spec) == []
    boxes = fb.parse_boxes(json.loads((EXAMPLE / "boxes.json").read_text()))
    assert fm.box_problems(spec, boxes["box_0"]) == []


def test_spec_validation_names_what_is_wrong():
    spec = json.loads((EXAMPLE / "specs" / "side-table.json").read_text())
    bad = copy.deepcopy(spec)
    bad["parts"].append({"kind": "torus", "mat": "wood"})
    bad["parts"].append({"kind": "box", "mat": "nope", "size": [1, 1, 1]})
    bad["parts"].append({"kind": "cyl", "mat": "wood"})
    bad["colour"] = "red"
    text = "\n".join(fm.validate_spec(bad))
    for needle in ("torus", "nope", "missing or has a bad field", "colour"):
        assert needle in text
    assert "missing box_dims" in "\n".join(fm.validate_spec({k: v for k, v in spec.items() if k != "box_dims"}))


def test_box_problems_notice_a_resized_box_and_a_wandering_part():
    spec = json.loads((EXAMPLE / "specs" / "side-table.json").read_text())
    boxes = fb.parse_boxes(json.loads((EXAMPLE / "boxes.json").read_text()))
    big = dict(boxes["box_0"], size=[0.9, 0.55, 0.4])
    assert "box_dims" in "\n".join(fm.box_problems(spec, big))
    far = copy.deepcopy(spec)
    far["parts"].append({"kind": "box", "mat": "wood", "size": [0.1, 0.1, 0.1], "at": [2.0, 0.1, 0]})
    assert "beyond the box" in "\n".join(fm.box_problems(far, boxes["box_0"]))


def test_build_writes_a_bundle_from_boxes_specs_and_the_shell(tmp_path):
    scene = tmp_path / "scene"
    scene.mkdir()
    (scene / "shell.json").write_text(json.dumps(_shell()))
    (scene / "boxes.json").write_text((EXAMPLE / "boxes.json").read_text())
    bundle = fm.build(scene, EXAMPLE / "specs")
    assert bundle["furniture_version"] == 1 and bundle["scene_id"] == "scene-test"
    (o,) = bundle["objects"]
    assert o["key"] == "side-table" and o["position"] == pytest.approx([1.0, 0.0, 1.0]) and o["rule"] == "floor"
    assert "place" not in o["spec"] and "object" not in o["spec"]
    json.dumps(bundle)


def test_build_strict_fails_on_a_warning(tmp_path):
    scene = tmp_path / "scene"
    scene.mkdir()
    (scene / "shell.json").write_text(json.dumps(_shell()))
    boxes = json.loads((EXAMPLE / "boxes.json").read_text())
    boxes["boxes"][0]["size"] = [0.9, 0.55, 0.4]
    (scene / "boxes.json").write_text(json.dumps(boxes))
    fm.build(scene, EXAMPLE / "specs")  # a warning, not a failure
    with pytest.raises(SystemExit):
        fm.build(scene, EXAMPLE / "specs", strict=True)


# ----------------------------------------------------- evidence and compare --
def test_evidence_and_compare_read_the_new_boxes(tmp_path):
    from thegoodguest_room_look import furniture_compare as fcmp
    from thegoodguest_room_look import furniture_evidence as fev

    world, centre, _ = fb.box_corners(_box("a", (1, 0.5, 1), (1, 1, 1)))
    assert world.shape == (8, 3) and centre.tolist() == [1, 0.5, 1]
    specs = tmp_path / "furniture" / "specs"
    specs.mkdir(parents=True)
    (specs / "side-table.json").write_text((EXAMPLE / "specs" / "side-table.json").read_text())
    assert fcmp.spec_for(tmp_path, "box_0")["key"] == "side-table"
    with pytest.raises(SystemExit):
        fcmp.spec_for(tmp_path, "box_9")
    assert fev.pick_spread([{"score": 1, "azimuth_deg": 0}, {"score": 0.9, "azimuth_deg": 5}, {"score": 0.8, "azimuth_deg": 90}], 3) == [
        {"score": 1, "azimuth_deg": 0}, {"score": 0.8, "azimuth_deg": 90}]
