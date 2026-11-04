# 0296 — a box is the surfaces seen, and seven filters decide what a surface is

**Date:** 2026-09-15, amended 2026-09-20 with what the phone showed
**Status:** Decided — synthetic acceptance met; the screen chooses which tracks become boxes (0301); glass is 0299's

**Net state, 2026-11:** the fusion and the seven filters below are what live boxes runs
during a capture (0301). The review screen this note's "what the phone changed"
section describes is gone, and with it the person's finish gesture as the thing that
locks a box: the Scan screen settles a box itself, and `BoxFusion.finish` remains in
the engine, tested, unused by the app. The measurements stand.

## Context

Live boxes (0295) turns a detector's 2D instance mask into a 3D box
with our own code: the LiDAR depth under the mask becomes world points, the points
become a gravity-aligned box, and boxes fuse across frames. Every learned 2D-to-3D
lifter found was non-commercial, so there was nothing to borrow.

The lane's acceptance bar was fixed before the first run and has not moved: on
synthetic rooms with ground-truth boxes, seen from at least three views, every
fused box within **3 cm** at the centre, **5 cm** on every extent, and **5°** of yaw
for anything 20 cm or more across — with depth noise, low-confidence pixels and
masks that bleed past the silhouette. `LiveBoxesLiftingTests` holds that bar; the
renderer behind it (`LiveBoxesSyntheticScene`) states the depth registration, the
pinhole model, the quarter-turn and the letterbox in its own code rather than
calling the maps under test, so a convention error shows up as a misplaced box.

## What we tried

**The first run** used the obvious chain: drop low-confidence and out-of-range
depths, drop pixels with a depth step to any 4-neighbour, keep the largest group of
depths, then fuse 2 cm voxels with votes, take yaw from the minimum-area rectangle
around the points' hull, and read each extent as a trimmed range.

The frame maps were right from the first run: in all four holds the renderer's
mask, sampled through production's letterbox, turn and depth registration, landed
on the object's depth pixels at IoU above 0.85. Four of seven objects met the bar.
The other three, and one honest-partial check, did not:

| object | first run | cause |
|---|---|---|
| monitor on a side table | depth +8.2 cm, yaw 8.5° | mask bleed onto the table top around its base |
| bookshelf against a wall | depth +7.1 cm | bleed onto the wall beside it |
| picture frame | width +9.5 cm | bleed along the wall, stretched by oblique views |
| shelf, one frontal view | 33 cm deep | a face seen once cannot have depth |

Each cause was found by instrumenting the frame that showed it, fixed, and
measured again:

1. **Bleed onto a background at a depth the object also spans.** Beside a tall
   shelf seen from close, the wall is no further away than the shelf's own far
   corners, so neither the depth-step filter nor the depth-group split can see it.
   Added a BORDER check: within 4 pixels of the mask's edge, a depth must agree with
   the median of the mask's own measured depths around it. The first version read
   only the depths that had survived the step filter, and saw nothing but other
   bleed pixels — at a silhouette, flying pixels and the step filter blank a band 3–4
   pixels wide. It reads the measured depths now.
2. **Bleed onto the surface an object stands on.** A support is now every
   horizontal plane ARKit reports below the object's median height — the floor and
   table tops alike — not only the floor. (Where that plane is came later; see the
   review below.)
3. **A one-sample voxel counted as much as a face.** Extents are trimmed by the
   number of measurements in each voxel, not by the count of voxels.
4. **Yaw from a noisy hull.** The rectangle reached 5.5° on the lamp. Yaw now comes
   from the direction the object's vertical faces run: each floor-plane
   neighbourhood gives a local direction and how line-like it is, pooled as 4θ so
   perpendicular faces reinforce — the device `FloorPlanMath.gridHeading` already
   uses. Weighting by the fourth power of line-likeness silences box corners, which
   biased even exact synthetic faces by 0.9° (0.4° after). Objects with no faces to
   speak of fall back to the rectangle.
5. **Every floor-standing bottom sat 2.8–3.1 cm high**, because the supporting
   surface's ±2 cm band hides the object's own last centimetres as well as the
   bleed. An object whose lowest points reach the band's edge is reported as
   resting on that surface, and fusion takes the box down to it when most sightings
   agree.
6. **Sides no view faces were short by about 2 cm**, because the step filter threw
   away the object's own silhouette pixel with the flying pixel beside it. A pixel
   is now dropped only when a neighbour is NEARER by more than the step — the
   background past an edge, or a flying pixel — and the foreground edge stays.

Fusion's votes changed with them: a view that detected the object votes each
visible voxel inside or outside its UNDILATED mask, and a voxel goes when outside
outnumbers inside after three votes, or when views saw clear space behind it more
often than points landed in it.

**A review of the finished code found two more,** both invisible to the furnished
room, where nothing nests and the only table top has the monitor standing on it:

7. **A plane was a height, applied to the whole room.** A desk anywhere cut a 4 cm
   slice out of every object at its height, and a picture hanging with its bottom
   edge 3 cm above the desk's height was reported resting on it and stretched down.
   A floor or ceiling still reaches the room. Any other plane now carries the
   minimum-area rectangle around its measured boundary, 10 cm wider, and filters or
   supports only what is over it. An unclassified plane supports what is above it
   and is the ceiling of what hangs below it; before, which of the two it was
   depended on how high the phone was held. A synthetic picture beside a
   desk-height plane pins it, with the room-wide rule as the control.
8. **A cushion on a sofa sits inside the sofa's box.** Tracks of different labels
   merged when one box was 85 % inside the other, measured against the smaller,
   so the cushion folded into the sofa. A close-up of the cushion alone joined the
   sofa too: its mask then voted the rest of the sofa away, and on that code the
   sofa track did not survive four close-ups. Across labels a detection now joins
   a track only when its mask covers at least 60 % of the track where the frame
   measures it. Tracks merge only when their boxes agree (IoU 0.5), and never once
   they have been detected in the same frame. The same test still makes one track
   of a shelf the detector names two ways.

## What the phone changed (2026-09-15 to 09-20)

The synthetic rooms held only solid boxes, and the phone walks in the operator's
home found what they could not. Each rule below is pinned on a synthetic scene,
most beside a control that fails without the rule (`LiveBoxesOpenFurnitureTests`,
`LiveBoxesFusionTests`, `LiveBoxesGeometryTests`).

9. **Surfaces come off before anything is split, and the object is the nearest
   connected piece.** A white armchair 25 cm from a wall was boxed 91 cm deep, and
   a sofa's box ran forward into the glass table before it: a real mask covers
   the floor between a chair's legs and the wall between its slats, and the floor
   spans every depth from the chair to the wall, so splitting by depth never
   separated them. The floor, table tops, ceilings and ARKit's vertical planes
   behind the object now come off first — a wall only when the object stands off
   it toward the camera, so a picture on it stays the object. What is left is cut
   into pieces that touch in 3D; the object is the NEAREST piece with at least a
   quarter of the largest's points, with what stands on it or hangs under it (the
   largest piece made a second lamp of the wall behind a floor lamp's pole). Under
   15 % of the mask's measured pixels is no observation. Synthetic armchair
   103 × 89 × 78 → 54 × 89 × 52 cm (56 × 90 × 51), sofa 129 × 85 × 172 → 161 × 85 × 86
   (160 × 85 × 85). `19abb156`, `6514fa2c`.
10. **A pixel two masks claim belongs to one of them.** The dining table's boxes
    were chair-shaped, 88–97 cm tall: LiDAR saw nothing of its glass top, and the
    chairs in its mask became the table. The smaller mask keeps shared pixels when
    most of it lies inside the larger (a cushion on a sofa); otherwise the surer
    detection does. `f5b938ef`.
11. **A box is square to the room's walls unless the object clearly is not.**
    Boxes re-guessed their turn every pass from weak faces or partial outlines — a
    chair's by up to 44.6°, a lamp's by 42.9°. With ARKit's walls known, a box
    takes their direction unless its own faces agree strongly and point more than
    7° off it; a round outline with no faces always takes it. `93263ba0`, `d8f1f71f`.
12. **Who may start a track.** A detection with no track to join starts one at
    0.5; from 0.3 up it starts an UNSURE track, only where no track stands, which
    needs four sightings to be confirmed and wears a faint dot, so that the white
    glass-door cabinet (never over 0.44) can be boxed at the person's choice. A
    detection the frame cuts off starts nothing — the bed seen mostly out of frame
    grew a box that jumped 27 cm and 44° — unless its outline covers the middle of
    the screen, where the person is aiming (the pooja cabinet, tall and close, was
    always cut off). `d8f1f71f`, `70a40cd6`, `70f66fce`, `a5ab9731`.
13. **The load has a ceiling.** The first walk died at two minutes holding 92
    tracks. RoomPlan's own categories are lifted only while RoomPlan is not
    running or when the menu asks; a detection covering under 0.5 % of the view is
    not lifted; a track under 10 cm on every side after five sightings goes; at
    most 60 tracks, the stalest tentative (unsure before sure) first; a track no
    point of which a frame can see is not visited. `30b10caf`, `d8f1f71f`, `f07750fe`.
14. **The floor and the ceiling always come off**, not only below the object's
    middle: through an all-glass table the outline measures only floor, which is
    then its middle, and the floor was returned as the table. `f0dc1d83`; how the
    table is boxed instead is 0299.
15. **Nothing locks by itself; the person finishes a box.** A rule that locked a
    box once its fit settled locked the white chair four seconds after first
    seeing it, from the front, at half its depth, and never locked 16 of the 21
    objects in the 19:34 walk (the clock and the art seen from one side, both
    sofas too big to see whole). Now the person aims at an object, walks round it
    and finishes it, and `BoxFusion.finish` locks exactly the box they were
    looking at; a finished track is never removed and never merges with another
    finished one. In the 23:30 walk 25 objects were worked on and 13 finished,
    median 4.2 s from starting on one; five finished chairs sat 3–11 cm from
    RoomPlan's nearest chair box, their heights within 8 cm of its, and two sofas
    were two boxes (110 and 128 cm) where RoomPlan made one of 237. `4feaf202`,
    `551ed3cc`, replacing `4a34e0f6`.
16. **The log says why a detection became no box** — name, reason and the 50 cm
    floor cell — which is how the glass table, the unsure cabinet and the cut-off
    pooja cabinet were found. A person is never among them (0089). `bcd37b13`.

## What we chose

The seven filters (exclusion, confidence and range, depth edges, borders,
surfaces, one object, coverage), the fusion rules and votes as described, and a
box drawn only once the person finishes it; the tolerances as fixed. The
acceptance tests hold with the walls known and unknown, and the open-furniture
scenes each within the bar. On the 2026-09-15 code, over seeds 1–10 of the
furnished walk: worst centre **1.7 cm**, worst extent **3.9 cm**, worst yaw
**1.5°**, one track per object. A single frontal view of the shelf stays a thin
face; three views grow it to the shelf; a person standing against it never shapes
it, and the control with exclusion switched off fails, so that test has teeth.

## Why

**Every filter is about LiDAR and masks, not about what the object is.** The one
class-aware rule is `flat` — a floor covering is coplanar with the floor, so the
border and support filters would erase it — and it is a property in the vocabulary
table, not a special case in the geometry.

**A box covers only what was seen.** Nothing is extrapolated to an unseen side; the
contact rule restores only centimetres our own filter hid, and only down to a
surface ARKit measured. The floor ring under the box being worked on fills in for
every direction it has been seen from, so a partial box reads as one — and the
person, not a rule, says when it is done. The one exception is what LiDAR sees
through, which has no surfaces to see: 0299.

**Two conventions look arbitrary without this note.** Depth pixel (i, j) is centred
at camera-image coordinate ((i + ½)·W_img/W_depth, (j + ½)·H_img/H_depth) — pixel i
covers [i, i + 1), the convention Metal's normalised texture sampling uses.
`placement_math.unproject_depth` in the perception pipeline indexes depth pixels at
integers with the same scaled intrinsics, which places each depth sample half a
depth pixel (3.75 camera pixels, about 5 mm sideways at 2 m) from where this code
places it. Neither has been measured against ARKit's registration on a device; the
difference is recorded so the two are not assumed to agree.

## What would change this decision

- **The operator's walks.** Synthetic bleed is random and one prototype cell wide;
  a real mask can bleed consistently, which no vote can remove. If boxes on real
  furniture read loose, the instrument is the log's agreement between the
  detector's boxes for RoomPlan's own categories and RoomPlan's boxes for the same
  objects — the one geometry check real rooms offer without a person's eyes.
- **A depth model in place of LiDAR** (the `live-boxes-depth` lane). The
  confidence values, the 5 m range, the edge-step thresholds tuned to LiDAR's
  flying pixels and the seen-through votes all assume LiDAR; each needs its own
  measurement against a model's depth, not an assumption.
- **Thin structures.** The border check prefers the mask's majority, so a lamp
  pole one depth pixel wide loses to its background. LiDAR at 256×192 barely
  measures it either; if the walk shows lamps boxed as shades alone, that is where
  to look.
- **Unreliable table-top planes** would reduce support rejection to the floor.
