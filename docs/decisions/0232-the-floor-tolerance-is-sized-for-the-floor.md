# 0232 — the floor tolerance is sized for the floor

**Date:** 2026-08-23
**Status:** Decided (refused; the parameter ships, the switch does not)

## Context

`_on_room_plane` rejects any measured point within `ROOM_PLANE_TOL_M`
(0.08 m) of a measured floor or wall. Applied inside an object's box that
reaches 8 cm up into every object standing on the floor, which is exactly
where feet and leg bases are. Nine of eleven legged boxes across the four
preserved captures have **exactly zero** off-plane voxels in the lowest tenth
of their height, and `truthlayer`'s docstring names this as the single most
likely way part-wise visibility could have died.

The obvious fix is a box-aware relaxation: keep 8 cm for the room, use a
tight tolerance inside a box where the question is not "what is floor" but
"where does the object end". `truthlayer.plane_flags` already had the
box-aware variant. This wired it into production, at 0.02 m, behind
`PERCEPTION_BOX_AWARE_FLOOR_TOL`.

## What we tried

Measured both settings over all 26 planned box views of the four preserved
captures, replaying production's own detector. A third height band, `foot`
[0, 0.10), was added first so the restored mass would be visible where it
lands.

Predictions registered before running:

| | predicted | measured | |
|---|---|---|---|
| considered points grow | +5 to +25% | **+6.9%** | hit |
| `foot` band share | > 2% | 0.18% → **6.14%** | hit |
| views flagged | 10-13 of 26 | 9 → **10** | hit (edge) |
| `lower` band moves | < 10% | **+2.2%** | hit |

`upper` moved **+0.00%** exactly — the change is strictly local to the floor
junction, as designed. Seventeen of 26 views changed at all; one changed its
flag.

**Then the restored points were asked what they are**, because the restored
band is 74-100% unclaimed on every view and that is either "masks stop short
of feet" or "we just re-admitted the floor". Two instruments, both free.

**Footprint occupancy** at 2 cm cells: legs occupy a few percent of a box's
footprint, a floor fills it. Four of seven large cases read sparse (4.6% to
18.3%) and three read 45-59% — the two 0197 desks and a nightstand.

**Height distribution above the floor plane**, which is decisive. Legs are
vertical structures with surface at every height, so a leg thins out linearly
as the tolerance grows. A mis-levelled plane vanishes as soon as the
tolerance covers its offset.

| box | tol .02 | .04 | .06 | .07 | .08 |
|---|---|---|---|---|---|
| rp7 b02 desk | 2042 | 627 | 107 | 46 | 0 |
| rp6g1 b00 desk | 1360 | 681 | 163 | 66 | 0 |
| rp7 b04 bed | 1499 | 68 | 0 | 0 | 0 |
| spike b04 desk | 1251 | 376 | 0 | 0 | 0 |
| spike b06 chair | 715 | 122 | 19 | 0 | 0 |
| rp6g1 b03 nightstand | 652 | 51 | 11 | 0 | 0 |

**96-100% of the restored mass is gone by 0.06.** Every case has p10 at
2.1-2.8 cm — piled immediately above the cut — with IQR 0.4-1.8 cm. That is a
thin sheet, not a leg.

**And the floor's own spread confirms it.** Measured on OPEN floor only —
depth returns within 15 cm of the plane and outside every box footprint, so
no object contaminates it:

| room | median | p90 |
|---|---|---|
| rp7 | +2.1 cm | **+4.3 cm** |
| rp6g1 | +1.3 | +2.9 |
| rp6g2 | +0.4 | +2.2 |
| spike | +0.0 | +2.5 |

A 0.02 m tolerance sits **inside the floor's own measurement spread**. 0.08
clears p90 on every room.

## What we chose

**Refused.** `_on_room_plane` keeps `floor_tol_m` as an explicit parameter —
floor-only, walls always keep the room tolerance — so the measurement is one
line to reproduce and a future local floor estimate has a seam. **No env
switch ships**, and a test pins its absence.

The `foot` band [0, 0.10) stays. It is inert at the shipped tolerance, which
is precisely its value: it reads 0.18% of considered points, zero on 24 of 26
views, and that number IS the statement that the bottom tenth is empty.

## Why

The premise was that 0.08 is a room-scale number misapplied at object scale.
It is not. **It is sized for the floor plane's own error**, and the error is
real: the depth returns sit up to 4.3 cm above where RoomPlan says the floor
is, on open floor with nothing to confuse them. Under and around objects the
offset runs higher still — 2.8 to 4.0 cm median — because grazing-angle
returns and the object's own base contaminate it.

So relaxing the tolerance does not uncover feet. It uncovers floor, and then
counts that floor as unclaimed object surface, which is the one thing the
detector must never do: it would raise `fraction` on exactly the views where
an object stands on a floor the plane fit slightly under, and send a
refinement after it.

**A flag was built and then removed**, which is the part worth stating
plainly. Shipping it default-off would have been the defensible-looking
choice and it is the wrong one. 0225 named the shape one stage earlier: a
gate whose margins sit inside the noise "is a gate that never fires, which is
worse than no gate because it looks live". This is the same hazard with the
sign flipped — a switch that DOES fire, into a defect, wearing the costume of
a conservative default. Nobody turning it on would see floor; they would see
the flag rate rise and read it as the detector working better.

**What the finding costs elsewhere.** The 8 cm rejection genuinely does
delete the bottom tenth of every floor-standing box, and that consequence is
unchanged — it is simply not recoverable by loosening a threshold. Anything
that needs an object's feet needs a floor level estimated locally, from the
depth under that box, rather than the room's single plane. That is the real
shape of the fix and it is not a tolerance.

## What would change this decision

A local floor estimate. If the floor level under a box can be estimated from
that box's own depth returns — a robust percentile of the returns in its
footprint, say — then the tolerance can tighten against a plane that is
actually where the surface is, and `floor_tol_m` is the seam it would use.
The numbers to beat are in the table above: the restored points must NOT
collapse between 0.02 and 0.06.

The measurement is single-frame and production-path. The fused cloud grows
22-37% in the lowest band under the same relaxation (probe19 A5), which is
the same phenomenon accumulated over every keyframe, and nothing here
suggests that growth is object either.
