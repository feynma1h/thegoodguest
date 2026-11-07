"""Path setup for packages/room-guide tests.

Adds the package root (for `thegoodguest_room_guide`) and the tests directory
(for the shared synthetic rooms in tests/rooms.py) to sys.path, so the tests
run without installing anything under the suite's importlib import mode.
"""

import sys
from pathlib import Path

_pkg_dir = Path(__file__).resolve().parent

for _p in (str(_pkg_dir), str(_pkg_dir / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
