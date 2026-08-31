# 0112 — Clip-sign A/B: the shipped render was never measured, and the numbers invert the shear story

**Date:** 2026-08-10
**Status:** Spent — the operator walk ran 2026-08-12, measured won, the flip shipped and the toggle was deleted.
The default is flipped, the toggle is deleted, and 0135's open question is
answered-positive. Verdicts and outcome in the section at the end.

## Context

Decision 0135 measured that `SplatViewer` builds every 0104 `splat_clip`
volume with the opposite yaw sign from the convention the server's
`yaw_rad` actually carries, leaving the clip box 2θ from the box it is
meant to cut — and left the one-line fix unapplied because 0104 had
adjudicated the clips by eye and both instruments compared boxes to WALLS,
not to the splat mass the clip cuts. Decision 0129 separately measured the
clip cross-section as the one visual defect a mutation feature must handle,
with per-object cut fractions (spike bed 30.7%, rp7 storage 28.7%, rp7
chair 16.5%). The trap this session existed to catch: 0104's by-eye
adjudication happened under the wrong sign, so a clip that looked right may
have looked right because two errors compensate.

## What we tried

Re-ran 0129's cut-fraction instrument over all nine clipped objects in the
four staged walk fixtures, under BOTH signs, through the exact viewer
transform chain (`outputs/clipsign-ab/measure_cut_fractions.py`; per-object
A/B render pairs in `outputs/clipsign-ab/renders/`). Trust gate: reproduce
0129's five reference numbers before believing anything new.

## What we found

**1. Every recorded clip number describes a clip nobody was rendering.**
The measured-sign column reproduces the manifest's `removed_fraction` on
all nine objects to ±0.01 points, and reproduces 0129's five fractions and
all five max-overshoots to the millimetre (bed 0.363→"0.36 m", storage
0.151→"0.15", chair 0.106→"0.11"). So perception's `removed_fraction` is
computed under its own (measured) convention — internally consistent — and
0129's probe-B instrument used the measured convention too, which resolves
0135's caveat in the opposite direction from the worry: 0129 did NOT
inherit the viewer's error; its numbers, 0104's "live values", and the
manifest all describe the clip as MEANT, not the clip as RENDERED. The
shipped render had no recorded number until this session. (0129's "28.7%"
for rp7 storage appears to be a transcription slip of 27.7 — the manifest
says 0.2768 and nothing under either sign produces 28.7.)

**2. What the browser actually cuts, vs what everyone believed
(count-based; alpha-weighted within ~2 points everywhere):**

| object | believed (= measured sign) | shipped render actually cuts | body mass the flip restores |
|---|---|---|---|
| spike bed | 30.8% | 22.0% | 0 (flip cuts +8.8pt MORE — see below) |
| spike table | 2.2% "inert" | **35.4%** — all four legs amputated | 34.1pt |
| rp7 chair | 16.5% | 3.6% | 0 (flip trims +13.0pt of real overshoot) |
| rp7 storage | 27.7% | **50.8%** — a diagonal sliver of the wardrobe | 23.1pt |
| rp7 bed | 1.8% | **24.0%** — mattress corner sliced | 22.2pt |
| rp6g1 table | 16.4% | **34.5%** | 18.1pt |
| rp6g2 chair/storage/sofa | 20.0/18.4/21.8% | 24.2/28.8/32.1% | 6.6/10.4/12.6pt |

**3. The flip cannot un-trim.** Mass beyond the measured box is cut under
both signs on every object where the trim mattered (`cut_only_measured` is
0.0 on rp7 storage/bed and rp6g1 table — the measured cut is a strict
subset of the shipped cut there). The reverse is false: the shipped sign
KEEPS phantom mass past the measured box on 4 of 9 objects (spike bed to
0.195 m, rp7 chair 0.105 m, rp6g2 chair/sofa ~0.08 m). On the spike bed
the flip therefore cuts MORE (22.0→30.8%): it completes the 0.44 m
length trim the shipped sign only partially performs.

**4. Where "two errors compensate" is real, and where it never was.** In
the measured frame the spike bed splat overshoots X to ±1.38 m against a
1.027 m half-extent while reaching only ±0.81 m on Z against 1.179 m; in
the shipped frame those swap. The wrong-sign box happens to fit the bed
splat's own (wrongly-oriented) mass — that is why the bed read acceptably
at 0104's adjudication and why its shipped cut is *smaller* than its
correct trim. On the other seven objects the same sign error was slicing
legs off tables and halving a wardrobe, and the recorded numbers said
"inert".

**5. A build finding that corrects 0135's prediction:** the stage-2
measured outline (`MeasuredOutline`, 0131) was drawn with the SAME shipped
sign as the clip — `SplatViewer`'s inline `u·cos+v·sin / −u·sin+v·cos` map
is R_y(+θ) on the server's raw `measured_footprint.yaw_rad`. 0135 stated
the outline would be "drawn at the correct yaw" and disagree with a
mis-clipped splat; in fact outline and clip agreed with each other and both
sat 2θ off the true box (the sign never mattered in the stage-2 browser
walk because the mock sofa's footprint was axis-aligned). The A/B toggle
governs both consumers through one pure function, so each mode is
internally coherent.

## What we chose

`lib/clipSign.ts` (`parseClipSign`, `viewerYawRad`) is the one home of the
sign choice, consumed at both yaw sites in `SplatViewer`; the dev viewer
reads `?clipsign=measured`; the default stays "shipped" and is pinned
untouched by tests, so nothing ships until the operator rules. The
per-object pairs, the numbers, and the walk script are in
`outputs/clipsign-ab/`.

## Why

0080/0085 make the operator's eyes the standard for "reads right", and
0135 explicitly reserved this change for an operator A/B. The numbers say
the measured sign wins outright on seven objects and completes the trim on
the eighth and ninth at the cost of cutting more (spike bed +8.8pt, rp7
chair +13.0pt) — those two are exactly where an eyes-call is needed,
because both signs shear through visually continuous mass there and the
question is whether cutting at the measured planes reads better than
cutting mid-body at rotated ones.

## What would change this decision

- **The operator walk.** Measured wins → flip the default in
  `lib/clipSign.viewerYawRad`, delete the toggle and param, keep the pins
  on the measured semantics, and append the verdict here. Shipped wins or
  mixed → remove the toggle, keep the shipped default, append the per-room
  verdicts here, and 0135's open question closes answered-negative.
- **Class-6 truncation closes** (0129's standing trigger): the splat stops
  being smaller than its box, overshoot shrinks, and the clip's
  orientation stakes drop with it.
- **Rotation resolution ships** (0104's parked thread): a splat whose own
  axes are corrected changes what the bed-style compensation looks like,
  and the spike bed's "more cut under the correct sign" case should be
  re-measured.

## Outcome — the walk ran, measured wins (2026-08-12)

Per-object verdicts (operator, filled slots in `outputs/clipsign-ab/
WALK.md`): spike table MEASURED ("doesn't make sense to have a table with
no legs"; side note recorded there — the measured table sits into the wall,
placement not clip); spike bed similar both ways, measured "more accurate
in its extents", remaining roughness attributed to rotation/truncation, not
the clip; rp7 storage MEASURED; rp7 bed MEASURED; rp7 chair can't-tell/
mixed; rp6g1 table reads the same both ways; rp6g2 same/no preference.
Tally: 3 clear measured wins, 1 lean, 3 ties, 0 shipped wins — the two
eyes-call objects (spike bed, rp7 chair) both landed "no worse", so nothing
argued for the shipped sign anywhere.

Executed same day: `viewerYawRad` is now unconditional (−θ, the server
convention), `parseClipSign`/`ClipSign`/`?clipsign` and the `clipSign` prop
are deleted, and the test pins flip — the semantic pin holds local +x at
world (cos θ, sin θ), and a new pin asserts the applied sign differs from
the raw yaw by exactly 2θ, so a regression to the shipped sign is loud.
Every room now renders the clip (and the stage-2 outline) at the box
perception measured.
