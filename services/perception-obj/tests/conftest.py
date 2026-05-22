"""pytest configuration for services/perception-obj tests.

Adds services/perception-obj to sys.path so that receiver_repo, oidc,
process_receiver, fcm, and server are importable without installation.
This mirrors the sys.path approach used in services/api/tests/.
"""
import sys
from pathlib import Path

_svc_dir = Path(__file__).resolve().parents[1]
if str(_svc_dir) not in sys.path:
    sys.path.insert(0, str(_svc_dir))
