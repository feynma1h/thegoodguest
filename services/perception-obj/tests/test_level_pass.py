"""Decision 0146 — levelling an upright-resting object.

The pass is a rotation, so it is a claim, and the tests are written around
the two gates that keep it honest rather than around the happy path:

  * the CLASS gate — gravity is evidence about a lamp's rotation and says
    nothing about an artwork's, whose relationship is with a measured wall;
  * the EVIDENCE gate — the correction ships only if the object's
    underside measurably flattens, so a mis-identified vertical axis costs
    nothing.

Both are pinned in both directions: a case each gate admits and a case
each gate refuses, because a gate that never fires and a gate that never
refuses are the same bug.

Real-data pins for the same pass — the four objects the acceptance walk
named, on their own splats — live in test_level_real_data.py.
"""
from __future__ import annotations

import fusion
import numpy as np
import pytest
from roomstudio_schemas.placement_math import minimal_rotation
from roomstudio_schemas.pose_math import quat_to_rotmat, rotmat_to_quat


class Ctx:
    """RefinementContext stand-in: splats by uri, nothing else."""

    budget = None
    min_remaining_s = 0.0

    def __init__(self, splats=None):
        self.splats = splats or {}
        self.get_appearance = None
        self.get_rgb = None

    def get_roomplan(self):
        return None

    def get_room_planes(self):
        return None

    def get_splat(self, uri):
        return self.splats.get(uri)

    def get_camera(self, frame_index):
        return None

    def mask_for(self, *a):
        return None

    def evidence_for(self, *a):
        return None


def _slab(nx=13, ny=5, nz=13, half=(0.3, 0.05, 0.3)):
    """A filled slab centred on the origin — flat-bottomed by construction."""
    return np.stack(np.meshgrid(
        np.linspace(-half[0], half[0], nx),
        np.linspace(-half[1], half[1], ny),
        np.linspace(-half[2], half[2], nz),
        indexing="ij",
    ), axis=-1).reshape(-1, 3).astype(np.float64)


def _tilted(deg: float, half=(0.3, 0.05, 0.3)):
    """(points, rotation_xyzw) for a slab tilted `deg` about world +Z."""
    a = np.radians(deg)
    R = np.array([
        [np.cos(a), -np.sin(a), 0.0],
        [np.sin(a), np.cos(a), 0.0],
        [0.0, 0.0, 1.0],
    ])
    return _slab(half=half), tuple(float(c) for c in rotmat_to_quat(R))


def _round_bottomed(n=40, radius=0.15, height=1.2, layers=10):
    """A vase: a column of rings closed by a hemispherical base. Its
    underside has no flat to find, so no rotation flattens it."""
    u = np.linspace(-1.0, 1.0, n)
    X, Z = np.meshgrid(u, u)
    inside = X**2 + Z**2 <= 1.0
    x, z = X[inside], Z[inside]
    y = -np.sqrt(np.maximum(1.0 - x**2 - z**2, 0.0))
    return np.concatenate([
        np.stack([x * radius, y * radius + h, z * radius], axis=1)
        for h in np.linspace(0.0, height, layers)
    ])


def _obj(label, pts_uri="gs://o/s.ply", rotation=(0.0, 0.0, 0.0, 1.0), **kw):
    o = {
        "object_id": "obj_000",
        "label": label,
        "placed": True,
        "splat_gcs_uri": pts_uri,
        "world_transform": {
            "position": [0.0, 1.0, 0.0],
            "rotation_xyzw": list(rotation),
            "scale": 1.0,
        },
        "quality": {},
    }
    o.update(kw)
    return o


def _tilt_deg(obj) -> float:
    """Angle from world up to the nearest axis of an object's rotation."""
    R = quat_to_rotmat(tuple(obj["world_transform"]["rotation_xyzw"]))
    return min(
        float(np.degrees(np.arccos(np.clip(s * R[1, i], -1.0, 1.0))))
        for i in range(3) for s in (1.0, -1.0)
    )


class TestLevelling:
    def test_a_tilted_lamp_is_stood_up(self):
        pts, rot = _tilted(12.0)
        obj = _obj("table lamp", rotation=rot)
        out = fusion._level_upright_object(obj, Ctx({"gs://o/s.ply": pts}))
        assert out["quality"]["level_correction_deg"] == pytest.approx(12.0, abs=0.5)
        assert _tilt_deg(out) < 0.5
        assert "levelled" in out["constraints_applied"]

    def test_the_correction_is_the_measured_tilt_and_no_more(self):
        """A minimal rotation, so a levelled object keeps whatever yaw it
        had — the DOF three instrument families are measured dead on
        (0081, 0104) must not be touched by a pass that has no evidence
        about it."""
        pts, rot = _tilted(20.0)
        obj = _obj("speaker", rotation=rot)
        ctx = Ctx({"gs://o/s.ply": pts})
        out = fusion._level_upright_object(obj, ctx)
        R0 = quat_to_rotmat(tuple(rot))
        R1 = quat_to_rotmat(tuple(out["world_transform"]["rotation_xyzw"]))
        delta = R1 @ R0.T
        angle = np.degrees(np.arccos(np.clip((np.trace(delta) - 1) / 2, -1.0, 1.0)))
        assert angle == pytest.approx(20.0, abs=0.5)

    def test_levelling_rotates_about_the_mass_not_the_origin(self):
        """The object stays where it is: an off-centre object levelled
        about the world origin would swing across the room."""
        pts, rot = _tilted(15.0)
        obj = _obj("monitor", rotation=rot)
        obj["world_transform"]["position"] = [4.0, 1.0, -3.0]
        out = fusion._level_upright_object(obj, Ctx({"gs://o/s.ply": pts}))
        moved = np.linalg.norm(
            np.array(out["world_transform"]["position"]) - np.array([4.0, 1.0, -3.0])
        )
        assert moved < 0.05

    def test_an_upright_object_is_left_alone(self):
        obj = _obj("table lamp")
        out = fusion._level_upright_object(obj, Ctx({"gs://o/s.ply": _slab()}))
        assert out is obj

    def test_a_wildly_wrong_rotation_is_refused(self):
        """Past the bound, which way is up stops being a reading and
        becomes a guess.

        The corner rotation — the one taking the body diagonal onto world
        up — is the worst case that exists: it leaves all three of the
        object's axes at 54.7 degrees from vertical, which is the furthest
        the NEAREST axis can ever be. Anything the bound refuses looks
        like this.
        """
        pts = _slab(nx=17, ny=11, nz=7, half=(0.40, 0.25, 0.12))
        R = minimal_rotation(
            np.array([1.0, 1.0, 1.0]) / np.sqrt(3.0), np.array([0.0, 1.0, 0.0])
        ).T
        obj = _obj("speaker", rotation=tuple(float(c) for c in rotmat_to_quat(R)))
        out = fusion._level_upright_object(obj, Ctx({"gs://o/s.ply": pts}))
        assert out is obj


class TestClassGate:
    def test_a_wall_class_is_never_levelled(self):
        """An artwork's rotation is owed to a measured wall, not to
        gravity — and levelling them measured actively worse."""
        pts, rot = _tilted(12.0)
        for label in ("artwork", "curtain", "mirror", "clock", "door"):
            obj = _obj(label, rotation=rot)
            out = fusion._level_upright_object(obj, Ctx({"gs://o/s.ply": pts}))
            assert out is obj, label

    def test_a_box_anchored_object_is_never_levelled(self):
        """A RoomPlan box is pure yaw by construction: there is no tilt to
        correct, and its rotation is measurement."""
        pts, rot = _tilted(12.0)
        obj = _obj("table", rotation=rot, roomplan_box={"box_id": "box_00"})
        out = fusion._level_upright_object(obj, Ctx({"gs://o/s.ply": pts}))
        assert out is obj


class TestEvidenceGate:
    def test_a_correction_that_does_not_flatten_is_discarded(self):
        """A round-bottomed object — a vase, a potted plant, both in the
        vocabulary — has no flat underside to flatten, so its own mass
        carries no evidence about which way it leans and the pass declines
        to invent one. That is the conservative direction and the whole
        point of the gate: where the object cannot show a contact, the
        rotation it shipped with stands."""
        _flat, rot = _tilted(12.0)
        pts = _round_bottomed()
        obj = _obj("vase", rotation=rot)
        out = fusion._level_upright_object(obj, Ctx({"gs://o/s.ply": pts}))
        assert out is obj

    def test_the_gate_admits_a_real_improvement(self):
        """The matched half of the test above: the same instrument on an
        object whose underside genuinely flattens does ship."""
        pts, rot = _tilted(9.0, half=(0.4, 0.06, 0.4))
        obj = _obj("speaker", rotation=rot)
        out = fusion._level_upright_object(obj, Ctx({"gs://o/s.ply": pts}))
        assert out is not obj
        assert out["quality"]["bottom_flatness_m"] < 0.01


class TestPassOrdering:
    def test_levelling_runs_before_the_support_snap(self):
        """A tilted object's bottom is a corner, so its contact height is
        only meaningful once it stands up. Pinned on the source rather
        than by eye: whichever call comes first in the driver wins, and
        getting it backwards would land objects at a corner's height."""
        import inspect
        src = inspect.getsource(fusion.fuse_scene_objects_with_meta)
        assert src.index("_level_upright_object") < src.index("_support_surfaces")

    def test_levelling_is_inert_without_the_refinement_pass(self):
        """PLACEMENT_REFINE=0 is the rollback lever for every 0067-and-
        later pass; this one must sit behind it like the rest."""
        import inspect
        src = inspect.getsource(fusion.fuse_scene_objects_with_meta)
        assert "_level_upright_object" in src.split("if run_refine")[-1]
