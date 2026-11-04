"""The hints a reviewer gives the finish: a closed vocabulary, validated.

`shell_finish.py` measures colours from the scan's frames. A few things the
measurements cannot say (is there a baseboard, how high is the tiled band,
what is the tile pitch, how big are the floor slabs, does the door have
raised panels, what does the window pane show) are read off the atlases and
photos by a person or a vision model and handed over as hints.

A hint is a parameter, never a pixel, and it must be one the renderer knows.
`parse_hints` therefore rejects anything outside the vocabulary below, any
value out of range, and any section that does not say where its values came
from (`source`: "measured" when code derived them, "review" when somebody
looked and decided). The result is the normalised dict `shell_finish.py`
consumes and records in `finish.json`.

    {
      "baseboard": {"source": "review", "present": false},
      "wainscot":  {"source": "review", "height_m": 1.3, "tile_u_m": 0.3,
                    "tile_v_m": 0.6, "joint": "light"},
      "floor":     {"source": "review", "slab_u_m": 0.6, "slab_v_m": 0.6},
      "openings": {
        "door":   {"source": "review", "casing": "frame",
                   "panels": [[0.15, 0.06, 0.85, 0.46]]},
        "window": {"source": "review", "casing": "none", "glass_hex": "#c8d4e0"}
      },
      "calibration": {"source": "measured", "paint": [2.0, 0.0, -1.5],
                      "floor": [-1.0, 0.0, 0.0], "texture_gain": 1.4}
    }

Every section is optional; an absent section means "use the measurement or
the design default". `calibration` is written by `finish_compare.py
calibrate --write`: Lab offsets per region, and a floor texture gain.
"""
from __future__ import annotations

import re
from typing import Any

SOURCES = ("measured", "review")
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
JOINTS = ("light", "dark")
OPENING_KINDS = ("door", "window")
CASINGS = ("frame", "none")  # or a "#rrggbb" casing colour
CALIBRATION_REGIONS = ("paint", "tile", "floor", "door", "glass")

# Section name -> the keys it may carry (besides `source`).
VOCABULARY = {
    "baseboard": {"present", "hex", "height_m"},
    "wainscot": {"height_m", "tile_u_m", "tile_v_m", "joint"},
    "floor": {"slab_u_m", "slab_v_m"},
    "openings": set(OPENING_KINDS),
    "calibration": set(CALIBRATION_REGIONS) | {"texture_gain"},
}
OPENING_KEYS = {"casing", "panels", "glass_hex"}


class HintsError(ValueError):
    """Every problem found in a hints document, one per line."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("invalid finish hints:\n  " + "\n  ".join(problems))


def _number(v: Any, lo: float, hi: float) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and lo <= v <= hi


def _source(sec: dict, where: str, problems: list[str]) -> None:
    if sec.get("source") not in SOURCES:
        problems.append(f"{where}.source must be one of {list(SOURCES)}, got {sec.get('source')!r}")


def _keys(sec: dict, allowed: set[str], where: str, problems: list[str]) -> None:
    for k in sec:
        if k != "source" and k not in allowed:
            problems.append(f"{where}.{k} is not in the vocabulary {sorted(allowed)}")


def _dims(sec: dict, keys: tuple[str, ...], lo: float, hi: float, where: str, problems: list[str]) -> None:
    for k in keys:
        if k in sec and not _number(sec[k], lo, hi):
            problems.append(f"{where}.{k} must be a number in [{lo}, {hi}] metres, got {sec[k]!r}")
    if ("tile_u_m" in keys or "slab_u_m" in keys) and (keys[0] in sec) != (keys[1] in sec):
        problems.append(f"{where}: give both {keys[0]} and {keys[1]}, or neither")


def _panels_ok(panels: Any) -> bool:
    if not isinstance(panels, list) or not 1 <= len(panels) <= 8:
        return False
    for p in panels:
        if not (isinstance(p, list) and len(p) == 4 and all(_number(x, 0, 1) for x in p)):
            return False
        if not (p[0] < p[2] and p[1] < p[3]):
            return False
    return True


def parse_hints(raw: Any) -> dict:
    """Validate a hints document and return it normalised. Raises HintsError."""
    if not isinstance(raw, dict):
        raise HintsError(["hints must be a JSON object"])
    problems: list[str] = []
    for name in raw:
        if name not in VOCABULARY:
            problems.append(f"{name} is not a hint section; sections are {sorted(VOCABULARY)}")
    out: dict = {}
    for name, sec in raw.items():
        if name not in VOCABULARY:
            continue
        if not isinstance(sec, dict):
            problems.append(f"{name} must be an object")
            continue
        _keys(sec, VOCABULARY[name], name, problems)
        if name == "openings":
            out[name] = _openings(sec, problems)
            continue
        _source(sec, name, problems)
        if name == "baseboard":
            if not isinstance(sec.get("present"), bool):
                problems.append("baseboard.present must be true or false")
            if "hex" in sec and not (isinstance(sec["hex"], str) and HEX.match(sec["hex"])):
                problems.append(f"baseboard.hex must be #rrggbb, got {sec['hex']!r}")
            _dims(sec, ("height_m",), 0.01, 0.4, name, problems)
        elif name == "wainscot":
            if "height_m" not in sec:
                problems.append("wainscot.height_m is required")
            _dims(sec, ("height_m",), 0.2, 2.5, name, problems)
            _dims(sec, ("tile_u_m", "tile_v_m"), 0.03, 1.5, name, problems)
            if "joint" in sec and sec["joint"] not in JOINTS:
                problems.append(f"wainscot.joint must be one of {list(JOINTS)}, got {sec['joint']!r}")
        elif name == "floor":
            _dims(sec, ("slab_u_m", "slab_v_m"), 0.1, 3.0, name, problems)
        elif name == "calibration":
            if sec.get("source") != "measured":
                problems.append("calibration.source must be 'measured': it is derived by finish_compare.py")
            for region in CALIBRATION_REGIONS:
                v = sec.get(region)
                if v is not None and not (isinstance(v, list) and len(v) == 3 and all(_number(x, -60, 60) for x in v)):
                    problems.append(f"calibration.{region} must be [dL, da, db] with each in [-60, 60], got {v!r}")
            if "texture_gain" in sec and not _number(sec["texture_gain"], 0.1, 8):
                problems.append(f"calibration.texture_gain must be in [0.1, 8], got {sec['texture_gain']!r}")
        out[name] = dict(sec)
    if problems:
        raise HintsError(problems)
    return out


def _openings(sec: dict, problems: list[str]) -> dict:
    out: dict = {}
    for kind, o in sec.items():
        if kind not in OPENING_KINDS:
            continue
        where = f"openings.{kind}"
        if not isinstance(o, dict):
            problems.append(f"{where} must be an object")
            continue
        _keys(o, OPENING_KEYS, where, problems)
        _source(o, where, problems)
        casing = o.get("casing")
        if casing is not None and casing not in CASINGS and not (isinstance(casing, str) and HEX.match(casing)):
            problems.append(f"{where}.casing must be 'frame', 'none' or #rrggbb, got {casing!r}")
        if "panels" in o:
            if kind != "door":
                problems.append(f"{where}.panels only applies to a door")
            elif not _panels_ok(o["panels"]):
                problems.append(f"{where}.panels must be 1-8 [u0, v0, u1, v1] rectangles inside 0..1 with u0<u1, v0<v1")
        if "glass_hex" in o:
            if kind != "window":
                problems.append(f"{where}.glass_hex only applies to a window")
            elif not (isinstance(o["glass_hex"], str) and HEX.match(o["glass_hex"])):
                problems.append(f"{where}.glass_hex must be #rrggbb, got {o['glass_hex']!r}")
        out[kind] = dict(o)
    return out
