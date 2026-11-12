"""The eval's rooms: each one ordinary, with one problem planted in it.

Every room comes with:
  - `problem`: the planted problem in a sentence, for the judge;
  - `expect`: the finding keys the problem should raise. Each entry may list
    alternatives with "|", and matches any finding whose key contains it, so
    needs written another reasonable way still count;
  - `planted`: the pieces the problem is made of. A problem that touches none
    of them is one nobody planted, and the room is wrong;
  - `key`: an answer key, the needs a careful designer would write. It proves
    the problem can be found at all, so a live miss is the rules pass's miss,
    not the room's.

Two rooms plant no problem: `good_bedroom` works as it is, and `box_room` is too
small for anything to be better. There the right answer is to say so.

Read by: run.py, judge.py, tests/test_evals.py.
"""
from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field

from needs_fixtures import WINDOW, door_needs
from rooms import SceneBuilder


@dataclass
class EvalRoom:
    name: str
    builder: SceneBuilder
    key: dict
    problem: str
    expect: list[str] = field(default_factory=list)
    planted: tuple[str, ...] = ()

    def scene(self) -> dict:
        return self.builder.scene()


def _window(strength: str = "soft") -> dict:
    w = copy.deepcopy(WINDOW)
    w["needs"][0]["strength"] = strength
    return w


def _moves(why: str = "", moves: str = "yes", needs: list | None = None, with_: list | None = None) -> dict:
    out = {"moves": moves, "why": why}
    if needs:
        out["needs"] = needs
    if with_:
        out["with"] = with_
    return out


def _need(need: str, strength: str = "hard", why: str = "it is used", **kw) -> dict:
    return {"need": need, "strength": strength, "why": why, **kw}


def _bed(b: SceneBuilder, u: float = 2.4, size=(1.4, 0.5, 2.0)) -> None:
    b.against("bed", "bed", "wall_-z", u, size, name="Double bed", params={"headboard": "panel"},
              description="Wooden double bed with a padded headboard, made up with a grey quilt.")


BED_KEY = _moves("a wooden double bed", "heavy", [_need("get_in", side="sides", posture="lying",
                                                         why="two people get in from either side")])


def door_blocked() -> EvalRoom:
    b = SceneBuilder(depth=3.6, kind="bedroom")
    b.door("door", "wall_+x", 0.3, 1.2)
    b.window("window", "wall_-x", 1.3, 2.3, 0.9, 2.1)
    _bed(b)
    b.against("bedside", "side_table", "wall_-z", 1.3, (0.45, 0.55, 0.4), name="Bedside table",
              params={"drawers": "1"}, description="Small white bedside table with one drawer.")
    b.on("lamp", "table_lamp", "bedside", (0.0, 0.0), (0.25, 0.45, 0.25), name="Bedside lamp",
         description="Table lamp with a linen shade.")
    b.against("dresser", "dresser", "wall_+z", 3.4, (1.0, 0.8, 0.45), name="Chest of drawers",
              params={"drawers": "6"}, description="Wide oak chest of six drawers in the corner by the door.")
    key = {"pieces": {
        "door": door_needs(), "window": _window(), "bed": BED_KEY,
        "bedside": _moves(with_=[{"piece": "bed", "how": "beside", "strength": "soft", "why": "by the pillow"}]),
        "lamp": _moves(),
        "dresser": _moves("full of clothes", "heavy", [
            _need("open", side="front", mechanism="drawers", why="its drawers pull out"),
            _need("use", side="front", posture="standing", why="you stand at it to dress")]),
    }}
    return EvalRoom("door_blocked", b, key, "The chest of drawers stands in the corner where the door swings open.",
                    ["zone:door"], ("door", "dresser"))


def glare_desk() -> EvalRoom:
    b = SceneBuilder(depth=3.6, kind="study")
    b.door("door", "wall_+z", 3.0, 3.8)
    b.window("window", "wall_-x", 1.3, 2.3, 0.9, 2.1)
    b.against("desk", "desk", "wall_+x", 1.8, (1.4, 0.75, 0.7), name="Writing desk",
              params={"drawers": "2", "legs": "four"}, description="Oak writing desk with two shallow drawers.")
    b.on("monitor", "monitor", "desk", (0.2, 0.0), (0.6, 0.45, 0.2), name="Monitor",
         description="27-inch monitor on a stand, facing into the room.")
    b.add("chair", "office_chair", (1.0, 0.0), (0.55, 1.0, 0.55), yaw=math.pi / 2, name="Office chair",
          description="Black mesh office chair on castors, at the desk.")
    b.against("shelves", "bookcase", "wall_-z", 2.0, (0.8, 1.8, 0.35), name="Bookshelf",
              params={"shelves": "5"}, description="Open white bookshelf.")
    key = {"pieces": {
        "door": door_needs(), "window": _window(),
        "desk": _moves("a solid oak desk", "heavy", [_need("use", side="front", posture="seated", why="worked at")]),
        "monitor": _moves(),
        "chair": _moves(with_=[{"piece": "desk", "how": "at", "strength": "hard", "why": "its chair"}]),
        "shelves": _moves("full of books", "heavy", [_need("use", "soft", side="front", posture="standing")]),
    }, "preferences": [{"pref": "task_light", "piece": "desk", "task": "screen", "viewer": "facing_piece",
                        "weight": "high", "why": "screen work"}]}
    return EvalRoom("glare_desk", b, key,
                    "The desk faces away from the only window, so daylight falls on the screen from behind.",
                    ["pref:task_light:desk"], ("desk", "window"))


def bed_no_way_in() -> EvalRoom:
    b = SceneBuilder(depth=3.6, kind="bedroom")
    b.door("door", "wall_+x", 0.3, 1.2)
    b.window("window", "wall_-x", 1.3, 2.3, 0.9, 2.1)
    _bed(b)
    b.against("bedside_2", "side_table", "wall_-z", 3.45, (0.45, 0.55, 0.4), name="Bedside table",
              description="Small white bedside table.")
    b.add("cupboards", "cabinet", (0.65, -0.69), (2.2, 0.9, 0.5), yaw=math.pi / 2, name="Low cupboards",
          params={"doors": "4"}, description="A long run of low white cupboards beside the bed, doors facing away from it.")
    key = {"pieces": {
        "door": door_needs(), "window": _window(), "bed": BED_KEY,
        "bedside_2": _moves(with_=[{"piece": "bed", "how": "beside", "strength": "soft", "why": "by the pillow"}]),
        "cupboards": _moves("long and full", "heavy", [
            _need("open", side="front", mechanism="hinged", leaves=4, why="four doors open outwards")]),
    }}
    return EvalRoom("bed_no_way_in", b, key,
                    "A run of cupboards stands a hand's width from one side of the double bed, so nobody can get in on that side.",
                    ["bed:get_in:right"], ("bed", "cupboards"))


def wardrobe_blocked() -> EvalRoom:
    b = SceneBuilder(depth=3.2, kind="bedroom")
    b.door("door", "wall_+x", 0.2, 1.0)
    b.window("window", "wall_-x", 1.0, 2.0, 0.9, 2.1)
    b.against("bed", "bed", "wall_-z", 2.4, (1.6, 0.5, 2.1), name="Queen bed",
              description="Queen bed with a low upholstered frame.")
    b.against("wardrobe", "wardrobe", "wall_+z", 1.6, (1.2, 2.0, 0.6), name="Wardrobe", params={"doors": "2"},
              description="Tall white wardrobe with two hinged doors, facing the foot of the bed.")
    key = {"pieces": {
        "door": door_needs(), "window": _window(),
        "bed": _moves("a queen bed", "heavy", [_need("get_in", side="sides", posture="lying")]),
        "wardrobe": _moves("full of clothes", "heavy", [
            _need("open", side="front", mechanism="hinged", leaves=2, why="its doors swing open"),
            _need("use", side="front", posture="standing", why="you stand at it to dress")]),
    }}
    return EvalRoom("wardrobe_blocked", b, key, "The foot of the bed stands where the wardrobe's doors swing open.",
                    ["zone:wardrobe|path:wardrobe"], ("bed", "wardrobe"))


def window_covered() -> EvalRoom:
    b = SceneBuilder(width=4.5, depth=3.5, kind="living room")
    b.door("door", "wall_+z", 3.4, 4.3)
    b.window("window", "wall_-x", 1.2, 2.4, 0.8, 2.1)
    b.against("sofa", "sofa", "wall_-z", 2.25, (2.0, 0.85, 0.9), name="Three-seat sofa",
              description="Grey three-seat fabric sofa.")
    b.against("bookcase", "bookcase", "wall_-x", 1.8, (1.2, 2.0, 0.4), name="Tall bookcase",
              params={"shelves": "6"}, description="Tall walnut bookcase full of books, standing against the window.")
    b.add("coffee", "coffee_table", (0.0, 0.0), (1.1, 0.42, 0.6), name="Coffee table",
          description="Low oak coffee table.")
    key = {"pieces": {
        "door": door_needs(), "window": _window("hard"),
        "sofa": _moves("a big sofa", "heavy", [_need("get_in", side="front", posture="seated")]),
        "bookcase": _moves("full of books", "heavy", [_need("use", "soft", side="front", posture="standing")]),
        "coffee": _moves(),
    }}
    return EvalRoom("window_covered", b, key, "A tall bookcase stands right in front of the room's only window.",
                    ["dark:window|light:window|zone:window"], ("window", "bookcase"))


def chair_cramped() -> EvalRoom:
    b = SceneBuilder(width=2.2, depth=3.2, kind="home office")
    b.door("door", "wall_+z", 0.15, 0.95)
    b.window("window", "wall_-z", 0.6, 1.6, 0.9, 2.1)
    b.against("desk", "desk", "wall_-x", 1.5, (1.2, 0.75, 0.7), name="Desk", params={"legs": "four"},
              description="White desk on four legs.")
    b.add("chair", "office_chair", (-0.105, 0.0), (0.55, 1.05, 0.55), yaw=-math.pi / 2, name="Desk chair",
          description="Grey office chair at the desk.")
    b.against("sofa", "sofa", "wall_+x", 1.6, (1.8, 0.85, 0.85), name="Sofa bed",
              description="Navy two-seat sofa bed against the far wall.")
    key = {"pieces": {
        "door": door_needs(), "window": _window(),
        "desk": _moves(needs=[_need("use", side="front", posture="seated", why="worked at")]),
        "chair": _moves(with_=[{"piece": "desk", "how": "at", "strength": "hard", "why": "its chair"}]),
        "sofa": _moves("a sofa bed", "heavy", [_need("get_in", side="front", posture="seated")]),
    }}
    return EvalRoom("chair_cramped", b, key,
                    "The sofa bed is so close behind the desk that the chair can't be pushed back.",
                    ["zone:desk|path:desk|zone:chair"], ("desk", "chair", "sofa"))


def heater_close() -> EvalRoom:
    b = SceneBuilder(width=4.0, depth=3.5, kind="living room")
    b.door("door", "wall_+z", 0.3, 1.1)
    b.window("window", "wall_-z", 1.5, 2.5, 0.9, 2.1)
    b.against("sofa", "sofa", "wall_+x", 1.75, (1.8, 0.85, 0.9), name="Sofa", description="Linen sofa.")
    b.add("heater", "heater", (0.75, 0.0), (0.6, 0.65, 0.25), yaw=math.pi / 2, name="Oil-filled heater",
          params={"type": "oil radiator"}, description="Portable oil-filled electric heater on castors, by the sofa.")
    b.against("tv_unit", "tv_stand", "wall_-x", 1.75, (1.6, 0.5, 0.45), name="TV unit",
              description="Low oak TV unit.")
    b.on("tv", "tv", "tv_unit", (0.05, 0.0), (1.2, 0.7, 0.08), name="Television",
         description="Flat-screen television.")
    key = {"pieces": {
        "door": door_needs(), "window": _window(),
        "sofa": _moves("a sofa", "heavy", [_need("get_in", side="front", posture="seated")]),
        "heater": _moves(needs=[_need("heat", side="all", why="it gets hot enough to scorch fabric")]),
        "tv_unit": _moves(), "tv": _moves(),
    }}
    return EvalRoom("heater_close", b, key, "An electric heater stands a hand's width from the sofa.",
                    ["zone:heater"], ("heater", "sofa"))


def ac_blocked() -> EvalRoom:
    b = SceneBuilder(width=4.2, depth=3.6, kind="living room")
    b.door("door", "wall_+z", 3.2, 4.0)
    b.window("window", "wall_-z", 1.6, 2.6, 0.9, 2.1)
    b.against("ac", "ac_unit", "wall_-x", 1.8, (0.45, 0.75, 0.38), name="Portable air conditioner",
              params={"mount": "floor"},
              description="White portable air conditioner on the floor, its vents facing into the room.")
    b.add("sofa", "sofa", (-1.08, 0.0), (2.0, 0.85, 0.9), yaw=math.pi / 2, name="Sofa",
          description="Brown leather sofa, its back to the air conditioner.")
    b.against("tv_unit", "tv_stand", "wall_+x", 1.8, (1.6, 0.5, 0.45), name="TV unit", description="TV unit.")
    key = {"pieces": {
        "door": door_needs(), "window": _window(),
        "ac": _moves("it vents out of the window", "heavy", [_need("air", side="front", why="it blows into the room")]),
        "sofa": _moves("a sofa", "heavy", [_need("get_in", side="front", posture="seated")]),
        "tv_unit": _moves(),
    }}
    return EvalRoom("ac_blocked", b, key, "The back of the sofa is right up against the air conditioner's vents.",
                    ["zone:ac"], ("ac", "sofa"))


def switch_hidden() -> EvalRoom:
    b = SceneBuilder(depth=3.6, kind="bedroom")
    b.door("door", "wall_+x", 0.3, 1.2)
    b.window("window", "wall_-x", 1.3, 2.3, 0.9, 2.1)
    _bed(b)
    b.on_wall("switches", "switch_panel", "wall_+z", 2.4, 1.1, (0.3, 0.2, 0.02), name="Light switches",
              description="Board of light switches and two sockets.")
    b.against("cabinet", "cabinet", "wall_+z", 2.4, (1.0, 1.8, 0.45), name="Tall cabinet", params={"doors": "2"},
              description="Tall white storage cabinet.")
    key = {"pieces": {
        "door": door_needs(), "window": _window(), "bed": BED_KEY,
        "switches": _moves("wired in", "fixed", [_need("reach", why="the room's lights are switched here")]),
        "cabinet": _moves("full", "heavy", [_need("open", side="front", mechanism="hinged", leaves=2)]),
    }}
    return EvalRoom("switch_hidden", b, key, "A tall cabinet stands in front of the room's light switches.",
                    ["covered:switches|zone:switches|reach:switches|unseen:switches"], ("switches", "cabinet"))


def mirror_hidden() -> EvalRoom:
    b = SceneBuilder(depth=3.6, kind="bedroom")
    b.door("door", "wall_+x", 0.3, 1.2)
    b.window("window", "wall_-x", 1.3, 2.3, 0.9, 2.1)
    _bed(b)
    b.on_wall("mirror", "mirror", "wall_+z", 1.0, 0.6, (0.6, 1.4, 0.03), name="Full-length mirror",
              description="Tall mirror in a thin black frame.")
    b.against("wardrobe", "wardrobe", "wall_+z", 1.0, (1.2, 2.0, 0.6), gap=0.04, name="Wardrobe",
              params={"doors": "2"}, description="Tall wardrobe with two doors, standing in front of the mirror.")
    key = {"pieces": {
        "door": door_needs(), "window": _window(), "bed": BED_KEY,
        "mirror": _moves("hung on the wall", "fixed", [_need("see", side="front", posture="standing",
                                                              why="used to dress")]),
        "wardrobe": _moves("full", "heavy", [_need("open", side="front", mechanism="hinged", leaves=2)]),
    }}
    return EvalRoom("mirror_hidden", b, key, "A wardrobe stands right in front of the full-length mirror.",
                    ["unseen:mirror|zone:mirror|covered:mirror"], ("mirror", "wardrobe"))


def sofa_table_tight() -> EvalRoom:
    b = SceneBuilder(width=4.5, depth=3.8, kind="living room")
    b.door("door", "wall_+x", 0.3, 1.2)
    b.window("window", "wall_-x", 1.2, 2.6, 0.8, 2.1)
    b.against("sofa", "sofa", "wall_-z", 2.25, (1.7, 0.85, 0.9), name="Two-seat sofa",
              description="Grey two-seat sofa.")
    b.add("coffee", "coffee_table", (0.0, -0.54), (1.2, 0.42, 0.6), name="Coffee table",
          description="Long glass-topped coffee table pushed up close to the sofa.")
    b.against("tv_unit", "tv_stand", "wall_+z", 2.25, (1.8, 0.5, 0.45), name="TV unit", description="TV unit.")
    b.on("tv", "tv", "tv_unit", (0.0, 0.05), (1.4, 0.8, 0.08), name="Television", description="Large television.")
    key = {"pieces": {
        "door": door_needs(), "window": _window(),
        "sofa": _moves("a big sofa", "heavy", [_need("get_in", side="front", posture="seated",
                                                      why="you sit down and stand up in front of it")]),
        "coffee": _moves(), "tv_unit": _moves(), "tv": _moves(),
    }}
    return EvalRoom("sofa_table_tight", b, key,
                    "The coffee table is pushed so close to the two-seat sofa that there's no room for knees on either seat.",
                    ["zone:sofa:get_in|path:sofa:get_in|zone:coffee"], ("sofa", "coffee"))


def good_bedroom() -> EvalRoom:
    b = SceneBuilder(depth=3.6, kind="bedroom")
    b.door("door", "wall_+x", 0.3, 1.2)
    b.window("window", "wall_-x", 1.3, 2.3, 0.9, 2.1)
    _bed(b)
    b.against("bedside", "side_table", "wall_-z", 1.3, (0.45, 0.55, 0.4), name="Bedside table",
              description="Small white bedside table.")
    b.against("bedside_2", "side_table", "wall_-z", 3.45, (0.45, 0.55, 0.4), name="Bedside table",
              description="Matching white bedside table.")
    b.on("lamp", "table_lamp", "bedside", (0.0, 0.0), (0.25, 0.45, 0.25), name="Bedside lamp",
         description="Table lamp with a linen shade.")
    b.against("dresser", "dresser", "wall_+z", 1.0, (1.0, 0.8, 0.45), name="Chest of drawers",
              params={"drawers": "6"}, description="Oak chest of six drawers.")
    key = {"pieces": {
        "door": door_needs(), "window": _window(), "bed": BED_KEY,
        "bedside": _moves(with_=[{"piece": "bed", "how": "beside", "strength": "soft", "why": "by the pillow"}]),
        "bedside_2": _moves(with_=[{"piece": "bed", "how": "beside", "strength": "soft", "why": "by the pillow"}]),
        "lamp": _moves(),
        "dresser": _moves("full", "heavy", [_need("open", side="front", mechanism="drawers"),
                                            _need("use", side="front", posture="standing")]),
    }}
    return EvalRoom("good_bedroom", b, key, "Nothing is planted: this bedroom works as it is.", [])


def box_room() -> EvalRoom:
    b = SceneBuilder(width=2.4, depth=2.6, kind="small bedroom")
    b.door("door", "wall_+z", 1.5, 2.3)
    b.window("window", "wall_+x", 0.8, 1.8, 0.9, 2.0)
    b.against("bed", "bed", "wall_-z", 1.94, (0.9, 0.45, 2.0), name="Single bed",
              description="Single bed with a white metal frame.")
    b.against("desk", "desk", "wall_+x", 1.3, (0.9, 0.75, 0.5), name="Small desk",
              description="Small white desk under the window.")
    b.add("stool", "stool", (0.505, 0.0), (0.35, 0.45, 0.35), name="Stool", description="Wooden stool at the desk.")
    key = {"pieces": {
        "door": door_needs(), "window": _window(),
        "bed": _moves("a single bed", "heavy", [_need("get_in", side="right", posture="lying")]),
        "desk": _moves(needs=[_need("use", "soft", side="front", posture="seated")]),
        "stool": _moves(with_=[{"piece": "desk", "how": "at", "strength": "soft", "why": "its seat"}]),
    }, "preferences": [{"pref": "task_light", "piece": "desk", "task": "work", "viewer": "facing_piece",
                        "weight": "medium", "why": "worked at"}]}
    # Not "nothing could be better": the first runs found a small slide of the desk
    # that takes the window off its front, and judged against "nothing is better"
    # both models were marked down for offering it.
    return EvalRoom("box_room", b, key,
                    "Nothing serious is planted: a small room that works. Its small desk faces the window, "
                    "so a designer may slide it a little to take the glare off, or leave it.", [])


ROOMS = [door_blocked, glare_desk, bed_no_way_in, wardrobe_blocked, window_covered, chair_cramped,
         heater_close, ac_blocked, switch_hidden, mirror_hidden, sofa_table_tight, good_bedroom, box_room]


def all_rooms() -> list[EvalRoom]:
    return [make() for make in ROOMS]


def matches(expect: str, keys: list[str]) -> bool:
    """Whether any finding key contains one of the expectation's alternatives."""
    return any(alt in k for alt in expect.split("|") for k in keys)
