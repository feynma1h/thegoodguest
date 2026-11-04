# 0313 — finish and furniture are separate optional files beside the shell

**Date:** 2026-11-05
**Status:** Decided

## Context

A designed finish (decision 0310) and furniture twins (0311, 0312) are things
the room page can draw over the measured shell, but nothing in the pipeline
produces them yet: today they are made offline and previewed locally. The room
page needs a way to receive them that does not disturb a room that has none.
An earlier experiment carried both inside `shell.json` as extra keys, which
rewrites a file the pipeline owns and ties two things with different producers
and lifetimes to one blob.

## What we tried

- Extra keys inside `shell.json`, passed through verbatim by the assets
  response. No API change, but the shell is the pipeline's output: a finish
  producer would have to rewrite it, and a re-run of the shell stage would
  erase them.
- Reading the files from a local server only (the preview page). Fine for the
  loop, no use for the room page.

## What we chose

- `finish.json` and `furniture.json` are separate files beside `shell.json` in
  the scene's folder, each written by whatever produces it.
- `GET /scenes/{id}/assets` adds `finish_url` and `furniture_url`: a signed
  link when the file exists, `null` when it does not. The files are not read by
  the server, add nothing to `asset_urls`, and an existence-check or signing
  failure is a null with a log, never a 502.
- The web app reads them in `lib/shellExtras.ts`, after the room is up, only
  when `NEXT_PUBLIC_SHELL_FINISH=1`; with the flag off no request is made. Each
  is validated against the shell it would dress (a finish for a different wall
  count is refused); twins are drawn only with a finish that fits. Anything
  absent, unreachable or invalid leaves the room drawing exactly as before.
- The room page does not hide the scanned splats when twins are present: that
  is a product decision for when twins are real, not part of the plumbing.

## Why

Separate files keep each producer's output its own, let one exist without the
other, and leave the pipeline's shell untouched. Null-on-any-failure is the
shell's own precedent (0066): an optional extra must never take a room down.
Gating the fetch behind the flag means the default build's network behaviour
is unchanged, which is checkable.

## What would change this decision

If a cloud step writes these files for every scan, the flag goes and the
fetch runs by default. If twins replace scanned objects, that is its own
decision and the splat filtering belongs with it. The bucket must allow the web
origin to GET signed links before this works outside the local preview.
