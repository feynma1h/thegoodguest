"""Pose math for the capture bundle.

The Pose message in capture_bundle.proto carries (pos_x, pos_y, pos_z,
quat_x, quat_y, quat_z, quat_w). This module is the single Python
implementation of operations on those quaternions:

  - rotate a vector by a unit quaternion
  - conjugate (inverse for unit quaternions)
  - compose two rotations (Hamilton product)
  - convert a 3x3 rotation matrix to a unit quaternion
  - convert a unit quaternion to a 3x3 rotation matrix
  - average a set of unit quaternions

The iOS capture client uses ARKit's simd_quatf directly and never calls
this code. But the conventions encoded here are the same ones ARKit
follows: unit quaternions in (x, y, z, w) order; rotation by a quaternion
takes camera-local vectors into world coordinates.

This module is small on purpose. If the math here ever changes, every
consumer in the Python codebase changes with it because they all import
from here.

Tests live at packages/schemas/tests/test_pose_math.py and pin canonical
rotations, conjugate-is-inverse, length preservation, and a cross-check
against the rotation-matrix path (R.T @ v == rotate_by_quat(v, conjugate(q))).
"""
from __future__ import annotations

import math
from typing import Tuple

import numpy as np

# Quaternion in (qx, qy, qz, qw) order — matches ARKit simd_quatf.vector,
# glTF, Unity, ARCore.
QuatXYZW = Tuple[float, float, float, float]
Vec3 = Tuple[float, float, float]


def rotate_vec_by_quat(v: Vec3, q: QuatXYZW) -> Vec3:
    """Rotate vector `v` by unit quaternion `q = (qx, qy, qz, qw)`.

    Formula (Fabian Giesen / 'rotate a vector by quaternion in 12 muls'):
        t  = 2 * (u × v)        where u = (qx, qy, qz)
        v' = v + qw * t + u × t

    Equivalent to v' = q · (0, v) · q⁻¹ written out, but reorganized to
    share the cross product and avoid intermediate quaternion multiplies.
    Used in this exact form by glm and Eigen's Quaternion::_transformVector.

    For unit quaternions the result is exact to float precision; this
    function does not renormalize. A non-unit q does NOT merely scale the
    result: the 12-mul form equals q · (0, v) · q⁻¹ only when ||q|| == 1,
    so off the unit sphere it returns a different rotation entirely. With
    q = 2·(0, √2/2, 0, √2/2) and v = (1, 0, 0) this returns (-3, 0, -4),
    where 4× the unit answer would be (0, 0, -4). The proto contract
    guarantees unit norm and ingest enforces it within QUAT_NORM_TOLERANCE
    (services/api-internal/validation.py `_check_quaternion_norms`), so we
    don't pay for a normalize on the hot path — normalize first if your q
    comes from anywhere other than a validated Pose.
    """
    vx, vy, vz = v
    qx, qy, qz, qw = q
    # t = 2 * cross(u, v)
    tx = 2.0 * (qy * vz - qz * vy)
    ty = 2.0 * (qz * vx - qx * vz)
    tz = 2.0 * (qx * vy - qy * vx)
    # v' = v + qw * t + cross(u, t)
    rx = vx + qw * tx + (qy * tz - qz * ty)
    ry = vy + qw * ty + (qz * tx - qx * tz)
    rz = vz + qw * tz + (qx * ty - qy * tx)
    return rx, ry, rz


def conjugate_quat(q: QuatXYZW) -> QuatXYZW:
    """Quaternion conjugate: negate the vector part, keep the scalar.

    For a unit quaternion this is the inverse rotation — i.e. if `q`
    rotates camera-local vectors into world, then `conjugate_quat(q)`
    rotates world vectors into camera-local.
    """
    qx, qy, qz, qw = q
    return -qx, -qy, -qz, qw


def quat_mul(a: QuatXYZW, b: QuatXYZW) -> QuatXYZW:
    """Hamilton product `a ⊗ b`: the rotation that applies `b` first, then `a`.

    Both operands and the result are (x, y, z, w). Composition order follows
    the same convention as the matrix path — `quat_to_rotmat(quat_mul(a, b))`
    equals `quat_to_rotmat(a) @ quat_to_rotmat(b)` — so pre-multiplying by a
    world-frame rotation reorients an object in place, and post-multiplying
    turns it about its own axes.
    """
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
        aw * bw - ax * bx - ay * by - az * bz,
    )


def rotmat_to_quat(R: np.ndarray) -> QuatXYZW:
    """Convert a 3x3 rotation matrix to a unit quaternion in (x, y, z, w) order.

    Uses Shepperd's method: pick the largest of the four diagonal-derived
    forms to keep the divisor large and avoid numerical issues near
    180-degree rotations.

    The output is renormalized to kill any drift introduced by the
    divisions, so the result is unit-norm to float precision.

    Caller must pass an actual rotation matrix (orthogonal, det = +1);
    this function does not validate. If you pass a near-rotation matrix
    (small drift from orthogonality) the result is still a valid unit
    quaternion, just one whose corresponding matrix is the closest
    rotation to your input — which is the desired behavior.
    """
    if R.shape != (3, 3):
        raise ValueError(f"rotmat_to_quat: expected 3x3, got {R.shape}")
    m00, m01, m02 = R[0]
    m10, m11, m12 = R[1]
    m20, m21, m22 = R[2]
    tr = m00 + m11 + m22
    if tr > 0.0:
        s = math.sqrt(tr + 1.0) * 2.0  # s = 4 * qw
        qw = 0.25 * s
        qx = (m21 - m12) / s
        qy = (m02 - m20) / s
        qz = (m10 - m01) / s
    elif (m00 > m11) and (m00 > m22):
        s = math.sqrt(1.0 + m00 - m11 - m22) * 2.0  # s = 4 * qx
        qw = (m21 - m12) / s
        qx = 0.25 * s
        qy = (m01 + m10) / s
        qz = (m02 + m20) / s
    elif m11 > m22:
        s = math.sqrt(1.0 + m11 - m00 - m22) * 2.0  # s = 4 * qy
        qw = (m02 - m20) / s
        qx = (m01 + m10) / s
        qy = 0.25 * s
        qz = (m12 + m21) / s
    else:
        s = math.sqrt(1.0 + m22 - m00 - m11) * 2.0  # s = 4 * qz
        qw = (m10 - m01) / s
        qx = (m02 + m20) / s
        qy = (m12 + m21) / s
        qz = 0.25 * s
    n = math.sqrt(qx * qx + qy * qy + qz * qz + qw * qw)
    return float(qx / n), float(qy / n), float(qz / n), float(qw / n)


def quat_to_rotmat(q: QuatXYZW) -> np.ndarray:
    """Convert a unit quaternion (x, y, z, w) to a 3x3 rotation matrix.

    Inverse of rotmat_to_quat. The returned matrix R satisfies
        R @ v == rotate_vec_by_quat(v, q)
    for every vector v — i.e. it rotates camera-local vectors into world
    coordinates when q comes from a Pose message. Use this when a whole
    point cloud needs rotating: `points @ R.T` vectorizes what
    rotate_vec_by_quat does one vector at a time.

    Like rotate_vec_by_quat, this assumes unit norm (the proto contract)
    and does not renormalize — and like it, a non-unit q does not scale the
    result. The 1 - 2(...) form is a rotation matrix only for unit q; off
    the unit sphere the returned matrix is not a rotation at all. Normalize
    first if q comes from anywhere other than a validated Pose.
    """
    qx, qy, qz, qw = q
    return np.array([
        [1 - 2 * (qy * qy + qz * qz), 2 * (qx * qy - qz * qw), 2 * (qx * qz + qy * qw)],
        [2 * (qx * qy + qz * qw), 1 - 2 * (qx * qx + qz * qz), 2 * (qy * qz - qx * qw)],
        [2 * (qx * qz - qy * qw), 2 * (qy * qz + qx * qw), 1 - 2 * (qx * qx + qy * qy)],
    ], dtype=np.float64)


def rotation_angle_deg(a: np.ndarray, b: np.ndarray) -> float:
    """The geodesic angle in degrees between two 3x3 rotation matrices —
    how far one orientation must turn, about some axis, to become the other.

    This is the only rotation *distance* in the codebase, and it is a
    distance in the metric sense: symmetric, zero exactly when the two agree,
    and maximal (180 degrees) when they are opposite. Use it to compare two
    independent claims about how one object sits; use per-axis dot products
    instead when the question is about a named axis, because this collapses
    every axis into a single number and cannot say which one disagrees.

    The trace form is clamped before arccos so float error near 0 and 180
    degrees returns the endpoint rather than a domain error.
    """
    cos = (float(np.trace(np.asarray(a) @ np.asarray(b).T)) - 1.0) / 2.0
    return float(math.degrees(math.acos(max(-1.0, min(1.0, cos)))))


def quat_average(quats: "list[QuatXYZW] | tuple[QuatXYZW, ...]") -> QuatXYZW:
    """Average a non-empty set of unit quaternions (Markley's method).

    Returns the unit quaternion maximizing sum-of-squared dot products with
    the inputs: the largest-eigenvalue eigenvector of M = sum(q qᵀ). This is
    the standard rotation average for orientations without weights, and is
    invariant to per-input sign flips (q and -q represent the same rotation,
    and q qᵀ == (-q)(-q)ᵀ).

    The returned sign is chosen to lie in the same hemisphere as the first
    input (dot >= 0), so callers comparing against an input quaternion get
    the nearby representative rather than its negation.
    """
    if not quats:
        raise ValueError("quat_average: need at least one quaternion")
    M = np.zeros((4, 4), dtype=np.float64)
    for q in quats:
        col = np.array(q, dtype=np.float64)
        M += np.outer(col, col)
    # eigh returns eigenvalues ascending; last column is the largest.
    _, vecs = np.linalg.eigh(M)
    avg = vecs[:, -1]
    if float(np.dot(avg, np.array(quats[0], dtype=np.float64))) < 0.0:
        avg = -avg
    avg = avg / np.linalg.norm(avg)
    return float(avg[0]), float(avg[1]), float(avg[2]), float(avg[3])


# -----------------------------------------------------------------------------
# Convenience wrappers tied to the Pose message
# -----------------------------------------------------------------------------

def pose_quat(pose) -> QuatXYZW:
    """Extract the quaternion from a thegoodguest_schemas.Pose protobuf as a
    plain tuple. Keeps consumer code free of the (pose.quat_x, pose.quat_y, ...)
    boilerplate."""
    return pose.quat_x, pose.quat_y, pose.quat_z, pose.quat_w


def pose_position(pose) -> np.ndarray:
    """Extract the position from a thegoodguest_schemas.Pose protobuf as a
    numpy array."""
    return np.array([pose.pos_x, pose.pos_y, pose.pos_z], dtype=np.float64)


def quat_norm(q: QuatXYZW) -> float:
    """Return ||q||. The proto contract requires unit norm within 1e-3."""
    qx, qy, qz, qw = q
    return math.sqrt(qx * qx + qy * qy + qz * qz + qw * qw)
