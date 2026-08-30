# 0272 — suppressing a person removes the furniture they touch

**Date:** 2026-08-27
**Status:** Decided (measured; no change made)

## Context

0089 made `person` a suppression-only concept: segmented so the shell can
exclude it, never shipped. 0070 records the residue — a person can still
contaminate a plane's measured albedo and reach the material-inference crops.
Neither records what suppression does to the FURNITURE.

## What we tried

Rendering each shipped object's actual model input for one room — the source
frame with its mask, beside the RGBA cut-out SAM 3D receives — showed the bed's
mask shredded: holes through it, disconnected fragments. Since alpha IS the
mask (`models/sam3d.py`), each hole is geometry deleted from the model's input
before it sees the photograph.

Measured against that frame's suppressed union:

| object | mask px | suppressed inside its bbox | as % of its own mask |
|---|---|---|---|
| **bed** | 227,918 | **108,920** | **47.8%** |
| **nightstand** | 38,742 | 5,629 | 14.5% |
| chair, cabinet x2, curtain, ceiling fan | — | ~0 | 0.0% |
| room total | 1,372,329 | 114,644 | 8.4% |

**99.8% of all suppression in that frame fell inside the bed's footprint** — the
person was on the bed — and it removed an area equal to nearly half the bed's
surviving mask. Six of the twelve sampled frames carried a suppressed person.

## What we chose

**Record it. Change nothing.**

## Why

The privacy rule is not negotiable and this note is not an argument against it.
A person must not reach reconstruction, and 0089's mechanism is correct.

What was missing is that the cost is not confined to the person. Cutting a
person out of a photograph takes the furniture they are touching with them, and
because the mask is the alpha channel there is no later stage at which that
geometry can be recovered — it was never in the model's input. A bed with
someone on it is reconstructed from a bed with a person-shaped bite out of it.

This is worth writing down for two reasons beyond the measurement.

**It is a plausible wrong diagnosis.** A shredded mask looks like a
segmentation failure, and the natural response is to reach for mask refinement
(0198) or a different view. Neither addresses it, and both would appear to fail
for no reason. The tell is that the holes coincide with the suppressed union,
which nothing currently surfaces — it took rendering the union alongside the
mask to see it.

**It concentrates rather than spreads.** 8.4% across the room reads as
negligible; 47.8% on the one object the person was touching does not. Any
future measurement of suppression's cost that averages over a room will
conclude it is harmless, and be wrong about the one object that matters — which
in a bedroom is usually the bed.

## What would change this decision

If the shell's exclusion union could be built from a person's mask WITHOUT
subtracting it from co-located object masks, the tension disappears — the
person still never reaches reconstruction, and the bed keeps its geometry. That
is a change to how suppression composes with object masks rather than to
whether people are suppressed, and it is worth pricing.

Until then: when an object's reconstruction looks damaged and the frame
contained a person, check the overlap before blaming segmentation. The probe
route now renders the suppressed union tinted for exactly this reason.
