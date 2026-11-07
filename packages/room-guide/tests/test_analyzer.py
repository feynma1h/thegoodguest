"""Findings: planted problems come out as sentences with their numbers; a good room has none."""
import copy
import math
from dataclasses import replace

from demo import demo_room
from needs_fixtures import WINDOW, bedroom_needs, door_needs
from rooms import SceneBuilder, bedroom
from thegoodguest_room_guide.analyzer import about, findings, room_line, the, wall_name
from thegoodguest_room_guide.assess import assess
from thegoodguest_room_guide.model import room_from_scene
from thegoodguest_room_guide.needs import parse_needs


def run(builder, data, arrangement=None):
    room = room_from_scene(builder.scene())
    needs = parse_needs(room, data)
    return room, findings(room, needs, assess(room, needs, arrangement))


def texts(fs, kind=None):
    return [f.text for f in fs if kind is None or f.kind == kind]


def test_how_lengths_are_said():
    assert about(0.7) == "about 0.7 m"
    assert about(0.649) == "about 0.6 m"
    assert about(0.03) == "almost no room"
    assert about(0.62, down=False) == "about 0.6 m"


def test_names_a_person_would_use():
    room = room_from_scene(bedroom().scene())
    assert the(room, "bedside_2") == "the bedside 2"
    assert wall_name(room, "wall_-x") == "the window wall"
    assert wall_name(room, "wall_+x") == "the door wall"
    assert wall_name(room, "wall_-z") == "the wall behind the bed"
    assert room_line(room).startswith("Bedroom, 4 m by 3.6 m")


def test_a_good_room_has_no_problems_and_says_what_works():
    room, fs = run(bedroom(), bedroom_needs())
    assert texts(fs, "problem") == []
    assert "The bed has its back to a solid wall." in texts(fs, "good")


def test_a_dresser_in_the_doors_swing():
    b = bedroom()
    room = room_from_scene(b.scene())
    door = room.pieces["door"].pose
    moved = {"dresser": replace(room.pieces["dresser"].pose, x=1.45, z=door.z, yaw=-math.pi / 2)}
    _, fs = run(b, bedroom_needs(), moved)
    problems = texts(fs, "problem")
    assert "The door has about 0.25 m to open before the dresser; its door needs about 0.9 m." in problems
    assert any(t.startswith("The way to the side of the bed") and "at the door, by the dresser" in t
               for t in problems)


def test_the_window_behind_a_desk():
    b = SceneBuilder(kind="study")
    b.door("door", "wall_+z", 3.0, 3.8)
    b.window("window", "wall_-x", 1.0, 2.0, 0.9, 2.1)
    b.against("desk", "desk", "wall_+x", 1.5, (1.2, 0.74, 0.6))
    data = {"pieces": {"door": door_needs(), "window": copy.deepcopy(WINDOW),
                       "desk": {"moves": "yes", "needs": [
                           {"need": "use", "posture": "seated", "strength": "hard", "why": "worked at"}]}},
            "preferences": [{"pref": "task_light", "piece": "desk", "task": "screen", "viewer": "facing_piece",
                             "weight": "high", "why": "screen work"}]}
    _, fs = run(b, data)
    light = [f for f in fs if f.key == "pref:task_light:desk"][0]
    assert light.text == "Sitting at the desk, the window is behind you, so daylight falls on the screen."
    assert light.severity == 2


def test_a_bed_side_nobody_can_get_to_names_where_it_pinches():
    b = bedroom()
    b.objects = [o for o in b.objects if o["id"] not in ("bedside", "lamp")]
    b.add("cupboards", "cabinet", (0.65, -0.69), (0.5, 0.9, 2.2))
    data = bedroom_needs()
    del data["pieces"]["bedside"], data["pieces"]["lamp"]
    data["pieces"]["cupboards"] = {"moves": "heavy", "why": "built in"}
    _, fs = run(b, data)
    path = [f for f in fs if f.key == "path:bed:get_in:right"][0]
    assert path.kind == "problem"
    assert path.text == "The way to the side of the bed by the cupboards narrows to almost no room."


def test_questions_are_findings_too():
    data = bedroom_needs()
    data["questions"] = [{"about": "door", "ask": "Does the door open into the room?",
                          "why": "its swing decides what can stand beside it"}]
    _, fs = run(bedroom(), data)
    assert "Does the door open into the room?" in texts(fs, "question")


def test_the_demo_room_reads_like_a_designer_would():
    room, needs = demo_room()
    fs = findings(room, needs, assess(room, needs))
    said = " | ".join(f.text for f in fs)
    assert "In front of the white desk there's about 0.7 m before the double bed." in said
    assert "The white desk reaches into the swing of the wooden panel door." in said
    assert "Sitting at the white desk, the window is behind you, so daylight falls on the screen." in said
    assert "The office chair isn't at the white desk." in said
    assert any(f.key == "path:bed:get_in:left" and f.kind == "problem" for f in fs)
