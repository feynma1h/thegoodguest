"""The demo room, when this machine has it.

The repository holds no room data, so the demo capture's scene and its cached
rules-pass answer live under the gitignored `outputs/guide/8cca44d4/`. Tests
that use them skip when they are absent.

Read by: test_analyzer.py, test_engine.py, test_motion.py.
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
DEMO = REPO / "outputs" / "guide" / "8cca44d4"


def demo_room():
    """(room, needs) for the demo room, or skip."""
    scene = DEMO / "scene.json"
    if not scene.exists() or not (DEMO / "llm" / "cache").exists():
        pytest.skip("the demo room is not on this machine")
    from thegoodguest_room_guide.gateway import Gateway
    from thegoodguest_room_guide.model import load_room
    from thegoodguest_room_guide.rules_pass import run_rules_pass
    room = load_room(scene, DEMO / "solids.json")
    try:
        needs = run_rules_pass(room, Gateway(DEMO / "llm", mode="replay"))
    except KeyError:
        pytest.skip("the demo room's rules pass is not cached for this scene")
    return room, needs
