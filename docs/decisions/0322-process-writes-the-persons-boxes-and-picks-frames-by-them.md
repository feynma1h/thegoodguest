# 0322 — /process writes the person's boxes and picks frames by them

**Date:** 2026-11-05
**Status:** Decided

## Context

Decision 0320 puts the boxes the person made into the capture bundle, and the
operator decided they are the only object source. The cloud stages that follow
(the finished room's furniture models) need those boxes as a file beside
`manifest.json` and `shell.json`, written by exactly one stage. Separately,
`/process` chose which frames to segment from the RoomPlan object boxes
(census set-cover, decision 0077); with RoomPlan boxes out of play it needs a
new box source or it silently falls back to blind pose spread.

## What we tried

- Letting each later stage re-read the bundle. Every stage would repeat the
  validation and could disagree about which boxes are usable.
- Writing the boxes into `manifest.json`. That file is `/process`'s own
  progress record and is rewritten as the run completes; boxes are an input
  other stages key on and should exist from the start of the run.

## What we chose

- `/process` reads `person_boxes`, writes `scenes/{scene_id}/boxes.json` as one
  blob PUT of canonical bytes (sorted keys, floats to 0.1 mm, ordered by
  creation time then id), and does it before any frame is segmented. Written
  even when empty, so an absent file always means "not yet". Single writer;
  the same bundle always yields the same bytes, so a Cloud Tasks retry is a
  harmless overwrite.
- The cloud applies its own limits (`boxes_json.py`): a box with an empty id, a
  non-finite number, or a side outside 0.05–6 m is dropped, never repaired; a
  repeated id keeps the first; the earliest 40 are kept; the label is capped at
  64 characters (it is advisory text a later prompt may quote). Dropped, not
  rejected: a rejected bundle loses the whole scan. The count dropped is logged.
- Frame selection keeps its census set-cover, now over the person's boxes
  (each given a transform and dimensions in the shape the selector reads); no
  boxes → the original pose-diverse sampler, unchanged.
- File shape: `{"boxes_version": 1, "scene_id", "source": "person", "boxes":
  [{"id", "label", "center", "yaw", "size", "created_at_us"}]}`. `label` is the
  detector's name verbatim; mapping it to a category is the consumer's job.

## Why

One reader of the bundle means one definition of "a usable box". Writing before
segmentation means later stages can start from the file without waiting for the
manifest. Reusing the census over the person's boxes keeps the frames that
actually show the boxed objects, which is the evidence the furniture stage needs.

## What would change this decision

Boxes that can be edited after the scan (a second writer) would need versioning
and a different single-writer story. If a later stage needs the boxes before
`/process` runs, the write moves earlier, to wherever the bundle is first read.
