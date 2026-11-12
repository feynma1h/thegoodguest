"""The demo room, when this machine has it.

The repository holds no room data, so the demo capture's scene and its cached
rules-pass answers live under the gitignored `outputs/guide/8cca44d4/`. Tests
that use them skip when they are absent.

The tests read the newest answer the rules pass gave for the room, whichever
prompt it answered: they check the engine and the analyzer on a real scan, not
the prompt, so a prompt change must not quietly skip them.

Read by: test_analyzer.py, test_engine.py, test_motion.py.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
DEMO = REPO / "outputs" / "guide" / "8cca44d4"


def _version(doc: dict) -> int:
    tail = str(doc.get("prompt_version", "")).rsplit("/", 1)[-1]
    return int(tail) if tail.isdigit() else -1


def demo_room():
    """(room, needs) for the demo room, or skip."""
    scene = DEMO / "scene.json"
    if not scene.exists():
        pytest.skip("the demo room is not on this machine")
    from thegoodguest_room_guide.model import load_room
    from thegoodguest_room_guide.needs import NeedsError, parse_needs
    from thegoodguest_room_guide.rules_pass import settle_bonds
    room = load_room(scene, DEMO / "solids.json")
    # The live runs' answers first, then the ones written offline; the newest prompt first.
    for llm in (DEMO / "live" / "llm", DEMO / "llm"):
        docs = [json.loads(p.read_text()) for p in sorted((llm / "cache").glob("*.json"))]
        for doc in sorted((d for d in docs if d.get("stage") == "rules"), key=_version, reverse=True):
            try:
                return room, settle_bonds(room, parse_needs(room, doc["response"]))
            except NeedsError:
                continue
    pytest.skip("no rules-pass answer is cached for the demo room")
