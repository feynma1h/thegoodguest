# 0201 — the repair is judged by what it added

**Date:** 2026-08-21
**Status:** Decided

## Context

0198 measured that SAM 3D's input is RGBA with alpha = the SAM mask, so an
incomplete mask deletes from the model's input structure the photograph
actually contains — rp7 f114's mask excluded both desk legs, and ~3,000
mask pixels took the splat from a 21 cm slab to a body with legs. It left a
production shape to build: detect with the unclaimed-depth signal, prompt
`add_geometric_prompt` with the detector's own region, "accept iff IoU with
the original stays high and the mask stays inside the box hull". It also
left a warning that the signal's contaminant is undetected OTHER objects,
so it must be validated after use rather than trusted blind.

Building it meant deciding what "validated" actually is. The eight refined
masks those benches produced were still on disk, at full resolution, each
with a verdict that came from looking at the resulting reconstruction. So
the acceptance test could be measured rather than guessed.

## What we tried

Seven checks, applied to all eight measured masks offline: the refinement
grew, it kept the original inside it, IoU with the original stayed high,
growth was bounded, the new pixels stayed inside the measured box's
projected hull, no neighbouring detection was absorbed, and the new pixels
landed on the region the detector pointed at.

Three of them turned out not to do the work:

- **Neighbour absorption does not catch the merge.** Variant B — the raw
  RoomPlan box bbox, which merged a chair base and a stool — absorbs a
  neighbouring *detection* at 0.0023. What it absorbed was not detected, so
  the check cannot see it. Across all six variant-C refinements the worst
  value is 0.015, on the deliberate false-positive control. The check is
  worth keeping and it is not the guard.
- **Growth ratio does not separate.** The merge grew 1.94x; the modest win
  (spike f142, an overflowing table that came to fit its box) grew 1.64x.
- **IoU does not separate.** 0.504 against 0.607, the same pair.

A cap fitted anywhere inside either of those windows would be a threshold
learned from one point on each side, which is 0197's refused sort key
wearing different clothes.

The seventh check does separate, and it separates cleanly. The share of
newly-claimed pixels landing on the unclaimed region reads **0.137** for
the merge and **0.075** for the false-positive flag, against **0.561,
0.627, 0.738 and 0.813** for every arm that improved the reconstruction or
left it alone. A 4.1x gap with nothing inside it. The region is painted by
giving each unclaimed LiDAR sample the block of RGB pixels it covers — a
ratio of the two grid shapes, not a tuned radius — and the separation
survives a 6x sweep of that block size, narrowing to 0.275 against 0.422 at
the widest and never closing.

## What we chose

`mask_refine.accept_refined` keeps all seven checks, but only one carries a
fitted threshold: `MIN_ADDED_ON_SIGNAL = 0.35`, inside the measured gap.
Growth and IoU stay as sanity ceilings at values that admit the measured
merge, and the notes say so rather than pretending otherwise.

The refined mask **replaces** the original rather than adding a second arm,
so refinement adds no reconstruction: the plan, its per-box view budget and
the request budget's admission are untouched, and a starved room's long
tail is the length it was. What it costs is one image encode plus two
grounding passes per flagged box view. On the four preserved captures the
detector flags 9 of 25 planned box views, so roughly two per room.

Refusals are free by construction: the original mask is what ships today.

## Why

The question an acceptance test is really asking is "did the repair recover
the structure we had evidence for?" — and the evidence is the detector's
own region. Every other check asks a question about shape in the abstract:
how much bigger, how similar, how contained. Those are proxies for the
thing that matters, and 0197's whole finding is that proxies for
reconstruction quality do not survive contact with a second case.

"The growth is where the signal was" is not a proxy. It closes the loop
between the reason we spent the GPU call and what came back, and it is the
only one of the seven that would have refused the merge for the right
reason rather than by luck of a threshold.

It also changes 0198's own summary in a way worth stating plainly. 0198
concluded that the refinement loop is safe because variant-C prompts
absorbed a neighbour zero times in six. That is true, and the reason is the
**prompt**, not the judgement — the prompt is precise because it excludes
pixels other masks already claim. The acceptance test is what protects the
case where the prompt is precise and the region is still wrong, which is
exactly the false-positive control: a bag inside a table's box, flagged at
0.435 unclaimed, whose refinement adds pixels that are only 0.075 on the
signal. 0198 recorded that arm as harmless; here it is refused, at no cost.

## What would change this decision

- **A refinement that helps and reads below 0.35 on the signal.** n is four
  accepts and two refusals; that is small, and the gap is what makes it
  usable rather than the count. A case inside the band closes the line.
- **A detector that also finds the contaminant.** The signal fires on
  undetected neighbouring objects — four of six flags in 0198's round 2
  were clutter or unphotographed mass. If those became separable before the
  GPU call, the acceptance test would be doing less work and the flag rate
  would drop from 36% of planned box views to something much smaller.
- **A warm room.** The per-object splat cache is checked before any of
  this, so turning the flag on changes nothing about a room whose frames
  are already reconstructed — 0160's lesson in a new place. The cure is
  clearing the per-frame cache, not the knob.
- **Turning the flag off after a refined run.** The accepted mask is
  persisted beside the splat and read back on a cache hit, so placement
  measures a splat against the mask it was built from. With the flag off
  that sidecar is not read, so a room refined once and then re-driven with
  the flag off places refined splats against segmentation masks. The
  supported rollback is clearing the cache, not flipping the flag.
