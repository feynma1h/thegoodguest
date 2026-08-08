"""Rewrite commit SHAs quoted in tracked documentation after a history rewrite.

WHY: this repo's documentation is unusually SHA-dense. CLAUDE.md and
`docs/decisions/*.md` cite specific commits constantly — "the fix landed in
`2e064a6`", "merged ff to main, `7a476d5`" — because that is how the project
records what happened. A `git filter-repo` run changes every commit hash, and
without this the entire written record silently points at commits that no
longer exist. That would be a worse outcome than the problem the rewrite was
run to solve.

HOW: `git filter-repo` writes `.git/filter-repo/commit-map`, two columns of
`<old-sha> <new-sha>`. This builds a prefix index over the old hashes and
rewrites any 7-to-40 character hex token in the target files that resolves to
exactly one of them, PRESERVING THE ORIGINAL ABBREVIATION LENGTH so a 7-char
citation stays 7 chars and the prose keeps its shape.

What it deliberately leaves alone: hex tokens that do not resolve to a mapped
commit. The docs are full of other hex — sha256 fixture pins, colour values
like `#c8c1b7`, appIds — and those must not be touched. Anything unresolved is
reported rather than guessed at.

Deletions map to all-zeros in filter-repo's output; a doc citing a commit whose
content was entirely removed would resolve to zeros, so those are reported and
skipped rather than written.

Usage (from the repo root, immediately after filter-repo):

    python tools/remap_doc_shas.py --dry-run     # report only
    python tools/remap_doc_shas.py               # rewrite in place

Written for decision 0101. Re-usable for any future rewrite; there is nothing
photo-specific in it.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

HEX = re.compile(r"\b[0-9a-f]{7,40}\b")
ZERO = "0" * 40
DEFAULT_GLOBS = ("CLAUDE.md", "docs/**/*.md", "README.md", "infra/**/*.md")


def load_map(path: Path) -> dict[str, str]:
    """old-sha -> new-sha, skipping entries whose new side is a deletion."""
    out: dict[str, str] = {}
    for line in path.read_text().splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1] != ZERO:
            out[parts[0]] = parts[1]
    return out


def resolve(token: str, commit_map: dict[str, str]) -> str | None:
    """New SHA for an abbreviated old SHA, or None if absent/ambiguous."""
    if token in commit_map:
        return commit_map[token]
    hits = [new for old, new in commit_map.items() if old.startswith(token)]
    if len(hits) == 1:
        return hits[0]
    return None  # unknown, or ambiguous prefix — never guess


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--commit-map", type=Path,
                    default=Path(".git/filter-repo/commit-map"))
    ap.add_argument("--glob", action="append", default=[],
                    help="file glob to rewrite (repeatable; defaults cover the docs)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    if not args.commit_map.exists():
        print(f"no commit-map at {args.commit_map} — run filter-repo first", file=sys.stderr)
        return 2
    commit_map = load_map(args.commit_map)
    print(f"commit-map: {len(commit_map)} usable mappings")

    files: list[Path] = []
    for pattern in (args.glob or DEFAULT_GLOBS):
        files.extend(p for p in Path().glob(pattern) if p.is_file())

    total_rewritten = total_unresolved = 0
    unresolved_samples: set[str] = set()

    for path in sorted(set(files)):
        text = path.read_text()
        rewritten = unresolved = 0

        def sub(match: re.Match[str]) -> str:
            nonlocal rewritten, unresolved
            token = match.group(0)
            new = resolve(token, commit_map)
            if new is None:
                # Only count tokens that LOOK like citations (short hashes);
                # long hex is almost always a fixture pin, not a commit.
                if len(token) <= 12:
                    unresolved += 1
                    unresolved_samples.add(token)
                return token
            rewritten += 1
            return new[: len(token)]  # keep the author's abbreviation length

        new_text = HEX.sub(sub, text)
        total_rewritten += rewritten
        total_unresolved += unresolved
        if rewritten:
            print(f"  {path}: {rewritten} rewritten"
                  + (f", {unresolved} unresolved" if unresolved else ""))
            if not args.dry_run:
                path.write_text(new_text)

    print(f"\n{'WOULD REWRITE' if args.dry_run else 'REWROTE'} "
          f"{total_rewritten} SHA citations across {len(set(files))} files")
    if total_unresolved:
        sample = ", ".join(sorted(unresolved_samples)[:8])
        print(f"{total_unresolved} short hex tokens did not resolve and were left "
              f"untouched (expected: colour values, ids, non-commit hex). e.g. {sample}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
