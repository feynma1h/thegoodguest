"""The rulebook: the sizes behind each need, and where each number comes from.

Keyed by need type and posture, never by furniture: the room a person needs to
push a chair back is the same whatever the chair is pushed back from. Each entry
carries the sentence the guide may say for it, verbatim.

`kind` decides how the guide may present it:
  - "standard": a published figure (an accessibility code, a fire-safety
    rule). The guide may call it a standard.
  - "guidance": what planning guides commonly give. The guide says
    "guides usually allow ...", never "the standard is ...".
  - "planning": this product's own planning value, used where no published
    figure was found. The guide says it as its own advice ("I keep about ...").

Sources were checked on 2026-11-07. Several guidance figures come from
furniture and planning guides that disagree at the edges, which is why the
hard value is the low end of what they give and the comfortable value their
usual figure.

Read by: needs.py (zone sizes), assess.py, analyzer.py (findings), the
guide's brief.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Size:
    hard: float          # below this the need is broken
    comfortable: float   # at or above this it is fully met
    say: str             # the guide's words for it, verbatim
    source: str
    kind: str            # "standard" | "guidance" | "planning"


SIZES: dict[tuple[str, str | None], Size] = {
    ("use", "standing"): Size(
        0.6, 0.9,
        "guides usually allow about 0.9 m in front of drawers or a wardrobe, and 0.6 m at the least",
        "Residential planning guides: 36 in to stand at drawers or a closet; 18-24 in to pull drawers out",
        "guidance"),
    ("use", "seated"): Size(
        0.75, 0.9,
        "guides usually ask for 0.75 to 0.9 m behind a desk, to push the chair back and stand up",
        "Home-office planning guides: 30 in minimum, 36 in common, behind a desk chair",
        "guidance"),
    ("get_in", "lying"): Size(
        0.6, 0.75,
        "guides usually allow 0.6 to 0.9 m beside a bed, with about 0.75 m comfortable",
        "Bedroom planning guides: 24-36 in each side of a bed, 30 in comfortable",
        "guidance"),
    ("get_in", "seated"): Size(
        0.3, 0.45,
        "people usually keep 35 to 45 cm between a seat and a low table in front of it",
        "Living-room planning guides: 14-18 in from a sofa to a coffee table",
        "guidance"),
    ("pass", None): Size(
        0.6, 0.9,
        "a main walkway is usually given about 0.9 m, and 0.6 m is the narrowest a side path is planned at",
        "ADA 2010 Standards 403.5.1 (36 in clear route); residential guides (24 in minimum path)",
        "standard"),
    ("air", None): Size(
        0.3, 0.6,
        "makers ask that nothing block an air outlet, and I keep about 0.3 m clear in front of one",
        "Manufacturers' installation guidance (no obstacle near the outlet); 0.3 m and 0.6 m are planning values",
        "planning"),
    ("heat", None): Size(
        0.9, 0.9,
        "fire services ask for at least 0.9 m between heating equipment and anything that can burn",
        "NFPA and US Fire Administration heating safety guidance: 3 ft from anything that can burn",
        "standard"),
    ("reach", None): Size(
        1.0, 0.6,
        "a switch or socket wants somewhere to stand within about 0.6 m of it, the deepest reach "
        "accessibility codes allow over a counter",
        "ADA 2010 Standards 308.2.2 (25 in maximum reach depth over an obstruction); 1.0 m is a planning limit",
        "standard"),
    ("see", None): Size(
        3.0, 0.5,
        "something to look at wants a clear spot to stand or sit in front of it, from about 0.5 to 3 m away",
        "Planning values",
        "planning"),
}

# Law 4's "person-sized path": about an adult's shoulder breadth.
PERSON_PATH = 0.5
PERSON_PATH_SAY = "about 0.5 m, the width of one person walking"

# Height of the space a standing person occupies, for keep-clear zones they use.
BODY_TOP = 1.8

# Eye height by posture, for sight lines.
EYE_HEIGHT = {"standing": 1.6, "seated": 1.2, "lying": 0.7}

# How far from a window solids count as standing in its light.
LIGHT_DEPTH = 0.4


def size_for(need: str, posture: str | None = None) -> Size:
    """The size entry for a need, by posture where the need has one."""
    if (need, posture) in SIZES:
        return SIZES[(need, posture)]
    return SIZES[(need, None)]
