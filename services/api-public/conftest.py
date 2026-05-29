"""Path setup and public_server module pre-loading for services/api-public tests.

Registers public_server (and auth) in sys.modules so test files can do
``import public_server`` regardless of pytest invocation directory.
No collision with api-internal's ingest_server — distinct module names mean
conftest load order is irrelevant.

auth.py is pre-loaded before public_server.py because public_server.py imports
from auth at module level; without this, the ``from auth import ...`` in
public_server.py would do a fresh sys.path search rather than hitting a cached
module.
"""

import importlib.util
import sys
from pathlib import Path

_svc_dir = Path(__file__).resolve().parent
_repo_root = _svc_dir.parents[1]

for _p in (
    str(_svc_dir),
    str(_repo_root / "packages/api-core"),
    str(_repo_root / "packages/schemas"),
):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _load_module(name: str, path: Path) -> None:
    """Load a module from an explicit path and register it in sys.modules."""
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)


# Load auth before public_server — public_server.py imports from auth at module level.
_load_module("auth", _svc_dir / "auth.py")
_load_module("public_server", _svc_dir / "public_server.py")
