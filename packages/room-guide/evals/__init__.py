"""The room guide's eval: synthetic rooms with one planted problem each, run live.

  rooms.py   the rooms, each with its planted problem, the finding that problem
             should raise, and an answer key (a needs file a careful designer
             would write) that proves the problem can be found at all
  run.py     runs the rules pass and three guide turns on every room, on one
             model, and records what was found, said, offered, flagged and spent
  judge.py   compares two models' answers room by room, both ways round
  compare.py puts two runs and their judges side by side, as a table

The rooms are built from numbers, like the tests' rooms: the repository holds
no room data. Their furniture names and descriptions read like the diorama's
inventory, so the rules pass has the same kind of material it gets from a scan.

Read by: a developer measuring a prompt or model change; tests/test_evals.py.
"""

import sys
from pathlib import Path

_tests = str(Path(__file__).resolve().parents[1] / "tests")
if _tests not in sys.path:
    sys.path.insert(0, _tests)
