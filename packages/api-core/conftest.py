"""Path setup for packages/api-core tests.

Adds api-core, schemas, and api-internal to sys.path so that test files can
import thegoodguest_api_core, thegoodguest_schemas, and the api-internal
``validation`` module (used by test_capture_bundle_fixture.py) without
installing packages.
"""

import sys
from pathlib import Path

_pkg_dir = Path(__file__).resolve().parent
_repo_root = _pkg_dir.parents[1]

for _p in (
    str(_pkg_dir),
    str(_repo_root / "packages/schemas"),
    str(_repo_root / "services/api-internal"),  # validation module
):
    if _p not in sys.path:
        sys.path.insert(0, _p)
