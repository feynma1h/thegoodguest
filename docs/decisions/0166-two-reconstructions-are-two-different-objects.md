# 0166 — two reconstructions of one object are two different objects

**Date:** 2026-08-19
**Status:** Refuted — the multi-view union is measured and not built

## Context

0151 probed whether two reconstructions of one physical object could be
registered into a union, found they do not already align, and identified the
trap: similarity ICP reaches a tight RMS by inflating one cloud 70–90% down to
5% mutual coverage. It left the lane open with a clear instruction — the
acceptance criterion is scale drift and mutual coverage, never RMS.

0155 then gave the idea its magnitude. A reconstruction is fed a median 0.18 of
the surface a capture holds of its object; the best single frame offers 0.31
against a hard geometric ceiling of 0.50; the best three frames together reach
0.65. Union looked like the only route to a complete object, and after 0181
killed the measured-pointmap alternative it was the only live route on class-6
truncation at all.

## What we tried

Everything below is offline, over the four preserved captures, through the
production `RefinementContext` replica. The yardstick throughout is the
object's own measured surface — depth backprojected inside the measured box,
voxelised at 3 cm, voxels seen by at least three frames — which is 0155's
reference, and the replica reproduces 0155's coverage medians exactly (0.18
shipped, 0.65 best-three) before any of this was measured.

Coverage is the natural instrument here because a splat is a **generated**
object: it invents its own back, so how much of the measured surface it reaches
is a direct reading of how truncated it is, and how much the union reaches is a
direct reading of whether two views are truncated differently enough to
complete each other.

**Registration was given an oracle it could never have in production** — each
reconstruction fitted directly to that measured surface, scale bounded to
±25%, twelve ICP passes, best in-bound iterate kept. Not a proposal; the most
generous registration available, so that a low number means no registration
method is worth writing.

    best single reconstruction   covers 0.214 of the measured surface
    union of two                 covers 0.258                        +0.044
    n = 11 objects, four rooms

    the same gain under the oracle:  +0.057
    the same gain with no registration at all, splats stacked as placed:  +0.063

**The oracle buys nothing.** It lifts both the single and the union by about
+0.03 and leaves the *marginal value of the second reconstruction* where it
was. Registration is not the constraint.

**The gain is flat across a 3× tolerance range** — +0.044 at 3 cm, +0.057 at
4 cm, +0.050 at 6 cm, +0.043 at 10 cm — while absolute coverage moves from 0.19
to 0.58. (The first sweep of this reported four identical rows because `tau`
was a default argument bound at definition time; a sweep that cannot vary its
parameter is worth naming, because it looked like a robustness result.)

**And it is bought at a price the coverage number hides:**

    off-surface mass    0.506 -> 0.578      (mass nowhere near the object)
    points carried      1.76x the best single
    mutual coverage     0.095               (the two barely occupy the same space)

**The renders settle it.** Three cases chosen to span the range — the best
union in the set (+0.14, mutual 0.56), the widest baseline (88°), and the
operator's own legless desk. In all three the union looks **worse**, and the
best case is the most striking: a clean cabinet becomes two cabinet fronts
interpenetrating at different angles with slabs protruding through the top of
its measured box, while coverage rises 0.70 → 0.84. Stacking as shipped rather
than oracle-aligned is differently bad, not better.

## What we chose

**Not built.** The bound is measured and recorded instead, which is the other
half of what this lane was chartered to deliver.

## Why

**Two reconstructions of one object are not two views of one object. They are
two different invented objects.** SAM 3D's canonical frame is per-reconstruction
arbitrary (0065) and each reconstruction fabricates its own unseen half (0156
found a cupboard back invented with panels much like its front). Registering
both to the same measured surface makes each fit that surface as well as it
can and leaves them disagreeing anyway, because the surfaces they represent are
different fabrications. That is exactly why an oracle changes nothing: there is
no transform that reconciles two different objects.

**Coverage rose while the object got worse, and that is the same trap 0151
named one level up.** A union only ever adds mass, so its coverage can only
rise; 0151 said RMS was not the acceptance criterion, and coverage is not
either. What catches it is off-surface mass, mutual coverage, and a picture.

**0155's promise was about frames, not reconstructions.** Its 0.31 → 0.65 is
what three *viewpoints* see. The union operates on reconstructions, and the
step from one to two of those is +0.06, not +0.34.

**The economics are bad even taking the gain at face value.** Each additional
reconstruction is a full SAM 3D run — 61.9 s observed per object (0080) against
a 900 s request budget — and the third view, on the one object that has one,
adds +0.050. Reaching 0.7 coverage at +0.06 a view would take roughly eight
reconstructions per object. It would also multiply the render payload, which
was this project's most recent emergency (0123/0125).

**The variant that would remove the false mass collapses structurally.**
Trimming each reconstruction to the points that land on measured surface and
unioning those leaves, by construction, a subset of the measured depth cloud —
which the pipeline already holds and does not ship, because it is a shell and
not an object. It cannot contain anything the capture did not already have.

## What would change this decision

**A reconstruction model that consumes several views itself.** This is 0052's
standing trigger, and this measurement sharpens why it is the right one: the
disagreement has to be resolved *inside* the model, where both views condition
one object, rather than downstream where two finished objects cannot be argued
into one.

**Or a reconstruction that says what it did not see.** If a splat carried
per-point observed-versus-invented provenance, a union could take each
reconstruction's observed part and one reconstruction's invention, and the
fabrication disagreement would have somewhere to go. SAM 3D emits no such
signal today.

**Not a wider baseline, and not a better-chosen second view.** The widest pair
available anywhere in these captures (88°) gains +0.084 and renders as two
mutually rotated slabs; the pair with the highest mutual coverage (0.56) is the
best-looking failure. The failure spans the whole range of baselines the data
holds, and r(separation, gain) is +0.35 at n = 8 — not separable. There is real
headroom in the *input* — the pipeline's two reconstructed views see a median
0.30 of the object where the best available pair sees 0.54 — but 0162 already
measured that handing this model a better-informed view does not produce a
better object, so that headroom has no demonstrated route to the output.
