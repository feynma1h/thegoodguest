# 0299 — glass is boxed from its outlines, and covering counts four times filling

**Date:** 2026-09-20
**Status:** Amended by 0300 — the weight in this note's own title is now EIGHT, not four; everything else here stands

## Context

Live boxes lifts a detector's mask into a box from the LiDAR depth under
it (0296). Through glass, LiDAR measures what is behind. In the operator's living
room the green glass coffee table (RoomPlan: 118 × 46 × 56 cm) was finished at
175 × 52 × 91 cm: its footprint was the floor under and beyond the glass, and it
moved with the viewpoint. The dining table's black glass top measured nothing at
all ("no depth under it" in the log's miss tally). The detector still outlines
both, and both stand on the floor.

The operator's direction (2026-09-19) is that boxes must be good without
RoomPlan, on phones without LiDAR too. A way to box glass that needs no depth
serves both.

## What we tried

**Removing the floor seen through the glass.** The lifter removed a supporting
surface only below the object's middle, so that a table keeps its own top. Seen
through an all-glass table the outline measures nothing but floor, which is then
its middle, and the floor came back as the table. The floor and the ceiling are
now always removed (`f0dc1d83`); a synthetic all-glass table is then "only
surfaces under it", and has no box at all.

**The box whose silhouette best matches the outlines, by intersection over
union.** For every view the detector outlined the object in, draw a candidate box
standing on ARKit's floor into that view and compare. On a synthetic all-glass
table walked round it fitted within the bar. On a glass-topped dining table on one
pedestal, among chairs, it came out **94 cm wide for 120**: a box holds the space
under a table top and round its pedestal, which the outline leaves out, and
IoU pays for that space as if it were wrong.

**The same, with covering the outline counting four times filling the
silhouette (an F2 score).** 117 × 78 × 81 cm for 120 × 75 × 80.

**Refitting only from the box a track already had.** The fit costs most of its
time building a start from the floor under every outline, so a warm start alone
was tried. From one side, a deep low box and a shallow tall one draw almost the
same silhouette; the first view's fit sits at one end of that family, and warm
starts kept it there: **156 × 24 × 108 cm** for a table seen across 60°.

## What we chose

- **The route.** A detection LiDAR sees through to the floor it stands on — half
  of what was measured under its outline is the floor's band or below it when the
  lifter kept nothing, three quarters when it kept something, so an open chair
  LiDAR did measure stays its own — or sees nothing of, with the floor in at least
  a fifth of a 3-pixel ring round the outline, is kept as its outline
  (`OutlineView`, `FloorShare`, `DetectorPipeline.observation`). A floor covering
  never takes it, and neither does a detection owning under 30 % of its outline:
  where two detections name one object, `DepthMask.owned` gives the shared pixels
  to one, and the other is not a second object. An outline no box on the floor
  fits leaves the observation the points LiDAR did measure.
- **What an outline can say.** Pixels claimed by something that could stand before
  the object — another object's detection, a chair pushed in, a person — and
  pixels outside the frame say nothing about where the object is not; agreement
  is counted over the rest. The room's own names do not blank anything, and
  neither does a rug, which lies under everything (`DetectorRole.canHide`): with
  it blanking, a glass table on a rug spread to 168 × 34 × 103 cm.
- **The fit** (`OutlineFit`). The box standing on the floor, square to the room's
  walls when they are known, that maximises the mean over views of the F2 score
  of *covered* (the share of the outline inside the silhouette) and *filled* (the
  share of the silhouette inside the outline). Coordinate descent on the four
  sides and the height, in steps from 16 cm to 1 cm. A fit scoring under 0.7, or
  under half filled, is no box standing on the floor.
- **Fusion.** A track most of whose sightings are outlines is fitted to them, and
  only such a track is spared for having too few voxels. An outline joins the
  track whose box agrees with it in the outline's own view (score 0.5, 0.7 across
  labels); an unsure one starts nothing where an existing box covers half of it;
  the track is missed when a frame looks at its box and does not detect it. It
  keeps the latest outline from each 10° direction, at most eight, thinned so the
  kept directions spread evenly, and is refitted from the floor under its
  outlines as well as from its last box whenever a new direction arrives.

## Why

**The detector sees glass that LiDAR does not.** Its outline is the only evidence
there is, and the floor fixes the scale a single camera lacks.

**A box holds its object, so an outline belongs inside the box's silhouette** —
the covering term — **but not the other way round**: an open table's box holds
air the outline never shows. Weighting covering four to one is what brings the
pedestal table from 94 cm to 117. The same lean grows a box to cover mask bleed:
synthetic boxes come out 3–4 cm over, inside the 5 cm bar.

**Nothing in the fit reads a depth.** Depth decides only the route. A phone
without LiDAR has ARKit's floor plane and the detector's outlines, so the same
fit boxes floor-standing things there.

**A new direction is new information, and the only thing that settles the
ambiguity.** Refitting from scratch then, and warm otherwise, keeps the fit's
cost off most passes: in a Debug simulator build, 0.12 s warm and 0.42 s fresh
for eight views.

Synthetic results, with bleeding filled masks and the walls known
(`LiveBoxesOutlineTests`): the all-glass table walked round 122 × 47 × 60 cm, and the
same on a rug; from one side, 60°, 121 × 47 × 61; the pedestal table among chairs
117 × 78 × 81, the chairs staying on the LiDAR route at 42 × 93 × 43; the table
named twice in every view, one track. Controls: from depth alone the
glass table has no box; the same table solid stays on the LiDAR route; a black
screen on a wall, no depth and the wall round it, is not taken from its outline,
while a black ottoman with the floor round it is.

## What would change this decision

- **The phone.** None of this has seen a real mask. If real outlines are not
  roughly filled — a glass table's mask of its edges only — covering and filling
  both fall, and the fit will reject rather than box. The next walk's log marks a
  track "seen through"; its box against RoomPlan's 118 × 46 × 56 is the check.
- **The cost on the phone** is unmeasured. The lift and fuse stage medians in the
  log say it; if they climb with a glass object in view, keep fewer outlines or
  refit fresh less often.
- **What is not on the floor.** A glass vase on a table, or a glass-door cabinet
  whose contents LiDAR does see, does not take this route; they stay the lifter's.
- **A depth model** (the `live-boxes-depth` lane) sees glass as a surface, as
  people do. Where it replaces LiDAR, this route should rarely be taken.
- **The table's own floor-covering names.** The detector also called the green
  table "mat" and "carpet"; those are flat, never take this route, and lift the
  floor under it as a separate object.
