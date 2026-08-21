# 0205 — fill sees one axis

**Date:** 2026-08-21
**Status:** Decided

## Context

0204 ships a rule that requires both output-side checks to prefer a
challenger before it displaces the arm that ships, and refuses where they
disagree. Across the four preserved captures exactly one box disagrees:
spike's bed. Refusing there was chosen on posture — 0081's margin gate, one
stage later — and nobody had ever looked at either of that bed's two
reconstructions.

So we looked.

## What we tried

Both arms rendered against the measured RoomPlan box from two angles
(`outputs/selection/walk/spike_box03_bed_view{A,B}.png`).

|  | A (ships, f10) | B (declined, f354) |
|---|---|---|
| spans, of measured box height | 1.029 | 0.816 |
| box fit error over three axes | **0.894 m** | **0.238 m** |
| axis mapping resolved | yes | no |

**A is a hollow shell that overflows its measurement; B is a filled block
sitting inside it.** A fits vertically almost exactly and misses by nearly a
metre across the other two axes of a box whose largest dimension is 2.158 m.

The mechanism is not subtle once seen. **Fill reads one axis** — the
vertical span over the measured height. The residual reads three. The two
can only disagree when the error is not vertical, and a bed is the shape
where that is most available: a mattress-sized slab of roughly the right
thickness can be any length at all.

A second fact lands on the same box, independently. Of all sixteen arms in
the corpus, this is the **only one** where the residual the instrument
reads differs from the residual that ships — 0.894 unscored against 1.502
in the built entry — because the cloud overrules the extent-best mapping
there and resolves it at margin 0.1604. An arm whose mapping is overruled
is an arm whose extents were read in a different frame, which is what a
disagreement between two extent-derived checks looks like from the inside.

Then the question that decides what to do about it: **can the walked
evidence separate the candidate rules?** Measured over the eight boxes, at
the same 0.10 margin:

| rule | acts on | rp6g1's table | rp7's desk |
|---|---|---|---|
| fill only | rp6g1/box_00 | switch ✓ | keep ✓ |
| residual only | rp6g1/box_00, **spike/box_03** | switch ✓ | keep ✓ |
| both must agree (shipped) | rp6g1/box_00 | switch ✓ | keep ✓ |

Residual-only is not a worse-conditioned instrument, either: its positive
gains are **0.0128, 0.4527, 0.6558** — bimodal at a 35.4× gap, the same
shape fill has at 33×.

## What we chose

**To refuse, and not to tune.** The shipped rule stands as 0204 describes
it, and the bed is written down as a question in
`outputs/selection/walk/WALK.md` rather than answered by a threshold.

## Why

All three rules get both walked objects right. **The walked evidence cannot
separate them** — n=2, and the only case that distinguishes fill-only from
residual-only is the one object nobody has adjudicated. Choosing between
them on how the bed looked to me is choosing on n=1, unwalked, by eye,
after seeing the answer. That is precisely the habit that produced eleven
refuted view measures in this repo, and 0197's refusal to build a sort key
is the standing example of not doing it.

The conservative rule is also the one whose failure is legible. Refusing a
real improvement leaves a room exactly as it is today, and it says so in
the manifest: the `arm_select` record names both arms and both readings
whether it acts or not. Acting on a wrong rule changes what a person sees
and reports nothing at all.

What this note buys is that the operator's verdict now selects between two
**already-measured** rules instead of opening an investigation. If the bed's
declined arm is better, the change is one line — drop the fill check to an
agreement test the residual leads, or replace fill outright — and its
margin already has a measured 35× window to sit in.

There is a reason to suspect fill will not survive that: it is a one-axis
special case of a three-axis check that the entry already carries. It
earned its place by being the thing 0197 measured and the thing that reads
rp6g1's table at 0.406 against 1.004, which is the sentence that made the
whole line worth building. But "the reconstruction spans 41% of its
measured height" is a vivid way of saying "it fits its box badly", and the
residual says that about every axis.

## What would change this decision

- **The operator answers Q2 of the walk pack.** B better → residual-led;
  refusing right → fill's one axis is doing real work and the shipped rule
  stands.
- **A second and third disagreement appear with the same structure** — a
  challenger better on three axes and worse on the vertical. One is an
  anecdote; three would make the structure the finding and settle it
  without a sitting.
- **Axis assignment becomes resolved on most boxes.** The disagreement and
  the mapping override land on the same box here, and with resolved
  mappings that coincidence would either persist or vanish. Either answer
  is informative and neither is available today.
