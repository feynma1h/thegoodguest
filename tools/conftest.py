"""Path setup for tools/ tests.

Adds tools/, api-core, and schemas to sys.path so that test files can import
upload_test_bundle, smoke_test_e2e, and roomstudio_api_core without
installing packages.
"""

import sys
from pathlib import Path

_tools_dir = Path(__file__).resolve().parent
_repo_root = _tools_dir.parent

for _p in (
    str(_tools_dir),
    str(_repo_root / "packages/api-core"),
    str(_repo_root / "packages/schemas"),
):
    if _p not in sys.path:
        sys.path.insert(0, _p)
