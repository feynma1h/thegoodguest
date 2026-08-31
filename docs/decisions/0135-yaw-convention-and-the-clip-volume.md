# 0135 — `yaw_rad` is not the rotation the viewer applies, and the clip volume is built with the wrong sign

**Date:** 2026-08-09
**Status:** Decided — measured. The solver uses the correct convention; the shipped
renderer is deliberately NOT changed — see "What we did not do".

## Context

Stage 2's solver needs a box's footprint: it decides whether a proposed
placement lands inside the measured floor and clear of the other pieces. That
means turning `roomplan_box.{center_world, dims, yaw_rad}` into four world XZ
corners, which requires knowing what `yaw_rad` means.

The obvious answer was to copy the shipped renderer. `SplatViewer.tsx` builds
every 0104 `splat_clip` volume as

```js
new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), s.clip.yaw_rad)
```

which is three.js's `Ry(θ)` and maps a local `(u, 0, v)` to
`x = u·cos θ + v·sin θ`, `z = −u·sin θ + v·cos θ`. The solver was written that
way, on the reasoning that the clip is browser-verified (0104: "a near-zero
clip volume makes the bed vanish… the real 0.10 m volume brings it back") and
therefore authoritative.

Then the solver was run on real rooms and refused almost everything, which is
what sent us to measure instead of reason.

## What we measured

Both instruments exploit the same physical fact, which 0076's operator walk
established independently: **RoomPlan furniture is aligned to the walls it
stands against** (9/9 on position, extent AND facing, including a chair that
is genuinely off-grid and reported as off-grid).

**Instrument 1 — angle between a box's local +x and the nearest wall's
lateral axis, mod 90°.** Restricted to the three four-wall rooms, because the
13-wall spike room has walls at so many angles that every sign looks aligned:

| room | boxes | as shipped in the viewer | opposite sign |
|---|---|---|---|
| rp6g1-09684dde | 4 | 18.6, 18.6, 18.6, 25.8 | **0.0, 0.0, 0.0, 7.2** |
| rp6g2-b667f891 | 6 | 25.2, 27.4 ×4, 27.4 | **0.0 ×5, 2.2** |
| rp7-a71d125f | 5 | 25.4, 25.5 ×4 | **0.0 ×5** |

**Instrument 2 — the flush-edge test.** A box standing against a wall presents
an EDGE to it, so its two nearest footprint corners sit at equal distance from
the wall plane; a mis-rotated box presents a CORNER and the two spread. Spread
in metres, over every wall-adjacent box in all four preserved walk rooms:

| room | as shipped | opposite sign |
|---|---|---|
| rp6g1 | 0.022, 0.226, 0.292, 0.438 | **0.0, 0.0, 0.0, 0.072** |
| rp6g2 | 0.084, 0.147, 0.229, 0.253 | **0.0, 0.0, 0.0, 0.018** |
| rp7 | 0.111, 0.222, 0.266, 0.284, 0.546 | **0.0 ×5** |
| spike | 0.007, 0.022, 0.029, 0.037, 0.088, 0.302 | **0.0, 0.0, 0.0, 0.001, 0.021, 0.296** |

14 of 15 boxes land at exactly 0.000 under one sign and 19–27° off under the
other. This is not close.

## What it means

`yaw_rad` rotates `(x, z)` as an ordinary 2D plane:

```
x = u·cos θ − v·sin θ
z = u·sin θ + v·cos θ
```

which is three.js's `setFromAxisAngle([0,1,0], **−**θ)`.

So **the shipped `splat_clip` volume is rotated by 2θ relative to the box it
is supposed to be**. For the spike bed, θ = −0.81 rad, so the clip box sits
about 93° from the mass it is cutting.

There is a suggestive corollary, and it is a hypothesis rather than a finding.
0129 measured the clip cross-section as the ONE visual defect a mutation
feature must handle — "a sparse, see-through, dithered haze", 30.7% of the
spike bed removed — and diagnosed it as a splat/box axis mismatch: the splat
0.25 m short on Z at each end while overshooting ±X by 0.46 m. A clip box
rotated by ~90° would produce exactly that signature. But 0129 expressed
Gaussians "in the object's own RoomPlan-box frame", so if it used this same
convention its diagnosis inherits the same error, and that is precisely why
this is not being called a root cause here.

## What we did not do, and why

**The one-line fix in `SplatViewer.tsx` is not applied.** Negating the yaw
there changes what every existing room renders. Three reasons to leave it:

1. 0104 adjudicated the clip **by eye**, and 0080/0085 make the operator's
   eyes the standard for "reads right". A rendering change to every room is
   theirs to accept, not a side effect of a stage-2 build.
2. Both instruments compare the box to the WALLS. Neither compares the box to
   the SPLAT, and the clip's job is to cut the splat. The physical argument is
   strong — RoomPlan boxes are wall-aligned and only one sign reproduces that
   — but the decisive test is a render A/B, which is an operator walk.
3. If the corollary above is right, this is a real quality win and deserves to
   be measured properly rather than smuggled in.

**The solver uses the correct convention**, because it is doing new geometry
and has no reason to inherit an error. One visible consequence: on a room
where the clip is mis-oriented, the measured outline (drawn from the box, at
the correct yaw) and the clipped splat will disagree. That is the pre-existing
defect becoming visible, not a new one.

Written down at both sites — `room_geometry.OrientedBox.local_axes_xz` carries
the measurement, and the clip call site in `SplatViewer.tsx` carries a pointer
to it — so the next session cannot miss it.

## What would change this decision

- **An operator walk on the A/B.** Render one real room with `yaw_rad` and
  with `−yaw_rad` in the clip and look. That is the whole remaining question.
- **Class-6 truncation closes.** Then the overshoot that makes clipping
  necessary shrinks, and the stakes of getting its orientation right change.
- **Perception changes how it emits `yaw_rad`.** The convention is measured
  off shipped data, not read out of `box_placement.py`; if that code ever
  changes sign, the tests in `test_room_geometry.py::TestYawConvention` fail
  loudly, which is what they are for.
