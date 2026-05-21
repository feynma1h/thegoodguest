# 0002 — Pose representation: position + quaternion, not 4×4 matrix

**Date:** 2026-05-21
**Status:** Decided

## Context

When designing the `Pose` message in `capture_bundle.proto`, two encodings were viable: a 4×4 row-major matrix (16 floats), or position (3 floats) + unit quaternion (4 floats).

## What we tried

Initial draft used a 4×4 matrix, justified post-hoc as "matches ARKit's `simd_float4x4`, matches numpy default; both sides skip a conversion."

## What we chose

Position + unit quaternion in `(qx, qy, qz, qw)` order. Unit norm required within 1e-3. Quaternion rotates camera-local vectors into world.

## Why

- **Wire size:** 7 floats vs 16. ~56% smaller per pose.
- **Validation:** "is q unit-norm?" is one cheap check. "Is this 4×4 a valid rotation?" needs orthogonality + unit length + det=+1 — three checks with tolerance picks.
- **Drift:** rotation matrices drift off SO(3) silently under float arithmetic. Quaternions drift off the unit sphere, which is one renormalize away.
- **Cross-platform parity:** ARKit's `simd_quatf.vector` is already `(ix, iy, iz, r)` matching our `(x, y, z, w)`. ARCore's `Pose` IS pos + quat. No client-side asymmetry if we add Android later.
- **Slerp-friendly:** any future temporal smoothing of poses is natively quaternion-shaped.

The "matches ARKit and numpy" justification was real but one-time. Pos+quat pays back forever after.

## What would change this decision

- If we ever need to represent non-rigid transforms (scale, shear) in the same field — would force a 4×4. Not anticipated; non-rigid lives in scene-graph nodes, not in the capture bundle.
