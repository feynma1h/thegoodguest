# 0268 — the leg is not hiding under the 0.5 threshold

**Date:** 2026-08-28
**Status:** Decided (measured; hypothesis refuted)

## Context

Reading the pinned upstream source turned up that SAM 3 computes
`masks = masks_logits > 0.5` from a per-pixel probability map — `masks_logits`
is post-`sigmoid()` despite its name — with a bare literal that has no parameter
behind it and has been unchanged in Meta's repo since the initial public commit
of 2025-11-19, through the SAM 3.1 release.

That produced an attractive hypothesis, recorded in the vendored README and
repeated to the operator: **a leg the model scored 0.45 is deleted with no way
to ask for it back, and the only record it was seen is a tensor we discard.**
The study table's masks are missing a second leg, so this was the cheapest
explanation available and the strongest untried instrument on the list.

It is wrong.

## What we tried

`segment()` gained `want_prob` and the probe route gained `write_prob`, writing
the probability map beside the binary mask as uint8. Run on the study table's
three surviving frames, sweeping the cut:

| cut | frame 50 | frame 51 | frame 109 |
|---|---|---|---|
| 0.50 (ships) | 342,108 px | 299,493 px | 142,603 px |
| 0.40 | 1.02× | 1.02× | 1.02× |
| 0.30 | 1.03× | 1.03× | 1.04× |
| 0.20 | 1.05× | 1.05× | 1.08× |
| 0.10 | 1.09× | 1.09× | 1.18× |
| 0.05 | 1.37× | 1.31× | 1.43× |

**And what it adds is a boundary skirt, not structure.** Measuring how far each
added pixel lies from the shipped boundary: at cut 0.40, **83–96% of the added
pixels are within 2 px** of it, and 90–98% within 4 px. Down at 0.10 the growth
is still ≤18% of the mask and 44–57% of it sits within 4 px. At 0.05 the band
breaks up into speckle across the desktop and the background — 7–11% within
2 px — which is noise arriving, not a part.

Rendered at `outputs/segment-quality/threshold-sweep.png`: no coherent
leg-shaped region appears at any cut, in any of the three frames.

## What we chose

**Abandon the threshold as a route to the missing leg**, and record why: the
model is not uncertain about the second leg. It does not see it as desk at
0.45, or 0.2, or 0.05. The mask boundary is confident, and the 0.5 cut is not
what is costing us the part.

The plumbing stays. `want_prob` / `write_prob` are off by default, production is
untouched, and the probability map remains the only dense depth-free signal the
model emits — it is just not carrying the answer to this question.

## Why

**A confident boundary and a missing part are different failures, and this
distinguishes them.** Had the leg sat at 0.45, the fix would have been a
threshold. What the sweep shows is that the leg is not in the model's output at
any confidence — so the input has to change, not the cut. That moves the whole
question back to a second pass: a point or box prompt telling SAM 3 where to
look, which is `predict_inst` or `add_geometric_prompt`, not a number.

**It also corrects a claim this investigation had already written down.** The
vendored README said the discarded map was where a lost part's record lives.
That was a hypothesis stated as a mechanism, and it survived two turns because
it was plausible and cheap. The map is real, the discarding is real, the
inference from it was not tested until now.

**And the measurement was only possible because of the vendoring.** Nothing in
upstream's README describes the threshold or the map; the fact came out of
reading the pinned processor. That is 0264 working — and the refutation is 0264
working twice, because the same discipline that produced the hypothesis is what
priced it.

## What would change this decision

**A different object.** This is one desk in three frames. A part that genuinely
sits near the cut would show as added pixels FAR from the boundary, and the
skirt measurement above is the test — it is cheap and it now runs offline over
any probe output.

**The sweep says nothing about other failures.** A mask that has run onto a
neighbour, or one whose object is cut by the image edge, is untouched by this
result.

**The second-pass route is unaffected and is now the only live one.** SAM 3
takes point prompts through `model.predict_inst(...)` and box prompts through
`add_geometric_prompt`, both on the model we already build, and
`predict(point_coords, point_labels, box, mask_input, multimask_output=True)`
can be seeded with the mask we already have. Where the prompt comes from is
still open — the probability map is now one candidate fewer.
