# 0149 — one object, one cluster, whatever SAM calls it

**Date:** 2026-08-13
**Status:** Decided

## Context

Chasing the walk's "the released monitor's SIZE doesn't represent its
actual size, it is much bigger" on rp7, the manifest says the shipped
monitor came from one frame — `frames_observed: 1` — out of twelve
sampled.

## What we tried

Counted the detections. SAM found a monitor in three of the sampled frames
(7, 114, 385), and a tv in the same three: six observations of one
physical object. The pipeline shipped one of them and demoted a second.

Traced the loss. `_dedup_cross_label` collapses same-frame near-identical
masks across labels and keeps whichever scored higher IN THAT FRAME —
monitor at f7 (0.895 over 0.836), tv at f114 (0.875 over 0.824), tv at
f385 (0.949 over 0.809). The label split then put the survivors in
different groups, so three views of one monitor became a one-view
`monitor` and a two-view `tv`. The collapse's own docstring says a
collapsed group "never seeds objects under several labels", which is true
inside a frame and false across them.

What it cost, measured: the shipped f7 reconstruction is 0.405 m on its
longest axis against its own LiDAR cloud's 0.490 m; the f114 one is
0.568 m against a 0.596 m cloud, has a better tier-1 silhouette in its own
view (0.690 against 0.549) and a better one summed across all three views
(1.72 against 1.28). It was thrown away — the tv cluster's best member was
f385's 0.235 m fragment, which the television scale floor then demoted.

## What we chose

The refined pass groups by confusable GROUP rather than raw label, using
the vocabulary the 3D duplicate gate already owns. Nothing is renamed: a
fused object still takes its name from its best-scoring member, and two
distinct objects of confusable labels stay apart because the proximity
clustering separates them exactly as it always has.

The same-frame nested-pair dedup stays PER LABEL. It absorbs on
containment of the smaller, so run across labels it swallows a small
object genuinely sitting inside a larger different-label one — which is
precisely what the same-frame cross-label collapse refuses by testing
containment of the LARGER instead. Its own test is what caught this.

## Why

Grouping is an internal question — which observations may describe one
object — and the label is a poor key for it because SAM's label is not
stable across frames of the same thing. The confusable groups already
encode exactly which labels SAM confuses; the 3D gate uses them to demote
a duplicate after the fact, and asking the same question earlier is
strictly better, because a duplicate absorbed into a cluster contributes
its position and can be reselected, where a demoted one is discarded.

Measured across the four rooms: rp7's three views become one object and
its demoted duplicate disappears; rp6g1's monitor goes from one view to
two with its duplicate absorbed rather than demoted; spike and rp6g2 are
unchanged. Placed counts are unchanged on all four.

## What would change this decision

Member selection was deliberately NOT changed with it. With the fork
closed, the reselection ranks the three rp7 members by the two-tier
instrument and still picks the smallest, because tier 2 — appearance —
prefers it (0.589 against 0.426) while tier 1 prefers the larger one.
There is a plausible mechanism for that: a splat containing only what one
camera saw reprojects cleanly into that same camera, so appearance
self-consistency can reward truncation.

The obvious replacement — rank by whether a reconstruction spans its own
measured LiDAR cloud, which is one-directional and metric — was measured
and is a weak signal: ratios sit between 0.79 and 1.12 on almost
everything, and it would change the pick on several objects that no
instrument and no operator has adjudicated. That is exactly the pattern
0104 warns against, so it was left. Re-open it when there is a
completeness instrument that can validate more than the single object the
operator has ruled on.
