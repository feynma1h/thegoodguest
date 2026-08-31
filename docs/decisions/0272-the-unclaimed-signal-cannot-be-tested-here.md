# 0272 — the unclaimed signal cannot be tested here, and without depth it is not a pointer

**Date:** 2026-08-30
**Status:** Decided (measured; nothing built)

## Context

0271 recovered the desk's second leg with a click at (1192, 967) — best coverage
0.1% → 75.0% — and the pointer was a human eye. 0270 recorded that four
automated searches had run past the region. The open question is whether
anything can point at it automatically, and the target now has coordinates, so
for the first time it can be scored.

`mask_refine.unclaimed_in_box` is the obvious first candidate because it already
exists and already ships: it back-projects a frame's LiDAR depth, keeps points
inside the object's measured box, drops the ones lying on a measured wall or
floor, and asks which of the rest no mask claims. That is the same question in
the same shape.

0267 recorded that it cannot run on this capture, depth being present on 1 frame
of 189. That understates the problem.

## What we tried

**The one depth-bearing frame does not see the desk.** Frame 0 is the first
accepted keyframe, and the table box's `in_frame_fraction` there is **0.000** —
it projects entirely outside the image. SAM 3 finds curtains, artwork,
paintings, a chair, a bed and a window in it. Per-box coverage in frame 0:

| box | category | in_frame_fraction |
|---|---|---|
| 0 | bed | 0.999 |
| 1 | storage | 1.000 |
| **2** | **table** | **0.000** |
| 3 | chair | 0.403 |
| 4 | storage | 0.054 |
| 5 | storage | 0.000 |

So this is not a mechanism that is disabled and could be re-enabled by a warm
re-drive or a flag. On this capture it has **no route to this object at all**,
and no amount of re-running reaches it.

**The depth-free skeleton was then measured against the located target.** Strip
the depth and what remains of `unclaimed_in_box` is: pixels inside the object's
projected measured box that no mask claims. That is check34's search with the
two changes 0270's findings imply — the `luma > 120` filter out (the leg reads
111, which is exactly why that search missed it) and the box no longer grown
25 cm (the leg is 100% inside the measured box).

| | |
|---|---|
| projected box hull | 864,786 px, 31.3% of the frame |
| unclaimed inside it | **432,513 px** |
| of which the target | 19,328 px — **100% recall, 4.47% precision** |
| the target's connected component | **308,560 px**, spanning x 744-1908, y 428-1296 |

**The target is recovered and cannot be isolated.** It ranks 1 of 59 components
by size, which refuted the prediction — but it ranks first by being *inside* a
blob 16× its own size that runs across the floor. Pointing at that component's
centroid lands on concrete.

## What we chose

**Nothing built, and no depth-free version of this signal.** What depth supplies
is not a per-pixel refinement of a signal that mostly works; it is the
`_on_room_plane` rejection, and that rejection is the entire mechanism. Without
it the answer is a third of the frame.

**And the candidate is not refuted — it is untested.** These two facts differ,
and conflating them is how a working mechanism gets written off. On the four
older captures depth is present on 99-100% of frames and 0198 measured this same
detector repairing a bench 58,386 → 61,439 px at IoU 0.9493. Nothing here says
it would have missed this leg. It says we cannot find out on this room.

## Why

**A capture-level defect can look like an algorithmic one.** Every attempt to
attack the second leg through the existing repair machinery was reading a null
return and inferring something about the algorithm. The null had one cause, and
it was 0267's missing depth, which nothing in the pipeline reports.

**And the measurement to reach for was the frame's own coverage, not the depth
census.** The depth census says 1 of 189 and sounds survivable — one frame is
still a frame. It is only when that frame's `in_frame_fraction` for this box
comes back 0.000 that the route is provably closed. Cheap, and it should have
been the first thing checked rather than the fourth.

## What would change this decision

**An operator-located target on a depth-bearing capture.** rp7, rp6g1, rp6g2 and
spike all carry depth on 99-100% of frames, and 0197 already names two truncated
objects there. What is missing is ground truth at pixel level, which took an
operator's eye to produce here and would take one again.

**Or 0267's depth defect being fixed and this room re-scanned.** That is the
cleaner route and it is owed anyway.

Do NOT re-open the depth-free version on a better connectivity rule, a
brightness rule, or a component-ranking rule. The signal at 4.47% precision is
not one good filter away; the filter that works is the one depth pays for. See
[0273](0273-the-vision-model-points-and-the-frame-is-sideways.md) for the
candidate that does not need depth at all.
