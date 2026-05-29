"""Root conftest: collection hygiene for the roomstudio test suite.

When pytest is invoked from a subdirectory, testpaths in pyproject.toml is
bypassed — pytest treats the invocation directory as the collection root
instead.  The pytest_configure hook below restores full-suite collection so
that ``pytest`` from any working directory yields the same 234 tests.

tools/claim1_test.py is a manual one-off script that happens to match the
*_test.py pattern; it is not part of the automated suite.
"""

from pathlib import Path

_ROOTDIR = Path(__file__).resolve().parent

collect_ignore = [str(_ROOTDIR / "tools" / "claim1_test.py")]

_TESTPATHS = [
    str(_ROOTDIR / "packages/schemas/tests"),
    str(_ROOTDIR / "packages/api-core/tests"),
    str(_ROOTDIR / "services/api-internal/tests"),
    str(_ROOTDIR / "services/api-public/tests"),
    str(_ROOTDIR / "tools/test_upload_test_bundle.py"),
    str(_ROOTDIR / "tools/test_smoke_test_e2e.py"),
]


def pytest_configure(config):
    """Override collection root when pytest is invoked from a subdirectory.

    Without this, testpaths (which is relative to rootdir) is only consulted
    when pytest is invoked with no args from rootdir itself.  From any
    other directory, pytest falls back to the invocation directory — meaning
    only the tests in that subtree are collected.

    We override only when no explicit user-provided test-path args were given
    (i.e. args is empty or contains only the invocation directory).
    """
    invdir = Path(config.invocation_params.dir).resolve()
    rootdir = Path(config.rootdir).resolve()
    if invdir == rootdir:
        return
    # Explicit user args other than the invdir → honour them, don't override.
    args_resolved = {Path(a).resolve() for a in config.args}
    if args_resolved and args_resolved != {invdir}:
        return
    config.args = _TESTPATHS
