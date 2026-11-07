"""Needs files for the synthetic rooms, written the way the rules pass writes them.

Read by: test_needs.py, test_assess.py, test_analyzer.py, test_engine.py, test_motion.py.
"""
from __future__ import annotations

import copy


def door_needs(swing_hard: bool = True) -> dict:
    return {"moves": "fixed", "why": "part of the wall", "needs": [
        {"need": "open", "side": "front", "mechanism": "hinged", "leaves": 1,
         "strength": "hard" if swing_hard else "soft", "why": "it swings into the room"},
        {"need": "pass", "strength": "hard", "why": "it is the way in"},
    ]}


WINDOW = {"moves": "fixed", "why": "part of the wall",
          "needs": [{"need": "light", "strength": "soft", "why": "the room's daylight"}]}


def bedroom_needs() -> dict:
    return {
        "rules_version": 1,
        "pieces": {
            "door": door_needs(),
            "window": copy.deepcopy(WINDOW),
            "bed": {"moves": "heavy", "why": "a double bed", "needs": [
                {"need": "get_in", "side": "sides", "posture": "lying", "strength": "hard",
                 "why": "two people get in from either side"}]},
            "bedside": {"moves": "yes", "with": [
                {"piece": "bed", "how": "beside", "strength": "soft", "why": "within reach of the pillow"}]},
            "bedside_2": {"moves": "yes", "with": [
                {"piece": "bed", "how": "beside", "strength": "soft", "why": "within reach of the pillow"}]},
            "lamp": {"moves": "yes"},
            "dresser": {"moves": "heavy", "why": "full of clothes", "needs": [
                {"need": "open", "side": "front", "mechanism": "drawers", "strength": "hard",
                 "why": "the drawers pull out"},
                {"need": "use", "side": "front", "posture": "standing", "strength": "hard",
                 "why": "you stand at it to dress"}]},
        },
        "preferences": [
            {"pref": "back_to_wall", "piece": "bed", "weight": "high", "why": "a headboard wants a solid wall"},
        ],
        "questions": [],
    }
