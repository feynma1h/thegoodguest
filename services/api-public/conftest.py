"""Path setup and server module pre-loading for services/api-public tests.

Background: pytest eagerly loads ALL conftest.py files across all testpaths
before importing any test module.  The conftest loading order depends on the
pytest invocation directory:

  • From repo root: api-internal conftest loads first (collection order),
    then api-public conftest — leaving api-public's server as
    sys.modules['server'] at test-module import time.
  • From services/api-public/: api-public conftest loads at startup
    (invdir ancestor), then api-internal conftest loads during collection —
    leaving api-internal's server as sys.modules['server'].

Both orderings bind the wrong server to at least one service's test modules.
The autouse scope="module" fixture repairs those bindings before tests run.

auth.py is pre-loaded before server.py because server.py imports from auth
at module level; without this, the ``from auth import ...`` in server.py
would do a fresh sys.path search rather than hitting a cached module.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

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


# Load auth before server — server.py imports from auth at module level.
_load_module("auth", _svc_dir / "auth.py")
# This is the last server load in conftest ordering, so api-public's server
# ends up as sys.modules['server'] when test modules are imported.
_load_module("server", _svc_dir / "server.py")
_API_PUBLIC_SERVER = sys.modules["server"]
sys.modules["_api_public.server"] = _API_PUBLIC_SERVER


@pytest.fixture(autouse=True, scope="module")
def _fix_api_public_server(request):
    """Repair wrongly-bound server references in api-public test modules.

    Conftest loading order depends on the pytest invocation directory.
    When pytest is invoked from services/api-public/, api-public conftest
    is loaded at startup (invdir ancestry), then api-internal conftest
    loads during collection — leaving api-internal's server as
    sys.modules['server'] when test modules are imported.  In that case,
    api-public test files that do ``import server`` and
    ``from server import X`` bind to api-internal's module and functions.

    This fixture fires before the first test in each api-public module and
    repairs those bindings to api-public's server.
    """
    test_mod = request.module
    correct = _API_PUBLIC_SERVER
    wrong = sys.modules.get("server")  # may be api-internal's server

    # Repair the `server` name itself.
    if getattr(test_mod, "server", None) is not correct:
        test_mod.server = correct

    # Repair names imported directly from the wrong server
    # (e.g. ``from server import _check_production_env, _PRODUCTION_REQUIRED_VARS``).
    if wrong is not None and wrong is not correct:
        for name in list(vars(test_mod).keys()):
            val = getattr(test_mod, name)
            if val is not correct and hasattr(wrong, name) and val is getattr(wrong, name):
                correct_val = getattr(correct, name, None)
                if correct_val is not None:
                    setattr(test_mod, name, correct_val)

    yield
