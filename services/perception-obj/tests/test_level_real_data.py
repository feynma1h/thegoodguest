"""Decision 0147 — the levelling pass on the objects the acceptance walk
actually named, using their own shipped splats and transforms.

The 2026-08-12 walk (outputs/item7-walk-2026-08-12/verdicts.md) ranked
contact tilt as its top new class and named four objects: the spike room's
speaker, rp7's table lamp, and rp6g1's lamp and monitor — each at the right
height and "touching at one point". The transforms below are verbatim from
the manifests those verdicts were given against, so a regression here is a
regression against the operator's own reading.

The speaker is the load-bearing case: its own capture photo (frame 142)
shows a soundbar standing vertically, and it ships lying at 40 degrees.
Any change that stops correcting it has undone the walk's headline finding.

Large evidence by absolute path with a clean skip, the house pattern:
these splats live in the gitignored dev-fixtures the walk was staged from.

Run from the repo root:
    python -m pytest services/perception-obj/tests/test_level_real_data.py -v
"""
from __future__ import annotations

from pathlib import Path

import fusion
import numpy as np
import placement
import pytest

FIXTURES = Path("/Users/aubrey/projects/roomstudio/web/public/dev-fixtures")

# label, splat, rotation_xyzw, scale, position — verbatim from the walked
# manifests; then the tilt the walk saw and the correction expected.
CASES = [
    (
        "speaker",
        "scene-spike-a7e073ae/obj_023_f0142_04_speaker.ply",
        (0.016357, -0.484233, -0.675065, 0.556361), 0.666358,
        (1.698, -0.7157, -2.7549), 39.9, 39.8,
    ),
    (
        "table lamp",
        "scene-rp7-a71d125f/obj_015_f0067_03_table_lamp.ply",
        (-0.726274, -0.07424, -0.116477, 0.673385), 0.52096,
        (-1.0099, -0.5565, -3.4846), 5.5, 3.6,
    ),
    (
        "table lamp",
        "scene-rp6g1-09684dde/obj_018_f0097_04_table_lamp.ply",
        (-0.337854, 0.635404, 0.568133, 0.399175), 0.533426,
        (0.3038, -0.4175, -3.5937), 7.4, 7.3,
    ),
    (
        "monitor",
        "scene-rp6g1-09684dde/obj_016_f0057_01_monitor.ply",
        (-0.633957, 0.693091, 0.232907, -0.251947), 0.490508,
        (0.9776, -0.512, -0.4312), 5.0, 3.7,
    ),
]

_needs_fixtures = pytest.mark.skipif(
    not FIXTURES.exists(),
    reason="walk splats only in the main checkout's dev-fixtures",
)


class _Ctx:
    budget = None
    min_remaining_s = 0.0
    get_appearance = None
    get_rgb = None
    get_depth = None

    def __init__(self, uri, pts):
        self._uri, self._pts = uri, pts

    def get_splat(self, uri):
        return self._pts if uri == self._uri else None

    def get_roomplan(self):
        return None

    def get_room_planes(self):
        return None

    def get_camera(self, frame_index):
        return None

    def mask_for(self, *a):
        return None

    def evidence_for(self, *a):
        return None


def _tilt(rotation) -> float:
    from thegoodguest_schemas.pose_math import quat_to_rotmat
    R = quat_to_rotmat(tuple(rotation))
    return min(
        float(np.degrees(np.arccos(np.clip(s * R[1, i], -1.0, 1.0))))
        for i in range(3) for s in (1.0, -1.0)
    )


def _run(case):
    label, rel, rot, scale, pos, _tilt_before, _corr = case
    path = FIXTURES / rel
    if not path.exists():
        pytest.skip(f"{rel} not staged")
    pts = placement.parse_ply_vertices(path.read_bytes())
    obj = {
        "object_id": "obj", "label": label, "placed": True,
        "splat_gcs_uri": "gs://x/s.ply",
        "world_transform": {
            "position": list(pos), "rotation_xyzw": list(rot), "scale": scale,
        },
        "quality": {},
    }
    return obj, fusion._level_upright_object(obj, _Ctx("gs://x/s.ply", pts))


@_needs_fixtures
@pytest.mark.parametrize("case", CASES, ids=[f"{c[0]}-{c[1][6:11]}" for c in CASES])
def test_each_walk_named_object_is_stood_up(case):
    label, rel, rot, _s, _p, tilt_before, correction = case
    obj, out = _run(case)
    assert _tilt(rot) == pytest.approx(tilt_before, abs=0.2), "the walked tilt"
    assert out is not obj, f"{label} in {rel} was not levelled"
    assert out["quality"]["level_correction_deg"] == pytest.approx(correction, abs=0.3)
    assert _tilt(out["world_transform"]["rotation_xyzw"]) < _tilt(rot)


@_needs_fixtures
def test_the_speaker_ends_upright():
    """The walk's worst case, pinned on the outcome rather than the delta:
    a soundbar that stands vertically in its own photo must end vertical,
    not merely less wrong."""
    _obj, out = _run(CASES[0])
    assert _tilt(out["world_transform"]["rotation_xyzw"]) < 1.0
    assert out["quality"]["bottom_flatness_m"] < 0.005


@_needs_fixtures
def test_levelling_moves_the_object_barely_at_all():
    """Levelling is a rotation about the object's own mass: it corrects
    how a thing stands, never where it stands. A pass that also moved
    objects would be re-litigating placement, which has its own evidence."""
    for case in CASES:
        obj, out = _run(case)
        moved = np.linalg.norm(
            np.asarray(out["world_transform"]["position"])
            - np.asarray(obj["world_transform"]["position"])
        )
        assert moved < 0.05, f"{case[0]} moved {moved:.3f} m"
