"""Every perception module the service imports must reach the image.

The Dockerfile enumerates modules one COPY line at a time rather than
copying the directory, so adding a module to the service is two edits and
the second one is easy to forget. When it is forgotten the failure is
expensive and late: the module is in the repo, in the build context and in
the build's own source tarball, so every local test passes and every
offline probe runs — and the first thing that notices is a Cloud Run
request, which dies with ModuleNotFoundError after paying for a GPU cold
start and a model load.

That is not hypothetical. `mask_refine.py` shipped without its COPY line
(decision 0211), which made the deployed `/process` raise for EVERY scene —
the import at the top of `_reconstruct_one_object` is unconditional, so the
flag being off did not protect it. It was found by a 0%-traffic candidate,
which is exactly the discipline decision 0142 asks for, one deploy short of
production.

Consumers: CI, and anyone adding a module under services/perception-obj/.
"""
from __future__ import annotations

import re
from pathlib import Path

SERVICE = Path(__file__).resolve().parents[1]
DOCKERFILE = SERVICE / "Dockerfile"

_COPY = re.compile(
    r"^COPY\s+services/perception-obj/([A-Za-z0-9_]+\.py)\s", re.MULTILINE
)


def _copied() -> set[str]:
    return set(_COPY.findall(DOCKERFILE.read_text()))


def _modules() -> set[str]:
    return {p.name for p in SERVICE.glob("*.py")}


def test_every_module_has_a_copy_line():
    missing = _modules() - _copied()
    assert not missing, (
        f"in the repo but never copied into the image: {sorted(missing)} — "
        "add a COPY line to services/perception-obj/Dockerfile"
    )


def test_no_copy_line_names_a_module_that_is_gone():
    """The other direction: a COPY of a deleted file fails the build
    outright, which is loud, but it also means this list is a live
    inventory rather than an append-only log."""
    stale = _copied() - _modules()
    assert not stale, (
        f"Dockerfile copies files that no longer exist: {sorted(stale)}"
    )


def test_mask_refine_specifically(  ):
    """The one that was missing. Pinned by name so the regression cannot
    come back quietly under a passing generic test."""
    assert "mask_refine.py" in _copied()
