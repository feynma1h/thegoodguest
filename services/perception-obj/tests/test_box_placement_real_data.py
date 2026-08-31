"""P1 regression pins on real data (decision 0077's verify-first probe,
productionized): box-frame candidate scoring on the 247003de bed through
box_placement's OWN candidate enumeration + the two-tier instrument.

The three P1 claims, each pinned at the achieved values:
  * POSITIVE — at a box-quality center the instrument is decisive: the
    correct facing (up+, long+) wins with combined winner margin ~0.10,
    facing-pair tier-2 margin ~0.15, upside-down rejected by ~0.37 tier-2,
    and the box-frame winner BEATS the shipped SAM-3D-layout rotation in
    its own source frame.
  * NEGATIVE — at the SHIPPED (0.79 m off) fused center the same scorer
    prefers the upside-down candidates: position precedes rotation, box
    centers are load-bearing. A future change making this pass "better"
    at bad centers is a regression of the recorded reason.
  * DEGENERACY — the f164 close view's projected box is marginal
    (in-frame fraction far below f129's); the scoring path must skip it.

Small evidence committed: tests/fixtures/scene_247003de/frames/{0129,0164}
masks.npz + objects.json (fetched from the outputs bucket during the LiDAR
adjudication). Large evidence by absolute path with clean skips: the bed
splat (outputs/roomplan-design/splats/00_bed.ply, ~30 MB) and the capture
RGB (outputs/real-capture-247003de/frames/). Camera poses/intrinsics are
copied verbatim from the preserved bundle below.

Run from repo root:
    python -m pytest services/perception-obj/tests/test_box_placement_real_data.py -v
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import box_placement
import numpy as np
import pytest
import reproject
from roomplan_room import RoomPlanBox

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "scene_247003de" / "frames"
BED_PLY = Path("/Users/aubrey/projects/thegoodguest/outputs/roomplan-design/splats/00_bed.ply")
RGB_DIR = Path("/Users/aubrey/projects/thegoodguest/outputs/real-capture-247003de/frames")

_needs_real_data = pytest.mark.skipif(
    not (BED_PLY.exists() and RGB_DIR.exists()),
    reason="bed splat + capture RGB only in the main checkout's outputs/",
)


@dataclass
class FakeIntrinsics:
    fx: float
    fy: float
    cx: float
    cy: float
    width: int = 1920
    height: int = 1440


@dataclass
class FakePose:
    pos_x: float
    pos_y: float
    pos_z: float
    quat_x: float
    quat_y: float
    quat_z: float
    quat_w: float


# Camera poses/intrinsics, verbatim from outputs/real-capture-247003de's
# bundle.pb (frames 129 and 164).
CAMERA = {
    129: (
        FakePose(-2.5451202392578125, 0.7263522744178772, 0.2468172013759613,
                 -0.36418992280960083, 0.4662730395793915, 0.6324490308761597,
                 -0.4999634623527527),
        FakeIntrinsics(1335.236328125, 1335.236328125, 964.2428588867188,
                       718.4969482421875),
    ),
    164: (
        FakePose(-1.1959527730941772, 0.8341411352157593, 0.6667147278785706,
                 0.326890230178833, -0.30692893266677856, -0.615561842918396,
                 0.6480901837348938),
        FakeIntrinsics(1335.763427734375, 1335.763427734375, 964.2626953125,
                       718.0972900390625),
    ),
}

# The shipped obj_001 (bed) world transform, verbatim from the recorded
# 247003de manifest — the P1 negative's "bad center" and the layout
# rotation the box-frame winner must beat.
SHIPPED_POSITION = np.array([0.006251679584182768, -0.1860450174952946,
                             -0.05556794805195037])
SHIPPED_ROTATION = (0.008608362495970249, 0.7005566977722327,
                    0.6954232399075425, -0.15978963263647356)
SHIPPED_SCALE = 1.9820798626533511

# The emulated RoomPlan-quality box (the P1 probe's construction from the
# bed's own measured rail plane + floor height): long axis along the rail,
# center snapped to rail_offset - width/2, bottom on the floor.
_LONG = np.array([0.475, 0.0, 0.88]) / np.linalg.norm([0.475, 0.0, 0.88])
_RAIL_OFFSET = 1.213
_FLOOR_Y = -0.692
_DIMS = np.array([1.99, 0.48, 0.92])  # (long, up, width) = box (X, Y, Z)


def _emulated_box() -> RoomPlanBox:
    up = np.array([0.0, 1.0, 0.0])
    norm = np.cross(_LONG, up)  # == the rail normal (-0.88, 0, 0.475)
    R = np.column_stack([_LONG, up, norm])
    norm_axis = norm
    target_n = _RAIL_OFFSET - _DIMS[2] / 2.0
    pos = SHIPPED_POSITION + (target_n - float(norm_axis @ SHIPPED_POSITION)) * norm_axis
    pos = pos.copy()
    pos[1] = _FLOOR_Y + _DIMS[1] / 2.0
    T = np.eye(4)
    T[:3, :3] = R
    T[:3, 3] = pos
    return RoomPlanBox(
        identifier="bed-box", category="bed", confidence="high", attributes={},
        dimensions=_DIMS.copy(), transform=T, center_world=pos.copy(),
        up_y=1.0, yaw_rad=float(np.arctan2(R[2, 0], R[0, 0])),
    )


def _mask(frame: int, mask_index: int) -> np.ndarray:
    with np.load(FIXTURES / f"{frame:04d}" / "masks.npz") as npz:
        return npz[npz.files[0]][mask_index].astype(bool)


def _rgb(frame: int) -> np.ndarray:
    from PIL import Image

    return np.asarray(Image.open(RGB_DIR / f"{frame:06d}.jpg").convert("RGB"))


@pytest.fixture(scope="module")
def bed():
    import placement

    ply = BED_PLY.read_bytes()
    return placement.parse_ply_vertices(ply), reproject.load_splat_appearance(ply)


def _score_all(candidates, center, pts, appearance, views):
    return box_placement.score_candidates_at_center(
        candidates, center, pts, appearance, views
    )


def _by_signs(candidates, scores):
    return {c.signs: s for c, s in zip(candidates, scores, strict=True)}


@_needs_real_data
class TestP1Pins:
    @pytest.fixture(scope="class")
    def scored(self, bed):
        pts, appearance = bed
        box = _emulated_box()
        candidates = box_placement.axis_mapping_candidates(
            box, box_placement.splat_axis_extents(pts)
        )
        pose, intr = CAMERA[129]
        ev = reproject._as_evidence(_mask(129, 0))
        views = [(ev, intr, pose, _rgb(129))]
        scores = _score_all(candidates, box.center_world, pts, appearance, views)
        return box, candidates, scores, views

    def test_candidate_set_matches_probe(self, scored):
        box, candidates, _scores, _views = scored
        # One extent-consistent assignment × 4 sign candidates — the P1 set.
        assert len(candidates) == 4
        assert [c.signs for c in candidates] == [(1, 1), (1, -1), (-1, 1), (-1, -1)]
        assert candidates[0].scale == pytest.approx(2.068, abs=0.01)

    def test_positive_winner_and_margins(self, scored):
        """P1(b) at achieved values: correct facing wins decisively at a
        box-quality center."""
        box, candidates, scores, _views = scored
        by_signs = _by_signs(candidates, scores)
        ranked = sorted(by_signs, key=lambda k: -by_signs[k])
        assert ranked[0] == (1, 1)  # up+, long+ — the verified-correct facing
        # Achieved (probe + this reproduction): winner 0.6716, margin 0.0999.
        assert by_signs[(1, 1)] == pytest.approx(0.6716, abs=0.02)
        margin = by_signs[ranked[0]] - by_signs[ranked[1]]
        assert margin == pytest.approx(0.0999, abs=0.02)
        assert margin >= box_placement._AXIS_MARGIN - 0.02

    def test_positive_tier2_margins(self, bed, scored):
        """Facing-pair tier-2 margin ~0.15; upside-down rejected ~0.37."""
        pts, appearance = bed
        box, candidates, _scores, views = scored
        ev, intr, pose, rgb = views[0]
        t2 = {}
        for c in candidates:
            r = reproject.score_placement(
                local_points=pts, rotation_xyzw=c.rotation_xyzw,
                translation=box.center_world, scale=c.scale,
                mask=ev, intrinsics=intr, pose=pose,
                appearance=appearance, rgb=rgb,
            )
            t2[c.signs] = r["tier2"]
        assert t2[(1, 1)] - t2[(1, -1)] == pytest.approx(0.153, abs=0.02)
        assert t2[(1, 1)] - t2[(-1, 1)] == pytest.approx(0.368, abs=0.02)

    def test_box_frame_beats_shipped_layout(self, bed, scored):
        pts, appearance = bed
        box, _candidates, scores, views = scored
        ev, intr, pose, rgb = views[0]
        shipped = reproject.score_placement(
            local_points=pts, rotation_xyzw=SHIPPED_ROTATION,
            translation=box.center_world, scale=SHIPPED_SCALE,
            mask=ev, intrinsics=intr, pose=pose,
            appearance=appearance, rgb=rgb,
        )
        shipped_combined = reproject.combined_score(shipped)
        assert shipped_combined == pytest.approx(0.5681, abs=0.02)
        assert max(scores) > shipped_combined + 0.08

    def test_negative_shipped_center_prefers_upside_down(self, bed):
        """P1(a), the pinned NEGATIVE: at the shipped fused center both
        upside-down candidates outrank both upright ones — the recorded
        reason candidate scoring happens only at box-quality centers."""
        pts, appearance = bed
        box = _emulated_box()
        candidates = box_placement.axis_mapping_candidates(
            box, box_placement.splat_axis_extents(pts)
        )
        pose, intr = CAMERA[129]
        ev = reproject._as_evidence(_mask(129, 0))
        views = [(ev, intr, pose, _rgb(129))]
        scores = _score_all(candidates, SHIPPED_POSITION, pts, appearance, views)
        by_signs = _by_signs(candidates, scores)
        assert min(by_signs[(-1, 1)], by_signs[(-1, -1)]) > max(
            by_signs[(1, 1)], by_signs[(1, -1)]
        )

    def test_f164_is_degenerate_and_skipped(self):
        """P1(c): the close view's projected box is marginal — the in-frame
        fraction lands far below the skip threshold while f129 clears it."""
        box = _emulated_box()
        pose129, intr129 = CAMERA[129]
        pose164, intr164 = CAMERA[164]
        _h1, frac129 = box_placement.project_box_footprint(box, intr129, pose129)
        _h2, frac164 = box_placement.project_box_footprint(box, intr164, pose164)
        assert frac129 >= box_placement._BOX_SCORE_MIN_INFRAME
        assert frac164 < box_placement._BOX_SCORE_MIN_INFRAME
        # Achieved values, pinned (regression baseline): the close view's
        # box footprint is ENTIRELY outside the frame.
        assert frac129 == pytest.approx(0.6295, abs=0.02)
        assert frac164 == pytest.approx(0.0, abs=0.01)


class TestF242CrossLabelTriple:
    """The committed f242 masks: one ~20k px region under three labels
    (artwork / painting / mirror), pairwise near-identity ~0.999 — the
    measured case behind the cross-label dedup gate. Mask-only: runs
    everywhere (no big artifacts needed)."""

    def test_masks_are_near_identical(self):
        m0, m1, m2 = (_mask(242, i) for i in range(3))
        import fusion

        assert fusion._mask_near_identity(m0, m1) >= 0.99
        assert fusion._mask_near_identity(m0, m2) >= 0.99
        assert fusion._mask_near_identity(m1, m2) >= 0.99

    def test_triple_collapses_through_the_gate(self):
        import fusion

        class Ctx:
            def mask_for(self, frame_index, mask_index):
                return _mask(242, mask_index)

        obs = [
            {"frame_index": 242, "label": label, "score": score,
             "mask_index": mi, "splat_gcs_uri": f"gs://o/{mi}.ply",
             "placement": {}, "view_ray": None}
            for mi, (label, score) in enumerate(
                [("artwork", 0.578), ("painting", 0.417), ("mirror", 0.412)]
            )
        ]
        kept, records = fusion._dedup_cross_label(obs, Ctx())
        assert len(kept) == 1
        assert kept[0]["label"] == "artwork"
        assert len(records) == 2
