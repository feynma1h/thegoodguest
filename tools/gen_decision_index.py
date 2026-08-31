#!/usr/bin/env python3
"""Generate docs/decisions/README.md, and check the tree's invariants.

`docs/decisions/` holds ~280 notes. The index exists so a reader can see, in
one screen, which of them actually constrain them -- most do not. It is
GENERATED rather than hand-maintained, because a hand-maintained index of 280
rows goes stale the first week and then misleads.

Run with no arguments to rewrite the index. Run with --check to verify without
writing: it exits non-zero on a duplicate number, a status outside the closed
vocabulary, a dangling link, or an index that is out of date. That is what
makes the vocabulary closed rather than aspirational.

Read by: anyone opening docs/decisions/, and by whoever adds a note (the
numbering rule and the vocabulary both live in 0000-template.md).
"""

from __future__ import annotations

import argparse
import collections
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
DECISIONS = REPO / "docs" / "decisions"
INDEX = DECISIONS / "README.md"
TEMPLATE = "0000-template.md"

# The closed set. A status must BEGIN with one of these. Anything after is free
# text and is where dates, revisions and measurements go.
STATUS = re.compile(
    r"^(Decided|Spent|Refuted|Superseded by 0\d{3}|Amended by (?:0\d{3}|measurement))\b"
)

# Rendering order: the values that ask something of the reader come last, so
# the terminal ones are what a skim sees first.
ORDER = ["Refuted", "Superseded", "Amended", "Spent", "Decided"]

GLOSS = {
    "Decided": "governs code that ships today",
    "Spent": "carried out; nothing left to comply with",
    "Refuted": "a measured negative -- read before proposing it again",
    "Superseded": "replaced by a later note",
    "Amended": "partly corrected by a later note",
}

Note = collections.namedtuple("Note", "num title date status token path")


def parse(path: pathlib.Path) -> Note:
    text = path.read_text()
    head = text.splitlines()[0].lstrip("# ").strip()
    title = head.split("—", 1)[1].strip() if "—" in head else head
    date = re.search(r"^\*\*Date:\*\* *(.*)$", text, re.M)
    stat = re.search(r"^\*\*Status:\*\* *(.*)$", text, re.M)
    status = stat.group(1).strip() if stat else ""
    m = STATUS.match(status)
    return Note(
        num=path.name[:4],
        title=title,
        date=date.group(1).strip() if date else "",
        status=status,
        token=m.group(1).split()[0] if m else None,
        path=path,
    )


def collect() -> tuple[list[Note], list[str]]:
    """Every note plus every invariant violation found while reading them."""
    problems: list[str] = []
    notes: list[Note] = []

    seen: dict[str, str] = {}
    for path in sorted(DECISIONS.glob("0*.md")):
        if path.name == TEMPLATE:
            continue
        note = parse(path)
        if note.num in seen:
            problems.append(
                f"duplicate number {note.num}: {seen[note.num]} and {path.name}"
            )
        seen[note.num] = path.name
        if note.token is None:
            problems.append(f"{path.name}: status outside the vocabulary: {note.status!r}")
        notes.append(note)

    # A link to a note that does not exist is how a renumber goes wrong.
    for path in sorted(DECISIONS.glob("*.md")):
        for m in re.finditer(r"\]\((0\d{3}-[a-z0-9-]+\.md)\)", path.read_text()):
            if not (DECISIONS / m.group(1)).exists():
                problems.append(f"{path.name}: dangling link -> {m.group(1)}")

    return notes, problems


def render(notes: list[Note]) -> str:
    tally = collections.Counter(n.token for n in notes)
    live = tally.get("Decided", 0)

    out = [
        "# Decision notes",
        "",
        f"{len(notes)} notes. **{live} of them are `Decided`** -- those govern code that",
        "ships today and are the ones worth reading before you change something. The",
        f"other {len(notes) - live} record decisions that were carried out, replaced, or",
        "measured and refuted; they are kept because source comments cite them, not",
        "because they constrain you.",
        "",
        "This file is generated. Run `python3 tools/gen_decision_index.py` after adding",
        "a note, and `--check` to verify the tree (duplicate numbers, statuses outside",
        "the vocabulary, dangling links, a stale index).",
        "",
        "The status vocabulary and the numbering rule live in",
        "[0000-template.md](0000-template.md). Write a new note from that template.",
        "",
        "## What is here",
        "",
        "| status | count | means |",
        "|---|---|---|",
    ]
    for token in ORDER:
        if tally.get(token):
            out.append(f"| `{token}` | {tally[token]} | {GLOSS[token]} |")

    for token in ORDER:
        group = [n for n in notes if n.token == token]
        if not group:
            continue
        out += ["", f"## {token} ({len(group)})", ""]
        if token != "Decided":
            out += [f"*{GLOSS[token].capitalize()}.*", ""]
        out += ["| # | title | status |", "|---|---|---|"]
        for n in sorted(group, key=lambda n: n.num):
            detail = n.status[len(token):].lstrip(" —-")
            # The table cell carries the pointer, not the essay.
            if token in ("Superseded", "Amended"):
                shown = " ".join(n.status.split()[:3])
            else:
                shown = token
            title = n.title.replace("|", "\\|")
            out.append(f"| [{n.num}]({n.path.name}) | {title} | {shown} |")

    out.append("")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="verify without writing; non-zero exit on any violation")
    args = ap.parse_args()

    notes, problems = collect()
    body = render(notes)

    if args.check:
        current = INDEX.read_text() if INDEX.exists() else ""
        if current != body:
            problems.append("docs/decisions/README.md is out of date "
                            "(run tools/gen_decision_index.py)")
        for p in problems:
            print(f"FAIL  {p}", file=sys.stderr)
        if problems:
            return 1
        print(f"ok  {len(notes)} notes, index current")
        return 0

    for p in problems:
        print(f"WARN  {p}", file=sys.stderr)
    INDEX.write_text(body)
    tally = collections.Counter(n.token for n in notes)
    print(f"wrote {INDEX.relative_to(REPO)} -- {len(notes)} notes: "
          + ", ".join(f"{v} {k}" for k, v in tally.most_common()))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
