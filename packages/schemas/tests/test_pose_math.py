"""Unit tests for roomstudio_schemas.pose_math.

These pin down the rotation operations that interpret the Pose message's
quaternion fields. Every Python consumer of the bundle imports from
pose_math; if any of these break, downstream code silently misinterprets
poses. Failures here are load-bearing.

Run from repo root:

    python -m pytest packages/schemas/tests/test_pose_math.py -v
"""
from __future__ import annotations

import math

import numpy as np
import pytest
from roomstudio_schemas.pose_math import (
    conjugate_quat,
    quat_mul,
    quat_norm,
    quat_to_rotmat,
    rotate_vec_by_quat,
    rotation_angle_deg,
    rotmat_to_quat,
)

SQRT2_2 = math.sqrt(2) / 2
TOL = 1e-12


# -----------------------------------------------------------------------------
# rotate_vec_by_quat — canonical rotations
# -----------------------------------------------------------------------------

def test_identity_quaternion_preserves_vector():
    """q = (0,0,0,1) is the identity rotation."""
    v = (1.0, 2.0, 3.0)
    out = rotate_vec_by_quat(v, (0, 0, 0, 1))
    assert all(abs(o - vi) < TOL for o, vi in zip(out, v))


def test_90deg_about_y_maps_x_to_neg_z():
    """Right-handed: 90° about +Y rotates +X into -Z.
    quat = (0, sin(45°), 0, cos(45°))."""
    q = (0, SQRT2_2, 0, SQRT2_2)
    out = rotate_vec_by_quat((1, 0, 0), q)
    assert all(abs(o - e) < TOL for o, e in zip(out, (0, 0, -1)))


def test_90deg_about_y_maps_z_to_x():
    q = (0, SQRT2_2, 0, SQRT2_2)
    out = rotate_vec_by_quat((0, 0, 1), q)
    assert all(abs(o - e) < TOL for o, e in zip(out, (1, 0, 0)))


def test_180deg_about_z_flips_x_and_y():
    """180° about +Z. quat = (0, 0, 1, 0). Maps +X to -X, +Y to -Y."""
    q = (0, 0, 1, 0)
    out_x = rotate_vec_by_quat((1, 0, 0), q)
    out_y = rotate_vec_by_quat((0, 1, 0), q)
    assert all(abs(o - e) < TOL for o, e in zip(out_x, (-1, 0, 0)))
    assert all(abs(o - e) < TOL for o, e in zip(out_y, (0, -1, 0)))


def test_rotation_preserves_length():
    """Unit quaternions preserve vector length."""
    q = (0.1, 0.2, 0.3, math.sqrt(1 - 0.01 - 0.04 - 0.09))
    v = (1.5, -2.5, 3.5)
    out = rotate_vec_by_quat(v, q)
    in_len = math.sqrt(sum(c * c for c in v))
    out_len = math.sqrt(sum(c * c for c in out))
    assert abs(in_len - out_len) < TOL


# -----------------------------------------------------------------------------
# conjugate_quat — inverse rotation
# -----------------------------------------------------------------------------

def test_conjugate_negates_vector_part():
    qx, qy, qz, qw = conjugate_quat((0.1, 0.2, 0.3, 0.5))
    assert (qx, qy, qz, qw) == (-0.1, -0.2, -0.3, 0.5)


def test_rotate_then_conjugate_is_identity():
    """For a unit quaternion, rotating by q then by conjugate(q) recovers
    the original vector. This is THE defining property of the inverse rotation."""
    q = (0.1, 0.2, 0.3, math.sqrt(1 - 0.01 - 0.04 - 0.09))
    v = (1.2, -3.4, 5.6)
    fwd = rotate_vec_by_quat(v, q)
    back = rotate_vec_by_quat(fwd, conjugate_quat(q))
    assert all(abs(b - vi) < TOL for b, vi in zip(back, v))


# -----------------------------------------------------------------------------
# quat_mul — composition
# -----------------------------------------------------------------------------

def test_quat_mul_identity_is_neutral():
    q = (0.1, 0.2, 0.3, math.sqrt(1 - 0.01 - 0.04 - 0.09))
    identity = (0.0, 0.0, 0.0, 1.0)
    assert all(abs(a - b) < TOL for a, b in zip(quat_mul(identity, q), q))
    assert all(abs(a - b) < TOL for a, b in zip(quat_mul(q, identity), q))


def test_quat_mul_with_conjugate_is_identity():
    q = (0.1, 0.2, 0.3, math.sqrt(1 - 0.01 - 0.04 - 0.09))
    x, y, z, w = quat_mul(q, conjugate_quat(q))
    assert abs(w - 1.0) < TOL
    assert max(abs(x), abs(y), abs(z)) < TOL


def test_quat_mul_matches_matrix_composition():
    """The composition convention, pinned against the matrix path: quat_mul(a, b)
    applies b first. Every consumer that reorients an object by pre-multiplying a
    world-frame rotation depends on this order being the one written down."""
    a = (0.2, -0.4, 0.1, math.sqrt(1 - 0.04 - 0.16 - 0.01))
    b = (-0.3, 0.5, 0.2, math.sqrt(1 - 0.09 - 0.25 - 0.04))
    composed = quat_to_rotmat(quat_mul(a, b))
    assert np.allclose(composed, quat_to_rotmat(a) @ quat_to_rotmat(b), atol=1e-12)


def test_quat_mul_is_not_commutative():
    """Guards the argument order: a symmetric implementation would pass every
    test above and silently compose rotations the wrong way round."""
    a = (0.2, -0.4, 0.1, math.sqrt(1 - 0.04 - 0.16 - 0.01))
    b = (-0.3, 0.5, 0.2, math.sqrt(1 - 0.09 - 0.25 - 0.04))
    assert max(abs(p - q) for p, q in zip(quat_mul(a, b), quat_mul(b, a))) > 0.1


def test_quat_mul_preserves_unit_norm():
    a = (0.2, -0.4, 0.1, math.sqrt(1 - 0.04 - 0.16 - 0.01))
    b = (-0.3, 0.5, 0.2, math.sqrt(1 - 0.09 - 0.25 - 0.04))
    assert abs(quat_norm(quat_mul(a, b)) - 1.0) < TOL


# -----------------------------------------------------------------------------
# Cross-check against the rotation-matrix path
# -----------------------------------------------------------------------------

def test_quat_path_matches_matrix_path():
    """For a known rotation R, converting R -> q via Shepperd, then rotating
    a vector with conjugate(q), must equal R.T @ v.

    This test is the WHOLE REASON we can use the quaternion path everywhere
    and trust that it agrees with the matrix-path formulation in physics
    textbooks. If this passes, every other consumer of pose_math can stop
    worrying about whether quat ≡ matrix.
    """
    # A non-trivial rotation: 30° about (1,2,3)/||(1,2,3)||
    axis = np.array([1.0, 2.0, 3.0])
    axis = axis / np.linalg.norm(axis)
    theta = math.radians(30)
    K = np.array([
        [0, -axis[2], axis[1]],
        [axis[2], 0, -axis[0]],
        [-axis[1], axis[0], 0],
    ])
    R = np.eye(3) + math.sin(theta) * K + (1 - math.cos(theta)) * (K @ K)

    q = rotmat_to_quat(R)
    v = (0.0, -1.0, 0.0)  # gravity in world
    via_matrix = R.T @ np.array(v)
    via_quat = rotate_vec_by_quat(v, conjugate_quat(q))
    err = np.linalg.norm(via_matrix - np.array(via_quat))
    assert err < 1e-9, f"matrix path and quaternion path disagree: err={err}"


# -----------------------------------------------------------------------------
# rotmat_to_quat — Shepperd's method covers all four branches
# -----------------------------------------------------------------------------

@pytest.mark.parametrize("axis,angle_deg", [
    ([1, 0, 0], 10),    # near identity -> hits 'tr > 0' branch
    ([1, 0, 0], 170),   # near 180° about X -> hits 'm00 largest' branch
    ([0, 1, 0], 170),   # near 180° about Y -> hits 'm11 largest' branch
    ([0, 0, 1], 170),   # near 180° about Z -> hits 'm22 largest' branch
])
def test_shepperd_branches_all_unit_norm(axis, angle_deg):
    """Each Shepperd branch must produce a unit-norm quaternion."""
    axis = np.array(axis, dtype=float)
    axis = axis / np.linalg.norm(axis)
    theta = math.radians(angle_deg)
    K = np.array([
        [0, -axis[2], axis[1]],
        [axis[2], 0, -axis[0]],
        [-axis[1], axis[0], 0],
    ])
    R = np.eye(3) + math.sin(theta) * K + (1 - math.cos(theta)) * (K @ K)
    q = rotmat_to_quat(R)
    assert abs(quat_norm(q) - 1.0) < 1e-9


def test_rotmat_to_quat_rejects_wrong_shape():
    """Defensive: passing something that isn't 3x3 should fail loudly."""
    with pytest.raises(ValueError):
        rotmat_to_quat(np.eye(4))


# -----------------------------------------------------------------------------
# quat_norm
# -----------------------------------------------------------------------------

def test_quat_norm_unit():
    assert abs(quat_norm((0, 0, 0, 1)) - 1.0) < TOL
    assert abs(quat_norm((SQRT2_2, 0, 0, SQRT2_2)) - 1.0) < TOL


def test_quat_norm_scaled():
    assert abs(quat_norm((0, 0, 0, 2)) - 2.0) < TOL
    assert abs(quat_norm((3, 0, 0, 4)) - 5.0) < TOL  # 3-4-5 triangle


# -----------------------------------------------------------------------------
# rotation_angle_deg — the one rotation distance
# -----------------------------------------------------------------------------

def test_rotation_angle_identical_is_zero():
    R = quat_to_rotmat((SQRT2_2, 0, 0, SQRT2_2))
    assert rotation_angle_deg(R, R) == pytest.approx(0.0, abs=1e-9)


@pytest.mark.parametrize("axis,angle_deg", [
    ([1, 0, 0], 30.0),
    ([0, 1, 0], 90.0),
    ([0, 0, 1], 150.0),
    ([1, 1, 1], 45.0),
])
def test_rotation_angle_recovers_the_turn(axis, angle_deg):
    """Turning by theta about any axis reads back as theta."""
    axis = np.array(axis, dtype=float)
    axis /= np.linalg.norm(axis)
    half = math.radians(angle_deg) / 2
    q = (*(axis * math.sin(half)), math.cos(half))
    assert rotation_angle_deg(np.eye(3), quat_to_rotmat(q)) == pytest.approx(
        angle_deg, abs=1e-9
    )


def test_rotation_angle_is_symmetric():
    a = quat_to_rotmat((0.2, 0.3, 0.4, math.sqrt(1 - 0.29)))
    b = quat_to_rotmat((SQRT2_2, 0, 0, SQRT2_2))
    assert rotation_angle_deg(a, b) == pytest.approx(rotation_angle_deg(b, a))


def test_rotation_angle_maxes_at_180():
    """A half turn is the farthest two orientations can be, and the trace
    form must not overshoot arccos's domain getting there."""
    flip = np.diag([-1.0, 1.0, -1.0])  # 180 deg about world +Y
    assert rotation_angle_deg(np.eye(3), flip) == pytest.approx(180.0, abs=1e-9)


def test_rotation_angle_clamps_beyond_the_domain():
    """Float error at the endpoints returns the endpoint, never NaN."""
    nudged = np.eye(3) * (1 + 1e-12)
    assert rotation_angle_deg(nudged, np.eye(3)) == pytest.approx(0.0, abs=1e-6)
