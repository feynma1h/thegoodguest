# 0267 — the newest capture carries no LiDAR depth, and that disables mask repair

**Date:** 2026-08-28
**Status:** Decided (measured; cause not confirmed — needs a hardware test)

## Context

The segment investigation reached the question it had been heading towards: the
study table's best masks still miss its second leg, so could SAM 3 be asked to
fix that with a feedback prompt, and how would we know which masks to ask about?

Both halves already exist in the pipeline. `models/sam3.refine_with_box` calls
SAM 3's interactive box prompt, and `mask_refine.unclaimed_in_box` is the
detector — it back-projects the frame's LiDAR depth, keeps points inside the
object's measured box, drops the ones lying on a measured wall or floor, and
asks which of the rest no mask claims. 0231 decomposes that signal by height
band, which is exactly the shape needed to say "the camera saw surface at the
bottom of this box and the mask claimed none of it."

Neither can run on this capture.

## What we tried

Depth is declared per frame in the bundle, and `_fetch_frame_depth` returns
nothing when `frame.HasField("depth")` is false, so `unclaimed_in_box` returns
`None` immediately. Counted across every preserved capture:

| capture | tier | frames | with depth | share |
|---|---|---|---|---|
| rp7 | LIDAR_ROOMPLAN | 386 | 385 | 99.7% |
| rp6g1 | LIDAR_ROOMPLAN | 249 | 247 | 99.2% |
| rp6g2 | LIDAR_ROOMPLAN | 124 | 123 | 99.2% |
| spike | LIDAR_ROOMPLAN | 722 | 722 | 100.0% |
| **`90eebfc4`** | LIDAR_ROOMPLAN | 189 | **1** | **0.5%** |

**The one frame that carries depth is frame 0** — the first accepted keyframe —
and no frame after it does.

The bundle also records the device, and only one variable moved:

| capture | hardware | iOS | app |
|---|---|---|---|
| rp7, rp6g2 | iPhone17,1 | **26.5.2** | 1.0 (1) |
| `90eebfc4` | iPhone17,1 | **26.6.1** | 1.0 (1) |

Same phone, same app build, different OS. The capture's own RoomPlan version
string agrees: `ios26.6.1;CapturedRoom.v2;beautifyObjects`.

## What we chose

**Record it, and do not guess the cause.** The correlation is one capture on one
OS, and the signature — depth on the first keyframe and none after — is
consistent with `sceneDepth` becoming unavailable once something else starts,
but consistent is not confirmed. The test is a fresh scan on a re-signed build,
which is the operator's and needs no code change.

**And stop treating the missing-leg question as a segmentation problem until
this is answered.** The repair mechanism and its detector both exist and are
both dark in this room for the same reason.

## Why

**This is not a small loss.** Per-frame depth feeds mask refinement (0198/0201),
its band decomposition (0231), `depth_fit` placement, and the LiDAR pointmap
path. A LIDAR_ROOMPLAN capture without it is a LIDAR_ARKIT capture wearing the
wrong tier, and the tier is computed from whether a built room shipped, not from
whether depth did — so nothing in the pipeline notices.

**It also explains a run of otherwise puzzling results in this investigation.**
Every attempt to find an instrument for "is this mask incomplete" came back
weak, and the strongest available detector was never in the running because its
input was absent. That absence was recorded nowhere, because nothing checks it.

**0079 is the note this bears on and it is not refuted.** It measured that
running RoomPlan co-resident does NOT strip `sceneDepth`, on hardware. That
measurement was taken on iOS 26.5.x. If 26.6.1 changed it, 0079 was right when
written and its conclusion has expired — which is a different thing from being
wrong, and the distinction matters for how much of the co-run design has to be
re-examined.

## What would change this decision

**A scan on 26.6.1 that carries depth** makes this capture-specific rather than
OS-specific, and the cause moves to whatever was different about that session.

**A second 26.6.1 scan that also loses depth** confirms it, and the app needs a
fix before any further capture is worth taking — every room scanned in the
meantime is unrepairable in the same way.

**Either way the pipeline should say so.** Tier is derived from the RoomPlan
room; nothing asserts that a LIDAR tier actually carries LiDAR. A count of
depth-bearing frames in the manifest would have made this visible on the first
room rather than on the fourth question about masks. That is the cheap fix and
it is independent of the cause.
