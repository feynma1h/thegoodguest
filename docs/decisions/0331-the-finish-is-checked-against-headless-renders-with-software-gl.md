# 0331 — the finish is checked against headless renders made with software GL

**Date:** 2026-11-05
**Status:** Decided

## Context

Phase 2 has Claude write wall, floor and furniture parameters and then checks
each against the scan's own photos by rendering the room at the photo's camera
pose (0310, 0311). Locally a person does that in a browser pane; in the cloud
nothing has a window or a GPU. A spike (branch claude/phase2-spike-523ed0)
showed the viewer draws headless on a CPU, and left two open items: the first
frames' region-id pass was unstable, and nothing compared the cloud renderer to
anything else.

## What we tried

- Plain headless Chrome: no WebGL at all, the viewer dies on context creation.
- Chrome with ANGLE on SwiftShader (software Vulkan): works. Measured on the
  local reference scan, 800 px wide, 4 frames, 10-core Mac: 1.0-2.6 s per frame
  for the three passes (look, region ids, furniture masks); page ready 20-27 s
  cold, ~10.6 s on a warm browser; a headless GPU run (ANGLE Metal) is 0.09 s a
  frame, ready 3 s.
- Waiting for the harness to appear (the spike): it appears before the
  entrance dolly, the staging transition and the canvas fade are over.

## What we chose

- The cloud renders with SwiftShader. `services/scene-finish/render_driver.mjs`
  serves the flagged static viewer and the room's three documents over
  loopback, opens `/shell-finish.html` at a 320 x 240 viewport (the harness
  resizes the canvas per frame), waits for `window.__shellFinishView.ready`, and
  runs the harness. Chrome stays warm between jobs; the page reloads per job
  because the furniture file is read at load.
- The viewer sets `ready` once a few frames have been drawn with nothing
  moving (entrance, staging rig, canvas fade, reveal). It exists only with the
  finish flag, which only the headless build sets.
- One retry in a fresh Chrome on any failure; a second failure is an error the
  caller turns into a stand-in.

## Why

No GPU instance: the spike measured the render as the cheap part of a loop that
waits on Claude, and a CPU service scales to one worker per piece. `ready`
replaces guessing at timers.

## What we measured about equality

Same four frames of the reference scan, region and furniture-mask means taken
inside the regions both renders draw identically:

- SwiftShader against ANGLE Metal: mean |dL| at most 0.16 L (every region and
  piece; pieces at most 0.11, n = 17). Beauty frames differ by under 1.3 / 255
  per channel on average; the worst frame has 6 % of pixels past 8 levels.
- SwiftShader run to run: byte-identical in 5 of 6 runs of the same frame.
- One exception, and it is not about timing: on one camera pose a large wall
  area flips between two region ids (paint and tile) between SwiftShader and
  Metal, and once between two SwiftShader runs. The flip leaves the look pass
  alone apart from a 5.8 % band. It moved the three-frame median tile delta from
  +10.7 L to +17.2 L. Cause not diagnosed (a depth tie between wall meshes is
  the suspect). Consequence: thresholds on region deltas need at least three
  frames, and the before and after of a gate must come from the same renderer.
- The service image (Linux arm64 Chromium headless shell, SwiftShader) against
  macOS Chrome with SwiftShader, same job: identical on three frames in every
  pass; on the fourth the look differs by 1.05 / 255 mean and the id pass has
  the same paint/tile flip. Which side of the flip a renderer lands on is
  therefore not a property of SwiftShader alone.
- In that container limited to 4 CPUs and 8 GiB (`docker run --cpus=4`), with
  11 furniture twins: page ready 14.9 s, 4.1 s per frame (2.3 times the 10-core
  figure; the design assumed 4-4.5 s), 676 MiB the highest of a 2 s sampling of
  `docker stats`. Without twins: ready 7.7 s, 1.5 s per frame.
- Not compared: the in-app browser pane; an amd64 image (Cloud Run's
  architecture; the check ran on arm64); a real Cloud Run instance.

## What would change this decision

If a 4-vCPU render takes much more than ~2.5x the 10-core time, or the tie
turns out to be a viewer bug that can be fixed, revisit; if cost ever matters
more than simplicity, a GPU service is the alternative the spike priced.
