# 0259 — disqualify a frame, do not rank it

**Date:** 2026-08-27
**Status:** Amended by 0270 — the three disqualifications below are the visibility veto rediscovered, and 0270 replaces the proposal with a pass that RESERVES rather than rejects. The measurements stand.

## Context

0247 established that the 3D representation is not good enough and that coverage
is not the lever. What it left open was whether frame SELECTION could be, and
that question had a standing answer: no. Eleven view measures have failed
(0146, 0152, 0162), and 0197 is the sharpest — the same swap gained one table a
full set of legs and cost another the ones it had, bidirectionally, with every
input measure pointing the same way on both. No sort key is buildable.

The operator asked a narrower question than any of those experiments had:
looking at a room's actual objects, which frames should have been used? Their
answers were specific — bed 0 and 1, table 50/51/109, chair 41 and 42, and so
on — and they were given before seeing any score.

## What we tried

`census_sampling.select_frames_census` is GPU-free, so production's own selector
runs offline. It reproduced the live 12-frame selection exactly
(`[0, 11, 24, 45, 59, 86, 95, 109, 124, 136, 158, 175]`), which made the whole
comparison free.

Scored against the operator's picks, **the instrument's ranking is far better
than what shipped and imperfectly aligned with the eye**:

| | bed | storage-01 | table | chair | storage-04 | storage-05 |
|---|---|---|---|---|---|---|
| operator's best pick ranks | #1 | #4 | #9 | #4 | #1 | #7 |
| what production SHIPPED ranks | #1 | #30 | #25 | #43 | #1 | #70 |

Two disagreements were then run down to their mechanism.

**The table.** V = clipped projected box area × in-frame fraction ranked frames
187, 186, 188 top; the operator said 187 is plainly cut off. Both are true.
187's box projects to **45.9% of the frame against frame 50's 31.2%** — 1.47×
larger — while its `frac` is 0.958. A 4.2% completeness penalty cannot offset a
47% size advantage, so proximity wins, and **proximity is what causes the cut**.

`frac` understates the cut for a specific reason: it is
`area(hull ∩ frame) / area(hull)` over a CONVEX HULL. Frame 187's hull runs
90 px off the right edge and 155 px off the top — 6% of its width and 10% of
its height — and that costs only **4.2% of its area**, because clipping a
quadrilateral's corners removes little area while removing a whole physical
edge of the object.

**storage-01.** The operator said frames 96-98 share a good view with 94-95 but
are blurry. The instrument ranked 98, 97, 96 as its top three. Segmenting all
four settled it:

```
frame 94 (sharp) : bed, artwork, table lamp, NIGHTSTAND, door, curtain, curtain, cabinet
frame 95 (sharp) : bed, table lamp, artwork, NIGHTSTAND, door, door, desk
frame 97 (blurry): bed, artwork, table lamp
frame 98 (blurry): bed, artwork, table lamp
```

**8 detections collapse to 3, and the nightstand disappears entirely.** The
instrument's top two picks for that box are frames where the object it is
ranking cannot be detected at all.

## What we chose

**Three DISQUALIFICATIONS, and no new ranking key.**

1. **The object's mask touches the image border** → the frame is cut, refuse it.
2. **The object yields no detection** → there is nothing to reconstruct.
3. **The object is not detected because the frame is blurry** → case 2 by another
   route; no separate rule is needed.

Applied to the table, the surviving order is **50, 51, 109** — the operator's
list, in the operator's order. Eight of eleven candidates are disqualified,
including both former top picks.

**Border contact is testable for free.** It needs a mask, which needs SAM 3 —
but "does the projected box HULL touch the image border" is pure geometry and
computable on every frame of every capture. Against the exact mask test on the
frames we segmented it agrees **11 of 11, zero disagreements**, so the cheap
proxy stands in for the expensive one.

## Why

**A disqualification is not a ranking, and 0197 refuted rankings.** Everything
retired by 0146/0152/0162/0197 answers "which of these photographs will
reconstruct better" — a prediction about a model's output from its input, and
the thing measured to be bidirectional and unbuildable. None of the three rules
above makes that prediction. They say the object is not fully in the picture, or
is not in the picture at all. Those are facts about the photograph, checkable
without reference to any reconstruction.

0197 also did not test this. Its two candidates were **both `in_frame` 1.000** —
it controlled for framing rather than measuring it, so the variable this note
acts on was held constant in the experiment usually cited against acting on it.

**The convex-hull area ratio is the wrong instrument for the right idea.** The
pipeline already computes in-frame fraction and already gates frame SAMPLING on
it. The failure is not that completeness is unmeasured; it is that it is
measured as an area ratio, which is insensitive to exactly the clipping that
destroys an object, and then MULTIPLIED by an area term that rewards the
proximity causing it. Border contact is binary, exact, and matches the eye on
every case checked.

**AMENDED 2026-08-27 — the paragraph below overstated this, and 0270 supersedes
the proposal.** Two corrections. First, these three disqualifications ARE
substantially the visibility veto rediscovered: 0234's veto 1 is whole-frame
usability including variance of the Laplacian, which is disqualifications 2 and
3; its veto 2 is per-(object, frame) lower-band visibility, motivated by
*"the desk whose legs run off the frame"*, which is disqualification 1 by a
different test. Second, 0236's objection was NOT answered here. It is not about
pool depth — it is that removing a candidate re-rolls a greedy selection, and
that the cost lands in alternatives only the chooser can see. Every number in
this note was taken with the chooser out of the loop, which is the exact
methodological error 0236 names.
Measured afterwards: making border contact a coverage gate moved 20 of 24
frames and orphaned a box outright, and as a scoring preference it never
reached the frames that mattered. **0270 keeps this note's measurements and
replaces its proposal** with a pass that RESERVES rather than rejects.
The paragraph as originally written follows.

**0236's objection does not apply here.** It refused `PERCEPTION_VISIBILITY_VETO`
because a veto shrank the candidate set arm selection exists to search — 16 of
48 frames changed and a box that had two arms was left with one. The candidate
pool here is 189 frames deep and the table keeps six eligible views after eight
are refused. A veto is dangerous when the pool is thin, not when it is deep.

## What would change this decision

The claim this note does NOT make is the important one: **it does not establish
that a whole mask reconstructs into a better object.** That is still 0197's open
question and only SAM 3D can answer it. The cheapest test is one reconstruction
of the chair from frame 42 against the shipped one, ~25 s of GPU.

If that comes back differently-broken rather than better, these rules still hold
as hygiene — a frame that cannot detect the object is worthless whatever
reconstruction does — but the case for changing production selection weakens to
"stop wasting reconstructions on cut objects", which is a cost argument rather
than a quality one.

Re-open the ranking question only on a new instrument, not on a new feature.
Eleven have failed.
