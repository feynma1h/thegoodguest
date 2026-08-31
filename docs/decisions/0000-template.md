# NNNN — <short slug>

**Date:** YYYY-MM-DD
**Status:** <one value from the closed set below>

## Context

What was the situation? What problem were we trying to solve? Two or three sentences.

## What we tried

The path or paths that were explored. If multiple, list them. Be concrete — file names, parameters, what was observed.

## What we chose

The path that was taken, or the path that was abandoned.

## Why

The reasoning. This is the most important section. Future-you reads this to understand whether the reasoning still holds.

## What would change this decision

If X were true, we'd revisit. (e.g. "if π³ ships with a working metric-scale recovery pipeline, the manual scale-calibration knobs can go.")

---

## The status vocabulary

**Closed set.** A status must BEGIN with one of these five, optionally followed
by ` — <detail>`. `tools/gen_decision_index.py --check` fails on anything else.
The detail is free text and is where dates, revisions and measurements go.

| value | means | how to read the note |
|---|---|---|
| `Decided` | The decision governs code that ships today. | Read it before changing that code. |
| `Spent` | It was carried out; the choice it describes no longer exists. | Nothing to comply with. Kept for the source comments that cite it. |
| `Superseded by NNNN` | A later note replaced it. | Read NNNN instead. This one is kept for what it measured. |
| `Amended by NNNN` | A later note corrected part of it; the rest stands. | Read both. The amendment names which part. |
| `Refuted` | A measured negative — the approach was tried and does not work. | Nothing to comply with. Read it before proposing the thing again. |

`Spent` and `Refuted` both mean *this note is not asking anything of you*. That
distinction is the point of the vocabulary: most of the tree is `Decided`, and a
reader should be able to tell in one line whether a note constrains them.

## Numbering

Pick the number by unioning `git ls-tree main --name-only docs/decisions/` with
every unmerged branch — `main` alone is not enough, and a bare `ls` reads a
working tree that may be behind. Concurrent lanes have collided on this five
times; the repair is in the git history for 0270–0274.

Never reuse a number, and never renumber a note that is cited from source
without updating the citation in the same commit.
