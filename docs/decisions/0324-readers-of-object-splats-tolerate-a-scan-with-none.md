# 0324 — readers of object splats tolerate a scan with none

**Date:** 2026-11-05
**Status:** Decided

## Context

From decision 0323 a new scan's manifest has `"objects": []` and no splat
files. Every place that read the manifest's objects, or the splats behind them,
had to be found and checked, because a reader that assumed at least one object
would break the room page for every new scan.

## What we tried

Reading each consumer and running the two that carry logic against the new
shape. This note records what was found; the checks that now pin it are in the
tests named below.

## What we found

- **`api-public` assets (`GET /scenes/{id}/assets`)**: signs one URL per placed
  splat; with none it signs nothing and returns 200 with empty `asset_urls`
  (test added). The finish/furniture links are independent of it.
- **`api-public` scene facts, room geometry, design spec, guest tools**: all read
  `manifest.get("objects", [])`. An empty list yields an empty inventory (the
  facts say "nothing was recognized", pinned by an existing test), no solver
  pieces, and an empty design spec (new geometry test). Consequence for the
  product: the guest conversation has no furniture to talk about for a new scan
  until its facts are taken from `boxes.json`. Flagged, not built.
- **Web (`assembleScene`, `RoomStage`, `SplatViewer`)**: reads `objects ?? []`;
  with a shell and no splats the room is "ready" with the shell alone, and with
  neither it is the honest empty room. Not changed here. Two copy decisions for
  the viewer track: the room page's piece count reads 0, and the share card
  (`card/measure.ts`, `pieceCount`) drops its PIECES cell when 0.
- **Landing hero**: uses pre-baked splats under `web/public/hero/`, not a live
  scene; unaffected.
- **`/compress`**: finds no rendered splats and returns a noop; it is no longer
  enqueued (0323), and runs only if re-driven.
- **Retention and deletion**: account deletion removes every blob under
  `scenes/{scene_id}/`, so `boxes.json` goes with the rest. The outputs
  lifecycle rule ages out only `masks.npz`; `boxes.json` is never age-deleted
  (note added to `eventarc_setup.sh`).
- **Tools** (`inspect_splats`, `measure_render_payload`, `make_shell_v3_fixtures`,
  `transcode_scene_splats`): operator utilities for scenes that have splats; they
  tolerate none and are left as they are.
- **Old scans**: untouched. Their manifests keep objects and splats, and every
  reader above still handles them.

## Why

The change is safe because every reader already took "no objects" as a case
(pre-v2 manifests, empty rooms). Pinning two with tests turns "found it
tolerant" into something CI keeps true.

## What would change this decision

If the room page should say something when there are no splats and no twins
(a processing state rather than an empty room), that is the viewer track's call,
and the conversation's facts moving to `boxes.json` is its own decision.
