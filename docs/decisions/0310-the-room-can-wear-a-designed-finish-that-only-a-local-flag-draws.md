# 0310 — the room can wear a designed finish, drawn only behind a local flag

**Date:** 2026-11-05
**Status:** Decided

## Context

The pipeline's `shell.json` gives the room page flat walls and a flat floor.
A room that looks like the actual room (a tiled band under the paint, no
baseboard, a panelled wood door, stone slabs) reads as far more convincing
than flat polygons, and the scan's own frames contain enough to get close:
colours, the band's top edge, door and window frame colours. They do not
contain tile pitch, slab size, door panels or whether there is a baseboard.

## What we tried

- Baking photos onto the shell. Rejected: pixels of a person's home would reach
  the viewer, and furniture in the frames would be baked in too.
- Measuring everything. Atlases rectified from all frames (median over frames
  removes furniture) support colours and the band's top edge well. Periodic-edge
  detection for tile pitch failed under furniture clutter, and the floor atlas
  is too smeared for slab joints.
- Reading the rest by eye (a person, or a vision model) and handing it over as a
  hints file.

## What we chose

- `tools/shell_finish.py` derives `finish.json` from `shell.json` and the
  frames; `tools/finish_compare.py` renders the viewer from the pose of a real
  frame and measures the colour error per region against the photo.
- The hints are a closed vocabulary validated in code (`tools/finish_hints.py`):
  baseboard yes/no, wainscot height and tile pitch, slab size, door panels,
  window glass, calibration offsets. Every section says `source: measured|review`;
  an unknown key, an out-of-range value or a missing source refuses the whole
  file, listing every problem. Parameters only, never pixels.
- The viewer (`lib/shellFinish.ts`, `components/shellFinishScene.ts`, the
  `/shell-finish` preview page) draws the finish and stages the room as a
  diorama: two walls cut away, a light studio backdrop, fixed corner views at
  24 degrees, opening at the corner nearest the door. `SplatViewer.tsx` has
  hooks for it that do nothing unless `NEXT_PUBLIC_SHELL_FINISH=1` is set when
  the app is built; the finish modules are loaded by dynamic import only then.
- A finish file that does not fit its shell (wrong version, wrong wall count, a
  bad colour) parses to null and the flat shell draws as before.

## Why

Code does the geometry and colour because it is measurable and cannot
hallucinate: the render-vs-photo colour error is a real objective and fell from
10 L to about 2 L in two rounds on the reference scan. A model is useful only
for the structural reading the measurements cannot do, and its claim is
checkable by the same compare loop. Validating the vocabulary in code keeps a
hand edit or a model answer from reaching the renderer unchecked.

## What would change this decision

If a cloud step produces `finish.json` for every scan, the flag goes and the
room page draws it by default (decision 0313 carries the plumbing). If the
compare loop shows the by-eye hints do not improve the render, the hints go.
