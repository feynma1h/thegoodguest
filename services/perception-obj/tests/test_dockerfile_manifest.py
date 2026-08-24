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

The COPY line is only half of it. A module reached by a function-scoped
import is invisible to /health and to every pre-traffic probe, so the
Dockerfile carries a build-time smoke that imports those modules by name;
`mask_refine` was absent from that list too, which is why the guard against
a recurrence did not exist even after the COPY landed. Both halves are
asserted here, so the pairing is checked in CI in milliseconds rather than
only by a build that costs 8-10 minutes and a new image digest.

Consumers: CI, and anyone adding a module under services/perception-obj/.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

SERVICE = Path(__file__).resolve().parents[1]
DOCKERFILE = SERVICE / "Dockerfile"

_COPY = re.compile(
    r"^COPY\s+services/perception-obj/([A-Za-z0-9_]+\.py)\s", re.MULTILINE
)


def _copied() -> set[str]:
    return set(_COPY.findall(DOCKERFILE.read_text()))


_SMOKE = re.compile(r'RUN python -c "import ([^"]+)"')

# uvicorn imports server:app at container start, so a missing server.py
# fails the boot and never reaches a probe to fool. It is the one module
# the smoke deliberately does not name.
EAGERLY_IMPORTED = {"server"}


def _modules() -> set[str]:
    return {p.name for p in SERVICE.glob("*.py")}


def _smoke() -> set[str]:
    """The names on the Dockerfile's deferred-import smoke line."""
    line = _SMOKE.search(DOCKERFILE.read_text())
    assert line, "the deferred-import smoke RUN line is gone from the Dockerfile"
    return set(re.findall(r"[A-Za-z0-9_]+", line.group(1).replace("\\\n", " ")))


def _lazily_imported() -> set[str]:
    """Local modules that some function imports at call time.

    Parsed rather than grepped: an import inside a docstring or a comment
    is not an import, and this list decides what the build must check.
    """
    local = {p.stem for p in SERVICE.glob("*.py")}
    found: set[str] = set()
    for path in SERVICE.glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for inner in ast.walk(node):
                if isinstance(inner, ast.Import):
                    found |= {a.name.split(".")[0] for a in inner.names}
                elif isinstance(inner, ast.ImportFrom) and inner.level == 0:
                    found.add((inner.module or "").split(".")[0])
    return found & local


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


def test_mask_refine_specifically():
    """The one that was missing. Pinned by name so the regression cannot
    come back quietly under a passing generic test."""
    assert "mask_refine.py" in _copied()
    assert "mask_refine" in _smoke()


def test_every_lazily_imported_module_is_on_the_smoke_line():
    """The half the COPY test cannot see.

    A module imported only inside a function is absent from the import
    graph any probe walks, so the Dockerfile's smoke is the only thing
    that can fail the build on its behalf.
    """
    missing = _lazily_imported() - _smoke()
    assert not missing, (
        f"imported inside a function but not on the Dockerfile's "
        f"deferred-import smoke line: {sorted(missing)} — add them, or the "
        "build cannot fail on a missing COPY and the first real "
        "reconstruction will"
    )


def test_the_smoke_line_covers_every_copied_module():
    """Anything shipped into the image is fair game for a later deferred
    import, so the smoke names all of them up front — one exclusion, and
    it is named rather than implied."""
    missing = {m[:-3] for m in _copied()} - _smoke() - EAGERLY_IMPORTED
    assert not missing, (
        f"copied into the image but never imported by the smoke: "
        f"{sorted(missing)}"
    )
