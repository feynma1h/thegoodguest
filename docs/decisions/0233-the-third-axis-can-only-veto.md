# 0233 — the third axis can only veto

**Date:** 2026-08-23
**Status:** Decided (built, extends `PERCEPTION_ARM_SELECT`, still default off)

## Context

`choose_arm` decides between an object's arms on two numbers, and 0205
measured that both are functions of the same six: three percentile spans of
the splat and three box dimensions. **A hollow shell and a solid body with
identical extents score identically on both.** spike's bed is that case —
"A is a hollow shell that overflows its measurement; B is a filled block
sitting inside it" — and the two checks disagree there about which AXIS, not
about which is hollow.

Trimmed splat->cloud Chamfer is the first available reading that sees a
reconstruction's INTERIOR. HARD STOP 2 cleared it: across four cloud
variants — shipped plane rejection, 0232's tighter floor tolerance, no
rejection at all, and high-confidence-only — **0 of 8 s2c winners move**, and
its agreement with `box_fit_residual` holds at **5/8 on every variant**. The
single movement in the whole sweep is spike b05 UNTRIMMED under
no-plane-rejection, a configuration nothing ships; trimmed is the shipping
configuration and it is stable. That is the property c2s does not have — 7 of
20 of its winners move under the same class of perturbation (0225).

## The substrate was swapped, and that is the headline

**HARD STOP 2's numbers are the FUSED instrument's. Production uses a
different cloud, and its numbers are worse.** Anyone reading 8-of-8 stability
or the 5-of-8 residual agreement as a statement about what ships is reading
the wrong instrument.

| | fused (every keyframe) | **local (what production builds)** |
|---|---|---|
| points per box | 36,931 - 444,126 | **1,761 - 29,896** |
| stable across cloud variants | 8 of 8 | **6 of 8** |
| agrees with the other one's ranking | — | **6 of 8** |

The gate this note cleared was measured on a cloud production does not have.
The substitution was deliberate and is stated here rather than left implicit,
because it is exactly the kind of swap that goes unrecorded: the instrument
that green-lit the decision and the instrument that ships are not the same
instrument, and every future claim about s2c must say which one it came from.

## What we tried

**The cloud is the hard part, and the answer is not the instrument's.**
`truthlayer`'s fused cloud is every keyframe's depth; production has none and
building one is a change nobody has proposed. What a `RefinementContext` can
reach is `get_depth` — already there for 0081's box-axis scorer — so the
cloud built here is the union of the frames the box's own arms come from,
clipped to the box and plane-rejected at the shipped tolerance.

That is a weaker instrument than the fused one, and the gap was measured
before anything was built rather than assumed:

| | fused (all keyframes) | local (box's own frames) |
|---|---|---|
| points per box | 36,931 - 444,126 | 1,761 - 29,896 |
| ranking agreement with each other | — | **6 of 8** |
| stable across cloud variants | **8 of 8** | 6 of 8 |

Prediction was >= 7 of 8 agreement: **MISS**, at 6. Both disagreements —
rp6g1 b03 and spike b03 — sit on margins of 3-8% on both clouds, and both
movers in the stability check move only under high-confidence-only, where
the local cloud thins out.

**Measured through production's own `select_arm` path over the eight boxes:**

| | two axes | three axes |
|---|---|---|
| boxes the rule acts on | **1 of 8** | **1 of 8** |

On rp6g1 b00 — 0197's floating slab, the corpus's only walked `switch` — s2c
prefers the challenger (0.0837 against 0.1180), so the veto does not fire on
the one case anyone has adjudicated.

## What we chose

A third axis on `ArmFit`, `s2c_m`, and `choose_arm` generalised from a
two-element agreement test to **k-of-n with k = n**: every axis that can
express an opinion must prefer the challenger, and one dissent refuses. All
three readings are recorded whether the rule acts or not, and a split is
recorded with the axes that agreed and dissented.

**No absolute threshold on Chamfer, anywhere.** It is comparative only: both
arms score against the SAME cloud, so the clutter probe 19 proved cannot be
removed topologically at any radius is a constant offset rather than a term
that differs between them. That is also why the cloud is built once per BOX
rather than once per arm.

**Abstention is not dissent.** With no cloud — a swept capture, an
ARKIT_ONLY tier, a starved room — `s2c_m` is None and the rule falls back to
the two axes that ship today, pinned byte-identical over the whole sweep.
The opposite choice would make enabling the axis a behaviour change wearing
the costume of a stricter rule.

`trimmed_nn_rms` lands in `placement_math` beside the other geometry
primitives, one-directional by construction so a caller must choose which
question it is asking.

**What it costs, since 0204 said the pass was free and this makes it not.**
Per BOX: one measured cloud, which is a depth back-projection per frame the
box has an association in, from rasters pass 1 already holds. Per ARM: one
trimmed Chamfer, measured at **~400 ms** and flat in cloud size, because
`trimmed_nn_rms` subsamples both sides to 4,000 points — 50k-vs-30k and
200k-vs-444k both come back in 0.4 s. At the shipped `_ARM_SELECT_MAX` of 4
that is under 2 s per multi-arm box, so a ten-box room pays seconds against a
900 s request. Small, but not the "one splat parse and nothing else" 0204
recorded, and the comment on `_ARM_SELECT_MAX` now says so.

## Why

**Unanimity means the axis can only make the rule act LESS often. That is a
STRUCTURAL safety guarantee, not an empirical one** — it holds by the shape
of the rule rather than because these eight boxes happened to come out that
way, so no future capture can violate it. The population it protects is one
the charter did not originally have in view: 0228 measured the second arm
currently carrying an **OOM fallback in six of nine affected boxes** — cases
where tier-1 is the view that failed and a lower-ranked one rescued the
object. That role
persists until the throughput charter lands. A third axis that could ENABLE
switches would be interacting with those boxes and not merely with the walked
ones; a veto cannot reach them at all. A test sweeps that property rather
than asserting it once.

**On this corpus the axis is insurance, not improvement, and it is recorded
as such.** It changes no outcome, and on the one box 0205 says nobody can
adjudicate it adds no evidence either. spike's bed reads **2-vs-1** on the
LOCAL cloud — fill and s2c prefer the shipped arm, the residual prefers the
other — but it is **1-vs-1 as an instrument**, because spike b03 is one of
the two boxes named above whose s2c ranking FLIPS between the two clouds: the
Chamfer axis prefers the challenger on the fused cloud and the shipped arm on
the cloud production can build, at a margin of **0.014**. So the third vote
here is a statement about which cloud was used, not about which arm is
better. The rule still refuses, correctly, and for a reason the first two
axes already supply. What the record buys is the split count itself, which is
the only evidence that will ever accumulate about how often the three
disagree — read it with the cloud provenance attached, as this note's own
6-of-8 table requires.

**The local cloud's 6-of-8 agreement with the fused one is the honest cost of
not having a fused cloud in production**, and it is not hidden. The two
disagreements are on boxes with 3-8% margins where nothing acts, and the veto
is safe on the one box that does act. But this is a weaker instrument than
HARD STOP 2 measured, and any future claim about s2c should say which cloud
it came from.

## What would change this decision

**A fused cloud in production.** If one ever exists — the throughput charter
is the only lane that would plausibly build the depth accumulation it needs —
re-measure the 6-of-8 agreement first. The fused readings are the better
instrument and this note's numbers are the local ones.

**An adjudicated case where the veto fires.** Today it fires on none of the
eight. The first time an operator walks a box where s2c refuses a switch that
fill and the residual both wanted, that is the evidence that decides whether
unanimity is right or whether 2-of-3 is. Do not pre-empt it: 0205 chose
refusal over a tiebreak on exactly this ground, and nothing here is new
evidence against that choice.

The thresholds that are NOT here matter as much as the ones that are. There
is no minimum s2c, no maximum, and no margin — only "strictly better". A
margin would need a noise measurement, and the only one available is the
6-of-8 cloud disagreement above, which is a statement about clouds rather
than about arms.
