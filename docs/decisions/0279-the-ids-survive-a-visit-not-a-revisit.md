# 0279 — the IDs survive a visit, not a revisit

**Date:** 2026-08-30
**Status:** Decided (measured on `capture-90eebfc4`, all 189 frames)

## Context

0271 made instance-ID stability the acceptance test for moving to SAM 3.1,
and said why: IDs that drift produce a map that looks complete and silently
conflates objects, which is worse than no map. The bands were fixed in
`tools/track_map.py` **before** the first GPU run — 0.90 and above means a
per-object frame list can be taken at face value, 0.70 and above means the map
is real but fragmentation must be merged first, below that 0271's instruction
is to report the number and not build on it.

## What we tried

SAM 3.1's multiplex tracker, **all 189 frames, all 30 concepts of
`DEFAULT_OBJECT_PROMPT`**, one concept per pass. It found **48 instances; 6
correspond to a RoomPlan box and 42 do not** — the six/nine split 0271 named,
now measured over the whole vocabulary rather than 19 sampled frames. Purity
is the share of a RoomPlan box's claimed frames won by its single dominant
instance; coverage is the share of frames where the box is on screen and
*anything* claimed it.

| box | visible | coverage | **purity** | distinct claimants |
|---|---|---|---|---|
| bed | 90 | 0.967 | **0.977** | 2 |
| storage `587D623F` | 25 | 0.840 | **1.000** | 1 |
| storage `4878C92B` | 63 | 0.730 | **0.478** | 3 |
| table | 92 | 0.913 | **0.500** | 8 |
| chair | 108 | 0.944 | **0.471** | 10 |
| storage `FB1F7793` | 86 | 0.837 | **0.417** | 4 |

**Mean purity 0.6404 over 6 of 6 boxes — below the 0.70 floor, so the
pre-registered verdict is UNSTABLE.**

**But the scalar hides the shape, and the shape is the finding.** Coverage is
0.73-0.97 everywhere: the tracker *finds* these objects in almost every frame
they are visible. What it does not do is give them the same name twice.

Four of the six boxes have their dominant concept arrive as **exactly three
IDs, in disjoint frame windows**:

| box | the one object arrives as |
|---|---|
| storage `4878C92B` | `nightstand#1` (15-27), `#2` (79-100), `#3` (131-142) |
| table | `desk#0` (29-75), `#1` (103-124), `#2` (180-188) |
| storage `FB1F7793` | `cabinet#1` (24-52), `#3` (67-78), `#4` (101-130) |
| chair | `chair#0`, `#2` (70-78), `#3` (102-132) |

**25 of 42 competing claimant pairs share no frame at all.** They are not two
objects arguing over one box; they are one object, seen on three separate
visits, named three times.

**And it is not a clean rule.** `bed#0` holds one ID across a 28-frame absence
and scores 0.977; `cabinet#0` holds one across a **124-frame** absence and
scores 1.000. So the tracker *can* re-identify after a long gap — it just does
not do so reliably. **32 of 48 instances are internally contiguous**; the other
sixteen carry gaps of up to 130 frames and keep their ID anyway.

## What we chose

**Report the number and do not present the raw IDs as an object→frame map.**
The map is written, and `tools/track_map.py` prints the UNSTABLE verdict beside
it so it cannot be read as a finished result.

## Why

**The failure is re-acquisition, not drift, and that matters for what to do
next.** Drift would mean an ID slides from one object onto another — the silent
conflation 0271 feared, and unfixable downstream. What actually happens is the
opposite and is repairable: the tracker over-segments in time, so the map says
three nightstands where there is one. Every fragment is internally trustworthy.

**A room capture is the worst case for this, by construction.** 0273 measured
that the capture is paced by rotation — a person pivoting, not walking — so
surfaces leave the frame and come back repeatedly. A tracker built for a
continuous video of a moving subject meets, here, a static room revisited from
new angles, and re-identification across those absences is the one thing it is
not doing.

**The instrument was checked before the conclusion.** Purity awards a box to
whichever instance overlaps its projected hull most, and a generous 2D hull can
be claimed by a neighbouring object — which would produce low purity with no ID
problem at all. That explanation is ruled out: 60% of competing pairs never
appear in the same frame, so they cannot be simultaneous neighbours.

**The sting is what this does to 0271's plan.** The hope was that a tracked
instance could replace the RoomPlan box as the argument every selection
instrument takes. Measured, the box is what you would need **to repair the
tracked instances** — merging `nightstand#1/#2/#3` into one object requires
knowing they are one object, and the box is the only thing here that knows.
**The nine unboxed kinds have no such repair available**, and they are exactly
the objects the map was supposed to serve.

## What would change this decision

**A geometric merge, and it is the obvious next lane.** Two fragments are the
same object if their masks back-project to the same place. The capture carries
per-frame camera pose and intrinsics, `placement_math.py` already has ray
triangulation, and the merge needs no depth — which matters because this capture
has none (0267). That would raise purity by construction and, unlike the box,
would work for the unboxed nine.

**Upstream has a knob we did not touch.** `Sam3MultiplexTrackingWithInteractivity`
is built with `recondition_every_nth_frame=16`, `hotstart_delay=15` and
`assoc_iou_thresh=0.1`, and the tracker "periodically re-prompts itself with
high-confidence detection masks to recover from drift, occlusion, or confusion".
Whether re-acquisition improves with a different association threshold is
untested and is one env-shaped experiment, not a migration.

**Do not re-open this by re-running one concept and eyeballing it.** The number
that matters is purity across all six boxes with coverage reported beside it;
a single well-behaved object (the bed scores 0.977) will make the tracker look
fine, and four of the six do not behave like the bed.
