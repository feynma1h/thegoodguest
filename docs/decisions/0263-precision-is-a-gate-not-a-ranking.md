# 0263 — precision against the box is a gate, not a ranking

**Date:** 2026-08-27
**Status:** Superseded by 0266 — on the operator's rulings of 2026-08-28. The gate below scores 8 of 9, not 10 of 10, and a rule needing no gate scores 9 of 9.

## Context

0261 measured SAM 3 returning two `desk` masks of one desk in each of three
frames at 99.5-99.8% mutual containment, with the shortlist taking the shorter
one every time by 9-12 points. It named three checks. This note runs them, and
records that the first answer they produced was wrong.

**The operator has ruled on the object itself: the arm the longer mask adds is
the table's own leg.** That ruling is the ground truth this note is measured
against, and it refutes an earlier reading in this same investigation which held
that the longer desk mask over-reached. It did not. The desk was right all along
and the instrument was wrong twice — once in production, once here.

## What we tried

**Check 3 — frequency.** On `90eebfc4`: 129 detections, 28 same-label pairs,
**6 nested**. Over the four preserved captures, on production's own masks under
`outputs/room-quality/cache/`: 194 detections over 48 frames, 93 same-label
pairs, **15 nested**, in all four rooms. So **21 across five captures**.
Containment is bimodal and stays bimodal on both corpora: of 121 same-label
pairs, 21 sit at >= 0.989 and 99 at <= 0.003, with **exactly one** in the middle.
Identifying a nested pair needs no threshold judgement.

**Check 1 — does the bias hit other objects?** Ten nested pairs associate to a
RoomPlan box, spanning `chair`, `desk` and `cabinet` in four rooms. **The
shortlist takes the shorter mask in 9 of 10.** Not a desk story. What it costs
is legible: `90eebfc4`'s chair loses both armrests and its base, rp6g1's chair
the same, and rp7's cabinet ships as its dark glass panel without the carcass.
Alpha IS the mask, so those go to SAM 3D as the object.

**Check 2 — what should replace it?** Two candidate rules were built and the
first was refuted by the operator's ruling.

**Refuted: resolving the pair by where the added region falls.** Measured
against each object's own projected box, the added regions split 30.4, 43.5,
45.7, 47.1, 50.4 against 95.1, 95.4, 98.0, 98.6, 99.4 — five and five, nothing
between, on two independent corpora. It looked decisive. It is also **wrong on
the desk**, whose three frames are three of the five low values: the leg is
genuinely outside the measured box, so the rule reads a correct mask as an
over-reaching one. A clean separation that puts the known answer on the wrong
side is a coincidence, not a discriminator.

**Why the leg is outside the box, measured without depth.** The projected
outline of a box is exactly the set of pixels whose viewing ray passes through
it, so a pixel outside images something outside the box at any depth.
**54.5% / 53.0% / 69.9%** of the leg's pixels are outside in frames 50 / 51 /
109. But it clears the box by very little: the minimum distance from each
missing ray to the box has median **2.6-3.4 cm** and never exceeds **7.7 cm**.

**So the box under-covers the object by about a hand's width, and precision has
no tolerance for that.** A 3 cm protrusion on a 1.18 m table costs the correct
mask 9-12 points and the pick.

**Refuted: giving the score that tolerance.** `splat_clip` already concedes the
same point — it declines to render only what lies more than
`PLACEMENT_SPLAT_CLIP_MARGIN_M` = 0.10 outside. Growing the box by that margin
before scoring makes the leg free. It also **destroys the metric**: saturation at
exactly 1.0000 goes **60% -> 100%** on `90eebfc4` and **27% -> 79%** across the
four captures. Every candidate ties, and the pick falls entirely to the
`frame_index` / `mask_index` tie-break. Worse, whether a nested pair then lands
on the longer mask becomes an accident of detection order: rp7 and rp6g1 happen
to carry the longer mask at the lower index and flip; the desk carries it at the
higher index and does not.

## What we chose

**Precision against the box is a gate, and the tolerance is what makes it a good
one.** The property that ruins it for ranking — a yes/no answer for almost
everything — is exactly what a gate wants:

- **gate:** grown-box precision >= 0.98. *Does this mask stay inside the
  object's measured volume plus a hand's width?*
- **rank, for a nested pair:** among the survivors, prefer the larger mask.

Across all ten box-associating nested pairs this agrees **10 of 10, where
today's sort agrees on 1 of 10**. The separation is wide rather than tuned: the
seven keep-the-longer cases all sit at 1.0000, and the two keep-the-shorter
cases — a `cabinet` mask that has run onto its neighbour and a `chair` mask that
has swallowed part of a desk — sit at 0.8303 and 0.9141.

**Both of the author-judged rows were wrong, and the operator ruled on
2026-08-28.** spike frame 398 `cabinet` is **better in the longer read**, so the
gate's refusal there is a miss. rp6g2 frame 0 `chair` is **accurate in
neither** — the shorter has no legs and the longer takes another chair's legs
and the table's — so it has no verdict and is excluded from scoring.

**Rescored: this gate is 8 of 9, and "always keep the longer" is 9 of 9.**
Every scoreable pair wants the longer mask, so every discriminator in this note
and in 0265 loses points by vetoing a correct merge. See 0266.

**Nothing ships.** The code change is not written, and what should rank the
non-nested candidates is still open — see 0262, which is the larger defect.

## Why

**A ratio against a bound cannot rank, and making it fairer makes it rank
worse.** Precision is the share of a mask inside a volume the object is supposed
to fit in. For anything that fits, it is 1.0 and says nothing; it moves only when
something is wrong. That is the definition of a detector. Ranking by it means
ranking by how little evidence of a problem there is, and the tolerance
experiment is the proof — the more correctly it forgives a real protrusion, the
more completely it stops discriminating.

**The box is a bound on what RoomPlan measured, not a bound on the object.**
0104 clips a splat to the box on the stated premise that mass outside it "is
known-false, because the box is measurement the operator verified 9/9". This
table refutes the premise as a general claim: its own leg is outside. That does
not overturn 0104 — the leg clears by under 7.7 cm and `splat_clip`'s margin is
10 cm, so this object is very likely inside the margin and nothing here shows
the clip removing real geometry. It does mean the premise is an assumption with
a measured counterexample, and its margin is now load-bearing rather than
generous.

**Where the box IS trusted, and how strongly.** Three places, in order of what
they cost here: the overlap sort, which is what lost the leg; association
admission at `PLACEMENT_BOX_MATCH_MIN` = 0.5, which the long desk masks clear
comfortably at 0.86-0.90 and which would exclude a mask outright on an object
sticking further out; and `splat_clip` at 0.10 m, which declines to render, and
which removed 14.01% of this table's Gaussians and 22.18% of `box_05`'s.

**The gate is not a ranking key, so 0197 does not retire it.** It makes no
prediction about what SAM 3D will do with either mask. It asks whether a mask
stays inside a measured volume — the same standing 0259's three
disqualifications have.

## What would change this decision

**Ten pairs is ten pairs.** The gate's margin is wide and it is measured on two
corpora, but the two negative cases are two. A third that lands near 0.98 means
the threshold is doing work the separation was doing, and it should not ship on
that.

**The gate inherits the box's error.** It works here because the leg clears by
under 8 cm and the margin is 10. An object protruding further — a chaise, a desk
with a wide cantilever base — would be gated out for being correctly segmented.
The margin is the assumption; it is 0104's, and it is now carrying a second
load.

**What ranks the rest is unanswered and is the bigger question.** This settles
which of two masks of one object to take. It says nothing about which of ten
views to take, which is 0262, where the same metric ties on a quarter to
two-thirds of all candidates.

**A vision model is the untried instrument, and it is not a refuted one.** Asked
"which of these two masks shows the whole object", it answers from the
photograph rather than by predicting a reconstruction — the same class as 0259's
rules, not the class 0146/0152/0162/0197 retired eleven times. The pipeline
already makes a confidence-gated vision call with a load-bearing fallback in
`shell_material.py`, so the pattern exists. It is the natural replacement for
the `frame_index` tie-break in 0262, where it would fire only where the metric
has no opinion and so could not override a confident measurement.
