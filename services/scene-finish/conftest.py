"""Path setup for services/scene-finish tests (flat-module service).

Puts the service directory and the two local packages on sys.path so tests can
``import finish_server`` and ``import render_client`` without installing anything.
"""

import sys
from pathlib import Path

_svc_dir = Path(__file__).resolve().parent
_repo_root = _svc_dir.parents[1]

for _p in (
    str(_svc_dir),
    str(_repo_root / "packages/room-look"),
    str(_repo_root / "packages/schemas"),
):
    if _p not in sys.path:
        sys.path.insert(0, _p)
