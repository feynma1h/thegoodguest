# 0076 — RoomPlan co-run spike: verdicts (board 3 → board 7)

**Date:** 2026-07-28
**Status:** Decided

## Context

The board-7 RoomPlan integration design session (Option A: RoomPlan-only,
Pro-only, assembly-first) had two documented risks parked against a hardware
spike: a `sceneDepth`-strip caveat under `RoomCaptureSession(arSession:)`
co-run, and an ARFrame-retention memory issue. The adjudication brief
(decision 0075) added yaw-fidelity and census questions. A throwaway
instrumented app (added in commit `46c2910`, removed from the tree once its
verdicts landed here and in the production co-run) ran four runs on
the iPhone 16 Pro (iOS 26.5.2), sharing an ARSession configured exactly like
production `CaptureManager`; the operator walked the resulting room against
the real furniture. Artifacts + full instrument streams:
`outputs/roomplan-spike/` (gitignored; README.md indexes the runs).

## Verdicts

**Q1 — sceneDepth under co-run: NOT STRIPPED (caveat refuted).** Depth on
9752/9765 frames across the full probe run incl. the entire active scan
(tick ratios 1.000/0.998; the only misses are five isolated single-frame
dropouts of the legal mid-walk class). Mechanism, measured on a virgin
session (rp-first run): **RoomPlan's native config is production's config
field-for-field** — `ARWorldTrackingConfiguration`, `.gravity`, planes h+v,
`.sceneDepth` (fs=8), 1920×1440@60 — plus one private `sceneReconstruction`
rawValue **24** whose mesh never surfaces as ARMeshAnchors. Co-run attach
changes exactly one visible thing (`recon 0→24`). A mid-scan
`arSession.run(mutatedCopy, options: [])` re-run is survivable: the scan
continued through it and built clean. `smoothedSceneDepth` is never enabled
by either side.

**Q2 — production keyframe pattern under co-run: RUNS VERBATIM.**
`ARSession.delegate` was never touched by RoomPlan (a prophylactic
delegate-interposer was built and never engaged). 722 keyframes in the probe
walk (pose-delta 10 cm/5°), JPEG + packed-depth writes 722/722/0 failures,
RGB locked 1920×1440 on every frame, depth rasters 256×192 with
production-scaled intrinsics (fx≈178–180). One continuous world frame: pose
jumps at every phase boundary ≤0.10 m (≤ p95 inter-keyframe distance); 33
plane anchors persisted. **Bundle poses and CapturedRoom coordinates compose
directly.**

**Q3 — ARFrame retention: not a leak — an instant pipeline kill.** Retaining
**10** ARFrames stalled the camera feed to 0 fps within ~1 s at a memory
delta of only ~88 MB (capture-pool starvation, not footprint growth).
Release restored the feed in ~1 s, but VIO tracking died (`relocalizing`)
and never recovered without a `.resetTracking` run. Rule: **copy-out
immediately (the production pattern, measured flat-memory), never retain.**
Two API facts fell out, both reproduced twice: **RoomPlan never resets
tracking** (the host owns tracking hygiene — production's `.resetTracking`
at capture start is load-bearing), and **RoomPlan self-aborts after exactly
10 s of tracking failure** via `didEndWith(error: worldTrackingFailure)`,
still delivering the partial room. Co-run memory: ~+370 MB while scanning a
bedroom, ~905 MB transient during RoomBuilder (1.7 s build), settling
~700 MB — fine for single rooms; re-measure for multi-room.

**Q4 — RoomPlan box fidelity: operator-confirmed 9/9 on position, extent,
and FACING.** All 9 object transforms are upright-by-construction (column-1
≡ (0,1,0), pure yaw). Six yaws sit exactly on the wall axes; the two chairs
are off-axis 2.2° and 40.8° — and the operator confirmed the angled chair
genuinely sits at that angle (yaw follows reality; it is not a hard snap).
Facing ticks (bed front, desk front) all confirmed. Sub-attributes are rich
(StorageType cabinet/shelf; ChairType swivel/dining incl. leg/back detail;
TableShapeType). One category error: the wardrobe shipped as `refrigerator`
at `low` confidence (box correct, label wrong, confidence honest).
Vocabulary bounds confirmed: mirror, textiles, picture frames, and the
wall-mounted AC are undetectable (not in the 16-category vocabulary) — **the
SAM long tail stays necessary**, per the brief's precision note. §6b
verdict: **boxes are viable fusion/yaw anchors for covered categories**
(facing was right here; keep the discrete-candidate appearance scorer as the
guard).

**Q5 — CapturedRoom shell: envelope-true, zero furniture-plane walls,
complete floor.** 13 walls, every one matched to a `wall`/`door`/`window`-
classified anchor plane within 1–25 cm, squared into two perpendicular
families within 0.3°, common 3.05 m top plus four door-height (1.95 m)
segments at a real entry nook. The same session's two `seat`-classified
anchors — the bed rail that becomes a phantom wall in the current pipeline —
were **rejected by RoomPlan**: the adjudication's #2 defect class is dead by
construction, now measured. Floor: one 10-corner polygon, 14.98 m², oriented
4.26×3.97 m — long side within 6 cm of the anchor-envelope ground truth; the
+0.7 m short side is a real alcove the envelope method truncated
(operator-confirmed), vs the current pipeline's 12% floor. Even the aborted
15 s leak-run scan produced an envelope-true partial floor.

**Q6 — census convergence: fast, then refining.** All 9 objects present in
the live room by ~27 s of scanning, stable thereafter; boxes keep refining
(bed until t≈123 s); confidence climbs low→medium→high. API semantics
measured: `didUpdate` carries the FULL room; `didAdd`/`didChange`/
`didRemove` carry DELTA rooms (only changed entities). Object-aware frame
selection has its census DURING the scan; the `didUpdate` stream is the
natural task-#13 live-coverage feed; the instruction stream is sparse and
real (one `moveAwayFromWall` in 2.4 min).

**Q7 — artifacts: both captured from one walk.**
`outputs/roomplan-spike/probe-20260728-143602/`: CapturedRoom JSON ×3
(built/raw/live) + parametric & mesh USDZ + `plane_anchors.json` (incl. the
rejected seat planes) + `events.ndjson` + `keyframes.ndjson` + 722
RGB/depth/confidence keyframes — the first LIDAR_ROOMPLAN prototype data,
all in one world frame.

## What would change this decision

All measurements are one device (iPhone17,1), one OS (26.5.2), one room. An
iOS update changing RoomPlan's session management (config, delegate use,
reset behavior, the 10 s abort) re-opens Q1–Q3 — the spike app is committed
and re-runnable in an afternoon. Multi-room/ARWorldMap flows, older-OS
behavior, category breadth beyond this bedroom, mirror behavior under
RoomPlan, and non-default (4K) video formats under co-run were not probed.
