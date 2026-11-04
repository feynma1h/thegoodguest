# 0330 — the room-look code is an importable package; the tools wrap it

**Date:** 2026-11-05
**Status:** Decided

## Context

The code that measures a room's finish, places furniture twins on boxes and
compares renders with photos (decisions 0310, 0311) lived as scripts in
`tools/`, importing each other by putting the script's own folder on
`sys.path`. A cloud step that runs it after every scan (`services/scene-finish`)
needs the same code, and a copy inside the service would drift from the tools
the operator keeps using.

## What we tried

- Copying the modules into the service. Fast, and the two copies differ by the
  second week.
- Importing `tools/` from the service. Works only with a `sys.path` hack in a
  container, and `tools/` also holds one-off scripts that must not ship.

## What we chose

- `packages/room-look`, import name `thegoodguest_room_look`, a real package
  like `packages/schemas` and `packages/api-core` (own `pyproject.toml`,
  installed editable by CI and by the service image). Depends on
  `thegoodguest-schemas`, numpy and Pillow, and on nothing cloud.
- Thirteen modules moved without being rewritten: `shell_finish`, `shell_atlas`,
  `shell_measure`, `shell_structure`, `finish_hints`, `finish_compare`,
  `furniture_boxes`, `furniture_geometry`, `furniture_clearance`,
  `furniture_placement`, `furniture_models`, `furniture_evidence`,
  `furniture_compare`. Imports between them are relative; the `sys.path` lines
  are gone. Their docstrings, which are the tools' `--help`, are unchanged.
- The six that have a command line (`shell_finish`, `finish_compare`,
  `furniture_models`, `furniture_clearance`, `furniture_evidence`,
  `furniture_compare`) stay in `tools/` as ten-line wrappers that put the repo's
  two packages on the path and call the module's `main`. Every
  `python tools/<name>.py …` in the flow documents still works as written.
- Their tests and the invented example scene moved with them to
  `packages/room-look/tests` and join the root suite, which they were not in
  before.

## Why

One copy of the logic that decides what a room looks like, importable by the
tools and the service, with its tests running in CI. The move is mechanical so
the diff is reviewable as a rename: `shell_finish.py --no-frames` on the hero
room gives byte-identical output before and after.

## What would change this decision

If the service needs a different subset than the tools (say, the measuring half
without Pillow), split the package then. If a second consumer wants a stable
API, the module names above become the contract and need a version.
