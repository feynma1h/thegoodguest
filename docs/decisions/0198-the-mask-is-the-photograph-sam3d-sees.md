# 0198 — the mask is the photograph SAM 3D sees

**Date:** 2026-08-20
**Status:** Decided — amended same day (operator viewer walk)

## Context

0197 found that rp7's desk has a fully-in-frame view (f114) already
reconstructed in the bucket — and it came out WORSE than the shipped clipped
view: a slab with no legs at all, from a photograph that contains the whole
desk. The operator, looking at the walk photographs, spotted why: the SAM 3
mask on f114 excludes both legs. SAM 3D's input is RGBA with **alpha = the
mask** (`models/sam3d.py`), so a mask that misses the legs deletes them from
the model's input even though they are in the pixels. The frame edge cut the
legs at f7; the MASK cut them at f114. The operator asked whether SAM 3's
follow-up prompts could recover them, and whether incomplete masks are even
detectable.

## What we tried

**Detection first, offline.** The incompleteness signal is data the pipeline
already holds: LiDAR depth that back-projects inside the object's RoomPlan
box, minus pixels lying on measured wall/floor planes, minus every SAM mask
in the frame. On the two frames the operator flagged it reads 40.3% / 43.5%
unclaimed vs 16.3% / 19.1% on each object's shipped frame — a ~2.4×
separation — and the overlays confirm the unclaimed pixels sit on the actual
missing structure. The signal's contaminants are undetected OTHER objects
(the stool under rp7's desk, a bag under rp6g1's), which is why its use must
be validated after the fact rather than trusted blind.

**Then the GPU bench** (0181's pattern: one candidate revision at 0% traffic,
predictions registered in writing first, production traffic untouched,
everything deleted after — both model-source clone layers were CACHED, so the
bench ran production's model code). A throwaway route drove upstream's
`Sam3Processor.add_geometric_prompt` — positive/negative box prompts,
normalized cxcywh, incremental on the same `set_image` state — which is in
the image we already ship; our wrapper had simply never called it. Trust
gate: the bench's text-only segmentation reproduced production's cached f114
mask stack **sha256-identical**, target mask at exactly 58,386 px.

Two prompt variants on rp7 f114's desk:

- **B — the RoomPlan box's projected bbox** (the naively automatic prompt):
  the registered merge risk fired exactly — 113,465 px with the chair base
  and stool absorbed — and its reconstruction OOM'd (0061's big-mask class).
- **C — bbox of shipped mask ∪ unclaimed in-box depth** (the detector's own
  region): mask grew 58,386 → **61,439 px** (+3,053, IoU 0.949 against the
  original), and the growth is the legs.

## What we chose

Nothing ships from this bench; it is a measured existence proof, recorded
for the lane that builds it. The result, seed-matched (production seeds
`42 + i`, so the cached splat is seed 48 — a registration error in the
bench's P0, caught and corrected by re-measuring the control at 42):

| arm | mask px | fill of measured box height | box_fit_residual Σ |
|---|---|---|---|
| original mask, seed 48 (production cache) | 58,386 | 0.356 | 0.798 |
| original mask, seed 42 (bench control) | 58,386 | 0.236 | 0.811 |
| **refined mask, seed 42** | **61,439** | **1.114** | **0.144** |

Same photograph, same seed, ~3,000 mask pixels of legs different. Seed
variance is real but small (0.236 vs 0.356, both slabs) and cannot explain
the jump. (The fill/residual figures in this table were later found to be
measured under a WRONG axis mapping — see the amendment below for the
corrected, mapping-independent statement; the mask effect itself stands.)

## Why

Every refuted attack on class-6 truncation aimed past the mask: selection
chose among views whose masks were taken as given (0146/0152/0162), the
measured pointmap conditioned a model that weights the image far more
heavily (0181), and the multi-view union stacked two fabrications (0166).
The image is the channel with leverage — 0181 measured that — and the mask
IS the image gate: alpha-zero pixels are not shown to the model at all. So a
mask defect is an input-pixel defect, and fixing it moves the output the way
no downstream fix could.

The prompt-variant split matters as much as the headline. The measured box's
raw bbox (B) is the obvious automatic prompt and it is the wrong one: a box
volume legitimately contains other objects (a chair tucked under a desk —
the 0148 lesson), so a box-shaped positive prompt asks SAM 3 to merge them.
The detector's own region (C) is precise because it excludes pixels other
masks already claim. Detection and prompt are the same computation.

Scope, stated plainly: this recovers structure the photograph HAS and the
mask dropped. The un-photographed half of an object is still fabricated —
0166's finding stands. For rp7's desk the mask was the whole defect; that
will not be true everywhere.

## Amendment (same day) — the desk rendered lying on its side

The operator walked the staged fixture in the real viewer and caught what my
four-azimuth eyes-read missed: the refined desk was on its side, tabletop as
a vertical panel. Three corrections, all measured:

1. **The table above quotes fill/residual under the WRONG axis mapping.**
   The entry shipped `splat_axis_resolved: false` at `axis_margin` 0.0259 vs
   the 0.10 gate — the known-open 0080/0081 assignment class, not a
   regression. The correct assignment (up = splat axis 2, rendering as a
   true desk with legs) sits at extent consistency 1.78, OUTSIDE the 1.6
   tolerance, so without an up prior it was never enumerated — 0081's
   spike-bed mechanism verbatim. Worse for 0197's candidate instrument:
   fill and box_fit_residual both PREFER the wrong mapping on this desk
   (1.114/0.144 lying vs 0.738/0.412 upright), because percentile extents
   under-read sparse legs and the box's height (0.795) and depth (0.660)
   are close. That is the concrete instance of 0197's mapping-dependence
   caveat.
2. **The mask-effect headline survives in a mapping-independent form, and
   it is the better statement:** the text-only splat's percentile extents
   are 0.983 × **0.212** × 0.718 — a 21 cm slab that cannot be a desk under
   ANY rotation — while the refined splat's are 0.983 × 0.655 × 0.444, a
   real three-dimensional body whose upright assignment renders as a desk
   with legs. The mask put the third dimension into the model's input.
3. **The bench dropped the layout sidecar** production saves at
   fresh-reconstruct time, and 0081's sign-agnostic up filter reads exactly
   that prior to widen enumeration to all six assignments — so production's
   own path may have enumerated (and possibly resolved) the correct
   mapping; the fixture showed the worst case. The staging compounded it by
   reusing the TEXT-ONLY observation's layout, meaningless for a new
   reconstruction (0065). Any follow-up bench must persist
   `extract_layout`'s output beside the splat, as production does.

## What would change this decision

- **n = 1 object.** Before any production build, run the same bench on two
  or three more incomplete-mask objects (the detector's unclaimed signal
  finds candidates automatically). A second object where the refined mask
  does NOT improve the reconstruction would bound the claim.
- The production shape wants its own design pass: threshold on the unclaimed
  signal, acceptance test after refinement (IoU with the original stays
  high, mask stays inside the box hull, fill increases), production's
  reconstruct-retry for bigger masks, and where it runs (a `/process`
  post-pass over box objects is the natural home — every quantity already
  exists server-side). Cost per refined object is one incremental grounding
  pass on an already-encoded image plus one reconstruction.
- Capture-time user input for mask correction was considered and declined:
  masks do not exist until the server segments, 0150 rules against per-object
  capture feedback, and the capture already contains what the server needs.
  Post-reveal correction on the web ("this looks wrong" → server refinement)
  remains open as a product call.
- (Superseded by the amendment: the axis question is not hypothetical — the
  refined arm shipped the wrong default and the operator saw it.) If axis resolution
  ever becomes load-bearing for shipping, the refined-mask path inherits
  0197's cost accounting.
