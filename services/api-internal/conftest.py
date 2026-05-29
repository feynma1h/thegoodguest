"""Path setup and ingest_server module pre-loading for services/api-internal tests.

Registers ingest_server in sys.modules so test files can do
``import ingest_server`` regardless of pytest invocation directory.
No collision with api-public's public_server — distinct module names mean
conftest load order is irrelevant.
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


_load_module("ingest_server", _svc_dir / "ingest_server.py")
