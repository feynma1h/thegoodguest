# 0226 — the family map and the prompt are one contract

**Date:** 2026-08-23
**Status:** Decided

## Context

A RoomPlan box associates with a SAM mask only if `family_compatible`
says the box's category admits the mask's label. 0077 wrote that map from
the categories and labels it expected. Nobody has since checked it against
the vocabulary that actually produces labels.

SAM 3 is open-vocabulary and returns **the prompt term verbatim** as a
detection's label. So `DEFAULT_OBJECT_PROMPT` and `BOX_LABEL_FAMILIES` are
not two independent lists — they are two halves of one contract, and a
member of either that is absent from the other is dead weight that looks
live. This is the same failure shape 0225 names one stage later.

## What we tried

Measured both directions against the four preserved captures — the 23
labels actually emitted across every cached frame, and the six RoomPlan
categories actually present across 31 boxes.

**Direction 1, categories with no family.** One: `refrigerator` (spike
b08, 0.91 x 1.64 x 0.68). It never associated however well anything
overlapped it, and SAM does see it — as `cabinet`, at 0.9932.

**Direction 2, family members the prompt cannot emit.** **Eight of
seventeen**: `bench`, `couch`, `dresser`, `shelf`, `stool`, `table`,
`television`, `wardrobe`. `table` is the one that matters — the prompt
carries `dining table`, `coffee table` and `side table` and no bare
`table` — so the `table` family was operationally `{desk, nightstand}` and
the `chair` family was operationally `{chair}`.

**Direction 3, prompt terms in no family.** Five furniture classes SAM can
emit and no box could ever accept: `armchair`, `dining chair`,
`dining table`, `coffee table`, `side table`.

Changes were applied as three separately measured steps through the
existing `PLACEMENT_BOX_LABEL_FAMILIES` env seam, against a 20/31, 28
association baseline.

| step | boxes matched | associations | boxes changed |
|---|---|---|---|
| V0 baseline | 20/31 | 28 | — |
| V1, remove the 8 inert members | 20/31 | 28 | **0** |
| V2, add the names SAM emits | 21/31 | 29 | 1 |
| V3, add `refrigerator:cabinet` | **22/31** | **30** | 1 |

Predictions registered before running: V1 byte-identical (**hit**);
`refrigerator` matches without stealing spike b00's cabinets (**hit** —
b00 kept both); V2 changes nothing on this corpus (**MISS**).

## What we chose

Remove the eight unemittable members, add the five specific names SAM
emits, add `refrigerator:cabinet`, and make both directions of the gap
observable rather than trusting the alignment to stay true.

`armchair` is listed under BOTH `chair` and `sofa`, for the reason 0104
gave for dual-listing `nightstand`: association is greedy and each
observation joins at most one box, so dual listing costs nothing and lets
the right box win on overlap.

`box_placement.vocabulary_gaps(boxes, prompt)` returns both lists and
`process_receiver` logs them once per room as `box_vocabulary_gap`. On all
four preserved captures it is now silent; before this change it would have
reported `unmapped_categories=['refrigerator']` and all eight inert
members. A test pins the shipped map fully emittable by the shipped prompt,
which is the invariant that stops this recurring.

`DEFAULT_OBJECT_PROMPT` moved from `server.py` to `process_receiver.py`.
Not tidying: `server.py` imports torch, so no test that must run without a
GPU container could ever read the prompt, and the alternative was
duplicating the string into a test where it would drift.

**The declined (b) matches stay declined** — spike b08 `refrigerator`/`door`
at 1.0000, rp6g1 b04 `storage`/`door`, rp6g2 b07 `table`/`chair`, rp6g2 b09
`storage`/`artwork`. Note that spike b08 appears in both lists: the box is
now matched, and it is matched to the `cabinet` at 0.9932 rather than the
`door` at 1.0000, because `door` is in no family and must not be.

## Why

**The V2 miss is the most useful result here.** The prediction was that
adding SAM's specific names changes nothing on this corpus, because
`coffee table` is emitted exactly once in four captures and the other four
names are emitted zero times, and that one detection still has to clear the
footprint-overlap bar.

It cleared it. **rp6g2 b08** (`table`, 1.15 x 0.49 x 0.66) acquired that
single `coffee table` association — and rp6g2 b08 is a box that appeared in
neither the six-box unmatched-with-no-mask list nor the four-box declined
list. It was the eleventh unmatched box, unclassified, and one detection in
the entire corpus was sitting on it.

That is what a vocabulary gap looks like from the outside: not a class of
objects that fails, but a single object that quietly never had a chance,
below the resolution of any summary anyone had drawn. The fix is worth more
than one box, because `dining table` and `armchair` are common furniture
that these four rooms happen not to contain.

Removal was chosen over adding the eight to the prompt. Adding them is a
pass-1 segmentation change: it alters what SAM returns on every frame of
every room, invalidates every cached mask, and cannot be measured without
GPU. Removal is provably behaviour-identical today — that is what V1's zero
measures — and `vocabulary_gaps` means prompt growth cannot silently
re-orphan a family the way it silently orphaned eight.

## What would change this decision

Any edit to `DEFAULT_OBJECT_PROMPT`. The pinning test fails closed if a
family member stops being emittable, which is the point; a term ADDED to
the prompt and to no family is reported by `vocabulary_gaps` but does not
fail anything, because a prompt term with no box category is legitimate —
`curtain`, `rug` and `artwork` are long tail by design.

If a capture ever logs `unmapped_categories` with a category not in
`{bed, table, chair, storage, sofa, refrigerator}`, that is Apple's
CapturedRoom enum reaching past what this repo can enumerate, and the map
grows by one line. That log exists because the enum is not enumerable from
here and guessing at it was the alternative.
