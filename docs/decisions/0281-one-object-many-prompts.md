# 0281 — one object, many prompts: the duplication 0279 does not measure

**Date:** 2026-08-31
**Status:** Decided (measured on `capture-90eebfc4`, all 189 frames, 30 concepts)

## Context

0279 measured SAM 3.1's instance ids as unstable across a revisit and named the
failure precisely: the tracker over-segments in TIME, so one nightstand arrives
as `nightstand#1/#2/#3` in disjoint frame windows. 0280 then measured the
obvious geometric merge and found it insufficient.

Both notes are about fragments that share no frame. Building a per-object
best-frame selector turned up a second kind of duplicate that neither measures,
and it is the one that decides whether an occlusion rule can be written at all:
`/track` runs **one concept per pass**, so a single physical object is claimed by
every prompt in `DEFAULT_OBJECT_PROMPT` that fits it, in the SAME frames.

## What we tried

For every pair of tracked instances that ever appear in one frame, the overlap
of their masks pooled over the frames they share — intersection over union, and
intersection over the smaller area (containment). No geometry, no camera, no
inference: two masks in one frame either cover the same pixels or they do not.

**48 pairs overlap at all. The distribution is bimodal with nothing in the
middle:**

| containment | pairs | what they are |
|---|---|---|
| 0.996 – 1.000 | **14** | one surface, two prompts |
| 0.511 | 1 | `desk#0` / `speaker#0` — a speaker standing on a desk |
| ≤ 0.047 | 33 | ordinary neighbours |

Eight of the fourteen are near-identical readings (IoU ≥ 0.966): `artwork#0 ≡
painting#1` over 54 shared frames, `monitor#1 ≡ tv#0` over 38, `cabinet#2 ≡
door#5` over 17. The other six are nested at containment ≥ 0.998 with IoU
0.166–0.493 — a wardrobe's `door` inside its `cabinet`, a `mirror` containing a
`door`. Collapsing them takes the capture from **48 instances to 34 objects** in
11 groups, every one of which reads correctly by eye.

## What we chose

**Two things, and the second is the one that would look wrong without this
note.**

1. `merge_nested_instances` collapses instances whose masks coincide in shared
   frames, offered as a helper and applied by no one automatically —
   `track_selection.py` never decides what an object is.
2. **The occlusion filter asks containment in ONE direction only.** A mask that
   CONTAINS the target is excluded from the occluder union; a mask the target
   contains is not.

## Why

**A bare "union of all other masks" makes the occlusion rule reject an object
because a duplicate of itself is in the frame.** `artwork#0` is ~99% covered by
`painting#1` in all 54 frames they share. Applied literally, the rule puts eight
instances on the fallback path with every frame rejected, and the diagnosis
would read as heavy occlusion in an empty bedroom.

**The one-directional test is provable, and the other direction is not.** If
another reading spans my whole extent, then every pixel the tracker attributed
to me was still attributed to me — so none of me is hidden, whatever that other
mask is called. The converse is genuinely ambiguous: a small mask inside a large
one is either a sub-part read separately (the wardrobe door) or a small object
standing in front (the speaker on the desk), and **mask geometry cannot separate
those two**. Rejecting is the conservative direction for "is this a good
photograph of the large object", so the ambiguous half stays counted. Merging
resolves it properly rather than by threshold, which is visible in the run:
occlusion rejections fall from **55 to 7** when duplicates are merged first.

**This half of the identity problem is exactly answerable, and that is the point
worth carrying forward.** 0280's instrument was weak because it triangulated a
mask CENTROID across disjoint visits, where the evidence is thin and a chair
tucked under a desk sits 0.088 m from its neighbour. Instances that share a
frame need none of that machinery — the comparison is an observation, and the
measured gap between 0.511 and 0.996 is a factor of two with **not one pair
inside it**, against 0280's 1.8× medians with heavy overlap. The identity
problem is not one problem: it is a solvable half and an unsolvable half, and
conflating them is what makes it look hopeless.

**It does not touch 0279.** `nightstand#1/#2/#3` share no frame, so this sees
nothing of them and does not pretend to. After merging, the capture still
reports 34 objects where perhaps 15 exist.

## What would change this decision

**A prompt list that cannot name one object twice** would remove the cause
rather than the symptom. `DEFAULT_OBJECT_PROMPT` carries `tv` and `monitor`,
`artwork` and `painting`, `door` and `cabinet` — 0226 already established that
the prompt and the label families are one contract, and this is a second reason
to read them together. It is not obviously the right trade: dropping a prompt
loses the objects only that prompt finds.

**A tracker session that takes several concepts at once.** The duplication is a
consequence of one-concept-per-pass, which 0278 shows is forced by L4 memory
rather than chosen. If the multiplex session could carry the vocabulary in one
pass, ids would be assigned across concepts and this would largely disappear.

**Do not re-open the ambiguous direction with a better threshold.** The two
cases it separates are geometrically identical; what would settle them is
evidence mask overlap does not carry — depth ordering, or appearance either side
of the boundary — and this capture has no depth at all (0267).
