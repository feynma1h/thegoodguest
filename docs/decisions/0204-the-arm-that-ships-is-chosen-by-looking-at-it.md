# 0204 — the arm that ships is chosen by looking at it

**Date:** 2026-08-21
**Status:** Decided

## Context

An object with two reconstructions shipped whichever one came first.
`build_box_object` walked its associations and took the first with a splat;
`associate_observations` sorts by mask-hull overlap. That is an input-side
measure, computed before any reconstruction exists, and it describes the
box's projected footprint rather than how well the object was
photographed — the family 0197 retired across eleven refuted measures. So
the second arm was segmented, reconstructed, uploaded, and never looked at.

0203 found this and deliberately did not build it: its boundary was what
`/process` shows the model, and selection lives in fusion's placement. It
also recorded that the instrument already existed and was already measured.
This note builds what 0203 recorded.

## What we tried

**The instrument, unchanged from 0197.** Two output-side checks against the
object's measured RoomPlan box, both smaller-is-better:

* `fill_dist` — `|rendered vertical span / measured box height − 1|`.
  Overshoot is penalised exactly like truncation, because mass outside the
  measurement is not legs;
* `residual_m` — the sum of `|scale·extent − dim|` over the three box axes,
  which every box entry already ships as `box_fit_residual`.

Each arm is measured by placing it through production's own
`build_box_object` with scoring off — 0197's call verbatim — so this is the
measured instrument rather than a relative of it. The cost is one splat
parse per arm: no cloud, no appearance, no GPU.

**The sweep reproduces.** Over the 31 boxes of the four preserved captures,
20 have an arm at all and **8 have two** — 0197's population exactly. All
sixteen arm fills reproduce 0197's own `fill_sweep.json` to three decimals.
The two checks agree on 7 of 8; fill is inert on 6 of 8; the gains are
bimodal — **0.000 six times, then 0.0177, then 0.5899**, a 33× gap. (0197
reported 0.017 and 0.590 for a 34.7× gap, computing the difference from
fills already rounded to 3dp. Same measurement, one rounding apart.)

**Both walked verdicts come out right, and they are opposite-signed.**
rp6g1's table switches — 0.406 → 1.004 of its measured height, a floating
slab becoming a table with four legs. rp7's desk keeps the arm it has, both
checks preferring it unprompted, because its alternative is worse
(0.415 → 0.356). An instrument that "improved" the second would be wrong.

## What we chose

`select_arm`, behind `PERCEPTION_ARM_SELECT`, **default off**.

* **Both checks must prefer the challenger.** Fill by `_ARM_FILL_MARGIN`,
  the residual at all. Where they disagree the rule refuses.
* **The margin is 0.10, the geometric centre of the measured gap**
  (√(0.0177 × 0.5899) = 0.102) — fitted to neither end, 5.7× above the
  noise it refuses and 5.9× below the case it accepts. Every margin in the
  whole window between the two live gains produces the same eight answers;
  that is pinned as a test, because a rule that only works at its default
  is a rule fitted to its answer.
* **Move-to-front, not replacement.** Only the chosen arm changes, so
  `frames_observed` still counts every association and the facing check
  still scores every view it would have.
* **Gated on `allow_scoring`**, which is both the recursion guard and the
  budget one. A starved scene loses this the way it loses every other
  post-pass, and no preserved room pays for it: rp6g2, the one room that
  budget-stops, has no multi-arm box at all.

Measured, flag on, across all four captures: 8 entries change, **7 of them
by the added record alone**, and one object moves — rp6g1's table. Flag off
is byte-identical across all 31.

The honest cost of that one switch, unchanged from 0197: the table gains
its legs, an exact box fit, no vertical seating fudge and no `splat_clip`
(0104 removes 16.4% of the shipped arm and nothing from the other) — and
**loses axis resolution**, `splat_axis_resolved` true → false, margin
0.1345 → 0.0656. A complete table whose facing is unresolved, against a
slab whose facing is not.

## Why

Every refuted view measure in this repo scores the input. Scoring the
output is a different kind of claim and a cheap one, and the reason it can
be made at all is that **the arm exists**: it can be compared to something
that is not itself a fabrication. The RoomPlan box is that thing —
measured, not derived from any splat, and already trusted this way, since
0104 clips to it and 0148 seats against its faces.

**Requiring agreement rather than combining is what the measurement asks
for.** With two checks and one disagreement in the whole corpus, any weight
that resolves that disagreement is fitted to a single unwalked object. A
refusal is not a failure of the instrument; it is the instrument saying it
cannot tell, which is the posture 0081's margin gate and 0171's flag-only
leaf already established here. The disagreement itself turns out to have a
mechanism, and that is decision 0205.

**Off does not record.** That is a deliberate departure from 0171, which
records its preference on every capture because reading it is free. Reading
this one is not — it costs a splat parse per extra arm — so the flag is the
recorder, and byte-identical off is worth more than a table that grows
while nobody is looking.

**Selection is the middle of a three-link chain and the reason the other
two are off.** Supply (0202) samples views with objects in mind; repair
(0198/0201) fixes a mask that cut its object short; selection chooses among
what supply produced. Supply without selection is not a quality change — it
is 48 to 60 usable views feeding a chooser that ranks by mask-hull overlap,
and more arms means more chances for that chooser to be wrong as well as
right. Repair never had this problem, which is why it lands alone: it does
not add an arm, it changes the one that was going to ship.

## What would change this decision

- **The operator answers Q1 of `outputs/selection/walk/WALK.md`.** B turns
  the default on and gives 0202 a reason to follow; A closes the whole
  output-side line, which is 0197's own stated condition and has not been
  withdrawn.
- **The operator says the spike bed's declined arm is better.** Then the
  refuse-on-disagreement rule is costing a real win and 0205 re-opens.
- **Axis assignment becomes resolved on most boxes.** Both checks read
  extents under the chosen mapping, and today `splat_axis_resolved` is
  false on most box placements. Selection built on an unresolved mapping
  inherits that, and 0198's amendment measured a case where both checks
  PREFER the wrong mapping on a strongly anisotropic object.
- **An object routinely gets more than two arms.** Everything measured here
  is n=2 per box; `_ARM_SELECT_MAX` exists so a room that turns 0202 on
  cannot make this pass unbounded, but 4 is a guess and nothing has tested
  a three-way choice.
- **Something makes SAM 3D produce a complete object from a partial view.**
  None of this reduces class-6 truncation. It picks better among what the
  model already produced, and 0052's standing trigger is still the thing
  that would retire the question.
