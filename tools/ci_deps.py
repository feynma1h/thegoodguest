"""Print the third-party dependencies of one or more pyproject.toml files.

WHY THIS EXISTS: CI has to install what the suites need, and the honest source
of that list is each component's own `pyproject.toml`. But the services are
deliberately NOT installable — `services/api-internal` and `services/api-public`
are flat module directories whose pyproject ends with the comment "No packages
to find: flat-module service, not an installable library", so
`pip install -e services/api-internal` fails at package discovery. Their tests
import the modules by path (see the root `conftest.py`), not from site-packages.

That leaves CI two options: hand-copy the dependency lists into the workflow,
where they rot silently the first time someone adds a dep, or read them from
the pyprojects at install time. This script is the second option.

Local sibling packages (`thegoodguest-*`) are dropped from the output: they are
installed separately and editable, because they ARE real packages.

Usage:

    python tools/ci_deps.py services/api-public/pyproject.toml --extra dev
    pip install $(python tools/ci_deps.py services/*/pyproject.toml)

Read by: .github/workflows/python.yml. Nothing else should depend on the exact
output format.
"""

from __future__ import annotations

import argparse
import sys
import tomllib
from pathlib import Path

# Installed separately, editable, by the workflow — they live in this repo.
LOCAL_PREFIX = "thegoodguest"


def deps_for(path: Path, extras: list[str]) -> list[str]:
    """Third-party requirement strings declared by one pyproject."""
    project = tomllib.loads(path.read_text()).get("project", {})
    out = list(project.get("dependencies", []))
    optional = project.get("optional-dependencies", {})
    for extra in extras:
        out.extend(optional.get(extra, []))
    return [d for d in out if not d.strip().lower().startswith(LOCAL_PREFIX)]


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("pyproject", nargs="+", type=Path)
    ap.add_argument(
        "--extra",
        action="append",
        default=[],
        help="optional-dependencies group to include (repeatable, e.g. --extra dev)",
    )
    ap.add_argument(
        "--exclude",
        action="append",
        default=[],
        help="drop requirements whose distribution name matches (repeatable)",
    )
    args = ap.parse_args(argv)

    excluded = {e.lower() for e in args.exclude}
    seen: dict[str, None] = {}
    for path in args.pyproject:
        for dep in deps_for(path, args.extra):
            # Distribution name is everything before the first version/extras
            # marker; good enough for the --exclude filter's purpose.
            name = dep.split("[")[0].split(">")[0].split("<")[0].split("=")[0].strip()
            if name.lower() in excluded:
                continue
            seen.setdefault(dep, None)

    print("\n".join(seen))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
