"""Real-data pins for the room-sanity gate (fusion refinement lock 10).

The measured room is REAL: tests/fixtures/scene_f3d70236/bundle.pb carries the
24 ARKit plane anchors of the first plane-carrying capture (floor + merged
walls), parsed through room_planes / contact_priors exactly as production
does. The failing OBJECTS are the operator's real observations from the
deployed reference scene (perception-obj-00032-km5): a mirror triangulated
2 m+ outside the room, a 5 cm speck "artwork", two doors triangulated to
room center, and — as the keep-side controls — a correctly placed bed and a
curtain near the wall.

The gate demotes exactly the failed placements and keeps the good ones, and
is inert on the outside-room test without measured planes (the degrade lock),
while the class/scale halves still fire (they need no geometry). Contact
placements (chunk D) are exempt — they sit ON a measured surface by
construction.

Run from repo root:

    python -m pytest services/perception-obj/tests/test_placement_sanity_gate_real_data.py -v
"""
from __future__ import annotations

from pathlib import Path

import contact_priors
import fusion
import numpy as np
import pytest
from roomstudio_schemas import CaptureBundle

BUNDLE = Path(__file__).resolve().parent / "fixtures" / "scene_f3d70236" / "bundle.pb"


def _load_planes() -> contact_priors.RoomPlanes:
    bundle = CaptureBundle()
    bundle.ParseFromString(BUNDLE.read_bytes())
    return contact_priors.extract_room_planes(bundle.plane_anchors)


def _ctx(planes):
    """A minimal ctx exposing only the room planes — the gate needs nothing
    else, and get_splat=None keeps refinement a no-op in end-to-end runs."""
    return fusion.RefinementContext(
        get_camera=lambda fi: None,
        get_mask_stack=lambda fi: None,
        get_splat=lambda uri: None,
        get_room_planes=(lambda: planes) if planes is not None else None,
    )


def _placed(label, position, *, method="layout_triangulated",
            position_source="triangulated", extent=None, scale=1.0):
    obj = {
        "object_id": "obj_000",
        "label": label,
        "placed": True,
        "method": method,
        "splat_gcs_uri": "gs://bucket/obj.ply",
        "source": {"frame_index": 0, "mask_index": 0},
        "world_transform": {
            "position": [float(c) for c in position],
            "rotation_xyzw": [0.0, 0.0, 0.0, 1.0],
            "scale": float(scale),
        },
        "position_source": position_source,
        "quality": {"frames_observed": 2, "score": 0.8},
    }
    if extent is not None:
        obj["extent_m_sorted"] = [float(v) for v in extent]
    return obj


# ---------------------------------------------------------------------------
# The measured room the gate judges against.
# ---------------------------------------------------------------------------

def test_real_planes_bounds():
    """Pin the reference room the gate uses (fixture defaults; slightly larger
    than the deployed calibrated shell — the blow-ups are outside either)."""
    planes = _load_planes()
    assert planes.has_geometry
    assert planes.floor_y == pytest.approx(-1.544, abs=0.01)
    c = planes.floor.corners_world
    assert float(c[:, 0].min()) == pytest.approx(-2.27, abs=0.05)
    assert float(c[:, 0].max()) == pytest.approx(1.58, abs=0.05)
    assert float(c[:, 2].min()) == pytest.approx(-1.83, abs=0.05)
    assert float(c[:, 2].max()) == pytest.approx(2.62, abs=0.05)
    assert fusion._wall_top_y(planes) == pytest.approx(0.97, abs=0.05)


# ---------------------------------------------------------------------------
# Demote side: the operator's four failed placements.
# ---------------------------------------------------------------------------

def test_mirror_outside_room_demoted():
    planes = _load_planes()
    ctx = _ctx(planes)
    # The deployed scene's mirror: (2.74, -1.02, 4.52), 2 m+ beyond the floor.
    obj = _placed("mirror", (2.74, -1.02, 4.52), scale=2.26)
    assert fusion._room_sanity_reason(obj, ctx) == "outside_room"


def test_artwork_speck_demoted():
    planes = _load_planes()
    ctx = _ctx(planes)
    # A 5 cm speck: a collapsed reconstruction, wherever it sits.
    obj = _placed("artwork", (-0.3, -0.5, 0.4), scale=0.05, extent=[0.05, 0.04, 0.01])
    assert fusion._room_sanity_reason(obj, ctx) == "implausible_scale"


def test_triangulated_door_demoted():
    planes = _load_planes()
    ctx = _ctx(planes)
    # A door triangulated to room center — the shell already renders it as a
    # wall opening; a free mid-room splat is double-wrong.
    obj = _placed("door", (-0.15, -1.0, -0.3), scale=0.27)
    assert fusion._room_sanity_reason(obj, ctx) == "represented_as_shell_opening"


def test_giant_extent_demoted():
    planes = _load_planes()
    ctx = _ctx(planes)
    obj = _placed("sofa", (-0.3, -0.8, 0.4), extent=[7.0, 2.0, 1.0])
    assert fusion._room_sanity_reason(obj, ctx) == "implausible_scale"


def test_below_floor_demoted():
    planes = _load_planes()
    ctx = _ctx(planes)
    # Same XZ as a valid object, but a metre underground.
    obj = _placed("chair", (-0.3, planes.floor_y - 1.0, 0.4))
    assert fusion._room_sanity_reason(obj, ctx) == "outside_room"


def test_above_wall_top_demoted():
    planes = _load_planes()
    ctx = _ctx(planes)
    top = fusion._wall_top_y(planes)
    obj = _placed("lamp", (-0.3, top + 2.0, 0.4))
    assert fusion._room_sanity_reason(obj, ctx) == "outside_room"


# ---------------------------------------------------------------------------
# Keep side: the good placements survive.
# ---------------------------------------------------------------------------

def test_bed_inside_room_kept():
    planes = _load_planes()
    ctx = _ctx(planes)
    # Near floor center, plausible bed extents.
    obj = _placed("bed", (-0.34, planes.floor_y + 0.3, 0.4),
                  scale=1.15, extent=[2.0, 1.6, 0.5])
    assert fusion._room_sanity_reason(obj, ctx) is None


def test_curtain_near_wall_kept():
    planes = _load_planes()
    ctx = _ctx(planes)
    # A curtain near a wall edge but inside the floor rectangle + margin.
    obj = _placed("curtain", (1.5, -0.5, 2.5), scale=1.86, extent=[1.86, 1.2, 0.1])
    assert fusion._room_sanity_reason(obj, ctx) is None


def test_contact_placement_exempt():
    """A chunk-D contact placement is exempt even for a door label at an
    off-floor position — it is placed ON a measured surface, self-gated."""
    planes = _load_planes()
    ctx = _ctx(planes)
    obj = _placed("door", (2.74, -1.02, 4.52),
                  method="single_view_wall_contact",
                  position_source="single_view_wall_contact")
    assert fusion._room_sanity_reason(obj, ctx) is None


# ---------------------------------------------------------------------------
# Degrade lock: no measured planes -> only class/scale halves fire.
# ---------------------------------------------------------------------------

def test_no_planes_outside_room_inert():
    """Without measured planes there is no room to be 'outside' of — the
    mirror is NOT demoted on position (nothing to judge against)."""
    ctx = _ctx(None)
    obj = _placed("mirror", (2.74, -1.02, 4.52), scale=2.26)
    assert fusion._room_sanity_reason(obj, ctx) is None


def test_no_planes_scale_still_fires():
    ctx = _ctx(None)
    obj = _placed("sofa", (99.0, 99.0, 99.0), extent=[0.03, 0.02, 0.01])
    assert fusion._room_sanity_reason(obj, ctx) == "implausible_scale"


def test_no_planes_opening_class_still_fires():
    ctx = _ctx(None)
    obj = _placed("window", (99.0, 99.0, 99.0))
    assert fusion._room_sanity_reason(obj, ctx) == "represented_as_shell_opening"


# ---------------------------------------------------------------------------
# End-to-end through the production fusion path.
# ---------------------------------------------------------------------------

def _ray_frames(label, target, splat_max=0.5, angular=0.1):
    """Two observations from two cameras whose rays meet at `target`."""
    target = np.asarray(target, dtype=np.float64)
    cams = [np.array([0.0, 0.0, 0.0]), np.array([1.0, 0.0, 0.0])]
    frames = []
    for i, cam in enumerate(cams):
        d = target - cam
        d = d / np.linalg.norm(d)
        frames.append({
            "frame_index": i, "ok": True,
            "objects": [{
                "label": label, "score": 0.9, "mask_index": 0, "ok": True,
                "splat_gcs_uri": "gs://bucket/obj.ply",
                "placement": {
                    "placed": False, "method": None,
                    "reason": "no_depth_pending_triangulation",
                    "world_transform": None, "quality": {},
                    "world_rotation_xyzw": [0.0, 0.0, 0.0, 1.0],
                    "rotation_source": "sam3d_layout",
                    "splat_max_extent": float(splat_max),
                },
                "view_ray": {
                    "origin": list(cam), "direction": list(d),
                    "angular_extent_rad": float(angular),
                },
            }],
        })
    return frames


def test_end_to_end_outside_room_demoted():
    """Full fusion path: two rays triangulate a mirror 2 m+ outside the room;
    the gate demotes the placed object to unplaced."""
    planes = _load_planes()
    ctx = _ctx(planes)
    frames = _ray_frames("mirror", (2.74, -1.02, 4.52))
    objects, _meta = fusion.fuse_scene_objects_with_meta(frames, ctx)
    assert len(objects) == 1
    obj = objects[0]
    assert obj["placed"] is False
    assert obj["reason"] == "outside_room"
    assert obj["world_transform"] is None
    # Identity/provenance preserved for the inventory ledger.
    assert obj["label"] == "mirror"
    assert obj["quality"]["frames_observed"] == 2


def test_end_to_end_inside_room_kept():
    """A mirror triangulated to floor center stays placed."""
    planes = _load_planes()
    ctx = _ctx(planes)
    frames = _ray_frames("mirror", (-0.34, -1.24, 0.40))
    objects, _meta = fusion.fuse_scene_objects_with_meta(frames, ctx)
    assert len(objects) == 1
    obj = objects[0]
    assert obj["placed"] is True
    assert obj["method"] == "layout_triangulated"


def test_placement_refine_off_skips_gate(monkeypatch):
    """PLACEMENT_REFINE=0 reproduces legacy fusion — the gate never runs, the
    outside-room mirror ships placed (bit-parity rollback lever)."""
    monkeypatch.setenv("PLACEMENT_REFINE", "0")
    planes = _load_planes()
    ctx = _ctx(planes)
    frames = _ray_frames("mirror", (2.74, -1.02, 4.52))
    objects, _meta = fusion.fuse_scene_objects_with_meta(frames, ctx)
    assert objects[0]["placed"] is True
