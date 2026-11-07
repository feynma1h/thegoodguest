"""The motion planner: ordering, parking, paths, and a frame-by-frame check."""
import math
from dataclasses import replace

import pytest

from needs_fixtures import bedroom_needs
from rooms import SceneBuilder, bedroom
from thegoodguest_room_guide import laws
from thegoodguest_room_guide.engine import Engine
from thegoodguest_room_guide.model import Pose, room_from_scene
from thegoodguest_room_guide.motion import Key, NoPath, Plan, plan, plan_json, pose_at, smoothstep, verify
from thegoodguest_room_guide.needs import parse_needs


def poses(room, arrangement=None):
    return laws.all_poses(room, arrangement or {})


def test_easing_never_overshoots():
    assert smoothstep(0.0) == 0.0 and smoothstep(1.0) == 1.0
    assert all(0.0 <= smoothstep(u / 100) <= 1.0 for u in range(101))
    keys = [Key(0, 0, 0, 0, 0), Key(1, 1, 0, 0, 0)]
    assert pose_at(keys, 0.5).x == pytest.approx(0.5)
    assert pose_at(keys, 2.0).x == 1.0


def test_a_slide_along_a_wall_is_straight_and_checked_frame_by_frame():
    room = room_from_scene(bedroom().scene())
    d = room.pieces["dresser"].pose
    after = poses(room, {"dresser": replace(d, x=d.x + 0.8)})
    p = plan(room, poses(room), after)
    assert p.methods["dresser"] == "straight"
    assert p.frames_checked >= int(p.duration * 60)
    end = p.tracks["dresser"][-1]
    assert (end.x, end.z) == pytest.approx((d.x + 0.8, d.z))


def test_riders_travel_with_what_they_stand_on():
    room = room_from_scene(bedroom().scene())
    b = room.pieces["bedside"].pose
    to = replace(b, x=b.x + 0.4)
    after = poses(room, {"bedside": to, "lamp": replace(room.pieces["lamp"].pose, x=room.pieces["lamp"].pose.x + 0.4)})
    p = plan(room, poses(room), after)
    assert set(p.tracks) == {"bedside", "lamp"}
    for t in (0.0, p.duration / 2, p.duration):
        a, l = pose_at(p.tracks["bedside"], t), pose_at(p.tracks["lamp"], t)
        assert l.x - a.x == pytest.approx(0.0, abs=1e-6)


def _two_cabinets():
    b = SceneBuilder(width=4.0, depth=3.0, kind="hall")
    b.door("door", "wall_+z", 3.0, 3.8)
    b.against("a", "cabinet", "wall_-z", 1.0, (0.8, 1.0, 0.4))
    b.against("b", "cabinet", "wall_-z", 1.9, (0.8, 1.0, 0.4))
    return room_from_scene(b.scene())


def test_two_pieces_trading_places_use_a_parking_spot():
    room = _two_cabinets()
    a, b = room.pieces["a"].pose, room.pieces["b"].pose
    after = poses(room, {"a": b, "b": a})
    p = plan(room, poses(room), after)
    assert p.parked, "a swap cannot be done without one piece waiting somewhere"
    assert pose_at(p.tracks["a"], p.duration).x == pytest.approx(b.x)
    assert pose_at(p.tracks["b"], p.duration).x == pytest.approx(a.x)


def test_a_piece_boxed_in_is_lifted_over_rather_than_passed_through():
    b = SceneBuilder(width=3.0, depth=3.0, kind="store room")
    b.add("crate", "crate", (-1.0, 0.0), (0.4, 0.4, 0.4))
    # A ring of low benches round the crate.
    for i, (x, z, sx, sz) in enumerate([(-1.0, 0.45, 1.3, 0.3), (-1.0, -0.45, 1.3, 0.3),
                                        (-0.4, 0.0, 0.3, 0.6), (-1.45, 0.0, 0.1, 0.6)]):
        b.add(f"bench{i}", "bench", (x, z), (sx, 0.45, sz))
    room = room_from_scene(b.scene())
    after = poses(room, {"crate": replace(room.pieces["crate"].pose, x=1.0)})
    p = plan(room, poses(room), after)
    assert p.methods["crate"] == "lifted"
    assert max(k.y for k in p.tracks["crate"]) > 0.45


def test_the_check_refuses_a_plan_that_passes_through_something():
    room = room_from_scene(bedroom().scene())
    d = room.pieces["dresser"].pose
    bed = room.pieces["bed"].pose
    # Straight through the bed.
    bad = Plan({"dresser": [Key(0, d.x, d.y, d.z, d.yaw), Key(2, bed.x, d.y, bed.z, d.yaw),
                            Key(4, d.x, d.y, d.z, d.yaw)]}, ["dresser"], 4.0)
    with pytest.raises(NoPath):
        verify(room, poses(room), bad)


def test_every_engine_proposal_can_be_played():
    room = room_from_scene(bedroom().scene())
    e = Engine(room, parse_needs(room, bedroom_needs()))
    for kwargs in (dict(piece="dresser", wall="wall_-x"), dict(piece="bed", along="wall_-z")):
        p = e.place(**kwargs)
        motion = plan(room, poses(room), poses(room, p.arrangement))
        assert motion.frames_checked > 0
        doc = plan_json(motion)
        assert doc["plan_version"] == 1 and doc["easing"] == "smoothstep"
        assert set(doc["tracks"]) == {m.piece for m in p.moves}
