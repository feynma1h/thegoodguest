# 0340 — the finished room is in the product build behind one runtime switch

**Date:** 2026-11-05
**Status:** Decided

## Context

The designed finish, diorama staging, furniture twins and day/night (0310–0313)
were drawn only when `NEXT_PUBLIC_SHELL_FINISH=1` was baked into a build, so the
product never showed them. The operator wants this to be the real look.

## What we tried

Keeping the build flag and setting it in production. A build flag is invisible in
the code that reads it and cannot be turned off without a rebuild.

## What we chose

One named constant, `ROOM_FINISH_ENABLED` in `lib/shellFinish.ts`, true.
`shellFinishEnabled()` returns it. A scene whose assets link a finish that fits is
drawn finished; a scene without the files makes no request and is built from the
same inputs as before. The developer preview page (`app/shell-finish`) loads
arbitrary files by URL, so it keeps `NEXT_PUBLIC_SHELL_FINISH=1` as its own gate.

## Why

Default on is the decision; a constant is the smallest switch that can still take
the whole path out again.

## What would change this decision

A need to switch it per user or per scene, which would make it a setting.
