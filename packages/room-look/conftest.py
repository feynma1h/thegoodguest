"""Path setup for packages/room-look tests.

Adds the package root and the schemas package to sys.path so the tests run
without installing either.
"""

import sys
from pathlib import Path

_pkg_dir = Path(__file__).resolve().parent
_repo_root = _pkg_dir.parents[1]

for _p in (str(_pkg_dir), str(_repo_root / "packages/schemas")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
