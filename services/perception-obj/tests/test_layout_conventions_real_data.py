"""Real-data regression pin for the SAM 3D layout conventions (decision 0065).

Six objects from the first real capture (scene 25a14caf) with their
recorded raw layout rotations (manifest layout_prior.raw_rotation,
verbatim model output) and camera poses (preserved bundle). Each object's
physical orientation is known from the capture photos: doors and cabinets
stand plumb, the curtain hangs, artwork sits flat on the wall, the bed
lies flat FACE-UP. The verdict chain — wxyz read, CONJUGATED (the
model's quaternion maps camera→local), pytorch3d camera basis
diag(-1,1,-1) — must map each object's semantic canonical axis to within
the pinned angle of its physical direction, WITH the right sign where a
sign is knowable.

Three families of pins, in increasing sign-sensitivity (the first probe
shipped a wrong basis — the 180°-about-camera-Y twin of the truth —
because it relied on the first family alone):
  * axis-LINE pins: canonical axis within N° of vertical/horizontal as an
    unsigned line. Blind to 180° flips; kept for tilt regressions.
  * SIGNED-axis pins: the bed's duvet face (canonical +Z, established by
    color asymmetry of the real splat) and the chair's +Z must point UP,
    not down. These fail loudly under the identity-basis twin.
  * TRANSLATION-DIRECTION pins: the model's layout translation, mapped
    through the basis, must point from the camera toward the
    triangulated (convention-independent) object center. Pure geometry,
    fully sign-sensitive — the instrument that settled the basis.

Tolerances are pinned at the accuracy ACHIEVED on this data (plus ~2°),
not at loose thresholds.

These tests exercise the production path: extract_layout() (order +
conjugation) -> rotation_world_from_layout() (basis + pose lift), plus
the module basis constant directly for the translation pins.

Run from repo root:

    python -m pytest services/perception-obj/tests/test_layout_conventions_real_data.py -v
"""
from __future__ import annotations

import math

import numpy as np
import pytest

import placement
from roomstudio_schemas.capture_bundle_pb2 import CaptureBundle

# --- Recorded real data: scene 25a14caf ------------------------------------
# Camera pose quaternions (xyzw, ARKit world-from-camera) per frame index.
CAMERA_QUAT_XYZW = {
    0: (-0.098697, -0.022193, -0.700617, 0.706330),
    18: (-0.543685, 0.488530, -0.450641, 0.512511),
    28: (0.677954, -0.663067, 0.203857, -0.243232),
}

# Raw layout rotations exactly as SAM 3D emitted them (wxyz), keyed by
# (frame_index, mask_index) — copied verbatim from the ready manifest's
# layout_prior.raw_rotation.
RAW_ROTATION = {
    (0, 1): (0.076726, -0.073680, 0.763699, -0.636744),   # door
    (18, 0): (0.025013, 0.037700, 0.630318, 0.775017),    # cabinet
    (18, 1): (0.345910, -0.610788, -0.596639, -0.388860), # bed
    (18, 3): (0.003145, 0.765639, -0.182814, 0.616726),   # chair
    (28, 0): (0.941448, -0.326645, -0.079467, 0.025763),  # artwork
    (28, 1): (0.931919, 0.361710, -0.005628, 0.025721),   # curtain
}

_AXES = {"x": np.array([1.0, 0, 0]), "y": np.array([0, 1.0, 0]), "z": np.array([0, 0, 1.0])}

# (frame, mask, label, canonical axis, expectation, pinned max angle from it)
# The canonical axis semantics come from each splat's measured extents
# (e.g. the bed's thin axis is canonical Z, the door's height is canonical
# X) — canonical frames are per-reconstruction, so these pins are valid
# for exactly these recorded reconstructions.
PINS = [
    (0, 1, "door", "x", "vertical", 4.0),        # achieved 2.5
    (0, 1, "door", "y", "horizontal", 4.0),      # achieved 2.5 off horizontal
    (18, 0, "cabinet", "x", "vertical", 3.5),    # achieved 1.7
    (28, 1, "curtain", "x", "vertical", 7.0),    # achieved 4.8
    (28, 1, "curtain", "z", "horizontal", 3.0),  # achieved 0.9 off horizontal
    (28, 0, "artwork", "x", "vertical", 8.0),    # achieved 6.2
    (28, 0, "artwork", "y", "horizontal", 6.0),  # achieved 3.6 off horizontal
    (18, 1, "bed", "z", "vertical", 23.0),       # achieved 20.7 (noisy obs)
    (18, 3, "chair", "z", "vertical", 17.0),     # achieved 14.9
]

# Signed pins: canonical +Z of these reconstructions is their semantic UP
# (bed: the duvet face carries the LIGHT colors — measured slab
# brightness 0.767 on +Z vs 0.382 on -Z of the real frame-18 splat), so
# the world image of +Z must have a POSITIVE vertical component. The
# identity-basis twin sends both NEGATIVE (face-down) — the regression
# the first probe missed.
SIGNED_UP_PINS = [
    (18, 1, "bed", 0.5),    # achieved +0.94
    (18, 3, "chair", 0.5),  # achieved +0.97
]

# Translation-direction pins: (label, frame, cam_quat_xyzw, cam_pos,
# t_layout from the production sidecar, triangulated center_world from
# the fused manifest). B @ t_layout must align with the camera->center
# direction. Achieved dots under diag(-1,1,-1): 0.94-1.00; identity
# scores NEGATIVE on every row.
TRANSLATION_PINS = [
    ("bed", 116,
     (0.674319, -0.517985, 0.199880, -0.486860),
     (-0.630373, -0.075065, 1.761533),
     (-0.239391, 0.582202, 1.435286),
     (-1.374418, -0.903125, 1.549894)),
    ("bed", 18,
     (-0.543685, 0.488530, -0.450641, 0.512511),
     (-0.281136, 0.041637, 0.127982),
     (-0.526480, -0.477516, 1.399245),
     (-1.005161, -0.262961, 0.521690)),
    ("curtain", 105,
     (0.696598, -0.656247, -0.020831, -0.289235),
     (-0.807838, -0.046057, 0.823107),
     (0.235385, -0.143320, 1.989225),
     (-0.996111, -0.303813, 2.045214)),
    ("door", 67,
     (0.319938, -0.098088, -0.638988, 0.692613),
     (-1.169780, 0.196276, 0.254248),
     (-0.523318, -0.262040, 1.486459),
     (-1.043011, 0.107793, -0.035046)),
    ("table lamp", 116,
     (0.674319, -0.517985, 0.199880, -0.486860),
     (-0.630373, -0.075065, 1.761533),
     (0.341062, 0.055109, 1.813480),
     (-2.057827, -0.451242, 2.529120)),
]


def _camera_pose(frame_index: int):
    frame = CaptureBundle().frames.add()
    q = CAMERA_QUAT_XYZW[frame_index]
    frame.camera_pose.quat_x = q[0]
    frame.camera_pose.quat_y = q[1]
    frame.camera_pose.quat_z = q[2]
    frame.camera_pose.quat_w = q[3]
    return frame.camera_pose


def _world_rotation(frame_index: int, mask_index: int) -> np.ndarray:
    """Recorded raw rotation through the PRODUCTION chain."""
    layout = placement.extract_layout(
        {"rotation": list(RAW_ROTATION[(frame_index, mask_index)])}
    )
    assert layout is not None
    return placement.rotation_world_from_layout(layout, _camera_pose(frame_index))


def _line_angle_to_vertical_deg(v: np.ndarray) -> float:
    return math.degrees(math.acos(min(1.0, abs(float(v[1])))))


@pytest.mark.parametrize(
    "frame,mask,label,axis,expectation,max_deg",
    PINS,
    ids=[f"{p[2]}-f{p[0]}-{p[3]}-{p[4]}" for p in PINS],
)
def test_verdict_conventions_on_real_capture(frame, mask, label, axis, expectation, max_deg):
    R = _world_rotation(frame, mask)
    v = R @ _AXES[axis]
    angle_to_vertical = _line_angle_to_vertical_deg(v)
    if expectation == "vertical":
        assert angle_to_vertical <= max_deg, (
            f"{label} canonical +{axis.upper()} should be plumb; "
            f"{angle_to_vertical:.1f} deg off vertical"
        )
    else:
        assert 90.0 - angle_to_vertical <= max_deg, (
            f"{label} canonical +{axis.upper()} should be horizontal; "
            f"{90.0 - angle_to_vertical:.1f} deg off horizontal"
        )


def test_min_axis_metric_matches_bed_pin():
    """The quality metric (min axis to vertical) on the bed observation
    equals the bed's thin-axis deviation — no other axis is closer."""
    R = _world_rotation(18, 1)
    got = placement.min_axis_to_vertical_deg(R)
    assert got == pytest.approx(20.7, abs=0.5)


@pytest.mark.parametrize(
    "frame,mask,label,min_up",
    SIGNED_UP_PINS,
    ids=[f"{p[2]}-f{p[0]}-signed-up" for p in SIGNED_UP_PINS],
)
def test_semantic_up_axis_points_up_signed(frame, mask, label, min_up):
    R = _world_rotation(frame, mask)
    vert = float((R @ _AXES["z"])[1])
    assert vert >= min_up, (
        f"{label} semantic up (canonical +Z) has vertical component "
        f"{vert:+.2f} — face-down/flipped (identity-twin regression?)"
    )


def test_layout_translations_point_at_true_centers():
    """The basis constant, applied to the model's own translation
    predictions, must point each source observation at its triangulated
    center (pure sign-sensitive geometry — the instrument that settled
    diag(-1,1,-1) over its identity twin)."""
    from roomstudio_schemas.pose_math import quat_to_rotmat

    B = placement._SAM3D_CAM_TO_ARKIT_CAM
    for label, _f, cam_q, cam_p, t_layout, center in TRANSLATION_PINS:
        R_wc = quat_to_rotmat(cam_q)
        c_cam = R_wc.T @ (np.asarray(center) - np.asarray(cam_p))
        c_cam /= np.linalg.norm(c_cam)
        tb = B @ np.asarray(t_layout)
        tb /= np.linalg.norm(tb)
        dot = float(np.dot(c_cam, tb))
        assert dot >= 0.90, f"{label}: basis-mapped translation dot {dot:+.2f}"
        # And the identity twin must fail this — pin the discrimination.
        ti = np.asarray(t_layout) / np.linalg.norm(t_layout)
        assert float(np.dot(c_cam, ti)) < 0.0, (
            f"{label}: identity basis unexpectedly matches — pin is vacuous"
        )


@pytest.mark.parametrize(
    "wrong_chain",
    ["shipped_0052", "candidate_0063"],
)
def test_wrong_conventions_fail_the_bed(wrong_chain):
    """Discriminator: the two previously-considered conventions put the
    bed's thin axis far from vertical on the same recorded data — proving
    the pins above actually distinguish conventions and did not pass
    vacuously. (0052 shipped wxyz-unconjugated + CV basis; 0063's offline
    candidate was xyzw-as-read + identity.)"""
    a, b, c, d = RAW_ROTATION[(18, 1)]
    from roomstudio_schemas.pose_math import quat_to_rotmat

    if wrong_chain == "shipped_0052":
        q = (b, c, d, a)  # wxyz read, NOT conjugated -> xyzw
        B = np.diag([1.0, -1.0, -1.0])
    else:
        q = (a, b, c, d)  # xyzw as-read
        B = np.eye(3)
    n = math.sqrt(sum(v * v for v in q))
    R_layout = quat_to_rotmat(tuple(v / n for v in q))
    R_wc = quat_to_rotmat(CAMERA_QUAT_XYZW[18])
    v = (R_wc @ B @ R_layout) @ _AXES["z"]
    assert _line_angle_to_vertical_deg(v) > 45.0
