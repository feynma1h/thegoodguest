<!--
docs/briefs/perception-envelope-fix-brief.md — implementation brief for the
perception-obj envelope fix (frame sampling, GPU memory lifecycle, budget
honesty, re-enqueue tool).

Produced by the 2026-07-21 first-real-capture session, which watched scene
25a14caf (126 real keyframes) break the reconstruction envelope live — the
findings behind each item are recorded in CLAUDE.md's envelope bullet and the
first-real-capture bullet. Consumer: the Code session that fixes perception's
envelope. Hand over via a fresh session; the preserved capture at
outputs/real-capture-25a14caf/ (main checkout, gitignored) is the regression
fixture and first live patient.

Delete this file when the fix ships — CLAUDE.md and the fix session's decision
note become the durable record.
-->

# Build brief — perception-obj envelope fix

```
Read CLAUDE.md and .claude/WORKFLOW.md first.

Task:        Make perception-obj survive real captures. Tonight's first real
             capture (scene 25a14caf, 126 keyframes, preserved at
             outputs/real-capture-25a14caf/ in the main checkout) proved the
             pipeline correct but the envelope wrong: (1) the receiver iterates
             EVERY keyframe (~70-130 s each) against a 900 s request budget
             that ALSO contains the ~3.5 min GPU cold start; (2) GPU memory
             climbs monotonically across objects — 22.03 GiB saturated by
             frame 10, then intermittent per-object OOM (suspect: per-object
             results with on-GPU tensors retained in the accumulator for the
             whole run; verify before fixing); (3) when an attempt times out,
             the handler thread keeps computing on the always-on CPU and holds
             the concurrency slot, so Cloud Tasks retries 504 platform-queued
             without ever reaching the app — the 0011/0012 reclaim machinery
             never runs, and a crashed zombie strands the scene in processing.

Constraints: services/perception-obj/ only (+ tools/ for the re-enqueue
             script). No proto/schema change; manifest v2 contract unchanged
             (frames[] provenance simply reflects the sampled subset — record
             the sampling in the manifest, e.g. frames_total vs
             frames_sampled). Do not touch api-*, web/, ios/, packages/.
             The zombie attempt for scene 25a14caf may still be running —
             do NOT deploy mid-session without checking; deploy at the end
             (SIGTERM resets the scene to queued, which the re-enqueue tool
             then re-drives through the fixed revision).

Contract:    (1) Frame sampling: select a bounded, well-spread subset
             (~10-16 frames) before reconstruction — spread by pose diversity
             (translation/yaw spread serves triangulation), not just stride;
             cap total reconstruction work so cold-start + full run fits
             ~11 min worst-case. Fusion is designed for sparse multi-view
             observations; per-frame-uniqueness guards must still hold.
             (2) Memory lifecycle: after each object's reconstruction, move
             everything the later placement/fusion stages need to CPU (or
             serialize), free GPU tensors, and empty the CUDA cache between
             frames; peak VRAM must stay roughly flat across frames. Keep the
             per-object soft-fail exactly as is — it worked.
             (3) Budget honesty: log per-frame and cumulative elapsed against
             the request budget; if the remaining budget can't fit another
             frame, stop sampling early, proceed to placement/fusion with
             what's banked, and finish INSIDE the request — a degraded-but-
             ready scene beats a zombie. (4) tools/reenqueue_scene.py:
             re-create the Cloud Tasks task for an existing scene doc +
             bundle (resets status queued → enqueue), for stranded scenes and
             for re-driving preserved captures; document the stranded-scene
             gap it cures in the docstring (retries that never reach the app
             can't reclaim — decision-note-worthy this session).

Verify by:   Full perception-obj suite green (135 baseline) plus new tests:
             sampling bounds + pose-spread invariants + budget cutoff;
             memory-lifecycle unit test asserting results are device-free
             post-accumulation (mock tensors). Then live: deploy, run
             tools/reenqueue_scene.py against scene 25a14caf's preserved
             bundle (re-upload from outputs/real-capture-25a14caf/ if the
             lifecycle rule already swept GCS), and confirm: completes well
             inside one request, scene → ready, manifest v2 with fused
             objects[], gravity_deviation_deg logged and sane (decision
             0052's remaining convention check), splats in the outputs
             bucket. That result — the first real assembled room — closes
             the software half of board item 1(a)'s checklist; view it in
             the web app afterwards via the dev workbench.

Convention:  See CLAUDE.md. Tests pin invariants, not implementation.
             Housekeeping at end: the envelope findings + the stranded-scene
             gap; expect to rebase over parallel sessions' commits. No merge,
             no push — report the branch ready.
```
