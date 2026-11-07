"""The laws: overlap, inside, support, fixed, and never worse than the scan."""
import math
from dataclasses import replace

from rooms import SceneBuilder, bedroom
from thegoodguest_room_guide.laws import check, new_violations
from thegoodguest_room_guide.model import Pose, carry, room_from_scene


def kinds(violations):
    return sorted((v.kind, tuple(sorted(v.pieces))) for v in violations)


def test_a_room_that_works_breaks_no_law():
    room = room_from_scene(bedroom().scene())
    assert check(room, {}) == []


def test_two_solids_cannot_share_space():
    room = room_from_scene(bedroom().scene())
    bed = room.pieces["bed"].pose
    arrangement = {"dresser": replace(bed, yaw=0.0)}
    assert ("overlap", ("bed", "dresser")) in kinds(check(room, arrangement))


def test_nothing_leaves_the_room():
    room = room_from_scene(bedroom().scene())
    d = room.pieces["dresser"].pose
    arrangement = {"dresser": replace(d, z=d.z + 0.3)}
    assert ("outside", ("dresser",)) in kinds(check(room, arrangement))


def test_a_rider_left_behind_is_unsupported():
    room = room_from_scene(bedroom().scene())
    b = room.pieces["bedside"].pose
    moved = replace(b, x=b.x + 0.6)
    assert ("unsupported", ("bedside", "lamp")) in kinds(check(room, {"bedside": moved}))
    carried = carry(room.pieces["lamp"].pose, b, moved)
    assert not any(v.kind == "unsupported" for v in check(room, {"bedside": moved, "lamp": carried}))


def test_fixed_things_do_not_move():
    room = room_from_scene(bedroom().scene())
    door = room.pieces["door"].pose
    out = check(room, {"door": replace(door, z=door.z - 0.5)}, fixed={"door"})
    assert ("fixed_moved", ("door",)) in kinds(out)


def test_a_rug_can_be_stood_on():
    b = bedroom()
    b.add("rug", "rug", (-0.4, 0.2), (1.6, 0.01, 2.2))
    room = room_from_scene(b.scene())
    assert check(room, {}) == []


def test_a_door_or_window_piece_never_collides():
    b = bedroom()
    b.against("wardrobe", "wardrobe", "wall_-x", 1.8, (1.0, 2.0, 0.6))   # in front of the window
    room = room_from_scene(b.scene())
    assert not any("window" in v.pieces for v in check(room, {}))


def _desk_room(parts: bool):
    b = SceneBuilder()
    b.against("desk", "desk", "wall_-z", 2.0, (1.2, 0.74, 0.6))
    desk = b.objects[-1]
    # A stool tucked under the desk: its footprint is inside the desk's.
    b.add("stool", "stool", (desk["center"][0], desk["center"][2]), (0.35, 0.45, 0.35))
    solids = None
    if parts:
        top = [0.0, 0.72, 0.0, 0.6, 0.02, 0.3]
        legs = [[sx * 0.57, 0.35, sz * 0.27, 0.02, 0.35, 0.02] for sx in (-1, 1) for sz in (-1, 1)]
        solids = {"desk": [top, *legs]}
    return room_from_scene(b.scene(), solids)


def test_real_shapes_let_a_stool_live_under_a_desk():
    assert check(_desk_room(parts=True), {}) == []
    assert kinds(check(_desk_room(parts=False), {})) == [("overlap", ("desk", "stool"))]


def test_never_worse_than_the_scan():
    room = _desk_room(parts=False)
    base = check(room, {})
    desk, stool = room.pieces["desk"].pose, room.pieces["stool"].pose
    # Moving the pair together keeps what the scan had.
    to = replace(desk, x=desk.x - 1.0)
    together = {"desk": to, "stool": carry(stool, desk, to)}
    assert new_violations(room, together, base) == []
    # Nudging the stool alone is a new overlap, not the scan's.
    nudged = {"stool": replace(stool, x=stool.x + 0.05)}
    assert kinds(new_violations(room, nudged, base)) == [("overlap", ("desk", "stool"))]
    # Pulling it clear is fine.
    clear = {"stool": replace(stool, z=stool.z + 0.8)}
    assert new_violations(room, clear, base) == []


def test_turning_a_piece_is_checked_with_its_turned_shape():
    room = room_from_scene(bedroom().scene())
    dresser = room.pieces["dresser"].pose
    turned = {"dresser": replace(dresser, yaw=dresser.yaw + math.pi / 2)}
    assert ("outside", ("dresser",)) in kinds(check(room, turned))
    assert isinstance(dresser, Pose)
