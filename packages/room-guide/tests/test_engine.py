"""The layout engine: directed placements, refusals with reasons, groups, and search."""
import copy
import math
from dataclasses import replace

import pytest

from demo import demo_room
from needs_fixtures import WINDOW, bedroom_needs, door_needs
from rooms import SceneBuilder, bedroom
from thegoodguest_room_guide.assess import assess, backing_wall
from thegoodguest_room_guide.engine import Engine, Refusal
from thegoodguest_room_guide.model import room_from_scene
from thegoodguest_room_guide.needs import parse_needs


def engine(builder, data, base=None):
    room = room_from_scene(builder.scene())
    return Engine(room, parse_needs(room, data), base or {})


def valid(e: Engine, proposal) -> bool:
    a = assess(e.room, e.needs, proposal.arrangement)
    return a.valid(e.scanned, e.room, proposal.arrangement)


def test_a_dresser_goes_against_another_wall():
    e = engine(bedroom(), bedroom_needs())
    p = e.place("dresser", wall="wall_-x")
    assert backing_wall(e.room, "dresser", p.arrangement["dresser"]) == "wall_-x"
    assert valid(e, p)
    assert p.words == ["the dresser goes against the window wall"]
    assert p.effort == "a two-person job"


def test_fixed_things_are_refused_with_their_reason():
    e = engine(bedroom(), bedroom_needs())
    with pytest.raises(Refusal) as r:
        e.place("door", wall="wall_-x")
    assert r.value.code == "fixed" and "part of the wall" in r.value.reason


def test_the_bed_takes_its_bedside_tables_and_lamp_with_it():
    e = engine(bedroom(), bedroom_needs())
    p = e.place("bed", along="wall_-z")
    roles = {m.piece: m.role for m in p.moves}
    assert roles["bed"] == "anchor"
    assert roles.get("bedside") == "follower" and roles.get("bedside_2") == "follower"
    assert roles.get("lamp") == "rider"
    assert valid(e, p)


def _study():
    """A desk against the wall opposite the window, so the window is behind whoever sits at it."""
    b = SceneBuilder(width=4.0, depth=3.6, kind="study")
    b.door("door", "wall_+z", 3.0, 3.8)
    b.window("window", "wall_-x", 1.3, 2.3, 0.9, 2.1)
    b.against("desk", "desk", "wall_+x", 1.8, (1.2, 0.74, 0.6))
    b.add("chair", "office_chair", (1.05, 0.0), (0.55, 1.0, 0.55), yaw=math.pi / 2)
    data = {"pieces": {
        "door": door_needs(), "window": copy.deepcopy(WINDOW),
        "desk": {"moves": "yes", "needs": [
            {"need": "use", "posture": "seated", "strength": "hard", "why": "worked at"}]},
        "chair": {"moves": "yes", "with": [{"piece": "desk", "how": "at", "strength": "hard", "why": "its chair"}]},
    }, "preferences": [{"pref": "task_light", "piece": "desk", "task": "screen", "viewer": "facing_piece",
                        "weight": "high", "why": "screen work"}]}
    return b, data


def test_a_piece_held_only_by_a_soft_bond_may_leave_its_anchor():
    """A heater wanted beside the sofa it warms must still find a place clear of it."""
    b = SceneBuilder(width=4.0, depth=3.5, kind="living room")
    b.door("door", "wall_+z", 0.3, 1.1)
    b.window("window", "wall_-z", 1.5, 2.5, 0.9, 2.1)
    b.against("sofa", "sofa", "wall_+x", 1.75, (1.8, 0.85, 0.9))
    b.add("heater", "heater", (0.75, 0.0), (0.6, 0.65, 0.25), yaw=math.pi / 2)
    data = {"pieces": {
        "door": door_needs(), "window": copy.deepcopy(WINDOW),
        "sofa": {"moves": "heavy", "why": "a sofa", "needs": [
            {"need": "get_in", "side": "front", "posture": "seated", "strength": "hard", "why": "sat on"}]},
        "heater": {"moves": "yes", "needs": [{"need": "heat", "side": "all", "strength": "hard", "why": "hot"}],
                   "with": [{"piece": "sofa", "how": "beside", "strength": "soft", "why": "it warms the sofa"}]},
    }}
    e = engine(b, data)
    assert "zone:heater:heat:front" in [f.key for f in e.current_findings]
    proposals = e.explore("fix:zone:heater:heat:front")
    assert proposals and proposals[0].moves[0].piece == "heater"
    data["pieces"]["heater"]["with"][0]["strength"] = "hard"
    held = engine(b, data).explore("fix:zone:heater:heat:front")
    assert all(m.piece != "heater" or m.role == "follower" for p in held for m in p.moves), \
        "a hard bond still moves it only with the sofa"


def test_search_turns_a_desk_side_on_to_the_window():
    e = engine(*_study())
    proposals = e.explore("light:desk")
    assert proposals, "a side-lit place exists and should be found"
    best = proposals[0]
    light = next(p for p in assess(e.room, e.needs, best.arrangement).preferences if p.pref == "task_light")
    assert light.detail["light"] == "side"
    assert any(m.piece == "chair" and m.role == "follower" for m in best.moves)
    assert all(valid(e, p) for p in proposals)
    assert best.score_after > best.score_before


def test_a_move_into_a_wall_item_is_refused_naming_it():
    b, data = _study()
    b.on_wall("ac", "ac_unit", "wall_-x", 1.8, 0.7, (0.6, 0.45, 0.3))
    data["pieces"]["ac"] = {"moves": "fixed", "why": "set into the window", "needs": [
        {"need": "air", "strength": "hard", "why": "it blows into the room"}]}
    e = engine(b, data)
    with pytest.raises(Refusal) as r:
        e.place("desk", under="window")
    assert "the ac" in r.value.reason


def test_search_clears_a_blocked_door():
    b = bedroom()
    room = room_from_scene(b.scene())
    door = room.pieces["door"].pose
    base = {"dresser": replace(room.pieces["dresser"].pose, x=1.5, z=door.z, yaw=-math.pi / 2)}
    e = Engine(room, parse_needs(room, bedroom_needs()), base)
    proposals = e.explore("fix:zone:door:open:front")
    assert proposals
    assert any(f.key == "zone:door:open:front" for f in proposals[0].fixes)


def test_measure_speaks_a_gap_net_of_both_margins():
    e = engine(bedroom(), bedroom_needs())
    text = e.measure("bed", "dresser")
    assert text.startswith("There's about") and text.endswith("by the scan.")


def test_the_demo_rooms_window_ac_rules_out_the_desk_under_the_window():
    room, needs = demo_room()
    e = Engine(room, needs)
    with pytest.raises(Refusal):
        e.place("desk", under="window")
