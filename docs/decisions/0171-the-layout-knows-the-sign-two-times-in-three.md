# 0171 — the layout knows the sign, two times in three

**Date:** 2026-08-14
**Status:** Decided — built, recording only, not applied

## Context

Five instrument families are measured dead on the 180° facing sign (0081,
0104, 0156), and they share a mechanism: a single-view reconstruction's
unseen half is fabricated, and every one of them asked that fabricated half
a question.

One channel never asked it anything, because it is thrown away first. A
reconstruction is made FROM one frame, so SAM 3D's layout rotation is a
statement about which way the object was facing when it was photographed.
RP-4 discards it for box-placed objects — orientation is re-derived from
box extents scored against the LiDAR cloud — and 0081 keeps exactly one bit
of it, a sign-AGNOSTIC up-axis filter, because the layout's up SIGN measured
wrong on one box in six.

Nobody had put the layout's HORIZONTAL sign to a table. The sign may not
have been unmeasurable; it may have been unmeasured.

## What we tried

`resolve_facing_sign` measures the rotation distance from the layout to the
shipped candidate and to its 180° partner, and takes the nearer. The
RESIDUAL — the distance to that nearer one — is the gate, and it is the
honest one: the layout can only arbitrate a sign along axes both systems
agree on. Fifteen box placements across three of the four preserved walk
captures (rp6g2 excluded per 0163 — its manifest was assembled over four
rounds from frames the cache does not hold).

**The residual is bimodal, which no refuted scorer ever managed.** Eight
rows land at 2.9°–28.9° and seven at 70.0°–177.2°, with nothing between 29
and 70. The five dead instruments all lived inside their own gate's noise
at margins of 0.002–0.089 against a 0.10 gate; this is a gap, not a
continuum, and the gate sits in it.

**Every abstention is explained, none is a near-tie.** On all seven the
layout is close to SOME candidate — 3.3° to 34.1°, median 17° — just never
to either of the two the leaf may choose between. Three are near a
different ASSIGNMENT, where the cloud instrument is the better witness and
the layout has no standing. The other four are near the same assignment
with the opposite UP sign: the layout has the object upside down, which is
precisely the defect 0081 measured at 1 in 6 and refused to trust. Here it
is 4 in 15. So the leaf abstains exactly where 0081's known failure is
present, and decides otherwise.

**Through the production path**, driven by `fusion.fuse_scene_objects` over
the preserved captures, the leaf changes the rotation of three objects by
exactly 180.00° and changes nothing else: position delta 0.00e+00 m, scale
delta 0.0e+00, and the 0104 `splat_clip` removed-fraction identical before
and after — lane A's invariance argument (0158), reproduced out of
production code rather than asserted.

**Two of the three flips are exactly the objects the operator reported.**
rp7's cupboard, at residual 2.91°, and rp7's bed, at 28.85° — decision
0156's two MUST-FLIP rows. Rendered from the source camera, the cupboard's
glass doors and shelves match the photograph under the flip and a blank
white slab matches it before.

**The third is wrong.** rp6g1's nightstand, at residual 15.41°: the
photograph shows a wooden drawer with a brass knob facing the camera, the
shipped rotation puts that drawer toward the camera, and the flip puts a
blank white face there. Checked twice, from the source camera and from
inside the room, after a controlled test of the renderer's camera
convention that caught an inverted azimuth in the first attempt.

So on the rows anyone can read: four right, one wrong, three unreadable
(a cabinet with knobs on both faces — 0169 measured that invented back —
and two beds that are near enough symmetric).

## What we chose

Built in `box_placement.resolve_facing_sign`, recording its preference on
every capture and applying it only under `PLACEMENT_FACING_SIGN_APPLY`,
which defaults off. The 0080 lock-6 / 0081 flag-only precedent, and here it
is not caution but arithmetic: **no number the leaf reports separates the
miss from the hits.** The residuals are 2.91° (right), 15.41° (wrong),
28.85° (right) — the wrong one sits between the two right ones — and
neither the separation, the assignment margin, nor `splat_axis_resolved`
orders them either. There is no gate that ships the two fixes without the
break, and inventing one to exclude a single adjudicated case is the
pattern 0104 warns against.

Recording is free and compounds: every future ROOMPLAN capture adds rows to
a table whose scarcity is the whole reason this question has been open, and
`facing_sign_preference` is exactly the column a later adjudication needs.

## Why this is not a sixth refutation

The four earlier geometric families and the vision model all landed in
noise. This one separates cleanly, abstains for reasons that name a
previously-measured defect, and gets the operator's own two reported
failures right. It is a working instrument with a measured error rate, not
an instrument that cannot see. The honest summary is that one in three of
its turns is wrong and it cannot tell which — which is a reason to withhold
the hands, not the eyes.

## What would change this decision

- **An operator sitting.** The three flips are prepared with per-object
  renders and staged `-facing` viewer rooms. If they judge the two hits
  worth the miss, `PLACEMENT_FACING_SIGN_APPLY=1` is an env-only change.
- **More adjudicated rows.** Five operator rows and a handful of legible
  renders is still a small table. Every capture now records a preference;
  twenty rooms would settle whether 2-of-3 is the rate or an accident.
- **A second witness that disagrees with the layout on the nightstand and
  agrees on the other two.** The layout is one channel; the miss is a
  layout error, not a wiring error, so a combination could beat it where a
  gate cannot.
- **A complete object** (0151). If a union of registered reconstructions
  gives the far side real observed texture, the sign stops depending on a
  fabricated half for every instrument at once, including this one.
