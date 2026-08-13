# 0169 — the room supplies the ground truth the facing sign never had

**Date:** 2026-08-14
**Status:** Decided

## Context

The 180° facing sign on box-placed splats has defeated five instrument
families (0081, 0104, 0156). Each was refuted, and each refutation deepened a
shared conclusion: a single-view reconstruction's unseen half is fabricated,
and every one of those instruments asked that fabricated half a question.

0156 named the binding constraint without quite framing it as one. The sign is
**one bit**, so a coin scores 50%, and the truth table has **five rows** drawn
from operator walk verdicts. Five rows cannot separate a good instrument from
luck: 5/5 is p≈0.03 and 4/5 is nothing. Every instrument to date has been
scored against a table too small to grade it, which is why "refuted" and
"refuted as implemented" have been hard to tell apart.

The scarce resource is not instruments. It is ground truth.

## What we tried

Every prior attempt scored the splat: appearance NCC in many variants, cloud
alignment, per-view aggregation, a truncation-direction prior, and a vision
model shown two renders. The splat is the one input that is partly invented,
and all five went to it.

Measured on the spike room's cupboard, the object the operator reports facing
backwards: the reconstruction is hollow with both faces populated (mass at the
extremes of its shallow axis outnumbers the middle 5.4:1), and the two halves
are statistically near-identical — counts within 1.3%, median gaussian scale
identical to five decimal places. SAM 3D invented a back that mimics the
front, which is the symmetric-completion behaviour documented for native 3D
generators. 0156's stated mechanism is now corroborated numerically rather
than by a vision model's self-report.

The room is not invented. RoomPlan measures the walls; the box carries a
measured yaw.

## What we chose

Derive the facing of wall-backed furniture from room geometry, and use it as
**ground truth to grade instruments** — not as a placement rule on its own.

The procedure, per box-placed object: take the two horizontal box axes
(`dims[0]` and `dims[2]`; `dims[1]` is vertical per 0137/0143), find the
nearest wall to the corresponding box face, and test perpendicularity against
that wall's interior normal. Where an axis is perpendicular and the object is
against the wall, a functional prior fixes the direction along it — storage
opens away from the wall, a bed's headboard is against it, a sofa's back is to
it.

Measured on the live post-deploy manifests of the four preserved walk rooms,
with a class-dependent facing axis (long horizontal for beds, shallow for
storage/sofa/table): **12 of 14 wall-backed objects are determinate.** Every
determinate case measures |dot| = 1.000 against the interior normal; every
other measures ~0.0. The distribution is bimodal with nothing in between,
which is what a geometric relationship looks like and what a scorer never
produces — the five refuted instruments all lived in the middle, at margins of
0.002–0.089 against a 0.10 gate.

Both objects the operator reported are in the determinate set: the spike
room's cupboard (`obj_000`, standing 3 cm from `wall_06`) and rp7's bed
(`obj_004`), which is the row 0156's truth table records as MUST FLIP.

## Why this is ground truth and not a fix

**The room gives the answer, not the mapping.** It yields the world direction
an object's front must point. It does not say which face of the splat is that
front — and that remains an object question, which is exactly what the five
dead instruments failed at. A placement rule cannot be built from the room
alone, and an earlier draft of this note claiming otherwise was wrong.

What it does deliver is decisive for the thing that was actually blocked:
**12 mechanically generated truth-table rows, from geometry, with no operator
walk.** That is more than double the hand-adjudicated table, it costs nothing
to extend to future rooms, and it finally makes the sign a gradeable question.

Two candidates can now be scored properly rather than argued about: SAM 3D's
layout rotation sign, which RP-4 discards for box-placed objects and which no
instrument has ever tested, and a proper Gaussian render in place of the
256 px sparse-dot rasteriser that 0156 named as its own confound.

## What would change this decision

If a room's walls are unmeasured — an ARKIT_ONLY capture with no plane
anchors, or an `anchor_envelope` shell — this yields nothing and the table
does not grow. It degrades to silence, never to a wrong row.

The class-dependent axis rule is not complete: the spike room's bed has its
side against the wall rather than its headboard, and falls out of the
determinate set under a rule that assumes headboards. The robust form tests
both horizontal axes for perpendicularity and applies the functional prior
only to choose the direction along whichever one is wall-normal. That would
likely recover it, and should be built before the table is treated as
exhaustive.

If a union of registered reconstructions (0151) ever restores real observed
texture on the far side, the appearance family stops interrogating a
fabricated half and deserves one more attempt — graded against this table.
