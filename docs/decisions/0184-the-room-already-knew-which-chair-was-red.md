# 0184 — the room already knew which chair was red

**Date:** 2026-08-19
**Status:** Decided — built; perception half not yet deployed (see Rollout)

## Context

Asked on the production origin to "move the red chair next to the bed", the
deployed guest replied that "no colors came through in this scan at all", and
offered a first, second, third, fourth and fifth chair instead. Both halves of
that were wrong in the same way: the scan did carry colour, and the numbers it
offered were not names.

The scene was `a7e073ae`, and its manifest is preserved. It holds five chairs,
of which two are placed — exactly the transcript. `obj_006` is the first of
them, and its reconstruction's gaussians are `#880607` at a concentration of
0.74. The room already knew which chair was red. Nothing read it.

Every manifest object carries a `splat_gcs_uri`, every splat carries per-point
RGB — it is why the room renders in colour in front of the person — and
`reproject.load_splat_appearance` was already parsing exactly those fields for
the facing scorer. The colour was one function call away from a field nobody
had asked for.

## What we tried

**Where the reading happens.** api-public never fetches a PLY and should not
start; perception holds the gaussians. The first shape considered was inside
`build_box_object`, which the charter suggested and which already loads the
appearance. It was rejected because it covers only box-anchored objects, and
the pieces that most need a colour are the ones with no box and no position —
an unplaced chair cannot be moved, taken out or turned, so a colour is the
ONLY handle a person has for saying which one they mean. It ships instead as a
post-pass over the whole fused object list, on the 0082 precedent, budget-gated
like every other context-reading pass and therefore absent rather than partial
on a starved scene.

**What the reading is.** The opacity-weighted median of the visible gaussians,
warranted by concentration: the share of visible mass falling within 0.15 in
RGB of that median. Refused below 0.55, and refused outright when the visible
mass is under 2,000 gaussians or under a quarter of the splat.

**Clipping to the measured box was measured and rejected.** 0104 declares mass
outside the box known-false and the viewer declines to render it, so reading
colour over it is reading partly off the neighbouring furniture. Across the
nine objects in the walk rooms that carry a `splat_clip`, restricting the
reading to the kept mass moves it by at most 0.035 in RGB — 0.001 on most —
and changes no name. The pass stays decoupled from the clip.

**Tone qualifiers were rejected.** "Dark blue", "muted brown" and the like read
well and are the first thing the vocabulary reaches for. They are also where
the instability is: see below.

## Why

**Stability was measured, not assumed.** 0100 is the standing hazard here — an
inference that is stable only because nothing re-runs it is not stable at all,
and a colour is re-derived on every re-drive from whichever view wins. Grouping
the four walk rooms' per-frame observations by label and world position gives
ten physical pieces read through this gate by two or more views:

- **eight agree on the colour family**, with RGB spreads of 0.024 to 0.107 —
  a red chair from two frames, three brown doors and cabinets, a blue curtain,
  two near-black artworks and a lamp.
- **two disagree, and both are grey versus black** on pieces sitting at value
  0.11 to 0.48. Neither is a disagreement about hue.

All five chromatic pieces agree. That result is what the naming rule is built
on, and it is why the tone qualifier went: the qualifier rides on value, which
is exactly the axis that moved.

**So a hue names a piece; a mid grey does not.** A measured colour is always
spoken ("reads grey"), but it may only be used to tell two same-named pieces
apart when it clears a stricter margin — a real hue at saturation 0.35 or
more, or a black at value 0.15 or less, or a white at 0.92 or more. The two
disagreeing pieces fall in the gap between the family boundary and the naming
margin, by construction.

**Perception measures, api-public names.** The manifest carries a hex and its
evidence; the word is chosen in `scene_facts`. This is 0143's split, and it has
a second payoff: the vocabulary can be revised without a perception deploy,
which matters when a perception deploy costs a GPU re-drive of every room.

**The vocabulary's own correction, measured.** The first cut bucketed hue
first, and a wooden door at `#611c02` came out "red" while a dark monitor at
`#3f2c27` came out "red" too. Their hues are within 17 degrees of the red
chair's; their names are not adjacent at all. VALUE separates them: dark warm
is brown however saturated it is. With that rule the four rooms yield brown 6,
blue 4, beige 2 and exactly one red — the operator's chair.

**Absent, never wrong.** Of 67 cached object splats across the four rooms, 37
ship a colour and 30 are refused, including every mirror (a mirror's gaussians
carry whatever it reflected). Of the 37, 19 clear the naming margin. A refusal
is not a claim that the piece is colourless, and the facts say so in as many
words, because "no colour was readable" and "it has no colour" are different
statements and only one of them is true.

**And it is the piece under the room's own light.** A white cabinet reads
`#bdbdba`. The charter carries that hedge — good enough to point at a chair
with, not good enough to match anything to — and nothing in the pipeline rounds
it up.

## Rollout, and what is honest in the meantime

The perception half is built, unit-tested and verified against the real cached
splats; it is **not deployed**, so no production manifest carries a `color`
block yet, and none will until perception ships and the rooms are re-driven.

The charter and `scene_facts` are honest in both worlds by construction: a room
with no colour lines produces a limit saying no piece read one clear colour,
and the guest says exactly that. The shipped behaviour on the day api-public
deploys is therefore no worse than today's, and the day perception follows it
becomes right without a second charter revision or a second evals run — which
is the whole reason the six defects were bundled into one bump.

## What would change this decision

A second colour reading per piece — the union of views 0151 is chasing would
give one — would let the gate compare rather than trust a single view, and the
two dark-band disagreements would become measurable rather than something the
naming margin sidesteps.

If a re-drive is ever observed to change a shipped colour FAMILY on a real
room, the cross-view measurement above was too small a sample and the gate
should rise; the concentration knob is `PERCEPTION_COLOR_MIN_CONCENTRATION`
and raising it to 0.65 refuses four more readings without fixing either known
disagreement, which is why it is not there already.
