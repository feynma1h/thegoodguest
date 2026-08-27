# 0265 — five instruments for one choice, and the experiment none of them needs

**Date:** 2026-08-28
**Status:** SUPERSEDED by 0266 on the operator's rulings of 2026-08-28. Both author-judged labels were wrong; rescored, no discriminator beats keeping the longer mask.

## Context

0263 settled how to choose between two nested masks of one object using a
grown-box precision gate — 10 of 10 against the eye where today's sort gets 1 of
10. The operator declined the mechanism: they do not want the RoomPlan box grown.

That is a legitimate constraint and this note records what happens when it is
honoured. Four further instruments were built and measured. None replaces the
one that was refused, and the pattern they make is more useful than any of them.

## What we tried

All offline, over the ten box-associating nested pairs in five captures.

| instrument | agrees with the eye | uses the box? |
|---|---|---|
| today's `mask_overlap_with_hull` sort | **1 / 10** | yes |
| added region's containment in the box (0263, refuted) | wrong on the desk | yes |
| SAM 3's own score — i.e. the existing dedup | 3 / 4 where it fires | no |
| the larger mask absorbs another detection | **6 / 10** | no |
| shape of the added region (pieces, coherence, attachment) | no separation | no |
| grown-box precision >= 0.98 (0263, **refused**) | **10 / 10** | yes, grown |

**The existing dedup, run early, is a real improvement and not a fix.**
`fusion._dedup_same_frame_per_label` already collapses same-frame same-label
nested pairs and keeps the higher-scoring member — it simply runs in fusion,
after the shortlist has spent a reconstruction. Moved ahead of association it is
**eligible on all four of `90eebfc4`'s pairs**, so it would engage on the room
that prompted this. Across the corpus it fires on 4 of 6 and keeps the right
member on 3 of those 4.

Its two failures are structural, not tunable. It is **blocked on rp7 f162 by the
mutual-singleton guard**, correctly by that guard's own logic: masks 2 and 3 are
disjoint (IoU 0.0000) and both sit fully inside mask 1, which is exactly the
coarse-parent-over-separate-children case the guard protects. But here the three
masks are one cabinet — two glass panels and the whole unit — and containment
alone cannot tell that from two real cabinets. And where it does fire it decides
on a **detection** confidence, which is why it keeps the over-reaching mask on
spike f398.

**The absorption veto fails in both directions.** It flags rp7 f162 at 100%,
because a mask legitimately containing its own sub-parts is indistinguishable
from one that has eaten a neighbour; and it misses spike f398 at 7.8%, because
what that mask ran onto was never separately detected.

**Shape does not separate at all.** The two rows that should be refused sit in
the middle of the rows that should be kept on every measure tried — piece count,
largest-piece share, and attachment to the original mask.

## What we chose

**Stop building instruments, and run the experiment none of them needs.**

Since 0259 one question has been open: **does a more complete mask actually
reconstruct into a better object?** Five instruments have now been built to
choose between two masks, and nobody has verified that the choice changes the
output. That is one reconstruction, ~25 s of GPU — `90eebfc4`'s chair from frame
42 against the shipped frame-24 arm, prediction registered first.

If it comes back better, the impasse above is worth spending real effort on. If
it comes back differently-broken, everything in this note and most of 0263 is
moot, and the mask question drops behind class-6 truncation again.

**Nothing else here ships.** Moving the dedup earlier is the only change with a
positive measured record and no new instrument, but at 3 of 6 it is not worth a
code change before the experiment above.

## Why

**This is starting to rhyme with the eleven refuted view measures, and the
resemblance should be taken seriously.** Those were input-side scores, each
plausible, each tested against a small labelled set, each failing on the cases
that mattered. The difference 0259 relied on — that a disqualification is a fact
about the photograph rather than a prediction about a model — holds for the
border rule and holds for the grown-box gate. It does **not** obviously hold for
"SAM 3 scored this higher" or "this mask absorbs a neighbour". Those are
proxies, and proxies are what failed eleven times.

**RULED 2026-08-28 — and the labels were wrong in the direction that mattered.**
spike f398 is better in the longer read; rp6g2 f0 is accurate in neither. Every
pair with a verdict wants the longer mask, and the table above is a list of
instruments losing points for refusing one. 0266 carries the rescore. The
paragraph below stands as the reason it was worth asking.

**The labels are the weakest part of the whole comparison, and they are load
bearing.** Of the ten, three are the operator's ruling on the desk and five are
visually unambiguous — a chair gaining its armrests and base, a cabinet gaining
its carcass. **Two are the author's alone: spike f398 `cabinet` and rp6g2 f0
`chair`.** Both are negatives, and the instruments above disagree with one
another almost entirely on those two rows. So the ranking in the table is being
decided by the labels with the least authority behind them. A sheet asking for a
ruling is at `outputs/segment-quality/two-calls-to-check.png`; until it is
answered, treat every score in that table as ±2.

**And the refused mechanism is still the only one that works.** That is worth
stating plainly rather than burying: on the labels as they stand, grown-box
precision as a gate is 10 of 10 and nothing else is close. The objection to it
is not that it fails — it is that it leans harder on a box already known to be a
few centimetres small. Both things are true.

## What would change this decision

**The reconstruction experiment, first and cheaply.** Everything here is
downstream of an assumption nobody has tested.

**`masks_logits` is the strongest untried instrument and we already discard it.**
SAM 3 returns per-pixel mask logits alongside the binary masks (verified in the
vendored processor, 0264); `models/sam3.py` keeps only the thresholded mask. It
is the only signal the model emits that is about the boundary rather than the
label, which is exactly what every instrument above is missing. Capturing it
costs a probe re-run, not a reconstruction.

**A vision model comparing the two masks** remains untried and is the operator's
own instinct. Unlike score and absorption it is not a proxy — "which of these
shows the whole chair" is a question about the photograph. It needs an API call
rather than a GPU.

**And negative geometric prompts exist and we have never sent one** (0264).
Where a mask has run onto a neighbour, the upstream-supported repair is to
re-segment with a negative box over the neighbour rather than to pick the other
mask. That reframes the whole choice as a repair rather than a selection, and no
instrument in the table above would be needed for it.
