"""Path setup for packages/schemas tests.

Adds the schemas package root to sys.path so that test files can do
``from thegoodguest_schemas import ...`` without installing the package.
"""

import sys
from pathlib import Path

_pkg_dir = Path(__file__).resolve().parent
if str(_pkg_dir) not in sys.path:
    sys.path.insert(0, str(_pkg_dir))
