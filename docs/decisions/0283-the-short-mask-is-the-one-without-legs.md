# 0283 — the shorter of two nested masks is the one without the legs

**Date:** 2026-08-31
**Status:** Decided (measured; names a candidate mechanism for class-6 truncation)

## Context

The operator, reviewing the per-object contact sheets, said the desk segments
never capture its legs and that this did not happen under SAM 3. Both halves are
checkable offline: `outputs/sam31/track_probe/desk/` holds every SAM 3.1 tracker
mask and `outputs/capture-90eebfc4/segment_probe/` holds SAM 3's own masks over
19 frames of the same capture.

0261 already measured that SAM 3 returns **two `desk` instances in one frame** —
"same top, same bottom, same left edge, the larger continuing 400-530 px further
right" — and that the per-box shortlist's `(-overlap, ...)` sort takes the
shorter one every time, because `mask_overlap_with_hull` is precision with no
recall term. It left three checks open.

## What we tried

**First, and this was nearly a wrong answer: the capture is rotated.** Profiling
the masks by image ROW showed SAM 3 and SAM 3.1 agreeing everywhere and
suggested there was nothing to the report. Projecting world-down through each
frame's camera pose shows it lands at **+0.3° to +3.4° from image RIGHT** — the
phone was held rotated, so a row profile measures a horizontal world axis and
can say nothing about legs at all. Re-profiled along the true gravity axis:

| frame | SAM 3 short reaches | SAM 3 long reaches | SAM 3.1 `/track` |
|---|---|---|---|
| 50 | 0.711 | **0.988** | 0.712 |
| 51 | 0.653 | **0.919** | 0.656 |
| 109 | 0.736 | **0.981** | 0.737 |

as a fraction of the frame toward the floor. The extra reach is a narrow tail
53-114 px wide and 533 px long at frame 50, and rendered upright it is
unmistakably **the sit-stand desk's leg column and foot**.

**The tracker reproduces SAM 3's SHORTER reading, everywhere.** Over the 11
frames where both segmented a desk its area lands within 0.2-0.3 percentage
points of SAM 3's smallest instance every time, and across **all 78** tracker
desk detections the longest tail is 100 px against SAM 3's 533.

**And it is not the desk, and not a storage artefact.** Two candidate excuses
were measured and both are dead. `track_receiver` stores `m[::4, ::4]`, but a
stride-4 round trip costs **≤0.4%** of a desk mask's area and a synthetic bar
**4 px wide survives intact**. And the split is cross-label — every nested
same-label pair in the 19 probed frames, with the larger instance's extra reach
toward the floor:

| frame | label | small | large | containment | extra reach |
|---|---|---|---|---|---|
| 45 | monitor | 3.49% | 5.52% | 0.999 | **+0.111** |
| 45 | door | 7.62% | 23.15% | 0.984 | **+0.288** |
| 50 | desk | 10.30% | 12.38% | 0.995 | **+0.277** |
| 50 | chair | 7.26% | 8.15% | 1.000 | **+0.116** |
| 51 | desk | 9.10% | 10.84% | 0.998 | **+0.266** |
| 109 | desk | 4.25% | 5.16% | 0.997 | **+0.245** |

**Six pairs, four labels, and all six have the larger instance reaching further
toward the floor.** Never the other way.

## What we chose

**Record that the operator's report is confirmed with one correction, and that
0261's phenomenon has a direction nobody had named.** No code change here: what
this asks for is a reconstruction, not a threshold.

## Why

**The correction matters as much as the confirmation.** SAM 3 does not reliably
produce a legged desk mask — it produces one on 3 of the 11 shared frames, as a
SECOND instance beside the legless one, and production's own sort then discards
it (0261). So the legs are lost on both paths; what changes at `/track` is that
they are no longer even offered. The tracker commits to one extent per `obj_id`
and propagates it, where the image detector returns several candidates per frame
and something downstream chooses. **0261's remedy — a recall-aware metric, or
precision gated on "not contained by a sibling of the same label" — is
unavailable on the tracker path, because there is no sibling.** That is a real
loss in the migration and it is not visible from purity, coverage, or any
instrument 0279 used.

**The direction is the finding.** 0261 framed this as a sort preferring
precision, which is true and is about the METRIC. What the six pairs add is that
the thing systematically omitted is the object's LOWER STRUCTURE — its legs,
base or foot. That is not a property of a sort; it is a property of what SAM 3
considers the object, and it is the same shape across a desk, a monitor, a door
and a chair.

**It names a candidate mechanism for the defect this repo has no live route to.**
Class-6 truncation is "reconstructions missing legs, bases, and backs", and
0198 established that SAM 3D's input is RGBA with **alpha = the SAM mask**, so an
incomplete mask deletes from the model's input what the photograph contains. The
chain is then: SAM 3 offers a legged and a legless reading → the shortlist takes
the legless one → SAM 3D is handed a photograph with the legs erased → the
reconstruction has no legs. Every link is measured except the last.

**Stated as a hypothesis, deliberately.** Six pairs on 19 frames of one capture
is thin, the three attacks on class-6's cause are measured dead (0162, 0181,
0166) and this is not one of them — it is upstream of the model, which is the
half 0197/0198 found alive. It fits the strategy already written down: **change
the input, judge on the OUTPUT.**

## AMENDED 2026-08-31 — the video path cannot carry both readings, by construction

The operator asked the sharp version: **would using SAM 3.1 deprive me of the
leg?** Read from SAM 3.1's own source rather than inferred, the answer is yes
while the mask comes from the tracker, and **it is not a 3.1-versus-3.0
difference — it is the video path versus the image path.**

Two gates, both keyed on **intersection-over-minimum**, which is containment:

1. **Detector NMS.** `build_sam3_multiplex_video_model` sets
   `det_nms_thresh=0.1` and `det_nms_use_iom=True` (`model_builder.py:1171-1172`).
   `chk_sam3_multiplex_base.py:699-702` forwards them into the detector, and the
   source comments the result: *"detections in `sam3_image_out` has already gone
   through NMS"*. Of two nested masks, one is removed before anything downstream
   exists.
2. **The new-object test.** Survivors reach `_associate_det_trk_compilable`
   (`sam3_video_base.py:163`), where
   `is_new_det = (score >= 0.65) & keep & ~any(intersection_metric >= 0.1)`, and
   `intersection_metric` is `mask_iom` because `use_iom_recondition=True`
   (`model_builder.py:1183`). A detection overlapping an existing track above
   0.1 **cannot be given its own id**.

The desk pair measures containment **0.995** — roughly ten times either gate. So
the legged and legless readings can never coexist on the video path, and which
one survives is decided by detector SCORE, not by completeness.

**`build_sam3_image_model` (`model_builder.py:573-676`) configures no NMS and no
association at all.** That is precisely why SAM 3's image path hands back both
instances and the tracker hands back one. The multiplex tracker's whole job is
to maintain one identity per object; suppressing a second, nested reading of an
object it already holds is that job working, not failing.

**The knob exists and is unusable.** Raising `det_nms_thresh` and
`assoc_iou_thresh` above 0.995 would let both survive, and would also disable
NMS almost entirely and let nearly every re-detection spawn a fresh id — on a
capture whose id stability is already UNSTABLE at 0.6404 purity (0279). Do not
reach for it.

**So the resolution is architectural, and it costs nothing.** `/track` exists to
answer *where is the object* for the nine kinds with no box (0271). Nothing
requires the mask handed to SAM 3D to come from the same model. Let `/track` and
the selector choose the FRAME, and let the image path produce the MASK on that
frame — which is what production already does today. The legged candidate stays
on the table, and 0261's sibling-gated fix stays available to pick it.

**One thing this does NOT mean:** the tracker is not taking the leg away
relative to today. Today's shortlist already discards it (0261). What the video
path removes is the possibility of ever fixing it, because the better candidate
never reaches the sort.

## What would change this decision

**One reconstruction, and 0259 already priced it.** Build the desk from frame
50's LONG mask and from its short mask, and score both against the measured
RoomPlan box with `arm_fit` — the output-side instrument that read rp6g1's table
at 0.406 → 1.004 of its box height. ~25 s of GPU on a 0%-traffic candidate. If
the legged mask reconstructs legs, the shortlist's sort is a live cause of class
6 and 0261 stops being a curiosity. **If it does not, the mask was never the
constraint** and this closes as another dead end with the others.

**Do not fix this by preferring the larger mask.** 0261's own reasoning applies:
the box is a BOUND, not a silhouette, and a coarse parent containing disjoint
children is exactly what `fusion._dedup_same_frame` refuses to collapse. The
door pair here is the warning — 7.62% to 23.15% is a threefold jump, far larger
than the desk's, and "largest wins" would take a doorway over a door.

**And repeat the gravity check before profiling any mask on any capture.** This
one is rotated 90°, an axis-naive profile said there was nothing here, and that
answer was wrong.
