"""Assessing an arrangement: planted problems are found, a good room has none, and
the scan's own problems are excused only while their pieces stay put."""
import copy
import math
from dataclasses import replace

import numpy as np
import pytest

from needs_fixtures import WINDOW, bedroom_needs, door_needs
from rooms import SceneBuilder, bedroom
from thegoodguest_room_guide.assess import assess, window_cover
from thegoodguest_room_guide.model import room_from_scene
from thegoodguest_room_guide.needs import parse_needs


def setup(builder: SceneBuilder, needs: dict):
    room = room_from_scene(builder.scene())
    return room, parse_needs(room, needs)


def kinds(a):
    return sorted((b.kind, b.need, b.pieces) for b in a.breaks)


def test_a_room_that_works_breaks_nothing():
    room, needs = setup(bedroom(), bedroom_needs())
    a = assess(room, needs)
    assert a.breaks == []
    assert all(w >= 0.8 for w in a.paths.values())     # 0.9 m corridors, read on a 5 cm grid
    bed_pref = next(p for p in a.preferences if p.pref == "back_to_wall")
    assert bed_pref.value == 1.0 and bed_pref.detail["wall"] == "wall_-z"


def test_a_dresser_in_front_of_the_door_breaks_its_swing_and_its_way_in():
    room, needs = setup(bedroom(), bedroom_needs())
    door = room.pieces["door"].pose
    arrangement = {"dresser": replace(room.pieces["dresser"].pose, x=1.45, z=door.z, yaw=-math.pi / 2)}
    found = kinds(assess(room, needs, arrangement))
    assert ("zone", "open", ("door", "dresser")) in found
    assert ("zone", "pass", ("door", "dresser")) in found


def test_a_chair_beside_part_of_a_bed_leaves_a_way_in_elsewhere_along_it():
    b = bedroom()
    b.add("chair", "office_chair", (0.65, -0.2), (0.5, 1.0, 0.5))
    data = bedroom_needs()
    data["pieces"]["chair"] = {"moves": "yes"}
    room, needs = setup(b, data)
    a = assess(room, needs)
    assert not [x for x in a.breaks if x.kind == "zone" and x.pieces[0] == "bed"]


def test_a_desk_along_the_whole_bed_side_leaves_no_body_wide_strip():
    b = bedroom()
    b.objects = [o for o in b.objects if o["id"] not in ("bedside", "lamp")]
    b.add("long_desk", "desk", (0.85, -0.69), (0.5, 0.74, 2.2))   # 0.3 m off the bed's right side
    data = bedroom_needs()
    del data["pieces"]["bedside"], data["pieces"]["lamp"]
    data["pieces"]["long_desk"] = {"moves": "heavy", "why": "long"}
    room, needs = setup(b, data)
    zone = [x for x in assess(room, needs).breaks if x.kind == "zone" and x.pieces[0] == "bed"]
    assert len(zone) == 1 and zone[0].side == "right" and zone[0].pieces[1:] == ("long_desk",)
    assert zone[0].amount == pytest.approx(0.3, abs=0.02)


def test_a_bed_side_with_no_way_to_it():
    b = bedroom()
    b.objects = [o for o in b.objects if o["id"] not in ("bedside", "lamp")]
    # A run of cupboards along the bed's whole right side, 10 cm off it, from the wall
    # behind the bed to past its foot.
    b.add("cupboards", "cabinet", (0.65, -0.69), (0.5, 0.9, 2.2))
    data = bedroom_needs()
    del data["pieces"]["bedside"], data["pieces"]["lamp"]
    data["pieces"]["cupboards"] = {"moves": "heavy", "why": "built in"}
    room, needs = setup(b, data)
    a = assess(room, needs)
    unreachable = [x for x in a.breaks if x.kind == "unreachable"]
    assert [(x.pieces[0], x.side) for x in unreachable] == [("bed", "right")]
    assert a.paths[("bed", "get_in", "left")] >= 0.75


def _back_door_room():
    b = bedroom()
    b.door("back_door", "wall_-z", 0.2, 1.0)                 # x from 1.8 to 1.0
    b.against("bookcase", "bookcase", "wall_-z", 0.6, (0.9, 1.9, 0.4))
    data = bedroom_needs()
    data["pieces"]["back_door"] = door_needs()
    data["pieces"]["bookcase"] = {"moves": "heavy", "why": "full of books"}
    data["pieces"]["bedside"]["with"] = []
    room, needs = setup(b, data)
    return room, needs


def test_the_scans_own_problem_is_excused_while_its_pieces_stay():
    room, needs = _back_door_room()
    base = assess(room, needs)
    blocked = [b for b in base.breaks if b.kind == "zone" and b.pieces[0] == "back_door"]
    assert {b.need for b in blocked} == {"open", "pass"}
    assert all("bookcase" in b.pieces for b in blocked)
    dresser = room.pieces["dresser"].pose
    unrelated = {"dresser": replace(dresser, x=dresser.x + 0.2)}
    assert assess(room, needs, unrelated).unexcused(base, room, unrelated) == []
    bookcase = room.pieces["bookcase"].pose
    nudged = {"bookcase": replace(bookcase, x=bookcase.x - 0.05)}
    left = assess(room, needs, nudged).unexcused(base, room, nudged)
    assert any(b.kind == "zone" and b.pieces[0] == "back_door" and "bookcase" in b.pieces for b in left)


def test_a_switch_covered_by_a_wardrobe_and_reachable_over_a_desk():
    b = bedroom()
    b.on_wall("switches", "switch_panel", "wall_+z", 2.6, 1.1, (0.3, 0.2, 0.02))
    data = bedroom_needs()
    data["pieces"]["switches"] = {"moves": "fixed", "why": "wired in", "needs": [
        {"need": "reach", "strength": "hard", "why": "the lights are switched here"}]}
    b.against("wardrobe", "wardrobe", "wall_+z", 2.6, (1.0, 2.0, 0.6))
    data["pieces"]["wardrobe"] = {"moves": "heavy", "why": "tall and full"}
    room, needs = setup(b, data)
    assert ("covered", "reach", ("switches", "wardrobe")) in kinds(assess(room, needs))
    b2 = bedroom()
    b2.on_wall("switches", "switch_panel", "wall_+z", 2.6, 1.1, (0.3, 0.2, 0.02))
    b2.against("desk", "desk", "wall_+z", 2.6, (1.0, 0.74, 0.6))
    data2 = copy.deepcopy(data)
    del data2["pieces"]["wardrobe"]
    data2["pieces"]["desk"] = {"moves": "yes"}
    room2, needs2 = setup(b2, data2)
    a2 = assess(room2, needs2)
    assert not [x for x in a2.breaks if x.need == "reach"]
    assert a2.reach["switches"] == pytest.approx(0.6, abs=0.06)


def _mirror_room(blocker: str):
    b = bedroom()
    b.on_wall("mirror", "mirror", "wall_+z", 1.0, 0.85, (0.6, 0.9, 0.03))
    data = bedroom_needs()
    data["pieces"]["mirror"] = {"moves": "rehang", "why": "it hangs over the dresser",
                                "needs": [{"need": "see", "posture": "standing", "strength": "hard",
                                           "why": "you check yourself in it"}],
                                "with": [{"piece": "dresser", "how": "over", "strength": "soft",
                                          "why": "a mirror over the dresser"}]}
    if blocker == "wardrobe":
        data["pieces"]["dresser"]["needs"] = []
        b.objects = [o for o in b.objects if o["id"] != "dresser"]
        del data["pieces"]["dresser"]
        data["pieces"]["mirror"]["with"] = []
        data["pieces"]["mirror"]["moves"] = "fixed"
        b.against("wardrobe", "wardrobe", "wall_+z", 1.0, (1.0, 2.0, 0.6))
        data["pieces"]["wardrobe"] = {"moves": "heavy", "why": "tall"}
    return setup(b, data)


def test_a_mirror_over_a_dresser_is_seen_and_behind_a_wardrobe_is_not():
    room, needs = _mirror_room("dresser")
    assert not [x for x in assess(room, needs).breaks if x.need == "see"]
    room, needs = _mirror_room("wardrobe")
    assert ("unseen", "see", ("mirror",)) in kinds(assess(room, needs))


def test_a_window_mostly_covered_is_dark():
    b = bedroom()
    b.against("wardrobe", "wardrobe", "wall_-x", 1.8, (1.2, 2.2, 0.6))
    data = bedroom_needs()
    data["pieces"]["window"] = copy.deepcopy(WINDOW)
    data["pieces"]["window"]["needs"][0]["strength"] = "hard"
    data["pieces"]["wardrobe"] = {"moves": "heavy", "why": "tall"}
    room, needs = setup(b, data)
    a = assess(room, needs)
    assert ("dark", "light", ("window", "wardrobe")) in kinds(a)
    share, who = window_cover(room, "window", a.poses)
    assert share > 0.9 and who == ("wardrobe",)


def test_things_no_rule_has_heard_of():
    """A piano, an aquarium, a kiln and a floor fan: their needs come from the file, not from code."""
    b = SceneBuilder(width=5.0, depth=4.0, kind="studio")
    b.door("door", "wall_+x", 0.5, 1.4)
    b.against("piano", "piano", "wall_-z", 1.5, (1.5, 1.3, 0.6))
    b.against("aquarium", "aquarium", "wall_+z", 1.0, (1.2, 1.4, 0.5))
    b.against("kiln", "kiln", "wall_-x", 1.0, (0.7, 1.0, 0.7))
    b.add("fan", "floor_fan", (-1.0, 1.0), (0.4, 1.2, 0.4))
    b.add("stool", "stool", (-1.6, -1.0), (0.4, 0.5, 0.4))
    data = {"pieces": {
        "door": door_needs(),
        "piano": {"moves": "heavy", "why": "very heavy", "needs": [
            {"need": "use", "posture": "seated", "strength": "hard", "why": "played sitting at the keys"}]},
        "aquarium": {"moves": "heavy", "why": "full of water", "needs": [
            {"need": "see", "posture": "seated", "strength": "soft", "why": "people sit and watch the fish"},
            {"need": "reach", "strength": "hard", "why": "the fish are fed from the front"}]},
        "kiln": {"moves": "fixed", "why": "wired to its own circuit", "needs": [
            {"need": "heat", "side": "all", "strength": "hard", "why": "it fires to over 1000 C"}]},
        "fan": {"moves": "yes", "needs": [
            {"need": "air", "side": "front", "strength": "soft", "why": "it blows forward"}]},
        "stool": {"moves": "yes"},
    }}
    room, needs = setup(b, data)
    a = assess(room, needs)
    assert ("zone", "heat", ("kiln", "stool")) in kinds(a)
    assert not [x for x in a.breaks if x.pieces[0] in ("piano", "aquarium")]


def test_where_the_light_falls_at_a_desk():
    b = SceneBuilder(kind="study")
    b.door("door", "wall_+z", 3.0, 3.8)
    b.window("window", "wall_-x", 1.0, 2.0, 0.9, 2.1)
    b.against("desk", "desk", "wall_+x", 1.5, (1.2, 0.74, 0.6))
    data = {"pieces": {"door": door_needs(), "window": copy.deepcopy(WINDOW),
                       "desk": {"moves": "yes", "needs": [
                           {"need": "use", "posture": "seated", "strength": "hard", "why": "worked at"}]}},
            "preferences": [{"pref": "task_light", "piece": "desk", "task": "screen", "viewer": "facing_piece",
                             "weight": "high", "why": "screen work"}]}
    room, needs = setup(b, data)
    light = next(p for p in assess(room, needs).preferences if p.pref == "task_light")
    assert light.detail["light"] == "behind" and light.value == 0.0
    turned = {"desk": replace(room.pieces["desk"].pose, x=0.0, z=-1.19, yaw=0.0)}
    light = next(p for p in assess(room, needs, turned).preferences if p.pref == "task_light")
    assert light.detail["light"] == "side" and light.value == 1.0


def test_near_is_measured_between_edges_not_centres():
    from thegoodguest_room_guide.assess import bond_holds
    from thegoodguest_room_guide.laws import all_poses
    b = SceneBuilder(width=4.5, depth=4.0, kind="living room")
    b.against("sofa", "sofa", "wall_-z", 2.25, (2.0, 0.85, 0.9))
    b.add("coffee", "coffee_table", (0.0, -0.29), (1.2, 0.42, 0.6))        # 0.5 m off the sofa's front
    b.add("pouf", "pouf", (0.0, 1.2), (0.5, 0.4, 0.5))                       # well over a metre off
    room = room_from_scene(b.scene())
    poses = all_poses(room, {})
    assert bond_holds(room, "coffee", "sofa", "near", poses)
    assert not bond_holds(room, "pouf", "sofa", "near", poses)


def test_only_a_window_nearly_straight_ahead_is_in_front():
    from thegoodguest_room_guide.assess import light_direction
    room = room_from_scene(bedroom().scene())          # its one window is on wall_-x, centred on z = 0
    at = np.array([0.0, 0.0])

    def facing(deg):                                   # degrees away from looking straight at the window
        r = math.radians(deg)
        return np.array([-math.cos(r), math.sin(r)])

    assert light_direction(room, at, facing(20))[0] == "front"
    assert light_direction(room, at, facing(48))[0] == "side"
    assert light_direction(room, at, facing(160))[0] == "behind"


def _box_room(side: str):
    """A single bed pushed against the wall of a small room."""
    b = SceneBuilder(width=2.4, depth=2.6, kind="small bedroom")
    b.door("door", "wall_+z", 1.5, 2.3)
    b.against("bed", "bed", "wall_-z", 1.94, (0.9, 0.45, 2.0))
    data = {"pieces": {"door": door_needs(), "bed": {"moves": "heavy", "why": "a bed", "needs": [
        {"need": "get_in", "side": side, "posture": "lying", "strength": "hard", "why": "slept in"}]}}}
    return setup(b, data)


def test_a_single_bed_against_a_wall_needs_one_free_side_when_either_will_do():
    room, needs = _box_room("sides")
    assert [(b.need, b.side) for b in assess(room, needs).breaks if b.pieces[0] == "bed"]
    room, needs = _box_room("either")
    a = assess(room, needs)
    assert not [b for b in a.breaks if b.pieces[0] == "bed"]
    assert not [s for s in a.shortfalls if s.piece == "bed" and s.side == "left"]
    assert ("bed", "get_in", "left") not in a.paths, "the side that doesn't count isn't walked to either"


def test_heat_is_kept_from_pieces_not_from_walls():
    b = SceneBuilder(width=4.0, depth=3.5, kind="living room")
    b.door("door", "wall_+z", 0.3, 1.1)
    b.against("heater", "heater", "wall_-x", 1.75, (0.6, 0.65, 0.25))
    data = {"pieces": {"door": door_needs(), "heater": {"moves": "yes", "needs": [
        {"need": "heat", "side": "all", "strength": "hard", "why": "it gets hot"}]}}}
    room, needs = setup(b, data)
    assert not [x for x in assess(room, needs).breaks if x.need == "heat"]
    b.add("sofa", "sofa", (-1.1, 0.0), (1.8, 0.85, 0.9), yaw=math.pi / 2)
    data["pieces"]["sofa"] = {"moves": "heavy", "why": "a sofa"}
    room, needs = setup(b, data)
    assert ("zone", "heat", ("heater", "sofa")) in kinds(assess(room, needs))
