"""The room model: reading a diorama scene, poses, solids and riders."""
import math

import pytest

from rooms import bedroom
from thegoodguest_room_guide.model import (
    MARGIN_ESTIMATED, MARGIN_HELD, MARGIN_MEASURED, Pose, carry, room_from_scene, spoken,
)


def test_reads_the_shell_and_pieces():
    room = room_from_scene(bedroom().scene())
    assert room.kind == "bedroom"
    assert [w.id for w in room.walls] == ["wall_-x", "wall_+z", "wall_+x", "wall_-z"]
    assert {o.id for o in room.openings} == {"door", "window"}
    assert room.pieces["door"].opening == "door"
    assert room.pieces["bed"].opening is None
    assert room.pieces["lamp"].support == "object" and room.pieces["lamp"].on == "bedside"


def test_refuses_other_schemas():
    scene = bedroom().scene()
    scene["schema"] = "diorama.scene/2"
    with pytest.raises(ValueError):
        room_from_scene(scene)


def test_a_piece_against_a_wall_faces_into_the_room():
    room = room_from_scene(bedroom().scene())
    bed = room.pieces["bed"]
    back = room.wall("wall_-z")
    assert back.normal == (0.0, 1.0)
    fx, fz = bed.box().front
    assert (fx, fz) == pytest.approx(back.normal, abs=1e-9)
    # Its back face sits 1 cm off the wall.
    assert back.offset_of((bed.pose.x, bed.pose.z)) - bed.size[2] / 2 == pytest.approx(0.01)


def test_pose_y_is_the_bottom_and_riders_sit_on_their_support():
    room = room_from_scene(bedroom().scene())
    bedside, lamp = room.pieces["bedside"], room.pieces["lamp"]
    assert bedside.pose.y == pytest.approx(0.0)
    assert lamp.pose.y == pytest.approx(bedside.size[1])
    assert room.riders("bedside") == ["lamp"]
    assert room.base_of("lamp") == "bedside"


def test_carry_moves_a_rider_rigidly():
    frm = Pose(1.0, 0.0, 0.0, 0.0)
    to = Pose(0.0, 0.0, 2.0, math.pi / 2)
    rider = Pose(1.0, 0.5, 0.3, 0.0)            # 0.3 m in front of the support's centre
    moved = carry(rider, frm, to)
    # The support now faces +x, so "in front" is +x.
    assert (moved.x, moved.y, moved.z) == pytest.approx((0.3, 0.5, 2.0))
    assert moved.yaw == pytest.approx(math.pi / 2)


def test_solids_default_to_the_whole_box_and_take_an_export():
    scene = bedroom().scene()
    room = room_from_scene(scene)
    desk_like = room.pieces["dresser"]
    assert desk_like.parts_from == "box" and len(desk_like.solids()) == 1
    exported = {"dresser": [[0, 0.78, 0, 0.5, 0.02, 0.225], [0.45, 0.38, 0, 0.03, 0.38, 0.2]]}
    room2 = room_from_scene(scene, exported)
    assert room2.pieces["dresser"].parts_from == "builder"
    assert len(room2.pieces["dresser"].solids()) == 2


def test_an_export_bigger_than_the_piece_is_not_believed():
    scene = bedroom().scene()
    room = room_from_scene(scene, {"dresser": [[0, 0.4, 0, 0.9, 0.4, 0.2]]})
    assert room.pieces["dresser"].parts_from == "box"


def test_margin_follows_how_a_size_was_measured():
    b = bedroom()
    b.add("a", "x", (0, 0), (0.3, 0.3, 0.3), size_from="measured")
    b.add("b", "x", (0.5, 0), (0.3, 0.3, 0.3), size_from="measured, held to estimate")
    b.add("c", "x", (1.0, 0), (0.3, 0.3, 0.3), size_from="estimate")
    room = room_from_scene(b.scene())
    assert [room.pieces[k].margin for k in "abc"] == [MARGIN_MEASURED, MARGIN_HELD, MARGIN_ESTIMATED]


def test_spoken_names():
    assert spoken("Double bed") == "double bed"
    assert spoken("AC unit") == "AC unit"
    assert spoken("Window AC") == "window AC"
