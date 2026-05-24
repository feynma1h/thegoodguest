"""pytest configuration for services/perception-obj tests.

Adds services/perception-obj to sys.path so that receiver_repo, oidc,
process_receiver, fcm, and server are importable without installation.
This mirrors the sys.path approach used in services/api/tests/.
"""
import sys
from pathlib import Path

import pytest

_svc_dir = Path(__file__).resolve().parents[1]
if str(_svc_dir) not in sys.path:
    sys.path.insert(0, str(_svc_dir))


@pytest.fixture(autouse=True)
def reset_process_receiver_module_state():
    """Reset process_receiver module-level state between tests.

    _held_scene_ids and _sigterm_repo_ref are process-lifetime singletons in
    production but must be clean between tests to prevent state leakage.
    """
    # Import lazily so test files that don't use process_receiver don't trigger
    # its module-level signal.signal() call unnecessarily.
    try:
        import process_receiver
        process_receiver._held_scene_ids.clear()
        process_receiver._sigterm_repo_ref = None
    except ImportError:
        pass
    yield
    try:
        import process_receiver
        process_receiver._held_scene_ids.clear()
        process_receiver._sigterm_repo_ref = None
    except ImportError:
        pass
