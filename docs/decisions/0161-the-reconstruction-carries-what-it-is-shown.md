# 0161 — the reconstruction carries what it is shown

**Date:** 2026-08-14
**Status:** Decided — measured, nothing built

## Context

0146 refused to close the view-selection question outright: "the refutation
is partly a statement about the instruments. If one appears, re-run the
paired comparison before concluding anything about views." Two instruments
had been tried, both mapping-independent, both coin flips.

0154 and 0155 then supplied something 0146 never had — an object's observed
surface, measured from depth in the box's own frame, where porosity cancels
and single-frame noise can be dropped by requiring a voxel to be seen by at
least three frames. That makes a third instrument possible: not whether a
splat's proportions agree with its box, but whether it puts Gaussians where
the capture measured surface.

## What we tried

**First, the obvious form of it, and it does not work.** Recall — the
fraction of an object's >=3-frame reference voxels the reconstruction
occupies — separates the operator's named-broken objects from the rest by
median 0.115 against 0.152, with fully overlapping ranges. Not an
instrument. Precision behaves no better.

**The numbers explain their own failure.** Recall runs 0.05 to 0.335, and
0155 measured a single frame as seeing 0.18 of an object (0.31 at the best
frame). A single-view reconstruction cannot put Gaussians on surface its own
view never saw, so recall against the whole object is bounded by the view
and is mostly re-measuring the view rather than the reconstruction.

**The decomposition that separates them,** all against the same reference,
with the view's own surface taken through production's own cloud recipe
(`placement.observation_world_cloud` — mask resized to the depth raster,
confidence-filtered, camera to world):

    view_cov   |V| / |U|             how much of the object this frame saw
    fidelity   |S & V| / |V|         of what it WAS shown, how much came back
    reach      |S & (U-V)| / |U-V|   surface it was not shown and recovered

Masking is load-bearing. The depth inside a table's box also contains the
chair tucked under it and the floor; charging the table's reconstruction for
missing those reads fidelity at 0.279 and manufactures a correlation with
view coverage (-0.285). Through the masked cloud both artefacts go: fidelity
0.482, and the correlation collapses to -0.081.

Over 22 reconstructions in three rooms, against the >=3-frame reference:

    view_cov   median 0.087   min 0.038   max 0.214
    fidelity   median 0.482   min 0.121   max 0.732
    fidelity   median 0.777   min 0.204   max 0.985   at one voxel tolerance
    reach      median 0.102
    recall     median 0.136   min 0.050   max 0.335

A 3 cm grid is unforgiving: a complete splat placed 3 cm off scores like a
truncated one. The gap between the exact and the one-voxel readings — 0.482
to 0.777 — is alignment slack, not missing surface.

## What we chose

Nothing built. The finding recorded, because it changes what the remaining
options are worth:

**The reconstruction is not where the surface is lost.** At one voxel it
carries a median 0.777 of the surface its own view measured. The deficit is
overwhelmingly in the input: the view itself only saw 0.087 of the object.

That makes 0155's ranking sharper rather than merely ordering it. More
surface in is expected to mean more surface out, because the model
demonstrably carries most of what it is given. Multi-view union (0151) is
the option that adds surface, and this is the measurement that says the
addition would survive into the object.

## Why this is not a quality instrument either

Fidelity does not separate the operator's named-broken objects from the rest
(0.462 against 0.482) any better than recall did, and within a box the view
that saw more surface reconstructed more surface in 4 of 7 — a coin flip,
consistent with 0146 and 0152. It is a descriptive statistic about the
regime, not a selector.

The one place it does move is gross misplacement: the two worst tolerant
readings are rp7's bed at 0.204, the object the operator called "facing
opposite", and spike's table at 0.412. That is suggestive at n=2 and is not
offered as more.

## The circularity, stated plainly

These placements were produced by `depth_fit`, which fits the transform to
this same cloud. So the alignment is not independent evidence, and fidelity
should be read as coverage GIVEN a fit to that cloud, not as a blind test.
What survives the objection is the direction that matters: a fit cannot
invent mass, so a truncated splat still cannot cover a cloud it lacks the
surface for, and 0.777 is a statement about how much mass is there.

## What would change this decision

A reconstruction path consuming more than one view, which is exactly what
this argues is worth building. If a union of two registered views does NOT
raise the surface an object ends up carrying, then fidelity being high was
misleading and the loss is somewhere this decomposition does not look.

An instrument that does separate good reconstructions from bad ones. Three
have now failed to (shape agreement, cross-view silhouette, surface
coverage), and until one exists every paired view comparison in this thread
— including the ones that came out negative — rests on instruments that
have not earned trust. That caveat belongs to 0146, 0152 and this note
equally.
