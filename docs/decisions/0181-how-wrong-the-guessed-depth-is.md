# 0181 — How wrong the guessed depth is, measured on rooms we already argue about

**Date:** 2026-08-16
**Status:** Measured offline on three preserved LiDAR captures; no GPU run

## Context

0180 established that SAM 3D reads a point map on every reconstruction, that
ours is estimated by MoGe from the single RGB frame, and that the point map
conditions the shape branch as well as the layout branch. What it could not say
is how much that costs, and the obvious way to find out — reconstruct one object
both ways — needs a GPU behind a deploy.

There is a cheaper thing to measure first, and it does not need SAM 3D at all:
run the same pinned MoGe on real captured frames and compare its point map with
the LiDAR one, through the normalisation the pipeline applies before the model
sees either.

## What we tried

`outputs/pointmap/` (gitignored). MoGe at the commit the image pins
(`microsoft/MoGe@a8c37341`), `MoGeModel.from_pretrained("Ruicheng/moge-vitl")`,
called as `sam3d_objects.pipeline.depth_models.moge.MoGe` calls it
(`infer(image, force_projection=False)`) on full-resolution frames. LiDAR
through `placement.sam3d_pointmap`, nearest-upsampled to the RGB grid exactly as
`compute_pointmap` would. **42 observations, 8 frames, 3 of the four walk
rooms** — frames chosen for objects already adjudicated: the spike bed, the
spike cabinet, rp7's legless desk, rp7's monitor/tv fork, rp6g1's baseless
monitor.

**First, the frame, because a mirrored point map would make everything below
meaningless.** The layout translation SAM 3D returns is decoded in the point
map's own frame and units, so the model has already told us where it thinks each
object centre is in point-map space, on every observation ever run. Against the
median LiDAR point under each object's own mask:

| candidate frame | median | p90 | beyond 45° |
|---|---|---|---|
| **+X left, +Y up, +Z forward (0180's)** | **3.1°** | **10.0°** | **0%** |
| X not flipped | 26.7° | 47.1° | 12% |
| Y flipped | 22.9° | 48.2° | 19% |
| Z not flipped | 139.0° | 159.5° | 100% |
| identity, no basis change | 157.1° | 172.4° | 100% |

The residual 3.1° is expected and is not error: a mask median is a point on the
visible surface, the layout translation is the object's centre. What matters is
that the rivals are tens of degrees away and two of them put the object behind
the camera. So the point map we would supply lands in the frame the model
answers in, verified by the model rather than by us.

**Then the two halves.**

**Layout — the guess has no usable metric scale, and no constant would fix it.**
MoGe v1 is scale-invariant by construction, so its point map is in arbitrary
units; the `ScaleShiftInvariant` pose decoder metrises the predicted translation
and scale with the scale read off that same map. The factor carrying MoGe units
to metres, measured per frame:

```
spike f10  0.845    rp7 f7    0.755    rp6g1 f57  1.010
spike f273 1.248    rp7 f114  1.630    rp6g1 f97  1.249
spike f354 1.552    rp7 f294  1.177
```

**Range 0.755–1.630, a 2.16× spread across eight frames of three rooms.** A
supplied LiDAR point map makes this factor 1.000 by construction.

**Shape — the relief is broadly right and the tails are not.** Comparing each
object's depth relief (5th-to-95th percentile spread along the camera axis) as a
fraction of its own scene scale, which is what the normalisation leaves the
model to read: **median ratio 1.017**, and the two maps disagree inside the mask
by a **median 10% of the object's own relief**. But the range is 0.62× to 1.72×,
and the disagreement reaches 68%. The worst are small or thin things — rp6g1's
chair 1.72×, rp7's nightstand 1.62×, a table lamp 1.38×, a curtain 0.62× — plus
one large one: the spike bed at **0.677× with 0.209 m of disagreement**, the same
bed 0080 measured ~90° wrong in yaw and 0129 measured 30.7% sheared by its clip
volume. Seen from a second view (f354) the same bed reads 0.931×, so this is a
property of the view, not of the object.

One difference in character, not accuracy: **MoGe returns a value at every pixel
(valid 1.000 on all eight frames) where LiDAR returns 0.89–0.97.** Supplying
measured depth hands the model a learned `invalid_xyz_token` on 3–11% of the
frame in exchange for measurement on the rest.

## What we chose

Record the measurement; change nothing in the pipeline. `models/sam3d.py` still
passes three arguments.

What did land is the input side, tested and unused:
`placement_math.depth_pointmap` (the dense form of the back-projection already
there, NaN for holes, pinned against `unproject_depth` on the pixels it keeps)
and `placement.sam3d_pointmap` (the same map in SAM 3D's camera frame). Passing
it is a keyword argument away, and that argument is what needs the bench.

## Why

Because the honest reading of these numbers is mixed, and the mixed reading is
more useful than either clean one.

The layout half is not mixed: a scale that swings 2.16× across eight frames
cannot be calibrated away, and it is the direct explanation for something this
project already knows by experience. Decision 0052 replaces SAM 3D's translation
and scale with a fit to the LiDAR cloud, and 0065 stopped fusing raw scales
across observations. Those were empirical workarounds for a defect nobody had
measured; this is the defect. Feeding the point map would attack it at the
source rather than downstream of it.

The shape half says a metric point map is **not** a general fix for
reconstruction quality — a median 10% disagreement will not turn a legless desk
into a desk with legs. It says something narrower and still worth having: the
guess is worst exactly where this project's complaints are, on small objects and
on one badly-truncated bed, and where it is worst it is wrong by tens of percent
of the object's own depth. Whether that propagates into the reconstruction is
precisely what the bench proof would answer, and it is the reason to run one
rather than to assume either way.

**Stated plainly so nobody quotes this as more than it is:** this measures the
model's *input*, not its *output*. A conditioning signal being wrong by 10% does
not entail a reconstruction wrong by anything in particular — the sparse
structure generator may be weighting the image far more heavily. Nothing here
tests that.

## What would change this decision

The bench proof: one object reconstructed both ways at an identical camera,
compared on extents against its measured RoomPlan box. If the reconstruction
barely moves, the pointmap path is a layout fix and should be judged as one —
still worth having, given the 2.16×. If the truncated objects fill out, this
becomes the most direct attack on class-6 anyone has proposed and lane D's
scope should be revisited before it is built.

Two limits on the numbers above, both of which a re-run should respect. MoGe ran
here on MPS in float32; production runs it on an L4 under float16 autocast, so
these are the shape of the error rather than the bytes production saw. And the
relief ratio is measured inside SAM's mask, so a mask that leaks onto the floor
behind a chair inflates the guess's relief — which is one plausible reading of
the 1.72× on rp6g1's chair, and a reason not to lean on any single row.
