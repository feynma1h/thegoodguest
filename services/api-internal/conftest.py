"""Path setup and server module pre-loading for services/api-internal tests.

Background: pytest eagerly loads ALL conftest.py files across all testpaths
before importing any test module.  When the full suite runs, api-public
conftest runs right after api-internal conftest — leaving api-public's
server.py as sys.modules['server'] by the time test modules are imported.
This means api-internal test files that do ``import server`` at module level
bind to api-public's server (wrong).

Fix: load api-internal's server under a service-unique key
``_api_internal.server`` so it survives the subsequent replacement.  An
autouse scope="module" fixture then repairs any wrongly-bound ``server``
references in each api-internal test module's globals before the first test
in that module runs — and before the ``client`` fixture creates its
TestClient — so the app under test is always the correct one.
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


# Load under the canonical name (so it's available when only api-internal
# tests run) AND under a service-unique alias so the autouse fixture can
# retrieve it after sys.modules['server'] has been replaced by api-public
# conftest.
_load_module("server", _svc_dir / "server.py")
_API_INTERNAL_SERVER = sys.modules["server"]
sys.modules["_api_internal.server"] = _API_INTERNAL_SERVER


@pytest.fixture(autouse=True, scope="module")
def _fix_api_internal_server(request):
    """Repair wrongly-bound server references in api-internal test modules.

    Runs once per test module, before any fixture in that module (including
    the module-scoped ``client`` fixture).  Rewrites ``server`` in the test
    module's globals to api-internal's server, then repairs any names
    imported directly from server (e.g. ``from server import X``).
    """
    test_mod = request.module
    correct = _API_INTERNAL_SERVER
    wrong = sys.modules.get("server")  # api-public's server by the time tests run

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
